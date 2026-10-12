"""Phase 2: essay workspace, prompt library and meeting notes."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods, require_POST

from core import audit

from . import essays as essay_service
from .forms import (
    CommentForm,
    EssayCreateForm,
    EssayEditForm,
    EssayPromptForm,
    EssayStatusForm,
    MeetingNoteForm,
    prompts_for_student,
)
from .models import Essay, EssayComment, EssayPrompt, MeetingNote
from .permissions import (
    can_edit_student,
    counselor_required,
    get_comment,
    get_essay,
    get_student,
    visible_notes,
)
from .views import _confirm_page, _form_page

Action = audit.Action


# ------------------------------------------------------------------ essays

@login_required
@require_http_methods(["GET", "POST"])
def essay_create(request, pk):
    student = get_student(request.user, pk, edit=True)
    form = EssayCreateForm(request.POST or None, instance=Essay(student=student), student=student)
    if request.method == "POST" and form.is_valid():
        essay = form.save()
        audit.log(request, Action.CREATE, essay)
        return redirect("essay_edit", pk=essay.pk)
    return render(
        request,
        "portal/essay_create.html",
        {"form": form, "student": student, "prompts": prompts_for_student(student)},
    )


@login_required
def essay_detail(request, pk):
    """Read the latest version with inline comments; add comments by selecting text."""
    essay = get_essay(request.user, pk)
    audit.log(request, Action.VIEW, essay)
    version = essay.latest_version
    comments = list(version.comments.select_related("author")) if version else []
    # Open comments left on older versions stay visible until someone resolves them.
    earlier_comments = (
        EssayComment.objects.filter(version__essay=essay, resolved=False)
        .exclude(version=version)
        .select_related("author", "version")
        .order_by("-version__number", "created_at")
        if version else []
    )
    open_comments = [c for c in comments if not c.resolved]
    return render(request, "portal/essay_detail.html", {
        "essay": essay,
        "student": essay.student,
        "version": version,
        "highlighted": essay_service.highlight(version.body, open_comments) if version else "",
        "open_comments": open_comments,
        "resolved_comments": [c for c in comments if c.resolved],
        "earlier_comments": earlier_comments,
        "can_edit": can_edit_student(request.user, essay.student),
        "comment_form": CommentForm(),
        "status_form": EssayStatusForm(instance=essay),
    })


@login_required
@require_http_methods(["GET", "POST"])
def essay_edit(request, pk):
    essay = get_essay(request.user, pk, edit=True)
    latest = essay.latest_version
    if request.method == "POST":
        form = EssayEditForm(request.POST)
        if form.is_valid():
            version, created, conflict = essay_service.save_version(
                essay, form.cleaned_data["body"], request.user,
                base_number=form.cleaned_data["base_number"], note=form.cleaned_data["note"],
            )
            if created:
                audit.log(request, Action.UPDATE, essay, detail=f"Saved version {version.number}")
                if conflict:
                    messages.warning(
                        request,
                        f"Someone else saved a newer version while you were editing. Your text was saved as "
                        f"version {version.number}; compare versions to merge any changes.",
                    )
                else:
                    messages.success(request, f"Saved as version {version.number}.")
            else:
                messages.info(request, "No changes to save.")
            if request.POST.get("then") == "stay":
                return redirect("essay_edit", pk=essay.pk)
            return redirect("essay_detail", pk=essay.pk)
    else:
        form = EssayEditForm(initial={"body": latest.body if latest else "", "base_number": latest.number if latest else 0})
    return render(request, "portal/essay_edit.html", {"essay": essay, "student": essay.student, "form": form, "latest": latest})


@login_required
@require_POST
def essay_status(request, pk):
    essay = get_essay(request.user, pk, edit=True)
    form = EssayStatusForm(request.POST, instance=essay)
    if form.is_valid():
        form.save()
        audit.log(request, Action.UPDATE, essay, detail=f"Status: {essay.get_status_display()}")
    return redirect("essay_detail", pk=essay.pk)


@login_required
def essay_versions(request, pk):
    essay = get_essay(request.user, pk)
    return render(request, "portal/essay_versions.html", {
        "essay": essay, "student": essay.student, "versions": essay.versions.select_related("created_by"),
        "can_edit": can_edit_student(request.user, essay.student),
    })


@login_required
def essay_version_detail(request, pk, number):
    essay = get_essay(request.user, pk)
    version = get_object_or_404(essay.versions, number=number)
    audit.log(request, Action.VIEW, version)
    previous = essay.versions.filter(number__lt=number).order_by("-number").first()
    return render(request, "portal/essay_version.html", {
        "essay": essay, "student": essay.student, "version": version, "previous": previous,
        "comparison": essay_service.compare(previous.body if previous else "", version.body),
        "is_latest": version.number == essay.latest_version.number,
        "can_edit": can_edit_student(request.user, essay.student),
    })


@login_required
@require_POST
def essay_restore(request, pk, number):
    essay = get_essay(request.user, pk, edit=True)
    old = get_object_or_404(essay.versions, number=number)
    version, created, _ = essay_service.restore_version(essay, old, request.user)
    if created:
        audit.log(request, Action.UPDATE, essay, detail=f"Restored version {number} as {version.number}")
        messages.success(request, f"Version {number} restored as version {version.number}.")
    return redirect("essay_detail", pk=essay.pk)


@login_required
@require_http_methods(["GET", "POST"])
def essay_delete(request, pk):
    essay = get_essay(request.user, pk)
    if not request.user.is_counselor:
        raise PermissionDenied
    back = reverse("essay_detail", args=[essay.pk])
    if request.method == "POST":
        student_pk = essay.student_id
        audit.log(request, Action.DELETE, essay)
        essay.delete()
        messages.success(request, "Essay deleted.")
        return redirect("student_detail", pk=student_pk)
    return _confirm_page(request, "Delete essay?", f"{essay.title} and all its versions and comments.", back)


# ------------------------------------------------------------------ comments

@login_required
@require_POST
def comment_create(request, pk):
    essay = get_essay(request.user, pk, edit=True)
    version = essay.latest_version
    form = CommentForm(request.POST)
    if version is None:
        messages.error(request, "Write a draft before adding comments.")
    elif form.is_valid():
        data = form.cleaned_data
        comment = essay_service.add_comment(
            version, request.user, data["body"], start=data["start"], end=data["end"], quote=data["quote"]
        )
        audit.log(request, Action.CREATE, comment)
    else:
        messages.error(request, "Comment can't be empty.")
    return redirect(reverse("essay_detail", args=[essay.pk]) + "#comments")


@login_required
@require_POST
def comment_resolve(request, pk):
    comment = get_comment(request.user, pk)
    comment.resolved = request.POST.get("resolved") != "0"
    comment.save(update_fields=["resolved"])
    audit.log(request, Action.UPDATE, comment, detail="Resolved" if comment.resolved else "Reopened")
    return redirect(reverse("essay_detail", args=[comment.version.essay_id]) + "#comments")


@login_required
@require_POST
def comment_delete(request, pk):
    comment = get_comment(request.user, pk)
    if not (request.user.is_counselor or comment.author_id == request.user.id):
        raise PermissionDenied
    essay_pk = comment.version.essay_id
    audit.log(request, Action.DELETE, comment)
    comment.delete()
    return redirect(reverse("essay_detail", args=[essay_pk]) + "#comments")


# ------------------------------------------------------------------ prompt library (counselor)

@login_required
@counselor_required
def prompt_list(request):
    year = request.GET.get("year", "")
    prompts = EssayPrompt.objects.select_related("university")
    if year.isdigit():
        prompts = prompts.filter(entry_year=int(year))
    years = EssayPrompt.objects.order_by("-entry_year").values_list("entry_year", flat=True).distinct()
    return render(request, "portal/prompt_list.html", {"prompts": prompts, "years": years, "year": year})


@login_required
@counselor_required
@require_http_methods(["GET", "POST"])
def prompt_form(request, pk=None):
    prompt = get_object_or_404(EssayPrompt, pk=pk) if pk else EssayPrompt()
    initial = {"university": request.GET.get("university")} if not pk and request.GET.get("university", "").isdigit() else None
    form = EssayPromptForm(request.POST or None, instance=prompt, initial=initial)
    if request.method == "POST" and form.is_valid():
        prompt = form.save()
        audit.log(request, Action.UPDATE if pk else Action.CREATE, prompt)
        messages.success(request, "Prompt saved.")
        return redirect("prompt_list")
    return _form_page(request, form, "Edit prompt" if pk else "New prompt", reverse("prompt_list"))


@login_required
@counselor_required
@require_http_methods(["GET", "POST"])
def prompt_delete(request, pk):
    prompt = get_object_or_404(EssayPrompt, pk=pk)
    if request.method == "POST":
        audit.log(request, Action.DELETE, prompt)
        prompt.delete()
        messages.success(request, "Prompt deleted. Essays written for it are kept.")
        return redirect("prompt_list")
    return _confirm_page(request, "Delete prompt?", str(prompt), reverse("prompt_list"))


# ------------------------------------------------------------------ meeting notes

@login_required
def note_list(request, pk):
    student = get_student(request.user, pk)
    notes = visible_notes(request.user, student)
    audit.log(request, Action.VIEW, student, detail="Meeting notes")
    return render(request, "portal/note_list.html", {"student": student, "notes": notes})


@login_required
@counselor_required
@require_http_methods(["GET", "POST"])
def note_form(request, pk, note_pk=None):
    student = get_student(request.user, pk)
    note = get_object_or_404(MeetingNote, pk=note_pk, student=student) if note_pk else MeetingNote(student=student, author=request.user)
    form = MeetingNoteForm(request.POST or None, instance=note)
    if request.method == "POST" and form.is_valid():
        note = form.save()
        audit.log(request, Action.UPDATE if note_pk else Action.CREATE, note)
        messages.success(request, "Note saved.")
        return redirect("note_list", pk=student.pk)
    return _form_page(request, form, f"{'Edit' if note_pk else 'New'} meeting note: {student}", reverse("note_list", args=[student.pk]))


@login_required
@counselor_required
@require_http_methods(["GET", "POST"])
def note_delete(request, pk, note_pk):
    student = get_student(request.user, pk)
    note = get_object_or_404(MeetingNote, pk=note_pk, student=student)
    if request.method == "POST":
        audit.log(request, Action.DELETE, note)
        note.delete()
        return redirect("note_list", pk=student.pk)
    return _confirm_page(request, "Delete note?", str(note), reverse("note_list", args=[student.pk]))

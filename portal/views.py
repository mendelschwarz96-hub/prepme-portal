from datetime import timedelta
from itertools import groupby

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.mail import send_mail
from django.core.paginator import Paginator
from django.db.models import Count, Min, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_http_methods, require_POST

from accounts.models import Invite
from core import audit
from core.models import AuditLog

from . import deadlines
from .forms import (
    AcademicRecordForm,
    AddSchoolForm,
    ChangeRoundForm,
    CounselorTaskForm,
    DeadlineTemplateForm,
    DocumentForm,
    InviteForm,
    SchoolForm,
    StudentProfileForm,
    StudentSelfForm,
    StudentTaskForm,
    TestScoreForm,
)
from .models import AcademicRecord, Application, DeadlineTemplate, DocumentItem, StudentProfile, Task, TestScore, University
from .permissions import (
    can_edit_student,
    can_edit_task_details,
    counselor_required,
    get_application,
    get_document,
    get_student,
    get_summary_student,
    get_task,
    summary_students,
    visible_notes,
)
from . import summary as progress_summary

Action = audit.Action


def _form_page(request, form, title, cancel_url, *, submit="Save", intro=""):
    return render(
        request,
        "portal/form.html",
        {"form": form, "title": title, "cancel_url": cancel_url, "submit": submit, "intro": intro},
    )


def _confirm_page(request, title, message, cancel_url, *, submit="Delete"):
    return render(
        request,
        "portal/confirm.html",
        {"title": title, "message": message, "cancel_url": cancel_url, "submit": submit},
    )


def _next_or(request, default):
    """Follow a ?next= / next field only if it points inside this site."""
    target = request.POST.get("next") or request.GET.get("next")
    if target and url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return target
    return default


def _add_validation_errors(request, exc):
    for message in exc.messages:
        messages.error(request, message)


# ------------------------------------------------------------------ home

def home(request):
    user = request.user
    if not user.is_authenticated:
        return redirect("login")  # plain /login/, without ?next=/
    if user.is_counselor:
        return redirect("dashboard")
    students = list(summary_students(user))
    target = "student_summary" if user.is_parent else "student_detail"
    if len(students) == 1:
        return redirect(target, pk=students[0].pk)
    return render(request, "portal/choose_student.html", {"students": students, "target": target})


@login_required
def student_summary(request, pk):
    """Read-only progress summary. This is the parent view; counselor and student can open it too."""
    student = get_summary_student(request.user, pk)
    audit.log(request, Action.VIEW, student, detail="Progress summary")
    return render(
        request,
        "portal/student_summary.html",
        {"student": student, "summary": progress_summary.build(student), "today": timezone.localdate()},
    )


@login_required
@counselor_required
def dashboard(request):
    today = timezone.localdate()
    week_end = today + timedelta(days=6)
    open_tasks = (
        Task.objects.filter(archived=False, student__is_active=True)
        .exclude(status=Task.Status.DONE)
        .select_related("student", "owner", "application__university")
    )
    context = {
        "today": today,
        "week_end": week_end,
        "overdue": open_tasks.filter(due_date__lt=today),
        "this_week": open_tasks.filter(due_date__gte=today, due_date__lte=week_end),
    }
    pending = (
        Application.objects.filter(status__in=[Application.Status.PENDING_ADD, Application.Status.PENDING_REMOVAL])
        .select_related("student", "university", "requested_by")
        .order_by("student__last_name", "student__first_name", "student_id", "created_at")
    )
    context["pending_groups"] = [(student, list(apps)) for student, apps in groupby(pending, key=lambda a: a.student)]
    context["pending_count"] = sum(len(apps) for _, apps in context["pending_groups"])
    return render(request, "portal/dashboard.html", context)


# ------------------------------------------------------------------ students

@login_required
@counselor_required
def student_list(request):
    show = request.GET.get("show", "active")
    students = StudentProfile.objects.select_related("school")
    if show == "active":
        students = students.filter(is_active=True)
    elif show == "inactive":
        students = students.filter(is_active=False)
    q = request.GET.get("q", "").strip()
    if q:
        students = students.filter(Q(first_name__icontains=q) | Q(last_name__icontains=q))
    open_filter = Q(tasks__archived=False) & ~Q(tasks__status=Task.Status.DONE)
    students = students.annotate(
        open_tasks=Count("tasks", filter=open_filter),
        next_due=Min("tasks__due_date", filter=open_filter),
    )
    return render(request, "portal/student_list.html", {"students": students, "show": show, "q": q})


@login_required
@counselor_required
@require_http_methods(["GET", "POST"])
def student_create(request):
    form = StudentProfileForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        student = form.save()
        audit.log(request, Action.CREATE, student)
        messages.success(request, f"{student} added.")
        return redirect("student_detail", pk=student.pk)
    return _form_page(request, form, "New student", reverse("student_list"))


@login_required
def student_detail(request, pk):
    student = get_student(request.user, pk)
    audit.log(request, Action.VIEW, student)
    all_tasks = student.tasks.filter(archived=False).select_related("owner", "application__university")
    tasks = all_tasks.exclude(source=Task.Source.AFTER_ADMISSION)
    applications = list(student.applications.filter(status__in=Application.OPEN).select_related("university"))
    context = {
        "student": student,
        "can_edit": can_edit_student(request.user, student),
        "applications": applications,
        "pending_ids": [a.pk for a in applications if a.status != Application.Status.ACTIVE],
        "open_tasks": tasks.exclude(status=Task.Status.DONE),
        "done_tasks": tasks.filter(status=Task.Status.DONE),
        "test_scores": student.test_scores.all(),
        "academic_records": student.academic_records.all(),
        "parents": student.parents.all(),
        "essays": student.essays.select_related("application__university", "prompt"),
        "notes": visible_notes(request.user, student)[:5],
        "attending": next((a for a in applications if a.attending), None),
        "after_admission": all_tasks.filter(source=Task.Source.AFTER_ADMISSION),
        "today": timezone.localdate(),
    }
    if request.user.is_counselor:
        context["invites"] = student.invites.filter(accepted_at__isnull=True, expires_at__gt=timezone.now())
    return render(request, "portal/student_detail.html", context)


@login_required
@require_http_methods(["GET", "POST"])
def student_edit(request, pk):
    student = get_student(request.user, pk, edit=True)
    form_class = StudentProfileForm if request.user.is_counselor else StudentSelfForm
    form = form_class(request.POST or None, instance=student)
    if request.method == "POST" and form.is_valid():
        form.save()
        audit.log(request, Action.UPDATE, student, detail="Profile")
        messages.success(request, "Profile saved.")
        return redirect("student_detail", pk=student.pk)
    return _form_page(request, form, f"Edit profile: {student}", reverse("student_detail", args=[student.pk]))


@login_required
@counselor_required
@require_http_methods(["GET", "POST"])
def school_create(request):
    form = SchoolForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        school = form.save()
        audit.log(request, Action.CREATE, school)
        messages.success(request, f"{school} added. You can now choose it on a student's profile.")
        return redirect(_next_or(request, reverse("student_list")))
    return _form_page(request, form, "New high school", reverse("student_list"))


# ------------------------------------------------------------------ test scores & grades

def _child_form(request, student_pk, model, form_class, item_pk, label):
    student = get_student(request.user, student_pk, edit=True)
    instance = get_object_or_404(model, pk=item_pk, student=student) if item_pk else model(student=student)
    form = form_class(request.POST or None, instance=instance)
    if request.method == "POST" and form.is_valid():
        obj = form.save()
        audit.log(request, Action.UPDATE if item_pk else Action.CREATE, obj, detail=label)
        messages.success(request, f"{label} saved.")
        return redirect("student_detail", pk=student.pk)
    title = f"{'Edit' if item_pk else 'Add'} {label.lower()}: {student}"
    return _form_page(request, form, title, reverse("student_detail", args=[student.pk]))


def _child_delete(request, student_pk, model, item_pk, label):
    student = get_student(request.user, student_pk, edit=True)
    obj = get_object_or_404(model, pk=item_pk, student=student)
    if request.method == "POST":
        audit.log(request, Action.DELETE, obj, detail=label)
        obj.delete()
        messages.success(request, f"{label} deleted.")
        return redirect("student_detail", pk=student.pk)
    return _confirm_page(request, f"Delete {label.lower()}?", str(obj), reverse("student_detail", args=[student.pk]))


@login_required
@require_http_methods(["GET", "POST"])
def score_form(request, pk, score_pk=None):
    return _child_form(request, pk, TestScore, TestScoreForm, score_pk, "Test score")


@login_required
@require_http_methods(["GET", "POST"])
def score_delete(request, pk, score_pk):
    return _child_delete(request, pk, TestScore, score_pk, "Test score")


@login_required
@require_http_methods(["GET", "POST"])
def grade_form(request, pk, grade_pk=None):
    return _child_form(request, pk, AcademicRecord, AcademicRecordForm, grade_pk, "Grade")


@login_required
@require_http_methods(["GET", "POST"])
def grade_delete(request, pk, grade_pk):
    return _child_delete(request, pk, AcademicRecord, grade_pk, "Grade")


# ------------------------------------------------------------------ school list

@login_required
@require_http_methods(["GET", "POST"])
def application_add(request, pk):
    student = get_student(request.user, pk, edit=True)
    form = AddSchoolForm(request.POST or None, initial={"entry_year": student.graduation_year})
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        try:
            application = deadlines.add_school(
                student, data["university"], data["entry_year"], data["round"], request.user, course=data["course"]
            )
        except ValidationError as exc:
            _add_validation_errors(request, exc)
        else:
            audit.log(request, Action.CREATE, application, detail=f"Status: {application.get_status_display()}")
            if application.status == Application.Status.ACTIVE:
                messages.success(request, f"{application.university} added. Deadlines were added as tasks.")
            else:
                messages.success(request, f"Request sent. {application.university} will appear once approved.")
            return redirect("student_detail", pk=student.pk)
    intro = "" if request.user.is_counselor else "Your counselor will approve this before it is added to your list."
    return _form_page(
        request, form, f"Add a school: {student}", reverse("student_detail", args=[student.pk]),
        submit="Add school" if request.user.is_counselor else "Send request", intro=intro,
    )


@login_required
def application_detail(request, pk):
    application = get_application(request.user, pk)
    audit.log(request, Action.VIEW, application)
    tasks = application.tasks.filter(archived=False).select_related("owner", "template")
    context = {
        "application": application,
        "student": application.student,
        "can_edit": can_edit_student(request.user, application.student),
        "tasks": tasks,
        "documents": application.documents.all(),
        "round_form": ChangeRoundForm(application=application) if request.user.is_counselor else None,
        "ucas_warnings": deadlines.ucas_problems(application.student, application.entry_year, application.university)
        if application.status == Application.Status.PENDING_ADD
        else [],
        "today": timezone.localdate(),
    }
    return render(request, "portal/application_detail.html", context)


@login_required
@counselor_required
@require_POST
def application_approve(request, pk):
    application = get_application(request.user, pk)
    try:
        deadlines.approve(application, request.user)
    except ValidationError as exc:
        _add_validation_errors(request, exc)
    else:
        audit.log(request, Action.APPROVE, application, detail=f"Now: {application.get_status_display()}")
        messages.success(request, f"Approved: {application.university} for {application.student}.")
    return redirect(_next_or(request, reverse("application_detail", args=[application.pk])))


@login_required
@counselor_required
@require_POST
def application_decline(request, pk):
    application = get_application(request.user, pk)
    try:
        deadlines.decline(application, request.user)
    except ValidationError as exc:
        _add_validation_errors(request, exc)
    else:
        audit.log(request, Action.DECLINE, application)
        messages.success(request, f"Declined: {application.university} for {application.student}.")
    return redirect(_next_or(request, reverse("student_detail", args=[application.student.pk])))


@login_required
@counselor_required
@require_POST
def applications_bulk(request):
    """Approve or decline many pending requests at once (e.g. a student's whole college list)."""
    accept = request.POST.get("decision") == "approve"
    ids = [i for i in request.POST.getlist("application") if i.isdigit()]
    pending = list(
        Application.objects.filter(
            pk__in=ids, status__in=[Application.Status.PENDING_ADD, Application.Status.PENDING_REMOVAL]
        )
        .select_related("student", "university")
        .order_by("student__last_name", "created_at")
    )
    if not pending:
        messages.error(request, "Select at least one request.")
        return redirect(_next_or(request, reverse("dashboard")))
    done, problems = deadlines.decide_many(pending, request.user, accept=accept)
    for application in done:
        audit.log(
            request, Action.APPROVE if accept else Action.DECLINE, application,
            detail=f"Bulk decision. Now: {application.get_status_display()}",
        )
    if done:
        verb = "Approved" if accept else "Declined"
        messages.success(request, f"{verb} {len(done)} request{'s' if len(done) != 1 else ''}.")
    for application, problem in problems:
        messages.error(request, f"{application.university} for {application.student}: {problem}")
    return redirect(_next_or(request, reverse("dashboard")))


@login_required
@require_http_methods(["GET", "POST"])
def application_remove(request, pk):
    application = get_application(request.user, pk, edit=True)
    back = reverse("application_detail", args=[application.pk])
    if request.method == "POST":
        try:
            deadlines.request_removal(application, request.user)
        except ValidationError as exc:
            _add_validation_errors(request, exc)
            return redirect(back)
        audit.log(request, Action.UPDATE, application, detail=f"Now: {application.get_status_display()}")
        if application.status == Application.Status.PENDING_REMOVAL:
            messages.success(request, "Removal requested. Your counselor will confirm it.")
        else:
            messages.success(request, f"{application.university} removed from the list.")
        return redirect("student_detail", pk=application.student.pk)
    if request.user.is_counselor:
        message = f"Remove {application.university} from {application.student}'s list? Open tasks will be hidden."
        submit = "Remove"
    else:
        message = f"Ask your counselor to remove {application.university} from your list?"
        submit = "Send request"
    return _confirm_page(request, "Remove school", message, back, submit=submit)


@login_required
@counselor_required
@require_POST
def application_round(request, pk):
    application = get_application(request.user, pk)
    form = ChangeRoundForm(request.POST, application=application)
    if form.is_valid():
        deadlines.change_round(application, form.cleaned_data["round"])
        audit.log(request, Action.UPDATE, application, detail=f"Round: {application.get_round_display()}")
        messages.success(request, "Round changed. Tasks were updated to match.")
    return redirect("application_detail", pk=application.pk)


# ------------------------------------------------------------------ tasks

def _task_back(task):
    if task.application_id:
        return reverse("application_detail", args=[task.application_id])
    return reverse("student_detail", args=[task.student_id])


@login_required
@require_POST
def task_status(request, pk):
    task = get_task(request.user, pk, edit=True)
    status = request.POST.get("status")
    if status not in Task.Status.values:
        raise PermissionDenied
    deadlines.set_task_status(task, status)
    audit.log(request, Action.UPDATE, task, detail=f"Status: {task.get_status_display()}")
    return redirect(_next_or(request, _task_back(task)))


@login_required
@require_http_methods(["GET", "POST"])
def task_create(request, pk):
    student = get_student(request.user, pk, edit=True)
    task = Task(student=student, source=Task.Source.MANUAL, created_by=request.user)
    if request.user.is_counselor:
        form = CounselorTaskForm(request.POST or None, instance=task, student=student)
    else:
        task.owner = request.user
        form = StudentTaskForm(request.POST or None, instance=task)
    if request.method == "POST" and form.is_valid():
        task = form.save()
        audit.log(request, Action.CREATE, task)
        messages.success(request, "Task added.")
        return redirect("student_detail", pk=student.pk)
    return _form_page(request, form, f"New task: {student}", reverse("student_detail", args=[student.pk]))


@login_required
@require_http_methods(["GET", "POST"])
def task_edit(request, pk):
    task = get_task(request.user, pk, edit=True)
    if not can_edit_task_details(request.user, task):
        raise PermissionDenied
    old_date = task.due_date
    if request.user.is_counselor:
        form = CounselorTaskForm(request.POST or None, instance=task, student=task.student)
    else:
        form = StudentTaskForm(request.POST or None, instance=task)
    if request.method == "POST" and form.is_valid():
        task = form.save(commit=False)
        new_date = task.due_date
        task.due_date = old_date
        task.save()
        if new_date != old_date:
            deadlines.set_task_due_date(task, new_date)
        deadlines.set_task_status(task, task.status)
        audit.log(request, Action.UPDATE, task)
        messages.success(request, "Task saved.")
        return redirect(_task_back(task))
    return _form_page(request, form, "Edit task", _task_back(task))


@login_required
@counselor_required
@require_POST
def task_reset_date(request, pk):
    task = get_task(request.user, pk)
    deadlines.reset_task_date(task)
    audit.log(request, Action.UPDATE, task, detail="Date reset to school deadline")
    messages.success(request, "Date reset to the school deadline.")
    return redirect(_task_back(task))


@login_required
@require_http_methods(["GET", "POST"])
def task_delete(request, pk):
    task = get_task(request.user, pk, edit=True)
    if not can_edit_task_details(request.user, task):
        raise PermissionDenied
    back = _task_back(task)
    if request.method == "POST":
        audit.log(request, Action.DELETE, task)
        task.delete()
        messages.success(request, "Task deleted.")
        return redirect(back)
    note = " It comes from a school deadline; it will not be re-created unless the deadline changes." if task.template_id else ""
    return _confirm_page(request, "Delete task?", f"{task.title}.{note}", back)


# ------------------------------------------------------------------ documents

@login_required
@require_http_methods(["GET", "POST"])
def document_create(request, pk):
    application = get_application(request.user, pk, edit=True)
    form = DocumentForm(request.POST or None, instance=DocumentItem(application=application))
    if request.method == "POST" and form.is_valid():
        document = form.save(commit=False)
        document.updated_by = request.user
        document.save()
        audit.log(request, Action.CREATE, document)
        return redirect("application_detail", pk=application.pk)
    return _form_page(request, form, f"Add document: {application.university}", reverse("application_detail", args=[application.pk]))


@login_required
@require_http_methods(["GET", "POST"])
def document_edit(request, pk):
    document = get_document(request.user, pk, edit=True)
    form = DocumentForm(request.POST or None, instance=document)
    back = reverse("application_detail", args=[document.application_id])
    if request.method == "POST" and form.is_valid():
        document = form.save(commit=False)
        document.updated_by = request.user
        document.save()
        audit.log(request, Action.UPDATE, document)
        return redirect(back)
    return _form_page(request, form, f"{document} - {document.application.university}", back)


@login_required
@require_http_methods(["GET", "POST"])
def document_delete(request, pk):
    document = get_document(request.user, pk, edit=True)
    back = reverse("application_detail", args=[document.application_id])
    if request.method == "POST":
        audit.log(request, Action.DELETE, document)
        document.delete()
        return redirect(back)
    return _confirm_page(request, "Remove document?", str(document), back, submit="Remove")


# ------------------------------------------------------------------ deadlines (counselor; university pages are in views_universities)

@login_required
@counselor_required
@require_http_methods(["GET", "POST"])
def deadline_form(request, pk, deadline_pk=None):
    university = get_object_or_404(University, pk=pk)
    template = get_object_or_404(DeadlineTemplate, pk=deadline_pk, university=university) if deadline_pk else None
    form = DeadlineTemplateForm(request.POST or None, instance=template, university=university)
    if request.method == "POST" and form.is_valid():
        template = deadlines.save_template(form.save(commit=False))
        audit.log(request, Action.UPDATE if deadline_pk else Action.CREATE, template)
        messages.success(request, "Deadline saved. Students with this school on their list were updated.")
        return redirect("university_detail", pk=university.pk)
    intro = (
        "Changing this date moves the matching task for every student, "
        "except students whose date you changed individually."
    )
    return _form_page(
        request, form, f"{'Edit' if deadline_pk else 'Add'} deadline: {university}",
        reverse("university_detail", args=[university.pk]), intro=intro,
    )


@login_required
@counselor_required
@require_http_methods(["GET", "POST"])
def deadline_delete(request, pk, deadline_pk):
    template = get_object_or_404(DeadlineTemplate, pk=deadline_pk, university_id=pk)
    back = reverse("university_detail", args=[pk])
    if request.method == "POST":
        audit.log(request, Action.DELETE, template)
        deadlines.delete_template(template)
        messages.success(request, "Deadline deleted. Open tasks based on it were hidden.")
        return redirect(back)
    return _confirm_page(request, "Delete deadline?", f"{template} ({template.due_date:%b %d, %Y})", back)


# ------------------------------------------------------------------ invites & audit (counselor)

@login_required
@counselor_required
@require_http_methods(["GET", "POST"])
def invite_create(request, pk):
    student = get_student(request.user, pk)
    form = InviteForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        role = form.cleaned_data["role"]
        if role == "student" and student.user_id:
            messages.error(request, f"{student} already has a login.")
            return redirect("student_detail", pk=student.pk)
        invite, token = Invite.create(email=form.cleaned_data["email"], role=role, student=student, created_by=request.user)
        link = settings.SITE_URL.rstrip("/") + reverse("accept_invite", args=[token])
        send_mail(
            "Your PrepMe Portal invitation",
            f"Hello,\n\nYou have been invited to the PrepMe Portal for {student.first_name}.\n"
            f"Create your login here (valid for {settings.INVITE_VALID_DAYS} days):\n\n{link}\n\n"
            "If you were not expecting this, you can ignore this email.",
            None,
            [invite.email],
        )
        audit.log(request, Action.INVITE, invite, detail=f"{role} invite to {invite.email}")
        return render(request, "portal/invite_sent.html", {"invite": invite, "link": link, "student": student})
    return _form_page(
        request, form, f"Invite to portal: {student}", reverse("student_detail", args=[student.pk]),
        submit="Send invite", intro="The person receives an email with a one-time link to create their login.",
    )


@login_required
@counselor_required
def audit_log(request):
    entries = AuditLog.objects.select_related("user")
    student_id = request.GET.get("student")
    student = None
    if student_id and student_id.isdigit():
        entries = entries.filter(student_id=int(student_id))
        student = StudentProfile.objects.filter(pk=student_id).first()
    page = Paginator(entries, 100).get_page(request.GET.get("page"))
    return render(request, "portal/audit_log.html", {"page": page, "student": student})

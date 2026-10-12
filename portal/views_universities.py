"""Phase 3: university profiles, College Scorecard import, CSV import, filter and compare.

Counselor and students can browse, filter and compare. Only the counselor can edit or import.
Parents have no access.
"""
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods, require_POST

from core import audit

from . import csv_import, scorecard
from .forms import CSVUploadForm, UniversityFilterForm, UniversityForm
from .models import Application, University
from .permissions import browse_universities_required, counselor_required
from .views import _form_page

Action = audit.Action
COMPARE_MAX = 4


@login_required
@browse_universities_required
def university_list(request):
    form = UniversityFilterForm(request.GET or None)
    universities = form.apply(University.objects.annotate(deadline_count=Count("deadlines")))
    page = Paginator(universities, 50).get_page(request.GET.get("page"))
    query = request.GET.copy()
    query.pop("page", None)
    return render(request, "portal/university_list.html", {
        "form": form, "page": page, "query": query.urlencode(), "filtered": any(v for k, v in request.GET.items() if k not in ("page", "sort")),
        "compare_max": COMPARE_MAX,
    })


@login_required
@browse_universities_required
def university_detail(request, pk):
    university = get_object_or_404(University, pk=pk)
    context = {"university": university, "deadlines": university.deadlines.all()}
    if request.user.is_counselor:
        context["applications"] = university.applications.filter(status__in=Application.OPEN).select_related("student")
    elif request.user.is_student:
        context["my_application"] = university.applications.filter(
            student__user=request.user, status__in=Application.OPEN
        ).first()
    return render(request, "portal/university_detail.html", context)


@login_required
@browse_universities_required
def university_compare(request):
    ids = [i for i in request.GET.getlist("id") if i.isdigit()][:COMPARE_MAX]
    universities = list(University.objects.filter(pk__in=ids))
    universities.sort(key=lambda u: ids.index(str(u.pk)))
    if len(universities) < 2:
        messages.info(request, f"Tick 2 to {COMPARE_MAX} universities to compare them.")
        return redirect("university_list")
    return render(request, "portal/university_compare.html", {"universities": universities})


@login_required
@counselor_required
@require_http_methods(["GET", "POST"])
def university_form(request, pk=None):
    university = get_object_or_404(University, pk=pk) if pk else University()
    form = UniversityForm(request.POST or None, instance=university)
    if pk and university.applications.exists():
        form.fields["application_system"].disabled = True
        form.fields["application_system"].help_text = "Can't change once students have this school on their list."
    if request.method == "POST" and form.is_valid():
        university = form.save(commit=False)
        university.profile_updated_at = timezone.now()
        university.save()
        audit.log(request, Action.UPDATE if pk else Action.CREATE, university)
        return redirect("university_detail", pk=university.pk)
    back = reverse("university_detail", args=[pk]) if pk else reverse("university_list")
    intro = (
        "Fields marked “From the College Scorecard” update automatically; the rest are yours to maintain."
        if university.from_scorecard else
        "For U.S. colleges, use “Add from College Scorecard” instead to get official data automatically."
    )
    return _form_page(request, form, "Edit university" if pk else "New university", back, intro=intro)


# ------------------------------------------------------------------ College Scorecard

@login_required
@counselor_required
def scorecard_search(request):
    q = request.GET.get("q", "").strip()
    results, error = [], None
    if q:
        try:
            results = scorecard.search(q)
        except scorecard.ScorecardError as exc:
            error = str(exc)
        linked = dict(University.objects.filter(scorecard_id__in=[r["id"] for r in results]).values_list("scorecard_id", "pk"))
        for r in results:
            r["university_pk"] = linked.get(r["id"])
    return render(request, "portal/scorecard_search.html", {"q": q, "results": results, "error": error})


@login_required
@counselor_required
@require_POST
def scorecard_add(request):
    raw = request.POST.get("scorecard_id", "")
    if not raw.isdigit():
        return redirect("scorecard_search")
    try:
        university, created = scorecard.import_school(int(raw))
    except scorecard.ScorecardError as exc:
        messages.error(request, str(exc))
        return redirect(reverse("scorecard_search") + "?" + urlencode({"q": request.POST.get("q", "")}))
    audit.log(request, Action.CREATE if created else Action.UPDATE, university, detail="College Scorecard import")
    messages.success(request, f"{university} {'added' if created else 'updated'} from the College Scorecard. "
                              "Add its deadlines and international details below.")
    return redirect("university_detail", pk=university.pk)


@login_required
@counselor_required
@require_POST
def scorecard_refresh(request, pk=None):
    try:
        if pk:
            university = get_object_or_404(University, pk=pk, scorecard_id__isnull=False)
            scorecard.import_school(university.scorecard_id)
            audit.log(request, Action.UPDATE, university, detail="College Scorecard refresh")
            messages.success(request, "Refreshed from the College Scorecard.")
            return redirect("university_detail", pk=pk)
        updated, missing = scorecard.refresh_all()
        audit.log(request, Action.UPDATE, detail=f"College Scorecard refresh of {updated} universities")
        messages.success(request, f"Refreshed {updated} universit{'y' if updated == 1 else 'ies'} from the College Scorecard.")
        if missing:
            messages.warning(request, "Not found in the Scorecard any more: " + ", ".join(missing))
    except scorecard.ScorecardError as exc:
        messages.error(request, str(exc))
    return redirect(reverse("university_detail", args=[pk]) if pk else reverse("university_list"))


# ------------------------------------------------------------------ CSV import

@login_required
@counselor_required
@require_http_methods(["GET", "POST"])
def university_import(request):
    form = CSVUploadForm(request.POST or None, request.FILES or None)
    context = {"form": form}
    if request.method == "POST" and form.is_valid():
        content = form.cleaned_data["content"]
        rows, problems = csv_import.parse(content)
        if request.POST.get("confirm") == "1":
            created, updated = csv_import.save(rows)
            audit.log(request, Action.UPDATE, detail=f"CSV import: {created} created, {updated} updated")
            messages.success(request, f"Import finished: {created} added, {updated} updated.")
            skipped = sum(1 for r in rows if not r.ok)
            if skipped:
                messages.warning(request, f"{skipped} row{'s' if skipped != 1 else ''} with errors {'were' if skipped != 1 else 'was'} skipped.")
            return redirect("university_list")
        context.update(preview=True, rows=rows, problems=problems, content=content,
                       valid_count=sum(1 for r in rows if r.ok))
    return render(request, "portal/university_import.html", context)


@login_required
@counselor_required
def university_import_template(request):
    response = HttpResponse(csv_import.template_csv(), content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="universities-template.csv"'
    return response

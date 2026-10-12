"""Phase 4 (outcomes, consent, benchmarks) and Phase 5 (attending school + checklist)."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods, require_POST

from core import audit

from . import benchmark, deadlines, outcome_import
from .forms import ConsentForm, CSVUploadForm, OutcomeForm
from .models import Application, Consent
from .permissions import counselor_required, get_application, get_student
from .views import _form_page

Action = audit.Action


@login_required
@require_http_methods(["GET", "POST"])
def outcome_form(request, pk):
    application = get_application(request.user, pk, edit=True)
    form = OutcomeForm(request.POST or None, instance=application)
    if request.method == "POST" and form.is_valid():
        application = form.save(commit=False)
        application.aid_currency = (application.aid_currency or "USD").upper()
        application.save(update_fields=["outcome", "aid_offered", "aid_currency"])
        if application.attending and application.outcome not in Application.ADMIT_OUTCOMES:
            application.attending = False
            application.save(update_fields=["attending"])
        audit.log(request, Action.UPDATE, application, detail=f"Outcome: {application.get_outcome_display() or 'none'}")
        messages.success(request, "Decision saved.")
        return redirect("application_detail", pk=application.pk)
    return _form_page(request, form, f"Decision: {application.university}",
                      reverse("application_detail", args=[application.pk]),
                      intro="Record the university's decision and any scholarship or grant offered.")


@login_required
@require_POST
def set_attending(request, pk):
    application = get_application(request.user, pk, edit=True)
    try:
        deadlines.set_attending(application, request.user)
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
    else:
        audit.log(request, Action.UPDATE, application, detail="Marked as attending")
        messages.success(request, f"Congratulations! The after-admission checklist for {application.university} was added.")
    return redirect("student_detail", pk=application.student_id)


@login_required
def student_benchmarks(request, pk):
    student = get_student(request.user, pk)
    audit.log(request, Action.VIEW, student, detail="Benchmarks")
    apps = student.applications.filter(status__in=Application.LISTED).select_related("university")
    results = [benchmark.compare(student, app.university) for app in apps]
    return render(request, "portal/benchmarks.html", {
        "student": student, "results": results, "min_group": benchmark.min_group(),
    })


# ------------------------------------------------------------------ consent (counselor)

@login_required
@counselor_required
def consent_list(request, pk):
    student = get_student(request.user, pk)
    return render(request, "portal/consent_list.html", {"student": student, "consents": student.consents.all()})


@login_required
@counselor_required
@require_http_methods(["GET", "POST"])
def consent_form(request, pk):
    student = get_student(request.user, pk)
    form = ConsentForm(request.POST or None, instance=Consent(student=student, recorded_by=request.user))
    if request.method == "POST" and form.is_valid():
        consent = form.save()
        audit.log(request, Action.CREATE, consent)
        messages.success(request, "Consent recorded.")
        return redirect("consent_list", pk=student.pk)
    return _form_page(request, form, f"Record consent: {student}", reverse("consent_list", args=[student.pk]),
                      intro="For students under 18, consent must come from a parent or legal guardian. "
                            "Keep the signed form in your files.")


@login_required
@counselor_required
@require_POST
def consent_withdraw(request, pk):
    consent = get_object_or_404(Consent, pk=pk)
    if consent.withdrawn_on is None:
        consent.withdrawn_on = timezone.localdate()
        consent.save(update_fields=["withdrawn_on"])
        audit.log(request, Action.UPDATE, consent, detail="Consent withdrawn")
        messages.success(request, "Consent withdrawn. This student's results are no longer used in benchmarks.")
    return redirect("consent_list", pk=consent.student_id)


# ------------------------------------------------------------------ past outcomes import (counselor)

@login_required
@counselor_required
@require_http_methods(["GET", "POST"])
def outcomes_import(request):
    form = CSVUploadForm(request.POST or None, request.FILES or None)
    context = {"form": form, "columns": outcome_import.COLUMNS}
    if request.method == "POST" and form.is_valid():
        content = form.cleaned_data["content"]
        rows, problems = outcome_import.parse(content)
        if request.POST.get("confirm") == "1":
            counts = outcome_import.save(rows)
            audit.log(request, Action.CREATE, detail="Past outcomes import: " +
                      ", ".join(f"{v} {k}" for k, v in counts.items()))
            messages.success(request, f"Imported {counts['applications']} results for {counts['students']} new "
                                      f"past students ({counts['consents']} consents).")
            return redirect("student_list")
        context.update(preview=True, rows=rows, problems=problems, content=content,
                       valid_count=sum(1 for r in rows if r.ok))
    return render(request, "portal/outcomes_import.html", context)


@login_required
@counselor_required
def outcomes_import_template(request):
    response = HttpResponse(outcome_import.template_csv(), content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="past-outcomes-template.csv"'
    return response

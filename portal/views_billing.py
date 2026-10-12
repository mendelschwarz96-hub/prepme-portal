"""Billing tab. Counselor adds charges and payments; students and their parents can view them."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods

from core import audit

from . import billing
from .forms import BillingProfileForm, ChargeForm, PaymentForm
from .models import BillingProfile, Charge, Payment, StudentProfile
from .permissions import counselor_required, get_student, get_summary_student, summary_students
from .views import _confirm_page, _form_page

Action = audit.Action


@login_required
def billing_home(request):
    if request.user.is_counselor:
        return redirect("billing_overview")
    students = list(summary_students(request.user))
    if len(students) == 1:
        return redirect("billing_account", pk=students[0].pk)
    return render(request, "portal/choose_student.html", {"students": students, "target": "billing_account"})


@login_required
@counselor_required
def billing_overview(request):
    rows = []
    for student in StudentProfile.objects.prefetch_related("charges", "payments"):
        data = billing.account(student)
        if data["charges"] or data["payments"]:
            rows.append({"student": student, "balances": data["balances"],
                         "last_charge": data["charges"][0].date if data["charges"] else None})
    rows.sort(key=lambda r: (-max((b["balance"] for b in r["balances"]), default=0), str(r["student"])))
    return render(request, "portal/billing_overview.html", {"rows": rows, "profile": BillingProfile.get()})


@login_required
def billing_account(request, pk):
    student = get_summary_student(request.user, pk)
    audit.log(request, Action.VIEW, student, detail="Billing")
    return render(request, "portal/billing_account.html", {"student": student, **billing.account(student)})


@login_required
def billing_statement(request, pk, year, month):
    student = get_summary_student(request.user, pk)
    audit.log(request, Action.VIEW, student, detail=f"Statement {year}-{month:02d}")
    return render(request, "portal/billing_statement.html", {
        "student": student, "profile": BillingProfile.get(), **billing.statement(student, year, month),
    })


def _billing_item_form(request, pk, model, form_class, item_pk, label):
    student = get_student(request.user, pk)
    instance = get_object_or_404(model, pk=item_pk, student=student) if item_pk else model(student=student, created_by=request.user)
    form = form_class(request.POST or None, instance=instance)
    if request.method == "POST" and form.is_valid():
        obj = form.save()
        audit.log(request, Action.UPDATE if item_pk else Action.CREATE, obj, detail=label)
        messages.success(request, f"{label} saved.")
        if request.POST.get("then") == "another":
            return redirect(request.path)
        return redirect("billing_account", pk=student.pk)
    return render(request, "portal/billing_form.html", {
        "form": form, "student": student, "label": label, "editing": bool(item_pk),
        "cancel_url": reverse("billing_account", args=[student.pk]),
    })


def _billing_item_delete(request, pk, model, item_pk, label):
    student = get_student(request.user, pk)
    obj = get_object_or_404(model, pk=item_pk, student=student)
    back = reverse("billing_account", args=[student.pk])
    if request.method == "POST":
        audit.log(request, Action.DELETE, obj, detail=label)
        obj.delete()
        messages.success(request, f"{label} deleted.")
        return redirect(back)
    return _confirm_page(request, f"Delete {label.lower()}?", f"{obj} · {obj.currency} {obj.amount:,.2f}", back)


@login_required
@counselor_required
@require_http_methods(["GET", "POST"])
def charge_form(request, pk, item_pk=None):
    return _billing_item_form(request, pk, Charge, ChargeForm, item_pk, "Charge")


@login_required
@counselor_required
@require_http_methods(["GET", "POST"])
def charge_delete(request, pk, item_pk):
    return _billing_item_delete(request, pk, Charge, item_pk, "Charge")


@login_required
@counselor_required
@require_http_methods(["GET", "POST"])
def payment_form(request, pk, item_pk=None):
    return _billing_item_form(request, pk, Payment, PaymentForm, item_pk, "Payment")


@login_required
@counselor_required
@require_http_methods(["GET", "POST"])
def payment_delete(request, pk, item_pk):
    return _billing_item_delete(request, pk, Payment, item_pk, "Payment")


@login_required
@counselor_required
@require_http_methods(["GET", "POST"])
def billing_settings(request):
    form = BillingProfileForm(request.POST or None, instance=BillingProfile.get())
    if request.method == "POST" and form.is_valid():
        profile = form.save()
        audit.log(request, Action.UPDATE, profile, detail="Billing settings")
        messages.success(request, "Billing settings saved.")
        return redirect("billing_overview")
    return _form_page(request, form, "Billing settings", reverse("billing_overview"),
                      intro="Printed at the bottom of every statement.")

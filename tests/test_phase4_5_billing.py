"""Billing, Phase 4 (outcomes, consent, benchmarks with the minimum group size) and Phase 5 (checklist)."""
from datetime import date
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db import connection
from django.test import override_settings
from django.urls import reverse

from accounts.models import User
from portal import benchmark, billing, deadlines, outcome_import
from portal.models import (
    Application, BillingProfile, Charge, Consent, Curriculum, Payment, Round, School, StudentProfile, Task,
    TestScore, University,
)

from .conftest import YEAR

pytestmark = pytest.mark.django_db


# ===================================================================== billing

@pytest.fixture
def charges(student, counselor):
    rows = [
        (date(2026, 6, 9), 60, "Common App Brainstorm"), (date(2026, 6, 15), 60, "Presencial"),
        (date(2026, 6, 29), 30, "Carta Padre"), (date(2026, 7, 2), 60, "Presencial"),
    ]
    return [Charge.objects.create(student=student, date=d, minutes=m, description=t,
                                  amount=billing.suggested_amount(m), created_by=counselor) for d, m, t in rows]


def test_billing_profile_prefilled_from_invoice():
    profile = BillingProfile.get()
    assert profile.tax_id == "30.466.564/0001-85" and "Itaú" in profile.payment_details
    assert profile.hourly_rate == Decimal("2750.00") and profile.currency == "BRL"


def test_amount_from_minutes():
    assert billing.suggested_amount(60) == Decimal("2750.00")
    assert billing.suggested_amount(30) == Decimal("1375.00")


def test_june_statement_matches_invoice_style(client, counselor, student, charges):
    client.force_login(counselor)
    html = client.get(reverse("billing_statement", args=[student.pk, 2026, 6])).content.decode()
    assert "Carta Padre" in html and "29/06/2026" in html
    assert "R$ 6,875.00" in html  # 2,750 + 2,750 + 1,375 (July charge excluded)
    assert "30.466.564/0001-85" in html and "Conta-corrente: 14044-6" in html


def test_balance_after_payment(student, charges):
    Payment.objects.create(student=student, date=date(2026, 7, 5), amount=Decimal("6875.00"))
    data = billing.account(student)
    assert data["balances"][0]["balance"] == Decimal("2750.00")
    assert [s["start"] for s in data["statements"]] == [date(2026, 7, 1), date(2026, 6, 1)]


def test_counselor_adds_charge_with_calculated_amount(client, counselor, student):
    client.force_login(counselor)
    client.post(reverse("charge_add", args=[student.pk]),
                {"date": "2026-06-09", "minutes": "30", "description": "Carta Padre", "amount": "", "currency": "brl"})
    charge = Charge.objects.get()
    assert charge.amount == Decimal("1375.00") and charge.currency == "BRL"


def test_charge_description_encrypted(charges):
    with connection.cursor() as cursor:
        cursor.execute("SELECT description FROM portal_charge")
        assert all(row[0].startswith("enc1:") for row in cursor.fetchall())


def test_student_and_parent_can_view_billing(client, student, student_user, parent_user, charges):
    for user in (student_user, parent_user):
        client.force_login(user)
        assert client.get(reverse("billing_home"))["Location"] == reverse("billing_account", args=[student.pk])
        html = client.get(reverse("billing_account", args=[student.pk])).content.decode()
        assert "Presencial" in html and "Add charge" not in html
        assert client.get(reverse("billing_statement", args=[student.pk, 2026, 6])).status_code == 200


def test_students_and_parents_cannot_change_billing(client, student, student_user, parent_user, charges):
    for user in (student_user, parent_user):
        client.force_login(user)
        assert client.post(reverse("charge_add", args=[student.pk]), {"description": "x", "amount": "1"}).status_code == 403
        assert client.post(reverse("charge_delete", args=[student.pk, charges[0].pk])).status_code == 403
        assert client.post(reverse("payment_add", args=[student.pk]), {"amount": "99999"}).status_code == 403
        assert client.get(reverse("billing_overview")).status_code == 403
        assert client.get(reverse("billing_settings")).status_code == 403
    assert Charge.objects.count() == 4 and not Payment.objects.exists()


def test_other_families_cannot_see_billing(client, student, other_student_user, charges):
    other_parent = User.objects.create_user("p2@test.dev", "pw", role=User.Role.PARENT)
    for user in (other_student_user, other_parent):
        client.force_login(user)
        assert client.get(reverse("billing_account", args=[student.pk])).status_code == 404
        assert client.get(reverse("billing_statement", args=[student.pk, 2026, 6])).status_code == 404


def test_billing_pages_render_for_counselor(client, counselor, student, charges):
    client.force_login(counselor)
    for url in [reverse("billing_overview"), reverse("billing_settings"), reverse("charge_add", args=[student.pk]),
                reverse("charge_edit", args=[student.pk, charges[0].pk]), reverse("payment_add", args=[student.pk]),
                reverse("billing_account", args=[student.pk])]:
        assert client.get(url).status_code == 200, url


# ===================================================================== outcomes & checklist

@pytest.fixture
def admitted_app(student, counselor, common_app_uni):
    app = deadlines.add_school(student, common_app_uni, YEAR, Round.RD, counselor)
    app.outcome = Application.Outcome.ADMITTED
    app.save()
    return app


def test_student_records_outcome(client, student_user, admitted_app):
    client.force_login(student_user)
    client.post(reverse("outcome_edit", args=[admitted_app.pk]),
                {"outcome": "admitted", "aid_offered": "25000", "aid_currency": "usd"})
    admitted_app.refresh_from_db()
    assert admitted_app.aid_offered == 25000 and admitted_app.aid_currency == "USD"


def test_parent_cannot_record_outcome(client, parent_user, admitted_app):
    client.force_login(parent_user)
    assert client.post(reverse("outcome_edit", args=[admitted_app.pk]), {"outcome": "denied"}).status_code == 404


def test_attending_creates_checklist(student, counselor, admitted_app):
    deadlines.set_attending(admitted_app, counselor)
    titles = list(Task.objects.filter(source=Task.Source.AFTER_ADMISSION).values_list("title", flat=True))
    assert len(titles) == 4
    assert any("deposit" in t for t in titles) and any("I-20" in t for t in titles)
    assert any("visa appointment" in t for t in titles) and any("housing" in t for t in titles)
    deadlines.set_attending(admitted_app, counselor)  # idempotent
    assert Task.objects.filter(source=Task.Source.AFTER_ADMISSION).count() == 4


def test_ucas_checklist_uses_cas(student, counselor, ucas_uni):
    app = deadlines.add_school(student, ucas_uni, YEAR, Round.UCAS, counselor)
    app.outcome = Application.Outcome.CONDITIONAL
    app.save()
    deadlines.set_attending(app, counselor)
    assert Task.objects.filter(title__contains="CAS").exists()


def test_switching_attending_school(student, counselor, admitted_app, ucas_uni):
    other = deadlines.add_school(student, ucas_uni, YEAR, Round.UCAS, counselor)
    other.outcome = Application.Outcome.ADMITTED
    other.save()
    deadlines.set_attending(admitted_app, counselor)
    deadlines.set_attending(other, counselor)
    admitted_app.refresh_from_db()
    assert not admitted_app.attending
    assert not admitted_app.tasks.filter(source=Task.Source.AFTER_ADMISSION, archived=False).exists()


def test_cannot_attend_without_admission(student, counselor, common_app_uni):
    app = deadlines.add_school(student, common_app_uni, YEAR, Round.RD, counselor)
    with pytest.raises(ValidationError):
        deadlines.set_attending(app, counselor)


# ===================================================================== benchmarks

def past_student(n, university, outcome, *, sat=None, ib=None, curriculum=Curriculum.IB, school=None, gpa="",
                 scale="", consent=True, aid=None):
    s = StudentProfile.objects.create(first_name=f"Past{n}", last_name="X", home_country="Brazil",
                                      curriculum=curriculum, graduation_year=2024, school=school, gpa=gpa,
                                      gpa_scale=scale, is_active=False)
    if sat:
        TestScore.objects.create(student=s, test=TestScore.Test.SAT, score=str(sat))
    if ib:
        TestScore.objects.create(student=s, test=TestScore.Test.IB_FINAL, score=str(ib))
    Application.objects.create(student=s, university=university, entry_year=2024, round=Round.RD,
                               status=Application.Status.ACTIVE, outcome=outcome, aid_offered=aid)
    if consent:
        Consent.objects.create(student=s, kind=Consent.Kind.ANONYMIZED_OUTCOMES, given_by="parent",
                               given_by_name="Parent", given_on=date(2024, 1, 1))
    return s


@pytest.fixture
def me(student):
    TestScore.objects.create(student=student, test=TestScore.Test.SAT, score="1450")
    TestScore.objects.create(student=student, test=TestScore.Test.IB_PREDICTED, score="40")
    return student


def section(result, key):
    return next(s for s in result["sections"] if s["key"] == key)


def test_group_below_minimum_is_hidden(me, common_app_uni):
    past_student(1, common_app_uni, "admitted", sat=1500)
    past_student(2, common_app_uni, "admitted", sat=1520)
    result = benchmark.compare(me, common_app_uni)
    assert section(result, "sat")["groups"] == []


def test_group_at_minimum_is_shown(me, common_app_uni):
    for i, sat in enumerate([1500, 1520, 1480]):
        past_student(i, common_app_uni, "admitted", sat=sat)
    past_student(9, common_app_uni, "denied", sat=1300)  # only 1 denied: hidden
    groups = section(benchmark.compare(me, common_app_uni), "sat")["groups"]
    assert [(g["label"], g["count"], g["median"]) for g in groups] == [("Admitted", 3, 1500)]
    assert groups[0]["position"] == "below"


@override_settings(BENCHMARK_MIN_GROUP=5)
def test_minimum_is_configurable(me, common_app_uni):
    for i in range(4):
        past_student(i, common_app_uni, "admitted", sat=1500)
    assert section(benchmark.compare(me, common_app_uni), "sat")["groups"] == []


def test_students_without_consent_excluded(me, common_app_uni):
    past_student(1, common_app_uni, "admitted", sat=1500)
    past_student(2, common_app_uni, "admitted", sat=1500)
    past_student(3, common_app_uni, "admitted", sat=1500, consent=False)
    assert section(benchmark.compare(me, common_app_uni), "sat")["groups"] == []


def test_withdrawn_consent_excluded(me, common_app_uni):
    people = [past_student(i, common_app_uni, "admitted", sat=1500) for i in range(3)]
    assert section(benchmark.compare(me, common_app_uni), "sat")["groups"]
    Consent.objects.filter(student=people[0]).update(withdrawn_on=date(2026, 1, 1))
    assert section(benchmark.compare(me, common_app_uni), "sat")["groups"] == []


def test_ib_compared_only_with_ib_students(me, common_app_uni):
    for i in range(2):
        past_student(i, common_app_uni, "admitted", ib=41)
    past_student(5, common_app_uni, "admitted", ib=41, curriculum=Curriculum.BRAZIL)
    assert section(benchmark.compare(me, common_app_uni), "ib")["groups"] == []
    past_student(6, common_app_uni, "admitted", ib=42)
    assert section(benchmark.compare(me, common_app_uni), "ib")["groups"][0]["count"] == 3


def test_gpa_only_same_school_and_scale(student, common_app_uni):
    mine = School.objects.create(name="Mine", country="Brazil")
    other = School.objects.create(name="Other", country="Brazil")
    student.school, student.gpa, student.gpa_scale = mine, "8.5", "0-10"
    student.save()
    past_student(1, common_app_uni, "admitted", school=mine, gpa="9.0", scale="0-10")
    past_student(2, common_app_uni, "admitted", school=mine, gpa="8.8", scale="0-10")
    past_student(3, common_app_uni, "admitted", school=other, gpa="9.5", scale="0-10")
    past_student(4, common_app_uni, "admitted", school=mine, gpa="3.9", scale="4.0")
    assert section(benchmark.compare(student, common_app_uni), "gpa")["groups"] == []
    past_student(5, common_app_uni, "admitted", school=mine, gpa="9.2", scale="0-10")
    assert section(benchmark.compare(student, common_app_uni), "gpa")["groups"][0]["count"] == 3


def test_each_past_student_counted_once(me, common_app_uni):
    s = past_student(1, common_app_uni, "admitted", sat=1500)
    Application.objects.create(student=s, university=common_app_uni, entry_year=2025, round=Round.RD,
                               status=Application.Status.ACTIVE, outcome="admitted")
    past_student(2, common_app_uni, "admitted", sat=1500)
    assert section(benchmark.compare(me, common_app_uni), "sat")["groups"] == []


def test_current_student_excluded_from_own_benchmark(me, counselor, common_app_uni):
    for i in range(2):
        past_student(i, common_app_uni, "admitted", sat=1500)
    app = deadlines.add_school(me, common_app_uni, YEAR, Round.RD, counselor)
    app.outcome = "admitted"
    app.save()
    Consent.objects.create(student=me, kind=Consent.Kind.ANONYMIZED_OUTCOMES, given_by="parent",
                           given_by_name="P", given_on=date(2026, 1, 1))
    assert section(benchmark.compare(me, common_app_uni), "sat")["groups"] == []


def test_aid_shown_only_with_enough_students(me, common_app_uni):
    for i in range(2):
        past_student(i, common_app_uni, "admitted", sat=1500, aid=20000)
    assert benchmark.compare(me, common_app_uni)["aid"] is None
    past_student(3, common_app_uni, "admitted", sat=1500, aid=30000)
    assert benchmark.compare(me, common_app_uni)["aid"] == {"median": 20000, "count": 3}


def test_benchmark_page_shows_no_names_or_schools(client, me, student_user, counselor, common_app_uni):
    school = School.objects.create(name="Secret High", country="Brazil")
    deadlines.add_school(me, common_app_uni, YEAR, Round.RD, counselor)
    for i in range(3):
        past_student(i, common_app_uni, "admitted", sat=1500, school=school)
    client.force_login(student_user)
    html = client.get(reverse("student_benchmarks", args=[me.pk])).content.decode()
    assert "median 1500" in html
    assert "Past0" not in html and "Secret High" not in html


def test_parents_and_other_students_cannot_see_benchmarks(client, me, parent_user, other_student_user):
    for user in (parent_user, other_student_user):
        client.force_login(user)
        assert client.get(reverse("student_benchmarks", args=[me.pk])).status_code == 404


# ===================================================================== past outcomes import & consent

OUTCOMES_CSV = (
    "first_name,last_name,graduation_year,curriculum,high_school,gpa,gpa_scale,ib_total,sat,university,"
    "university_country,entry_year,round,outcome,aid_offered,consent_given_by,consent_name,consent_date\n"
    "Joao,Silva,2025,ib,Escola A,8.9,0-10,40,1480,Sample U,United States,2025,rd,admitted,20000,parent,Maria Silva,2025-06-01\n"
    "Joao,Silva,2025,ib,Escola A,8.9,0-10,40,1480,New College,United States,2025,ea,denied,,parent,Maria Silva,2025-06-01\n"
    "Bia,Costa,2024,ib,,,,38,,Sample U,United States,2024,rd,waitlisted,,,,\n"
    "Bad,Row,2024,ib,,,,50,,Sample U,United States,2024,rd,maybe,,,,\n"
)


def test_outcomes_import(common_app_uni):
    rows, problems = outcome_import.parse(OUTCOMES_CSV)
    assert [r.ok for r in rows] == [True, True, True, False]
    counts = outcome_import.save(rows)
    assert counts == {"students": 2, "applications": 3, "consents": 1, "universities": 1}
    joao = StudentProfile.objects.get(first_name="Joao")
    assert not joao.is_active and joao.user is None
    assert joao.applications.count() == 2 and joao.consents.count() == 1
    assert not StudentProfile.objects.get(first_name="Bia").consents.exists()


def test_outcomes_import_preview_then_confirm(client, counselor, common_app_uni):
    client.force_login(counselor)
    html = client.post(reverse("outcomes_import"), {"content": OUTCOMES_CSV}).content.decode()
    assert "3 of 4 rows ready" in html and not StudentProfile.objects.exists()
    client.post(reverse("outcomes_import"), {"content": OUTCOMES_CSV, "confirm": "1"})
    assert StudentProfile.objects.count() == 2


def test_consent_record_and_withdraw(client, counselor, student):
    client.force_login(counselor)
    client.post(reverse("consent_add", args=[student.pk]), {
        "kind": "anonymized_outcomes", "given_by": "parent", "given_by_name": "Mom", "given_on": "2026-10-01",
        "text_version": "2026-1"})
    consent = Consent.objects.get()
    client.post(reverse("consent_withdraw", args=[consent.pk]))
    consent.refresh_from_db()
    assert consent.withdrawn_on is not None


def test_only_counselor_manages_consent_and_imports(client, student_user, student):
    client.force_login(student_user)
    assert client.get(reverse("consent_list", args=[student.pk])).status_code == 403
    assert client.get(reverse("outcomes_import")).status_code == 403


def test_decision_to_checklist_over_http(client, student, student_user, counselor, admitted_app):
    client.force_login(student_user)
    html = client.get(reverse("application_detail", args=[admitted_app.pk])).content.decode()
    assert "will attend" in html
    client.post(reverse("set_attending", args=[admitted_app.pk]))
    html = client.get(reverse("student_detail", args=[student.pk])).content.decode()
    assert "After admission: Sample U" in html and "Pay enrollment deposit" in html
    client.force_login(counselor)
    assert client.get(reverse("outcome_edit", args=[admitted_app.pk])).status_code == 200
    assert client.get(reverse("consent_list", args=[student.pk])).status_code == 200
    assert client.get(reverse("outcomes_import")).status_code == 200
    summary = client.get(reverse("student_summary", args=[student.pk])).content.decode()
    assert "Attending" in summary
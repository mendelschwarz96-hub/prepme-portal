"""Phase 3: College Scorecard import, CSV import, filters, compare and permissions.
The Scorecard API is mocked; tests never call the internet."""
from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from portal import csv_import, scorecard
from portal.forms import UniversityFilterForm
from portal.models import University

pytestmark = pytest.mark.django_db

STANFORD = {
    "id": 243744, "school.name": "Stanford University", "school.city": "Stanford", "school.state": "CA",
    "school.school_url": "www.stanford.edu/", "school.ownership": 2,
    "latest.admissions.admission_rate.overall": 0.0361,
    "latest.admissions.sat_scores.25th_percentile.critical_reading": 740,
    "latest.admissions.sat_scores.75th_percentile.critical_reading": 780,
    "latest.admissions.sat_scores.25th_percentile.math": 770,
    "latest.admissions.sat_scores.75th_percentile.math": 800,
    "latest.admissions.act_scores.25th_percentile.cumulative": 34,
    "latest.admissions.act_scores.75th_percentile.cumulative": 35,
    "latest.admissions.test_requirements": 5,
    "latest.student.size": 7554,
    "latest.student.demographics.race_ethnicity.non_resident_alien": 0.1277,
    "latest.cost.attendance.academic_year": 87833,
    "latest.cost.tuition.out_of_state": 65910,
    "latest.completion.completion_rate_4yr_150nt": 0.9192,
    "latest.earnings.10_yrs_after_entry.median": 124080,
}


@pytest.fixture
def api(monkeypatch):
    """Fake Scorecard API. `api.records` holds what it returns; `api.calls` records params."""
    class Fake:
        records = {STANFORD["id"]: dict(STANFORD)}
        calls = []
        error = None

    def fake_get(params):
        Fake.calls.append(params)
        if Fake.error:
            raise scorecard.ScorecardError(Fake.error)
        if "id" in params:
            ids = {int(x) for x in str(params["id"]).split(",")}
            return {"results": [r for i, r in Fake.records.items() if i in ids]}
        name = params.get("school.name", "").lower()
        return {"results": [r for r in Fake.records.values() if name in r["school.name"].lower()]}

    monkeypatch.setattr(scorecard, "_get", fake_get)
    return Fake


# ------------------------------------------------------------- Scorecard mapping

def test_scorecard_values_mapped():
    v = scorecard.values_from(STANFORD)
    assert v["admit_rate"] == Decimal("0.0361")
    assert (v["sat_25"], v["sat_75"]) == (1510, 1580)  # reading + math
    assert (v["act_25"], v["act_75"]) == (34, 35)
    assert v["test_policy"] == University.TestPolicy.CONSIDERED
    assert v["ownership"] == University.Ownership.PRIVATE_NONPROFIT
    assert v["website"] == "https://www.stanford.edu/"
    assert v["cost_of_attendance"] == 87833


def test_missing_values_stay_blank():
    v = scorecard.values_from({"id": 1, "school.name": "X"})
    assert v["admit_rate"] is None and v["sat_25"] is None and v["test_policy"] == ""


def test_import_creates_school(api):
    university, created = scorecard.import_school(243744)
    assert created and university.name == "Stanford University" and university.country == "United States"
    assert university.scorecard_id == 243744 and university.scorecard_synced_at


def test_import_links_existing_manual_entry(api):
    manual = University.objects.create(name="Stanford University", country="United States", toefl_min=100)
    university, created = scorecard.import_school(243744)
    assert university.pk == manual.pk and university.toefl_min == 100


def test_refresh_never_touches_counselor_fields(api):
    university, _ = scorecard.import_school(243744)
    university.intl_aid_policy = University.AidPolicy.NEED_BLIND
    university.toefl_min = 100
    university.intl_admit_rate = Decimal("0.02")
    university.save()
    api.records[243744]["latest.admissions.admission_rate.overall"] = 0.0400
    updated, missing = scorecard.refresh_all()
    university.refresh_from_db()
    assert updated == 1 and not missing
    assert university.admit_rate == Decimal("0.04")
    assert university.intl_aid_policy == University.AidPolicy.NEED_BLIND
    assert university.toefl_min == 100 and university.intl_admit_rate == Decimal("0.02")


def test_refresh_reports_missing(api):
    University.objects.create(name="Closed College", country="United States", scorecard_id=999)
    _, missing = scorecard.refresh_all()
    assert missing == ["Closed College"]


def test_scorecard_errors_shown_not_crashing(client, counselor, api):
    api.error = "The College Scorecard rate limit was reached."
    client.force_login(counselor)
    response = client.get(reverse("scorecard_search") + "?q=stanford")
    assert response.status_code == 200 and "rate limit" in response.content.decode()


def test_counselor_adds_school_from_search(client, counselor, api):
    client.force_login(counselor)
    html = client.get(reverse("scorecard_search") + "?q=stanford").content.decode()
    assert "Stanford University" in html
    response = client.post(reverse("scorecard_add"), {"scorecard_id": "243744"})
    university = University.objects.get(scorecard_id=243744)
    assert response["Location"] == reverse("university_detail", args=[university.pk])


# ------------------------------------------------------------- editing

def test_scorecard_fields_locked_in_edit_form(client, counselor, api):
    university, _ = scorecard.import_school(243744)
    client.force_login(counselor)
    client.post(reverse("university_edit", args=[university.pk]), {
        "name": university.name, "country": "United States", "application_system": "common_app",
        "admit_rate": "50", "sat_25": "400", "cost_currency": "USD",
        "intl_aid_policy": "need_aware", "toefl_min": "100", "ielts_min": "7.0",
    })
    university.refresh_from_db()
    assert university.admit_rate == Decimal("0.0361")  # unchanged: from the Scorecard
    assert university.sat_25 == 1510
    assert university.intl_aid_policy == "need_aware" and university.toefl_min == 100
    assert university.profile_updated_at is not None


def test_percent_entered_as_percentage(client, counselor):
    client.force_login(counselor)
    client.post(reverse("university_create"), {
        "name": "Oxford", "country": "United Kingdom", "application_system": "ucas", "cost_currency": "gbp",
        "admit_rate": "14.5", "intl_admit_rate": "9",
    })
    oxford = University.objects.get(name="Oxford")
    assert oxford.admit_rate == Decimal("0.145") and oxford.intl_admit_rate == Decimal("0.09")
    assert oxford.cost_currency == "GBP"


# ------------------------------------------------------------- CSV import

CSV = (
    "name,country,application_system,admit_rate,tuition,cost_currency,intl_aid_policy,merit_aid,ielts_min,oxbridge\n"
    "University of Oxford,United Kingdom,ucas,14.5,48620,GBP,no_need_aid,limited,7.5,yes\n"
    "Leiden University,Netherlands,direct,,15000,EUR,,,6.5,\n"
    "Bad Row,United Kingdom,ucas,250,,,,,,\n"
)


def test_csv_preview_saves_nothing(client, counselor):
    client.force_login(counselor)
    response = client.post(reverse("university_import"), {"file": SimpleUploadedFile("u.csv", CSV.encode())})
    html = response.content.decode()
    assert "2 of 3 rows ready" in html
    assert not University.objects.exists()


def test_csv_import_creates_and_reports_errors(client, counselor):
    client.force_login(counselor)
    client.post(reverse("university_import"), {"content": CSV, "confirm": "1"})
    oxford = University.objects.get(name="University of Oxford")
    assert oxford.oxbridge and oxford.admit_rate == Decimal("0.145") and oxford.tuition == 48620
    assert oxford.merit_aid == "limited" and oxford.ielts_min == Decimal("7.5")
    assert University.objects.filter(name="Leiden University", cost_currency="EUR").exists()
    assert not University.objects.filter(name="Bad Row").exists()


def test_csv_blank_cells_keep_existing_values(counselor):
    University.objects.create(name="Leiden University", country="Netherlands", application_system="direct",
                              toefl_min=90, admit_rate=Decimal("0.5"))
    rows, _ = csv_import.parse("name,country,ielts_min\nLeiden University,Netherlands,6.5\n")
    csv_import.save(rows)
    leiden = University.objects.get(name="Leiden University")
    assert leiden.toefl_min == 90 and leiden.admit_rate == Decimal("0.5") and leiden.ielts_min == Decimal("6.5")


def test_csv_cannot_overwrite_scorecard_fields(api):
    scorecard.import_school(243744)
    rows, _ = csv_import.parse("name,country,admit_rate,toefl_min\nStanford University,United States,90,100\n")
    assert rows[0].ok and rows[0].ignored == ["admit_rate"]
    csv_import.save(rows)
    stanford = University.objects.get(scorecard_id=243744)
    assert stanford.admit_rate == Decimal("0.0361") and stanford.toefl_min == 100


def test_csv_duplicate_rows_rejected():
    rows, _ = csv_import.parse("name,country\nA,UK\nA,UK\n")
    assert rows[0].ok and not rows[1].ok


def test_csv_requires_name_and_country():
    rows, problems = csv_import.parse("title,place\nA,UK\n")
    assert not rows and "Missing required column" in problems[0]


# ------------------------------------------------------------- filter & compare

@pytest.fixture
def catalog(db):
    U = University
    return {
        "blind": U.objects.create(name="Blind College", country="United States", admit_rate=Decimal("0.05"),
                                  intl_aid_policy="need_blind", sat_25=1500, sat_75=1570, cost_of_attendance=90000,
                                  test_policy="required", toefl_min=100),
        "aware": U.objects.create(name="Aware University", country="United States", admit_rate=Decimal("0.20"),
                                  intl_aid_policy="need_aware", merit_aid="yes", sat_25=1300, sat_75=1450,
                                  cost_of_attendance=70000, test_policy="considered"),
        "uk": U.objects.create(name="UK Uni", country="United Kingdom", application_system="ucas",
                               admit_rate=Decimal("0.60"), tuition=30000, cost_currency="GBP", ielts_min=Decimal("7.0")),
    }


def names(data):
    form = UniversityFilterForm(data)
    return [u.name for u in form.apply(University.objects.all())]


def test_filters(catalog):
    assert names({"max_admit": "10"}) == ["Blind College"]
    assert names({"aid": "need_blind"}) == ["Blind College"]
    assert set(names({"aid": "any"})) == {"Blind College", "Aware University"}
    assert names({"merit": "on"}) == ["Aware University"]
    assert names({"max_cost": "80000"}) == ["Aware University"]  # UK school has no USD cost
    assert names({"test_optional": "on"}) == ["Aware University"]
    assert names({"sat": "1350"}) == ["Aware University"]
    assert names({"system": "ucas"}) == ["UK Uni"]
    assert names({"country": "United Kingdom"}) == ["UK Uni"]


def test_english_filter_keeps_unknown(catalog):
    # TOEFL 95: Blind College (min 100) excluded; others have no TOEFL minimum recorded -> kept.
    assert set(names({"toefl": "95"})) == {"Aware University", "UK Uni"}
    assert set(names({"ielts": "6.5"})) == {"Blind College", "Aware University"}


def test_sorting_puts_unknown_last(catalog):
    University.objects.create(name="No Data College", country="United States")
    assert names({"sort": "admit_rate"}) == ["Blind College", "Aware University", "UK Uni", "No Data College"]


def test_compare_page(client, student_user, student, catalog):
    client.force_login(student_user)
    url = reverse("university_compare") + f"?id={catalog['blind'].pk}&id={catalog['uk'].pk}"
    html = client.get(url).content.decode()
    assert "Blind College" in html and "UK Uni" in html and "£30,000" in html


def test_compare_needs_two(client, student_user, student, catalog):
    client.force_login(student_user)
    assert client.get(reverse("university_compare") + f"?id={catalog['blind'].pk}").status_code == 302


# ------------------------------------------------------------- permissions

def test_students_can_browse_but_not_edit(client, student_user, student, catalog, api):
    client.force_login(student_user)
    assert client.get(reverse("university_list") + "?aid=any").status_code == 200
    html = client.get(reverse("university_detail", args=[catalog["blind"].pk])).content.decode()
    assert "Students with this school" not in html  # other students are never shown
    for url in [reverse("university_create"), reverse("university_edit", args=[catalog["blind"].pk]),
                reverse("university_import"), reverse("scorecard_search")]:
        assert client.get(url).status_code == 403, url
    assert client.post(reverse("scorecard_add"), {"scorecard_id": "243744"}).status_code == 403
    assert client.post(reverse("scorecard_refresh_all")).status_code == 403
    assert not University.objects.filter(scorecard_id=243744).exists()


def test_parents_cannot_browse(client, parent_user, student, catalog):
    client.force_login(parent_user)
    assert client.get(reverse("university_list")).status_code == 403
    assert client.get(reverse("university_detail", args=[catalog["blind"].pk])).status_code == 403


def test_counselor_pages_render(client, counselor, catalog, api):
    scorecard.import_school(243744)
    client.force_login(counselor)
    for url in [reverse("university_list"), reverse("university_list") + "?sort=-sat_75&q=c",
                reverse("university_detail", args=[catalog["uk"].pk]), reverse("university_import"),
                reverse("scorecard_search"), reverse("university_import_template")]:
        assert client.get(url).status_code == 200, url

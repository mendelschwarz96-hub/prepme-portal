"""Import past students' application results from CSV (for benchmarking).

One row per application. Students are matched by first name + last name + graduation year;
past students are created as inactive records without a login. A row may also record the
family's consent to use the results anonymously; without consent, the results are stored
but never used in benchmarks.
"""
import csv
import io
from datetime import datetime

from django.db import transaction

from .models import (
    Application, Consent, Curriculum, Round, School, StudentProfile, TestScore, University, rounds_for_system,
)

COLUMNS = [
    "first_name", "last_name", "graduation_year", "home_country", "curriculum", "high_school", "high_school_city",
    "gpa", "gpa_scale", "ib_total", "sat", "act", "university", "university_country", "entry_year", "round",
    "outcome", "aid_offered", "aid_currency", "consent_given_by", "consent_name", "consent_date",
]
REQUIRED = ["first_name", "last_name", "graduation_year", "curriculum", "university", "university_country",
            "entry_year", "round", "outcome"]
EXAMPLE = {
    "first_name": "Example", "last_name": "Student", "graduation_year": "2025", "home_country": "Brazil",
    "curriculum": "ib", "high_school": "Example School", "high_school_city": "São Paulo", "gpa": "8.7",
    "gpa_scale": "0-10", "ib_total": "40", "sat": "1480", "act": "", "university": "Boston University",
    "university_country": "United States", "entry_year": "2025", "round": "rd", "outcome": "admitted",
    "aid_offered": "20000", "aid_currency": "USD", "consent_given_by": "parent", "consent_name": "Parent Name",
    "consent_date": "2025-06-01",
}
MAX_ROWS = 3000


def template_csv():
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=COLUMNS)
    writer.writeheader()
    writer.writerow(EXAMPLE)
    return out.getvalue()


class Row:
    def __init__(self, number, data):
        self.number, self.data, self.errors, self.notes = number, data, [], []
        self.university = None

    @property
    def ok(self):
        return not self.errors


def _int(row, name, low=None, high=None, required=False):
    raw = row.data.get(name, "")
    if raw == "":
        if required:
            row.errors.append(f"{name} is required.")
        return None
    try:
        value = int(float(raw.replace(",", ".")))
    except ValueError:
        row.errors.append(f"{name}: '{raw}' is not a number.")
        return None
    if (low is not None and value < low) or (high is not None and value > high):
        row.errors.append(f"{name}: {value} is out of range.")
        return None
    return value


def _date(row, name):
    raw = row.data.get(name, "")
    if not raw:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    row.errors.append(f"{name}: use YYYY-MM-DD or DD/MM/YYYY.")
    return None


def _validate(row):
    d = row.data
    for name in REQUIRED:
        if not d.get(name):
            row.errors.append(f"{name} is required.")
    if d.get("curriculum") and d["curriculum"] not in Curriculum.values:
        row.errors.append(f"curriculum must be one of: {', '.join(Curriculum.values)}.")
    if d.get("round") and d["round"] not in Round.values:
        row.errors.append(f"round must be one of: {', '.join(Round.values)}.")
    if d.get("outcome") and d["outcome"] not in Application.Outcome.values:
        row.errors.append(f"outcome must be one of: {', '.join(Application.Outcome.values)}.")
    row.graduation_year = _int(row, "graduation_year", 1990, 2100, required=True)
    row.entry_year = _int(row, "entry_year", 1990, 2100, required=True)
    row.sat = _int(row, "sat", 400, 1600)
    row.act = _int(row, "act", 1, 36)
    row.ib = _int(row, "ib_total", 0, 45)
    row.aid = _int(row, "aid_offered", 0)
    row.consent_date = _date(row, "consent_date")
    if d.get("consent_date") or d.get("consent_name"):
        if not (d.get("consent_name") and d.get("consent_date") and d.get("consent_given_by") in Consent.GivenBy.values):
            row.errors.append("Consent needs consent_given_by (student/parent), consent_name and consent_date.")
    else:
        row.notes.append("No consent: stored, but not used in benchmarks.")
    if d.get("university") and d.get("university_country"):
        row.university = University.objects.filter(
            name__iexact=d["university"], country__iexact=d["university_country"]
        ).first()
        if row.university is None:
            row.notes.append(f"New university will be added: {d['university']}.")
        elif d.get("round") and d["round"] not in _rounds(row.university.application_system):
            row.errors.append(f"{d['round']} is not a round for {row.university}.")


def _rounds(system):
    return [r.value for r in rounds_for_system(system)]


def parse(content):
    reader = csv.DictReader(io.StringIO(content))
    if not reader.fieldnames:
        return [], ["The file is empty."]
    header = [h.strip() for h in reader.fieldnames]
    missing = [h for h in REQUIRED if h not in header]
    if missing:
        return [], [f"Missing required column(s): {', '.join(missing)}."]
    rows, problems = [], []
    for number, raw in enumerate(reader, start=2):
        if number - 1 > MAX_ROWS:
            problems.append(f"Only the first {MAX_ROWS} rows were read.")
            break
        data = {(k or "").strip(): (v or "").strip() for k, v in raw.items()}
        if not any(data.values()):
            continue
        for key in ("curriculum", "round", "outcome", "consent_given_by"):
            data[key] = data.get(key, "").lower()
        row = Row(number, data)
        _validate(row)
        rows.append(row)
    return rows, problems


@transaction.atomic
def save(rows):
    """Save valid rows. Returns counts."""
    counts = {"students": 0, "applications": 0, "consents": 0, "universities": 0}
    for row in rows:
        if not row.ok:
            continue
        d = row.data
        university = row.university
        if university is None:
            university, created = University.objects.get_or_create(
                name=d["university"], country=d["university_country"],
                defaults={"application_system": University.System.UCAS if d["round"] == Round.UCAS
                          else University.System.COMMON_APP},
            )
            counts["universities"] += created
        school = None
        if d.get("high_school"):
            school, _ = School.objects.get_or_create(
                name=d["high_school"], city=d.get("high_school_city", ""), country=d.get("home_country") or "Brazil"
            )
        student = StudentProfile.objects.filter(
            first_name__iexact=d["first_name"], last_name__iexact=d["last_name"], graduation_year=row.graduation_year
        ).first()
        if student is None:
            student = StudentProfile.objects.create(
                first_name=d["first_name"], last_name=d["last_name"], graduation_year=row.graduation_year,
                home_country=d.get("home_country") or "Brazil", curriculum=d["curriculum"], school=school,
                gpa=d.get("gpa", ""), gpa_scale=d.get("gpa_scale", ""), is_active=False,
            )
            counts["students"] += 1
        for test, value in ((TestScore.Test.SAT, row.sat), (TestScore.Test.ACT, row.act), (TestScore.Test.IB_FINAL, row.ib)):
            if value is not None and not any(
                s.test == test and s.score == str(value) for s in student.test_scores.all()
            ):
                TestScore.objects.create(student=student, test=test, score=str(value))
        application = Application.objects.filter(
            student=student, university=university, entry_year=row.entry_year
        ).exclude(status__in=[Application.Status.REMOVED, Application.Status.DECLINED]).first()
        if application is None:
            application = Application(student=student, university=university, entry_year=row.entry_year,
                                      status=Application.Status.ACTIVE)
            counts["applications"] += 1
        application.round = d["round"]
        application.outcome = d["outcome"]
        application.aid_offered = row.aid
        application.aid_currency = (d.get("aid_currency") or "USD").upper()
        application.save()
        if row.consent_date and not student.consents.filter(
            kind=Consent.Kind.ANONYMIZED_OUTCOMES, withdrawn_on__isnull=True
        ).exists():
            Consent.objects.create(
                student=student, kind=Consent.Kind.ANONYMIZED_OUTCOMES, given_by=d["consent_given_by"],
                given_by_name=d["consent_name"], given_on=row.consent_date, text_version="imported",
            )
            counts["consents"] += 1
    return counts

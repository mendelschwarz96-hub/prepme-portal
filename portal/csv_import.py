"""Import university data from a CSV file (for schools not in the U.S. College Scorecard,
and for international fields the Scorecard doesn't have).

Rows are matched to existing universities by name + country; otherwise a new one is created.
Percent columns take percentages (12.5 means 12.5%). Blank cells leave existing values unchanged.
"""
import csv
import io
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from .forms import UNIVERSITY_FIELDS, UniversityForm
from .models import University

MAX_ROWS = 2000
TEMPLATE_HEADER = UNIVERSITY_FIELDS
TEMPLATE_EXAMPLE = {
    "name": "Example University", "country": "United Kingdom", "city": "London", "application_system": "ucas",
    "oxbridge": "no", "website": "https://www.example.ac.uk", "admit_rate": "15", "tuition": "30000",
    "cost_currency": "GBP", "intl_aid_policy": "no_need_aid", "merit_aid": "limited", "ielts_min": "7.0",
    "toefl_min": "100", "english_notes": "Example row; delete before importing",
}
BOOLEAN_TRUE = {"yes", "y", "true", "1", "x"}


def template_csv():
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=TEMPLATE_HEADER)
    writer.writeheader()
    writer.writerow(TEMPLATE_EXAMPLE)
    return out.getvalue()


class Row:
    def __init__(self, number, data, form, instance):
        self.number = number
        self.data = data
        self.form = form
        self.instance = instance

    @property
    def ok(self):
        return self.form.is_valid()

    @property
    def action(self):
        return "update" if self.instance.pk else "create"

    @property
    def errors(self):
        return [f"{name}: {', '.join(msgs)}" if name != "__all__" else ", ".join(msgs)
                for name, msgs in self.form.errors.items()]

    @property
    def ignored(self):
        """Columns that were filled in but can't be changed (Scorecard-managed)."""
        return [name for name, field in self.form.fields.items() if field.disabled and self.data.get(name) not in ("", None)]


def parse(content):
    """Return (rows, problems). Nothing is saved."""
    reader = csv.DictReader(io.StringIO(content))
    if not reader.fieldnames:
        return [], ["The file is empty."]
    header = [h.strip() for h in reader.fieldnames]
    missing = [h for h in ("name", "country") if h not in header]
    unknown = [h for h in header if h and h not in UNIVERSITY_FIELDS]
    problems = []
    if missing:
        return [], [f"Missing required column(s): {', '.join(missing)}."]
    if unknown:
        problems.append(f"Ignored unknown column(s): {', '.join(unknown)}.")

    rows, seen = [], set()
    for number, raw in enumerate(reader, start=2):
        if number - 1 > MAX_ROWS:
            problems.append(f"Only the first {MAX_ROWS} rows were read.")
            break
        raw = {(k or "").strip(): (v or "").strip() for k, v in raw.items()}
        if not any(raw.values()):
            continue
        instance = University.objects.filter(name__iexact=raw.get("name", ""), country__iexact=raw.get("country", "")).first()
        data = _form_data(raw, instance)
        row = Row(number, raw, UniversityForm(data, instance=instance or University()), instance or University())
        key = (raw.get("name", "").lower(), raw.get("country", "").lower())
        if key in seen and row.form.is_valid():
            row.form.add_error(None, "This university appears more than once in the file.")
        seen.add(key)
        rows.append(row)
    return rows, problems


def _form_data(raw, instance):
    """Blank cells keep the current value; booleans accept yes/no."""
    data = {}
    for name in UNIVERSITY_FIELDS:
        value = raw.get(name, "")
        if value == "" and instance is not None:
            current = getattr(instance, name)
            if name == "oxbridge":
                value = "on" if current else ""
            elif current is None:
                value = ""
            elif name in ("admit_rate", "intl_admit_rate", "intl_student_share", "grad_rate"):
                value = format((current * 100).quantize(Decimal("0.01")), "f")
            else:
                value = str(current)
        elif name == "oxbridge":
            value = "on" if value.lower() in BOOLEAN_TRUE else ""
        data[name] = value
    if not data.get("cost_currency"):
        data["cost_currency"] = "USD"
    if not data.get("application_system"):
        data["application_system"] = University.System.COMMON_APP
    return data


@transaction.atomic
def save(rows):
    """Save valid rows. Returns (created, updated)."""
    created = updated = 0
    for row in rows:
        if not row.ok:
            continue
        university = row.form.save(commit=False)
        university.profile_updated_at = timezone.now()
        is_new = university.pk is None
        university.save()
        created += is_new
        updated += not is_new
    return created, updated

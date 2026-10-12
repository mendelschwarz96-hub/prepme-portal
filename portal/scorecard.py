"""U.S. Department of Education College Scorecard API (official open data, not scraping).

Docs: https://collegescorecard.ed.gov/data/api-documentation/
A free API key comes from https://api.data.gov/signup/ and goes in COLLEGE_SCORECARD_API_KEY.

Only U.S. institutions are covered. Fields the counselor maintains (international aid
policy, English test minimums, international admit rate, deadlines) are never touched here.
"""
import json
import urllib.error
import urllib.parse
import urllib.request
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import University

API_URL = "https://api.data.gov/ed/collegescorecard/v1/schools"
TIMEOUT = 20
PAGE_SIZE = 100


class ScorecardError(Exception):
    pass


OWNERSHIP = {1: University.Ownership.PUBLIC, 2: University.Ownership.PRIVATE_NONPROFIT,
             3: University.Ownership.PRIVATE_FOR_PROFIT}
# IPEDS admissions "test scores" codes.
TEST_POLICY = {1: University.TestPolicy.REQUIRED, 2: University.TestPolicy.RECOMMENDED,
               3: University.TestPolicy.NEITHER, 5: University.TestPolicy.CONSIDERED}

F = {
    "id": "id",
    "name": "school.name",
    "city": "school.city",
    "state": "school.state",
    "url": "school.school_url",
    "ownership": "school.ownership",
    "admit_rate": "latest.admissions.admission_rate.overall",
    "sat_r25": "latest.admissions.sat_scores.25th_percentile.critical_reading",
    "sat_r75": "latest.admissions.sat_scores.75th_percentile.critical_reading",
    "sat_m25": "latest.admissions.sat_scores.25th_percentile.math",
    "sat_m75": "latest.admissions.sat_scores.75th_percentile.math",
    "act_25": "latest.admissions.act_scores.25th_percentile.cumulative",
    "act_75": "latest.admissions.act_scores.75th_percentile.cumulative",
    "test_policy": "latest.admissions.test_requirements",
    "size": "latest.student.size",
    "intl_share": "latest.student.demographics.race_ethnicity.non_resident_alien",
    "coa": "latest.cost.attendance.academic_year",
    "tuition": "latest.cost.tuition.out_of_state",
    "grad_rate": "latest.completion.completion_rate_4yr_150nt",
    "earnings": "latest.earnings.10_yrs_after_entry.median",
}


def _api_key():
    return getattr(settings, "COLLEGE_SCORECARD_API_KEY", "") or "DEMO_KEY"


def _get(params):
    """One API request. Tests replace this function."""
    url = API_URL + "?" + urllib.parse.urlencode(params, safe=",")
    # Key in a header, not the URL, so it doesn't end up in logs.
    request = urllib.request.Request(url, headers={"X-Api-Key": _api_key(), "Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 429:
            raise ScorecardError(
                "The College Scorecard rate limit was reached. Wait an hour, or set your own free API key "
                "(COLLEGE_SCORECARD_API_KEY)."
            ) from exc
        if exc.code == 403:
            raise ScorecardError("The College Scorecard API key was rejected. Check COLLEGE_SCORECARD_API_KEY.") from exc
        raise ScorecardError(f"College Scorecard returned an error ({exc.code}).") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise ScorecardError("Could not reach the College Scorecard. Check the internet connection.") from exc


def _query(filters, page=0, per_page=PAGE_SIZE):
    params = {"fields": ",".join(F.values()), "per_page": per_page, "page": page, **filters}
    return _get(params)


def search(name, limit=20):
    """Bachelor's-granting, currently operating U.S. schools whose name matches."""
    name = name.strip()
    if len(name) < 3:
        return []
    data = _query({"school.name": name, "school.operating": 1, "school.degrees_awarded.predominant": 3},
                  per_page=limit)
    return [_summary(r) for r in data.get("results", [])]


def fetch(ids):
    """Records for the given Scorecard IDs, as {id: raw_record}."""
    found = {}
    ids = list(ids)
    for i in range(0, len(ids), PAGE_SIZE):
        chunk = ids[i:i + PAGE_SIZE]
        data = _query({"id": ",".join(str(x) for x in chunk)}, per_page=len(chunk))
        for record in data.get("results", []):
            found[record[F["id"]]] = record
    return found


def _summary(r):
    return {
        "id": r.get(F["id"]),
        "name": r.get(F["name"]),
        "city": r.get(F["city"]) or "",
        "state": r.get(F["state"]) or "",
        "admit_rate": r.get(F["admit_rate"]),
        "size": r.get(F["size"]),
    }


def _sum(a, b):
    return a + b if a is not None and b is not None else None


def _dec(value):
    return Decimal(str(round(value, 4))) if value is not None else None


def _url(value):
    if not value:
        return ""
    return value if value.startswith(("http://", "https://")) else "https://" + value


def values_from(record):
    """Map a Scorecard record to University field values."""
    return {
        "city": record.get(F["city"]) or "",
        "state": record.get(F["state"]) or "",
        "website": _url(record.get(F["url"]))[:200],
        "ownership": OWNERSHIP.get(record.get(F["ownership"]), ""),
        "undergrad_size": record.get(F["size"]),
        "admit_rate": _dec(record.get(F["admit_rate"])),
        # Composite range approximated as the sum of the section percentiles.
        "sat_25": _sum(record.get(F["sat_r25"]), record.get(F["sat_m25"])),
        "sat_75": _sum(record.get(F["sat_r75"]), record.get(F["sat_m75"])),
        "act_25": record.get(F["act_25"]),
        "act_75": record.get(F["act_75"]),
        "test_policy": TEST_POLICY.get(record.get(F["test_policy"]), ""),
        "intl_student_share": _dec(record.get(F["intl_share"])),
        "cost_of_attendance": record.get(F["coa"]),
        "tuition": record.get(F["tuition"]),
        "grad_rate": _dec(record.get(F["grad_rate"])),
        "median_earnings": record.get(F["earnings"]),
    }


def apply(university, record):
    for field, value in values_from(record).items():
        setattr(university, field, value)
    university.cost_currency = "USD"
    university.scorecard_synced_at = timezone.now()


@transaction.atomic
def import_school(scorecard_id):
    """Create or update a University from its Scorecard ID. Returns (university, created)."""
    record = fetch([scorecard_id]).get(scorecard_id)
    if record is None:
        raise ScorecardError("That school was not found in the College Scorecard.")
    university = University.objects.filter(scorecard_id=scorecard_id).first()
    created = university is None
    if created:
        name = record.get(F["name"])
        # Link to an existing manual entry with the same name instead of duplicating it.
        university = University.objects.filter(name=name, country="United States", scorecard_id__isnull=True).first()
        if university is None:
            university = University(name=name, country="United States", application_system=University.System.COMMON_APP)
        university.scorecard_id = scorecard_id
    apply(university, record)
    university.save()
    return university, created


def refresh_all():
    """Refresh every linked school. Returns (updated_count, missing_names)."""
    linked = {u.scorecard_id: u for u in University.objects.filter(scorecard_id__isnull=False)}
    records = fetch(linked.keys())
    updated, missing = 0, []
    for scorecard_id, university in linked.items():
        record = records.get(scorecard_id)
        if record is None:
            missing.append(university.name)
            continue
        apply(university, record)
        university.save()
        updated += 1
    return updated, missing

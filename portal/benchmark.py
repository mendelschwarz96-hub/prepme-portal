"""Anonymized comparison with past PrepMe students' results at a university.

Privacy rules (enforced here, on the server):
- Only past students with an active "anonymized outcomes" consent are included.
- Every number shown is based on at least settings.BENCHMARK_MIN_GROUP distinct students.
  Smaller groups are hidden entirely, and total counts are never shown, so hidden groups
  can't be worked out by subtraction.
- Only scores and outcomes are used: never names, schools attended, or free-text fields.
- Medians are rounded so they don't reproduce one person's exact score.
- IB is compared only with IB students; GPA only with students from the same high school
  using the same scale. SAT and ACT are compared across curricula.
"""
from statistics import median

from django.conf import settings

from .models import Application, Consent, TestScore

ADMITTED, DENIED, WAITLISTED = "admitted", "denied", "waitlisted"
BUCKET_OF = {
    Application.Outcome.ADMITTED: ADMITTED,
    Application.Outcome.CONDITIONAL: ADMITTED,
    Application.Outcome.DENIED: DENIED,
    Application.Outcome.WAITLISTED: WAITLISTED,
    Application.Outcome.DEFERRED: WAITLISTED,
}
BUCKET_LABELS = {ADMITTED: "Admitted", DENIED: "Denied", WAITLISTED: "Waitlisted or deferred"}


def min_group():
    return settings.BENCHMARK_MIN_GROUP


def _number(text):
    try:
        return float(str(text).replace(",", ".").strip())
    except (TypeError, ValueError):
        return None


def best_score(student, tests):
    values = [_number(s.score) for s in student.test_scores.all() if s.test in tests]
    values = [v for v in values if v is not None]
    return max(values) if values else None


def ib_total(student):
    final = best_score(student, [TestScore.Test.IB_FINAL])
    return final if final is not None else best_score(student, [TestScore.Test.IB_PREDICTED])


def gpa(student):
    return _number(student.gpa) if student.gpa else None


MEASURES = {
    "ib": {"label": "IB total", "value": ib_total, "round": 1},
    "sat": {"label": "SAT", "value": lambda s: best_score(s, [TestScore.Test.SAT]), "round": 10},
    "act": {"label": "ACT", "value": lambda s: best_score(s, [TestScore.Test.ACT]), "round": 1},
    "gpa": {"label": "GPA (same high school)", "value": gpa, "round": 0.1},
}


def _rounded(value, step):
    result = round(value / step) * step
    return round(result, 1) if step < 1 else int(result)


def consented_student_ids():
    return set(
        Consent.objects.filter(kind=Consent.Kind.ANONYMIZED_OUTCOMES, withdrawn_on__isnull=True)
        .values_list("student_id", flat=True)
    )


def past_results(university, exclude_student):
    """One result per consenting past student (their most recent application to this university)."""
    apps = (
        Application.objects.filter(university=university, outcome__in=list(BUCKET_OF))
        .exclude(student=exclude_student)
        .filter(student_id__in=consented_student_ids())
        .select_related("student")
        .prefetch_related("student__test_scores")
        .order_by("entry_year")
    )
    latest = {}
    for app in apps:
        latest[app.student_id] = app
    return list(latest.values())


def _peers(measure, student, results):
    if measure == "ib":
        return [a for a in results if a.student.curriculum == "ib"]
    if measure == "gpa":
        if not student.school_id or not student.gpa_scale:
            return []
        return [a for a in results if a.student.school_id == student.school_id
                and a.student.gpa_scale.strip() == student.gpa_scale.strip()]
    return results


def compare(student, university):
    """Benchmark the student's profile against past results at one university."""
    k = min_group()
    results = past_results(university, student)
    sections = []
    for key, spec in MEASURES.items():
        mine = spec["value"](student)
        if mine is None:
            continue
        values = [(spec["value"](a.student), BUCKET_OF[a.outcome]) for a in _peers(key, student, results)]
        values = [(v, b) for v, b in values if v is not None]
        groups = []
        for bucket, label in BUCKET_LABELS.items():
            scores = [v for v, b in values if b == bucket]
            if len(scores) >= k:
                mid = _rounded(median(scores), spec["round"])
                groups.append({"label": label, "median": mid, "count": len(scores),
                               "position": "above" if mine > mid else "below" if mine < mid else "at"})
        sections.append({
            "key": key, "label": spec["label"], "mine": _rounded(mine, spec["round"]) if key != "gpa" else mine,
            "groups": groups,
        })

    aid_values = [a.aid_offered for a in results
                  if BUCKET_OF[a.outcome] == ADMITTED and a.aid_offered and a.aid_currency == "USD"]
    aid = {"median": _rounded(median(aid_values), 1000), "count": len(aid_values)} if len(aid_values) >= k else None
    return {"university": university, "sections": sections, "aid": aid, "min_group": k}

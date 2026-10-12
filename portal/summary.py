"""Progress summary for the parent view.

Deliberately contains only statuses, counts and dates: no essay text, comments,
meeting notes, grades or scores.
"""
from django.utils import timezone

from .models import Application, DocumentItem, Task

DOC_DONE = (DocumentItem.Status.READY, DocumentItem.Status.SUBMITTED, DocumentItem.Status.NOT_NEEDED)


def build(student, upcoming_limit=8):
    today = timezone.localdate()
    tasks = list(student.tasks.filter(archived=False).select_related("application__university"))
    open_tasks = [t for t in tasks if t.status != Task.Status.DONE]

    schools = []
    for app in student.applications.filter(status__in=Application.OPEN).select_related("university").order_by("university__name"):
        app_tasks = [t for t in tasks if t.application_id == app.pk]
        docs = list(app.documents.all())
        schools.append({
            "name": app.university.name,
            "round": app.get_round_display(),
            "entry_year": app.entry_year,
            "status": app.status,
            "status_label": app.get_status_display(),
            "tasks_done": sum(1 for t in app_tasks if t.status == Task.Status.DONE),
            "tasks_total": len(app_tasks),
            "docs_done": sum(1 for d in docs if d.status in DOC_DONE),
            "docs_total": len(docs),
            "outcome": app.outcome,
            "outcome_label": app.get_outcome_display(),
            "attending": app.attending,
            "next_due": min((t.due_date for t in app_tasks if t.due_date and t.status != Task.Status.DONE), default=None),
        })

    essays = []
    for essay in student.essays.select_related("prompt", "application__university"):
        latest = essay.latest_version
        essays.append({
            "title": essay.title,
            "school": essay.application.university.name if essay.application else "",
            "status": essay.status,
            "status_label": essay.get_status_display(),
            "words": latest.word_count if latest else 0,
            "word_limit": essay.word_limit,
            "updated": essay.updated_at,
        })

    upcoming = sorted((t for t in open_tasks if t.due_date and t.due_date >= today), key=lambda t: t.due_date)
    return {
        "tasks_done": len(tasks) - len(open_tasks),
        "tasks_total": len(tasks),
        "overdue": sum(1 for t in open_tasks if t.due_date and t.due_date < today),
        "upcoming": [{"title": t.title, "due_date": t.due_date} for t in upcoming[:upcoming_limit]],
        "schools": schools,
        "essays": essays,
    }

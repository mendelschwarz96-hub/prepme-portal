"""Deadline engine and school-list workflow.

Rules:
- When a school goes on a student's list (counselor adds it, or approves a student's
  request), each matching DeadlineTemplate becomes a Task for that student.
- A template matches when university and entry year match and its round is blank
  (applies to every round) or equals the application's round.
- Editing a template moves every task copied from it, except tasks whose date the
  counselor changed by hand (date_overridden).
- Removing a school or changing its round archives tasks that no longer apply.
  Completed tasks are never archived or changed.
"""
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from .models import Application, DeadlineTemplate, DocumentItem, Round, Task, University, rounds_for_system

UCAS_MAX_CHOICES = 5

DEFAULT_DOCUMENTS = {
    University.System.COMMON_APP: [
        (DocumentItem.DocType.TRANSCRIPT, ""),
        (DocumentItem.DocType.TRANSLATION, ""),
        (DocumentItem.DocType.COUNSELOR_REC, ""),
        (DocumentItem.DocType.TEACHER_REC, "Teacher 1"),
        (DocumentItem.DocType.TEACHER_REC, "Teacher 2"),
        (DocumentItem.DocType.TEST_SCORES, ""),
        (DocumentItem.DocType.ENGLISH_TEST, ""),
    ],
    University.System.UCAS: [
        (DocumentItem.DocType.UCAS_REFERENCE, ""),
        (DocumentItem.DocType.ENGLISH_TEST, ""),
    ],
}
DEFAULT_DOCUMENTS[University.System.DIRECT] = DEFAULT_DOCUMENTS[University.System.COMMON_APP]


# ---------------------------------------------------------------- task sync

def matching_templates(application):
    return DeadlineTemplate.objects.filter(
        university_id=application.university_id, entry_year=application.entry_year
    ).filter(Q(round="") | Q(round=application.round))


def sync_tasks(application):
    """Make the application's automatic tasks match its deadline templates. Safe to call repeatedly."""
    if not application.is_listed:
        return
    wanted = {t.pk: t for t in matching_templates(application).select_related("university")}
    existing = {t.template_id: t for t in application.tasks.filter(template__isnull=False)}

    for template_id, template in wanted.items():
        task = existing.get(template_id)
        if task is None:
            Task.objects.create(
                student=application.student,
                application=application,
                template=template,
                source=Task.Source.AUTO,
                title=template.task_title(),
                due_date=template.due_date,
                owner=application.student.user,
            )
        elif task.archived:
            task.archived = False
            task.save(update_fields=["archived"])

    for template_id, task in existing.items():
        if template_id not in wanted and not task.archived and not task.is_done:
            task.archived = True
            task.save(update_fields=["archived"])


@transaction.atomic
def save_template(template):
    """Save a deadline template and push the change to every student who has that school listed."""
    template.full_clean()
    template.save()
    template.tasks.filter(date_overridden=False).exclude(status=Task.Status.DONE).update(due_date=template.due_date)
    template.tasks.update(title=template.task_title())
    for application in Application.objects.filter(
        university_id=template.university_id, entry_year=template.entry_year, status__in=Application.LISTED
    ):
        sync_tasks(application)
    return template


@transaction.atomic
def delete_template(template):
    template.tasks.exclude(status=Task.Status.DONE).update(archived=True)
    template.delete()


def set_task_due_date(task, due_date):
    """Counselor changes one task's date. Tasks from a template then stop following template edits."""
    task.due_date = due_date
    if task.template_id:
        task.date_overridden = due_date != task.template.due_date
    task.save(update_fields=["due_date", "date_overridden"])


def reset_task_date(task):
    if task.template_id:
        task.due_date = task.template.due_date
        task.date_overridden = False
        task.save(update_fields=["due_date", "date_overridden"])


def set_task_status(task, status):
    task.status = status
    task.completed_at = timezone.now() if status == Task.Status.DONE else None
    task.save(update_fields=["status", "completed_at"])


# ---------------------------------------------------------------- school list

def ucas_problems(student, entry_year, university):
    """Return a list of UCAS rule violations if `university` were added to the student's list."""
    if university.application_system != University.System.UCAS:
        return []
    open_ucas = Application.objects.filter(
        student=student,
        entry_year=entry_year,
        status__in=Application.OPEN,
        university__application_system=University.System.UCAS,
    ).exclude(university=university)
    problems = []
    if open_ucas.count() >= UCAS_MAX_CHOICES:
        problems.append(f"UCAS allows at most {UCAS_MAX_CHOICES} choices per year.")
    if university.oxbridge and open_ucas.filter(university__oxbridge=True).exists():
        problems.append("UCAS allows only one of Oxford or Cambridge per year.")
    return problems


def _validate_new_application(student, university, entry_year, round_):
    if round_ not in rounds_for_system(university.application_system):
        raise ValidationError(f"{Round(round_).label} is not a round for {university}.")
    if Application.objects.filter(
        student=student, university=university, entry_year=entry_year, status__in=Application.OPEN
    ).exists():
        raise ValidationError(f"{university} is already on the list for {entry_year}.")
    problems = ucas_problems(student, entry_year, university)
    if problems:
        raise ValidationError(problems)


@transaction.atomic
def add_school(student, university, entry_year, round_, by, course=""):
    """Counselor adds a school directly, or a student requests one (needs approval)."""
    _validate_new_application(student, university, entry_year, round_)
    application = Application.objects.create(
        student=student,
        university=university,
        entry_year=entry_year,
        round=round_,
        course=course,
        requested_by=by,
        status=Application.Status.PENDING_ADD,
    )
    if by.is_counselor:
        approve(application, by)
    return application


def _create_default_documents(application):
    if application.documents.exists():
        return
    for doc_type, label in DEFAULT_DOCUMENTS[application.university.application_system]:
        DocumentItem.objects.create(application=application, doc_type=doc_type, label=label)


@transaction.atomic
def approve(application, by):
    """Counselor approves a pending add or pending removal."""
    if application.status == Application.Status.PENDING_ADD:
        problems = ucas_problems(application.student, application.entry_year, application.university)
        if problems:
            raise ValidationError(problems)
        application.status = Application.Status.ACTIVE
        _decide(application, by)
        sync_tasks(application)
        _create_default_documents(application)
    elif application.status == Application.Status.PENDING_REMOVAL:
        remove(application, by)
    else:
        raise ValidationError("There is nothing to approve for this school.")


def decide_many(applications, by, *, accept):
    """Approve (accept=True) or decline a batch of pending requests.

    Each request is handled on its own, so one problem (e.g. a UCAS limit) does not
    block the rest. Returns (done, problems) where problems is a list of (application, message).
    """
    done, problems = [], []
    action = approve if accept else decline
    for application in applications:
        try:
            action(application, by)
        except ValidationError as exc:
            problems.append((application, " ".join(exc.messages)))
        else:
            done.append(application)
    return done, problems


@transaction.atomic
def decline(application, by):
    if application.status == Application.Status.PENDING_ADD:
        application.status = Application.Status.DECLINED
    elif application.status == Application.Status.PENDING_REMOVAL:
        application.status = Application.Status.ACTIVE
    else:
        raise ValidationError("There is nothing to decline for this school.")
    _decide(application, by)


@transaction.atomic
def request_removal(application, by):
    """Counselor removes immediately; a student's request waits for approval."""
    if by.is_counselor:
        return remove(application, by)
    if application.status == Application.Status.PENDING_ADD:
        # Withdrawing a request that was never approved needs no approval.
        application.status = Application.Status.DECLINED
        _decide(application, by)
        return
    if application.status != Application.Status.ACTIVE:
        raise ValidationError("This school is not on the list.")
    application.status = Application.Status.PENDING_REMOVAL
    application.requested_by = by
    application.save(update_fields=["status", "requested_by"])


@transaction.atomic
def remove(application, by):
    application.status = Application.Status.REMOVED
    _decide(application, by)
    application.tasks.exclude(status=Task.Status.DONE).update(archived=True)


@transaction.atomic
def change_round(application, round_):
    if round_ not in rounds_for_system(application.university.application_system):
        raise ValidationError(f"{Round(round_).label} is not a round for {application.university}.")
    application.round = round_
    application.save(update_fields=["round"])
    sync_tasks(application)


def _decide(application, by):
    application.decided_by = by
    application.decided_at = timezone.now()
    application.save(update_fields=["status", "decided_by", "decided_at"])

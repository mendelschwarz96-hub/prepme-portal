"""Deadline engine: adding schools creates tasks; editing deadlines updates them."""
from datetime import date

import pytest
from django.core.exceptions import ValidationError

from portal import deadlines
from portal.models import Application, DeadlineKind, DocumentItem, Round, Task, University

from .conftest import YEAR, make_template

pytestmark = pytest.mark.django_db


def live_tasks(application):
    return {t.template_id: t for t in application.tasks.filter(archived=False)}


def test_counselor_adding_school_creates_matching_tasks(student, counselor, common_app_uni, templates):
    app = deadlines.add_school(student, common_app_uni, YEAR, Round.EA, counselor)

    assert app.status == Application.Status.ACTIVE
    tasks = live_tasks(app)
    assert set(tasks) == {templates["ea"].pk, templates["aid"].pk}  # not the RD deadline
    ea_task = tasks[templates["ea"].pk]
    assert ea_task.due_date == date(2026, 11, 1)
    assert ea_task.source == Task.Source.AUTO
    assert ea_task.owner == student.user
    assert ea_task.title == "Sample U: Application"


def test_deadlines_for_other_years_are_ignored(student, counselor, common_app_uni, templates):
    make_template(common_app_uni, round_=Round.EA, year=YEAR + 1)
    app = deadlines.add_school(student, common_app_uni, YEAR, Round.EA, counselor)
    assert len(live_tasks(app)) == 2


def test_student_request_creates_no_tasks_until_approved(student, student_user, counselor, common_app_uni, templates):
    app = deadlines.add_school(student, common_app_uni, YEAR, Round.RD, student_user)
    assert app.status == Application.Status.PENDING_ADD
    assert app.tasks.count() == 0

    deadlines.approve(app, counselor)
    app.refresh_from_db()
    assert app.status == Application.Status.ACTIVE
    assert set(live_tasks(app)) == {templates["rd"].pk, templates["aid"].pk}


def test_declined_request_creates_nothing(student, student_user, counselor, common_app_uni, templates):
    app = deadlines.add_school(student, common_app_uni, YEAR, Round.RD, student_user)
    deadlines.decline(app, counselor)
    app.refresh_from_db()
    assert app.status == Application.Status.DECLINED
    assert app.tasks.count() == 0


def test_approval_creates_default_documents(student, counselor, common_app_uni, ucas_uni):
    app = deadlines.add_school(student, common_app_uni, YEAR, Round.RD, counselor)
    types = list(app.documents.values_list("doc_type", flat=True))
    assert DocumentItem.DocType.TRANSCRIPT in types
    assert types.count(DocumentItem.DocType.TEACHER_REC) == 2

    ucas_app = deadlines.add_school(student, ucas_uni, YEAR, Round.UCAS, counselor)
    assert set(ucas_app.documents.values_list("doc_type", flat=True)) == {
        DocumentItem.DocType.UCAS_REFERENCE, DocumentItem.DocType.ENGLISH_TEST,
    }


def test_editing_deadline_moves_every_students_task(student, other_student, counselor, common_app_uni, templates):
    a = deadlines.add_school(student, common_app_uni, YEAR, Round.EA, counselor)
    b = deadlines.add_school(other_student, common_app_uni, YEAR, Round.EA, counselor)

    template = templates["ea"]
    template.due_date = date(2026, 10, 25)
    deadlines.save_template(template)

    assert live_tasks(a)[template.pk].due_date == date(2026, 10, 25)
    assert live_tasks(b)[template.pk].due_date == date(2026, 10, 25)


def test_counselor_override_survives_school_wide_edit(student, other_student, counselor, common_app_uni, templates):
    a = deadlines.add_school(student, common_app_uni, YEAR, Round.EA, counselor)
    b = deadlines.add_school(other_student, common_app_uni, YEAR, Round.EA, counselor)
    template = templates["ea"]

    a_task = live_tasks(a)[template.pk]
    deadlines.set_task_due_date(a_task, date(2026, 10, 20))
    assert a_task.date_overridden

    template.due_date = date(2026, 10, 30)
    deadlines.save_template(template)

    a_task.refresh_from_db()
    assert a_task.due_date == date(2026, 10, 20)  # kept the student's own date
    assert live_tasks(b)[template.pk].due_date == date(2026, 10, 30)

    deadlines.reset_task_date(a_task)
    assert a_task.due_date == date(2026, 10, 30)
    assert not a_task.date_overridden


def test_setting_date_back_to_school_date_clears_override(student, counselor, common_app_uni, templates):
    app = deadlines.add_school(student, common_app_uni, YEAR, Round.EA, counselor)
    task = live_tasks(app)[templates["ea"].pk]
    deadlines.set_task_due_date(task, date(2026, 10, 1))
    deadlines.set_task_due_date(task, templates["ea"].due_date)
    assert not task.date_overridden


def test_new_deadline_reaches_students_already_listed(student, counselor, common_app_uni, templates):
    app = deadlines.add_school(student, common_app_uni, YEAR, Round.EA, counselor)
    interview = make_template(common_app_uni, kind=DeadlineKind.INTERVIEW, round_=Round.EA)
    assert interview.pk in live_tasks(app)


def test_new_deadline_does_not_reach_pending_or_removed(student, student_user, counselor, common_app_uni, templates):
    pending = deadlines.add_school(student, common_app_uni, YEAR, Round.EA, student_user)
    make_template(common_app_uni, kind=DeadlineKind.INTERVIEW)
    assert pending.tasks.count() == 0


def test_changing_round_swaps_tasks(student, counselor, common_app_uni, templates):
    app = deadlines.add_school(student, common_app_uni, YEAR, Round.EA, counselor)
    deadlines.change_round(app, Round.RD)
    assert set(live_tasks(app)) == {templates["rd"].pk, templates["aid"].pk}

    deadlines.change_round(app, Round.EA)  # switching back restores, not duplicates
    assert set(live_tasks(app)) == {templates["ea"].pk, templates["aid"].pk}
    assert app.tasks.filter(template=templates["ea"]).count() == 1


def test_changing_template_round_moves_tasks(student, counselor, common_app_uni, templates):
    app = deadlines.add_school(student, common_app_uni, YEAR, Round.EA, counselor)
    aid = templates["aid"]
    aid.round = Round.RD
    deadlines.save_template(aid)
    assert aid.pk not in live_tasks(app)


def test_completed_tasks_are_never_changed(student, counselor, common_app_uni, templates):
    app = deadlines.add_school(student, common_app_uni, YEAR, Round.EA, counselor)
    task = live_tasks(app)[templates["ea"].pk]
    deadlines.set_task_status(task, Task.Status.DONE)
    assert task.completed_at is not None

    templates["ea"].due_date = date(2026, 12, 1)
    deadlines.save_template(templates["ea"])
    deadlines.change_round(app, Round.RD)

    task.refresh_from_db()
    assert task.due_date == date(2026, 11, 1)
    assert not task.archived


def test_removing_school_archives_open_tasks(student, counselor, common_app_uni, templates):
    app = deadlines.add_school(student, common_app_uni, YEAR, Round.EA, counselor)
    done = live_tasks(app)[templates["aid"].pk]
    deadlines.set_task_status(done, Task.Status.DONE)

    deadlines.remove(app, counselor)
    assert app.status == Application.Status.REMOVED
    assert list(app.tasks.filter(archived=False)) == [done]


def test_student_removal_needs_approval(student, student_user, counselor, common_app_uni, templates):
    app = deadlines.add_school(student, common_app_uni, YEAR, Round.EA, counselor)
    deadlines.request_removal(app, student_user)
    assert app.status == Application.Status.PENDING_REMOVAL
    assert app.tasks.filter(archived=False).count() == 2  # still visible while waiting

    deadlines.approve(app, counselor)
    assert app.status == Application.Status.REMOVED
    assert app.tasks.filter(archived=False).count() == 0


def test_declining_removal_keeps_school(student, student_user, counselor, common_app_uni, templates):
    app = deadlines.add_school(student, common_app_uni, YEAR, Round.EA, counselor)
    deadlines.request_removal(app, student_user)
    deadlines.decline(app, counselor)
    assert app.status == Application.Status.ACTIVE


def test_school_can_be_readded_after_removal(student, counselor, common_app_uni, templates):
    first = deadlines.add_school(student, common_app_uni, YEAR, Round.EA, counselor)
    deadlines.remove(first, counselor)
    second = deadlines.add_school(student, common_app_uni, YEAR, Round.RD, counselor)
    assert set(live_tasks(second)) == {templates["rd"].pk, templates["aid"].pk}


def test_duplicate_school_rejected(student, counselor, common_app_uni):
    deadlines.add_school(student, common_app_uni, YEAR, Round.EA, counselor)
    with pytest.raises(ValidationError):
        deadlines.add_school(student, common_app_uni, YEAR, Round.RD, counselor)


def test_deleting_deadline_hides_open_tasks(student, counselor, common_app_uni, templates):
    app = deadlines.add_school(student, common_app_uni, YEAR, Round.EA, counselor)
    deadlines.delete_template(templates["ea"])
    assert app.tasks.filter(archived=False).count() == 1


def test_sync_is_idempotent(student, counselor, common_app_uni, templates):
    app = deadlines.add_school(student, common_app_uni, YEAR, Round.EA, counselor)
    deadlines.sync_tasks(app)
    deadlines.sync_tasks(app)
    assert app.tasks.count() == 2


# ------------------------------------------------------------- rounds and UCAS rules

def test_ucas_school_requires_ucas_round(student, counselor, ucas_uni, common_app_uni):
    with pytest.raises(ValidationError):
        deadlines.add_school(student, ucas_uni, YEAR, Round.RD, counselor)
    with pytest.raises(ValidationError):
        deadlines.add_school(student, common_app_uni, YEAR, Round.UCAS, counselor)


def test_ucas_limit_of_five_choices(student, counselor, student_user):
    unis = [
        University.objects.create(name=f"UK {i}", country="United Kingdom", application_system=University.System.UCAS)
        for i in range(6)
    ]
    for uni in unis[:4]:
        deadlines.add_school(student, uni, YEAR, Round.UCAS, counselor)
    deadlines.add_school(student, unis[4], YEAR, Round.UCAS, student_user)  # 5th, pending: counts too
    with pytest.raises(ValidationError, match="at most 5"):
        deadlines.add_school(student, unis[5], YEAR, Round.UCAS, counselor)


def test_ucas_limit_is_per_year(student, counselor):
    unis = [
        University.objects.create(name=f"UK {i}", country="United Kingdom", application_system=University.System.UCAS)
        for i in range(6)
    ]
    for uni in unis[:5]:
        deadlines.add_school(student, uni, YEAR, Round.UCAS, counselor)
    deadlines.add_school(student, unis[5], YEAR + 1, Round.UCAS, counselor)


def test_only_one_of_oxford_or_cambridge(student, counselor):
    ox = University.objects.create(name="Oxford", country="UK", application_system=University.System.UCAS, oxbridge=True)
    cam = University.objects.create(name="Cambridge", country="UK", application_system=University.System.UCAS, oxbridge=True)
    deadlines.add_school(student, ox, YEAR, Round.UCAS, counselor)
    with pytest.raises(ValidationError, match="Oxford or Cambridge"):
        deadlines.add_school(student, cam, YEAR, Round.UCAS, counselor)


def test_common_app_schools_do_not_count_toward_ucas_limit(student, counselor):
    for i in range(6):
        uni = University.objects.create(name=f"US {i}", country="United States")
        deadlines.add_school(student, uni, YEAR, Round.RD, counselor)
    uk = University.objects.create(name="UK", country="UK", application_system=University.System.UCAS)
    deadlines.add_school(student, uk, YEAR, Round.UCAS, counselor)


def test_ucas_deadline_round_validated(ucas_uni):
    with pytest.raises(ValidationError):
        make_template(ucas_uni, round_=Round.EA)

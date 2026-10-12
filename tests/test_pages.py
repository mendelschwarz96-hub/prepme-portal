"""Smoke test: every page renders for the roles allowed to see it."""
import pytest
from django.urls import reverse

from portal import deadlines
from portal.models import AcademicRecord, Round, Task, TestScore

from .conftest import YEAR

pytestmark = pytest.mark.django_db


@pytest.fixture
def world(student, student_user, counselor, common_app_uni, ucas_uni, templates):
    listed = deadlines.add_school(student, common_app_uni, YEAR, Round.EA, counselor)
    pending = deadlines.add_school(student, ucas_uni, YEAR, Round.UCAS, student_user)
    task = listed.tasks.first()
    deadlines.set_task_due_date(task, task.due_date.replace(day=2))
    manual = Task.objects.create(student=student, title="Mine", source=Task.Source.MANUAL)
    score = TestScore.objects.create(student=student, test=TestScore.Test.SAT, score="1450")
    grade = AcademicRecord.objects.create(student=student, subject="Math", grade="7")
    return dict(listed=listed, pending=pending, task=task, manual=manual, score=score, grade=grade,
                doc=listed.documents.first(), uni=common_app_uni, tpl=templates["ea"])


def counselor_urls(student, w):
    return [
        reverse("dashboard"),
        reverse("student_list") + "?show=all&q=an",
        reverse("student_create"),
        reverse("school_create"),
        reverse("student_detail", args=[student.pk]),
        reverse("student_edit", args=[student.pk]),
        reverse("invite_create", args=[student.pk]),
        reverse("score_add", args=[student.pk]),
        reverse("score_edit", args=[student.pk, w["score"].pk]),
        reverse("score_delete", args=[student.pk, w["score"].pk]),
        reverse("grade_add", args=[student.pk]),
        reverse("grade_edit", args=[student.pk, w["grade"].pk]),
        reverse("grade_delete", args=[student.pk, w["grade"].pk]),
        reverse("application_add", args=[student.pk]),
        reverse("application_detail", args=[w["listed"].pk]),
        reverse("application_detail", args=[w["pending"].pk]),
        reverse("application_remove", args=[w["listed"].pk]),
        reverse("document_create", args=[w["listed"].pk]),
        reverse("document_edit", args=[w["doc"].pk]),
        reverse("document_delete", args=[w["doc"].pk]),
        reverse("task_create", args=[student.pk]),
        reverse("task_edit", args=[w["task"].pk]),
        reverse("task_delete", args=[w["task"].pk]),
        reverse("university_list") + "?q=sam",
        reverse("university_create"),
        reverse("university_detail", args=[w["uni"].pk]),
        reverse("university_edit", args=[w["uni"].pk]),
        reverse("deadline_add", args=[w["uni"].pk]),
        reverse("deadline_edit", args=[w["uni"].pk, w["tpl"].pk]),
        reverse("deadline_delete", args=[w["uni"].pk, w["tpl"].pk]),
        reverse("audit_log") + f"?student={student.pk}",
        reverse("password_change"),
    ]


def test_counselor_pages_render(client, counselor, student, world):
    client.force_login(counselor)
    for url in counselor_urls(student, world):
        assert client.get(url).status_code == 200, url


def test_student_pages_render(client, student_user, student, world):
    client.force_login(student_user)
    for url in [
        reverse("student_detail", args=[student.pk]),
        reverse("student_edit", args=[student.pk]),
        reverse("score_add", args=[student.pk]),
        reverse("application_add", args=[student.pk]),
        reverse("application_detail", args=[world["listed"].pk]),
        reverse("application_detail", args=[world["pending"].pk]),
        reverse("application_remove", args=[world["listed"].pk]),
        reverse("document_edit", args=[world["doc"].pk]),
        reverse("task_create", args=[student.pk]),
        reverse("task_edit", args=[world["manual"].pk]),
    ]:
        assert client.get(url).status_code == 200, url


def test_parent_pages_render(client, parent_user, student, world):
    client.force_login(parent_user)
    assert client.get(reverse("home"))["Location"] == reverse("student_summary", args=[student.pk])
    assert client.get(reverse("student_summary", args=[student.pk])).status_code == 200


def test_phase2_pages_render(client, counselor, student_user, student, world):
    from datetime import date

    from portal import essays
    from portal.models import Essay, EssayPrompt, MeetingNote

    prompt = EssayPrompt.objects.create(university=world["uni"], entry_year=YEAR, title="Why us", text="Why?", word_limit=200)
    essay = Essay.objects.create(student=student, title="Why us", prompt=prompt, application=world["listed"])
    essays.save_version(essay, "Draft one.", student_user)
    v2, _, _ = essays.save_version(essay, "Draft two is better.", counselor)
    essays.add_comment(v2, counselor, "Good", quote="better")
    note = MeetingNote.objects.create(student=student, met_on=date(2026, 9, 1), title="Kickoff", body="Notes")
    pages = [
        reverse("essay_create", args=[student.pk]),
        reverse("essay_detail", args=[essay.pk]),
        reverse("essay_edit", args=[essay.pk]),
        reverse("essay_versions", args=[essay.pk]),
        reverse("essay_version", args=[essay.pk, 1]),
        reverse("essay_version", args=[essay.pk, 2]),
        reverse("note_list", args=[student.pk]),
        reverse("student_summary", args=[student.pk]),
    ]
    client.force_login(counselor)
    for url in pages + [
        reverse("prompt_list"), reverse("prompt_create"), reverse("prompt_edit", args=[prompt.pk]),
        reverse("note_create", args=[student.pk]), reverse("note_edit", args=[student.pk, note.pk]),
        reverse("essay_delete", args=[essay.pk]),
    ]:
        assert client.get(url).status_code == 200, url
    client.force_login(student_user)
    for url in pages:
        assert client.get(url).status_code == 200, url


def test_public_pages_render(client):
    for url in [reverse("login"), reverse("password_reset")]:
        assert client.get(url).status_code == 200, url

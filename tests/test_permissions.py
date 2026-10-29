"""Permissions are enforced on the server: each role is checked against real HTTP requests."""
from datetime import date

import pytest
from django.urls import reverse

from portal import deadlines
from portal.models import Application, DocumentItem, Round, Task, TestScore

from .conftest import YEAR

pytestmark = pytest.mark.django_db


@pytest.fixture
def app_listed(student, counselor, common_app_uni, templates):
    return deadlines.add_school(student, common_app_uni, YEAR, Round.EA, counselor)


def login(client, user):
    client.force_login(user)
    return client


# ------------------------------------------------------------- anonymous

@pytest.mark.parametrize("name", ["home", "dashboard", "student_list", "university_list", "audit_log"])
def test_anonymous_redirected_to_login(client, name):
    response = client.get(reverse(name))
    assert response.status_code == 302
    assert reverse("login") in response["Location"]


def test_bare_address_goes_to_plain_login(client):
    response = client.get("/")
    assert response["Location"] == "/login/"


def test_old_login_address_still_works(client):
    response = client.get("/accounts/login/?next=/students/")
    assert response["Location"] == "/login/?next=/students/"


def test_anonymous_cannot_view_student(client, student):
    response = client.get(reverse("student_detail", args=[student.pk]))
    assert response.status_code == 302


# ------------------------------------------------------------- counselor-only pages

@pytest.mark.parametrize("name", ["dashboard", "student_list", "student_create", "university_create", "audit_log"])
@pytest.mark.parametrize("who", ["student_user", "parent_user"])
def test_counselor_pages_forbidden_to_others(client, request, name, who, student):
    login(client, request.getfixturevalue(who))
    assert client.get(reverse(name)).status_code == 403


def test_counselor_sees_everything(client, counselor, student, other_student, app_listed):
    login(client, counselor)
    for url in [
        reverse("dashboard"),
        reverse("student_list"),
        reverse("student_detail", args=[student.pk]),
        reverse("student_detail", args=[other_student.pk]),
        reverse("application_detail", args=[app_listed.pk]),
        reverse("audit_log"),
    ]:
        assert client.get(url).status_code == 200, url


# ------------------------------------------------------------- students

def test_student_sees_own_record_only(client, student_user, student, other_student):
    login(client, student_user)
    assert client.get(reverse("student_detail", args=[student.pk])).status_code == 200
    assert client.get(reverse("student_detail", args=[other_student.pk])).status_code == 404


def test_student_home_redirects_to_own_record(client, student_user, student):
    login(client, student_user)
    response = client.get(reverse("home"))
    assert response["Location"] == reverse("student_detail", args=[student.pk])


def test_student_cannot_reach_other_students_objects(client, student_user, other_student, counselor, common_app_uni, templates):
    other_app = deadlines.add_school(other_student, common_app_uni, YEAR, Round.EA, counselor)
    task = other_app.tasks.first()
    doc = other_app.documents.first()
    score = TestScore.objects.create(student=other_student, test=TestScore.Test.SAT, score="1400")
    login(client, student_user)
    assert client.get(reverse("application_detail", args=[other_app.pk])).status_code == 404
    assert client.post(reverse("task_status", args=[task.pk]), {"status": "done"}).status_code == 404
    assert client.get(reverse("document_edit", args=[doc.pk])).status_code == 404
    assert client.get(reverse("score_edit", args=[other_student.pk, score.pk])).status_code == 404
    assert client.post(reverse("student_edit", args=[other_student.pk]), {}).status_code == 404
    task.refresh_from_db()
    assert task.status == Task.Status.TODO


def test_student_can_edit_own_profile_but_not_active_flag(client, student_user, student):
    login(client, student_user)
    response = client.post(reverse("student_edit", args=[student.pk]), {
        "first_name": "Ana", "last_name": "Souza", "home_country": "Brazil", "curriculum": "ib",
        "graduation_year": YEAR, "intended_major": "Physics", "is_active": "",
    })
    assert response.status_code == 302
    student.refresh_from_db()
    assert student.intended_major == "Physics"
    assert student.is_active  # field ignored for students


def test_student_request_to_add_school_needs_approval(client, student_user, student, common_app_uni, templates):
    login(client, student_user)
    client.post(reverse("application_add", args=[student.pk]), {
        "university": common_app_uni.pk, "entry_year": YEAR, "round": Round.EA,
    })
    app = Application.objects.get(student=student)
    assert app.status == Application.Status.PENDING_ADD
    assert app.tasks.count() == 0


def test_student_cannot_approve_own_request(client, student_user, student, common_app_uni):
    app = deadlines.add_school(student, common_app_uni, YEAR, Round.EA, student_user)
    login(client, student_user)
    assert client.post(reverse("application_approve", args=[app.pk])).status_code == 403
    app.refresh_from_db()
    assert app.status == Application.Status.PENDING_ADD


def test_student_removal_is_only_a_request(client, student_user, app_listed):
    login(client, student_user)
    client.post(reverse("application_remove", args=[app_listed.pk]))
    app_listed.refresh_from_db()
    assert app_listed.status == Application.Status.PENDING_REMOVAL


def test_student_can_mark_own_task_done(client, student_user, app_listed):
    task = app_listed.tasks.first()
    login(client, student_user)
    client.post(reverse("task_status", args=[task.pk]), {"status": "done"})
    task.refresh_from_db()
    assert task.status == Task.Status.DONE


def test_student_cannot_change_deadline_dates(client, student_user, app_listed, common_app_uni, templates):
    task = app_listed.tasks.get(template=templates["ea"])
    login(client, student_user)
    response = client.post(reverse("task_edit", args=[task.pk]), {"title": "x", "due_date": "2030-01-01", "status": "todo"})
    assert response.status_code == 403
    assert client.post(reverse("task_reset_date", args=[task.pk])).status_code == 403
    assert client.get(reverse("deadline_edit", args=[common_app_uni.pk, templates["ea"].pk])).status_code == 403
    task.refresh_from_db()
    assert task.due_date == templates["ea"].due_date


def test_student_cannot_change_round(client, student_user, app_listed):
    login(client, student_user)
    assert client.post(reverse("application_round", args=[app_listed.pk]), {"round": "rd"}).status_code == 403


def test_student_can_edit_own_manual_task(client, student_user, student):
    task = Task.objects.create(student=student, title="Draft essay", source=Task.Source.MANUAL)
    login(client, student_user)
    client.post(reverse("task_edit", args=[task.pk]), {"title": "Draft essay v2", "due_date": "2026-11-01", "status": "todo"})
    task.refresh_from_db()
    assert task.title == "Draft essay v2"
    assert task.due_date == date(2026, 11, 1)


def test_student_cannot_invite(client, student_user, student):
    login(client, student_user)
    assert client.get(reverse("invite_create", args=[student.pk])).status_code == 403


# ------------------------------------------------------------- parents (read-only)

def test_parent_sees_progress_summary_only(client, parent_user, student, app_listed):
    login(client, parent_user)
    assert client.get(reverse("home"))["Location"] == reverse("student_summary", args=[student.pk])
    assert client.get(reverse("student_summary", args=[student.pk])).status_code == 200
    # The full record (grades, essays, notes) is not available to parents.
    assert client.get(reverse("student_detail", args=[student.pk])).status_code == 404
    assert client.get(reverse("application_detail", args=[app_listed.pk])).status_code == 404
    assert client.get(reverse("note_list", args=[student.pk])).status_code == 404


def test_parent_cannot_view_other_children(client, parent_user, other_student):
    login(client, parent_user)
    assert client.get(reverse("student_summary", args=[other_student.pk])).status_code == 404


def test_parent_summary_has_no_edit_controls(client, parent_user, student, app_listed):
    login(client, parent_user)
    html = client.get(reverse("student_summary", args=[student.pk])).content.decode()
    assert "Edit" not in html
    assert "Mark done" not in html
    assert "<form" not in html.split("<main>")[1]


def test_parent_cannot_change_anything(client, parent_user, student, app_listed, common_app_uni):
    task = app_listed.tasks.first()
    doc = app_listed.documents.first()
    login(client, parent_user)
    attempts = [
        (reverse("student_edit", args=[student.pk]), {"first_name": "X"}),
        (reverse("score_add", args=[student.pk]), {"test": "sat", "score": "1600"}),
        (reverse("grade_add", args=[student.pk]), {"subject": "Math", "grade": "7"}),
        (reverse("application_add", args=[student.pk]), {"university": common_app_uni.pk, "entry_year": YEAR, "round": "rd"}),
        (reverse("application_remove", args=[app_listed.pk]), {}),
        (reverse("task_status", args=[task.pk]), {"status": "done"}),
        (reverse("task_create", args=[student.pk]), {"title": "x"}),
        (reverse("document_edit", args=[doc.pk]), {"doc_type": "transcript", "status": "submitted"}),
        (reverse("document_create", args=[app_listed.pk]), {"doc_type": "other", "status": "ready"}),
    ]
    for url, data in attempts:
        assert client.post(url, data).status_code in (403, 404), url
    task.refresh_from_db()
    doc.refresh_from_db()
    assert task.status == Task.Status.TODO
    assert doc.status == DocumentItem.Status.NOT_STARTED
    assert not TestScore.objects.exists()
    assert app_listed.__class__.objects.get(pk=app_listed.pk).status == Application.Status.ACTIVE


# ------------------------------------------------------------- counselor actions

def test_counselor_override_via_task_edit(client, counselor, app_listed, templates):
    task = app_listed.tasks.get(template=templates["ea"])
    login(client, counselor)
    client.post(reverse("task_edit", args=[task.pk]), {
        "title": task.title, "owner": "", "due_date": "2026-10-20", "status": "todo",
    })
    task.refresh_from_db()
    assert task.due_date == date(2026, 10, 20)
    assert task.date_overridden


def test_counselor_edits_deadline_via_form(client, counselor, app_listed, common_app_uni, templates):
    login(client, counselor)
    t = templates["ea"]
    client.post(reverse("deadline_edit", args=[common_app_uni.pk, t.pk]), {
        "entry_year": YEAR, "round": "ea", "kind": "application", "title": "", "due_date": "2026-10-28",
    })
    assert app_listed.tasks.get(template=t).due_date == date(2026, 10, 28)


def test_next_parameter_cannot_redirect_offsite(client, counselor, app_listed):
    task = app_listed.tasks.first()
    login(client, counselor)
    response = client.post(reverse("task_status", args=[task.pk]), {"status": "done", "next": "https://evil.example/"})
    assert "evil.example" not in response["Location"]

"""The counselor can accept a student's whole college list in one step."""
import pytest
from django.urls import reverse

from portal import deadlines
from portal.models import Application, Round, University

from .conftest import YEAR, make_template

pytestmark = pytest.mark.django_db


@pytest.fixture
def requested_list(student, student_user):
    """A student requests 8 schools: 6 Common App and 2 UCAS."""
    apps = []
    for i in range(6):
        uni = University.objects.create(name=f"US College {i}", country="United States")
        make_template(uni, round_="")
        apps.append(deadlines.add_school(student, uni, YEAR, Round.RD, student_user))
    for i in range(2):
        uni = University.objects.create(name=f"UK Uni {i}", country="UK", application_system=University.System.UCAS)
        make_template(uni)
        apps.append(deadlines.add_school(student, uni, YEAR, Round.UCAS, student_user))
    return apps


def test_approve_whole_list_in_one_request(client, counselor, requested_list):
    client.force_login(counselor)
    response = client.post(reverse("applications_bulk"), {
        "decision": "approve", "application": [a.pk for a in requested_list],
    })
    assert response.status_code == 302
    for app in requested_list:
        app.refresh_from_db()
        assert app.status == Application.Status.ACTIVE
        assert app.tasks.filter(archived=False).count() == 1  # deadline became a task
        assert app.documents.exists()


def test_approve_only_selected(client, counselor, requested_list):
    chosen, skipped = requested_list[:3], requested_list[3:]
    client.force_login(counselor)
    client.post(reverse("applications_bulk"), {"decision": "approve", "application": [a.pk for a in chosen]})
    assert all(Application.objects.get(pk=a.pk).status == Application.Status.ACTIVE for a in chosen)
    assert all(Application.objects.get(pk=a.pk).status == Application.Status.PENDING_ADD for a in skipped)


def test_decline_selected(client, counselor, requested_list):
    client.force_login(counselor)
    client.post(reverse("applications_bulk"), {"decision": "decline", "application": [requested_list[0].pk]})
    assert Application.objects.get(pk=requested_list[0].pk).status == Application.Status.DECLINED


def test_bulk_handles_removal_requests_too(client, counselor, student, student_user, common_app_uni):
    app = deadlines.add_school(student, common_app_uni, YEAR, Round.RD, counselor)
    deadlines.request_removal(app, student_user)
    client.force_login(counselor)
    client.post(reverse("applications_bulk"), {"decision": "approve", "application": [app.pk]})
    assert Application.objects.get(pk=app.pk).status == Application.Status.REMOVED


def test_one_problem_does_not_block_the_rest(counselor, student, student_user, requested_list):
    ox = University.objects.create(name="Ox", country="UK", application_system=University.System.UCAS, oxbridge=True)
    cam = University.objects.create(name="Cam", country="UK", application_system=University.System.UCAS, oxbridge=True)
    ox_app = deadlines.add_school(student, ox, YEAR, Round.UCAS, student_user)
    # Bypass the request-time check to create a conflicting pending request (Oxford AND Cambridge).
    cam_app = Application.objects.create(student=student, university=cam, entry_year=YEAR, round=Round.UCAS)

    done, problems = deadlines.decide_many(requested_list + [ox_app, cam_app], counselor, accept=True)
    # Every other school is approved; the conflicting pair is left for the counselor to choose between.
    assert done == requested_list
    assert {p[0] for p in problems} == {ox_app, cam_app}
    assert all("Oxford or Cambridge" in p[1] for p in problems)
    assert Application.objects.get(pk=cam_app.pk).status == Application.Status.PENDING_ADD


def test_only_counselor_can_bulk_approve(client, student_user, parent_user, requested_list):
    for user in (student_user, parent_user):
        client.force_login(user)
        response = client.post(reverse("applications_bulk"), {"decision": "approve", "application": [requested_list[0].pk]})
        assert response.status_code == 403
    assert Application.objects.get(pk=requested_list[0].pk).status == Application.Status.PENDING_ADD


def test_already_decided_items_are_ignored(client, counselor, student, common_app_uni):
    active = deadlines.add_school(student, common_app_uni, YEAR, Round.RD, counselor)
    client.force_login(counselor)
    client.post(reverse("applications_bulk"), {"decision": "decline", "application": [active.pk]})
    assert Application.objects.get(pk=active.pk).status == Application.Status.ACTIVE


def test_dashboard_groups_requests_by_student(client, counselor, requested_list):
    client.force_login(counselor)
    html = client.get(reverse("dashboard")).content.decode()
    assert "Waiting for your approval (8)" in html
    assert "Approve selected" in html

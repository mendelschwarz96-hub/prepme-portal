"""Encryption at rest, audit log, invites, two-factor login, and link validation."""
import pytest
from django.core import mail
from django.core.exceptions import ValidationError
from django.db import connection
from django.test import override_settings
from django.urls import reverse
from django_otp.oath import totp
from django_otp.plugins.otp_totp.models import TOTPDevice

from accounts.models import Invite, User
from core.models import AuditLog
from portal.models import TestScore, validate_google_link

pytestmark = pytest.mark.django_db


def raw_value(table, column, pk):
    with connection.cursor() as cursor:
        cursor.execute(f"SELECT {column} FROM {table} WHERE id = %s", [pk])
        return cursor.fetchone()[0]


def test_sensitive_fields_are_encrypted_in_database(student):
    student.gpa = "9.4"
    student.save()
    score = TestScore.objects.create(student=student, test=TestScore.Test.SAT, score="1530")

    raw_gpa = raw_value("portal_studentprofile", "gpa", student.pk)
    raw_score = raw_value("portal_testscore", "score", score.pk)
    assert raw_gpa.startswith("enc1:") and "9.4" not in raw_gpa
    assert raw_score.startswith("enc1:") and "1530" not in raw_score

    student.refresh_from_db()
    assert student.gpa == "9.4"
    assert TestScore.objects.get(pk=score.pk).score == "1530"


def test_test_score_range_validated(student):
    score = TestScore(student=student, test=TestScore.Test.SAT, score="1700")
    with pytest.raises(ValidationError):
        score.full_clean()


def test_viewing_a_student_is_audited(client, parent_user, student):
    client.force_login(parent_user)
    client.get(reverse("student_detail", args=[student.pk]))
    entry = AuditLog.objects.filter(action=AuditLog.Action.VIEW, student_id=student.pk).get()
    assert entry.user == parent_user
    assert entry.actor_email == parent_user.email


def test_audit_entries_cannot_be_changed(counselor):
    entry = AuditLog.objects.create(user=counselor, action=AuditLog.Action.VIEW)
    entry.detail = "tampered"
    with pytest.raises(ValueError):
        entry.save()
    with pytest.raises(ValueError):
        entry.delete()


def test_failed_login_is_audited(client, counselor):
    client.post(reverse("login"), {"username": counselor.email, "password": "wrong"})
    assert AuditLog.objects.filter(action=AuditLog.Action.LOGIN_FAILED, actor_email=counselor.email).exists()


@pytest.mark.parametrize("link,ok", [
    ("https://docs.google.com/document/d/abc/edit", True),
    ("https://drive.google.com/file/d/abc/view", True),
    ("http://docs.google.com/document/d/abc", False),
    ("https://evil.com/docs.google.com", False),
    ("https://docs.google.com.evil.com/x", False),
])
def test_only_google_links_accepted(link, ok):
    if ok:
        validate_google_link(link)
    else:
        with pytest.raises(ValidationError):
            validate_google_link(link)


# ------------------------------------------------------------- invites

def _invite_token(client, counselor, student, email, role):
    client.force_login(counselor)
    response = client.post(reverse("invite_create", args=[student.pk]), {"email": email, "role": role})
    client.logout()
    return response.context["link"].rsplit("/invite/", 1)[1].strip("/")


def test_parent_invite_creates_linked_parent(client, counselor, student):
    token = _invite_token(client, counselor, student, "dad@test.dev", "parent")
    assert len(mail.outbox) == 1
    response = client.post(reverse("accept_invite", args=[token]), {
        "first_name": "Dad", "last_name": "Souza", "password1": "a-Strong-pass-42", "password2": "a-Strong-pass-42",
    })
    assert response.status_code == 302
    dad = User.objects.get(email="dad@test.dev")
    assert dad.role == User.Role.PARENT
    assert student.parents.filter(pk=dad.pk).exists()

    # The link works only once.
    assert client.get(reverse("accept_invite", args=[token])).status_code == 404


def test_invite_token_is_not_stored_in_plain_text(client, counselor, student):
    token = _invite_token(client, counselor, student, "x@test.dev", "parent")
    assert not Invite.objects.filter(token_hash=token).exists()


def test_bad_invite_token_rejected(client):
    assert client.get(reverse("accept_invite", args=["not-a-real-token"])).status_code == 404


# ------------------------------------------------------------- two-factor login

@override_settings(REQUIRE_COUNSELOR_2FA=True)
def test_counselor_must_set_up_two_factor(client, counselor):
    client.force_login(counselor)
    response = client.get(reverse("dashboard"))
    assert response["Location"] == reverse("two_factor_setup")


@override_settings(REQUIRE_COUNSELOR_2FA=True)
def test_counselor_with_device_must_verify_then_gets_in(client, counselor):
    device = TOTPDevice.objects.create(user=counselor, name="phone", confirmed=True)
    client.force_login(counselor)
    assert client.get(reverse("dashboard"))["Location"] == reverse("two_factor_verify")

    code = totp(device.bin_key, step=device.step, t0=device.t0, digits=device.digits)
    client.post(reverse("two_factor_verify"), {"token": f"{code:06d}"})
    assert client.get(reverse("dashboard")).status_code == 200


@override_settings(REQUIRE_COUNSELOR_2FA=True)
def test_students_do_not_need_two_factor(client, student_user, student):
    client.force_login(student_user)
    assert client.get(reverse("student_detail", args=[student.pk])).status_code == 200

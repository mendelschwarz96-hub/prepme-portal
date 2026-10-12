"""Phase 2: essays (versions, comments), prompt library, meeting notes, parent summary."""
from datetime import date

import pytest
from django.db import connection
from django.urls import reverse

from portal import deadlines, essays
from portal.models import Essay, EssayComment, EssayPrompt, EssayVersion, MeetingNote, Round, University

from .conftest import YEAR

pytestmark = pytest.mark.django_db

SECRET_ESSAY = "My grandmother taught me to cook feijoada every Sunday."


@pytest.fixture
def essay(student):
    return Essay.objects.create(student=student, title="Personal statement")


@pytest.fixture
def written(essay, student_user):
    essays.save_version(essay, SECRET_ESSAY, student_user)
    return essay


# ------------------------------------------------------------- versions

def test_each_save_is_a_new_version(essay, student_user, counselor):
    v1, created, _ = essays.save_version(essay, "First draft.", student_user)
    v2, created2, _ = essays.save_version(essay, "Second draft, longer.", counselor)
    assert (v1.number, v2.number) == (1, 2)
    assert created and created2
    assert v2.word_count == 3
    assert essay.latest_version == v2
    assert EssayVersion.objects.get(pk=v1.pk).body == "First draft."


def test_saving_unchanged_text_creates_nothing(essay, student_user):
    essays.save_version(essay, "Same.", student_user)
    _, created, _ = essays.save_version(essay, "Same.", student_user)
    assert not created
    assert essay.versions.count() == 1


def test_windows_line_endings_normalized(essay, student_user):
    v, _, _ = essays.save_version(essay, "a\r\nb", student_user)
    assert v.body == "a\nb"


def test_versions_cannot_be_edited(written):
    v = written.latest_version
    v.body = "tampered"
    with pytest.raises(ValueError):
        v.save()


def test_conflict_detected_but_nothing_lost(written, student_user, counselor):
    # Counselor opened version 1, student saves version 2, then counselor saves.
    essays.save_version(written, "Student edit.", student_user, base_number=1)
    v3, created, conflict = essays.save_version(written, "Counselor edit.", counselor, base_number=1)
    assert created and conflict and v3.number == 3
    assert written.versions.get(number=2).body == "Student edit."


def test_restore_creates_new_version(written, student_user):
    essays.save_version(written, "Worse draft.", student_user)
    v3, created, _ = essays.restore_version(written, written.versions.get(number=1), student_user)
    assert created and v3.number == 3 and v3.body == SECRET_ESSAY


def test_essay_text_encrypted_at_rest(written):
    with connection.cursor() as cursor:
        cursor.execute("SELECT body FROM portal_essayversion")
        raw = cursor.fetchone()[0]
    assert raw.startswith("enc1:") and "feijoada" not in raw


def test_compare_marks_changes():
    html = essays.compare("I like cats.", "I love cats and dogs.")
    assert "<del>like</del>" in html and "<ins>love</ins>" in html


# ------------------------------------------------------------- comments

def test_comment_anchored_to_selection(written, counselor):
    start = SECRET_ESSAY.index("feijoada")
    c = essays.add_comment(written.latest_version, counselor, "Describe the smell!", start=start,
                           end=start + 8, quote="feijoada")
    assert (c.start, c.end) == (start, start + 8)


def test_comment_with_wrong_offsets_falls_back_to_quote(written, counselor):
    c = essays.add_comment(written.latest_version, counselor, "Nice", start=0, end=4, quote="Sunday")
    assert SECRET_ESSAY[c.start:c.end] == "Sunday"


def test_comment_without_match_is_general(written, counselor):
    c = essays.add_comment(written.latest_version, counselor, "Overall good", quote="not in text")
    assert not c.is_anchored


def test_highlight_escapes_html(essay, counselor):
    v, _, _ = essays.save_version(essay, "<script>alert(1)</script> hello", counselor)
    c = essays.add_comment(v, counselor, "x", quote="hello")
    html = essays.highlight(v.body, [c])
    assert "<script>" not in html and "&lt;script&gt;" in html
    assert f'data-comments="c{c.pk}"' in html and ">hello</mark>" in html


def test_overlapping_comments(essay, counselor):
    v, _, _ = essays.save_version(essay, "one two three", counselor)
    a = essays.add_comment(v, counselor, "a", quote="one two")
    b = essays.add_comment(v, counselor, "b", quote="two three")
    html = essays.highlight(v.body, [a, b])
    assert f'data-comments="c{a.pk} c{b.pk}"' in html  # "two" is covered by both


def test_comment_via_http_and_resolve(client, written, student_user, counselor):
    client.force_login(counselor)
    client.post(reverse("comment_create", args=[written.pk]), {"body": "Great opening", "quote": "My grandmother"})
    comment = EssayComment.objects.get()
    assert comment.is_anchored
    client.force_login(student_user)
    client.post(reverse("comment_resolve", args=[comment.pk]))
    comment.refresh_from_db()
    assert comment.resolved


def test_student_cannot_delete_counselors_comment(client, written, student_user, counselor):
    c = essays.add_comment(written.latest_version, counselor, "Keep this")
    client.force_login(student_user)
    assert client.post(reverse("comment_delete", args=[c.pk])).status_code == 403
    assert EssayComment.objects.filter(pk=c.pk).exists()


def test_open_comments_from_older_versions_stay_visible(client, written, student_user, counselor):
    essays.add_comment(written.latest_version, counselor, "Fix the ending")
    essays.save_version(written, SECRET_ESSAY + " New ending.", student_user)
    client.force_login(student_user)
    html = client.get(reverse("essay_detail", args=[written.pk])).content.decode()
    assert "Fix the ending" in html and "on version 1" in html


# ------------------------------------------------------------- essay permissions

def test_student_writes_own_essay_via_http(client, student, student_user):
    client.force_login(student_user)
    client.post(reverse("essay_create", args=[student.pk]), {"title": "Why us"})
    essay = Essay.objects.get(student=student)
    client.post(reverse("essay_edit", args=[essay.pk]), {"body": "Draft text", "base_number": 0})
    assert essay.latest_version.body == "Draft text"


def test_other_student_cannot_see_or_edit_essay(client, written, other_student_user):
    client.force_login(other_student_user)
    assert client.get(reverse("essay_detail", args=[written.pk])).status_code == 404
    assert client.post(reverse("essay_edit", args=[written.pk]), {"body": "hacked"}).status_code == 404
    assert client.post(reverse("comment_create", args=[written.pk]), {"body": "x"}).status_code == 404
    assert client.get(reverse("essay_version", args=[written.pk, 1])).status_code == 404
    assert written.versions.count() == 1


def test_parent_cannot_read_essays(client, written, parent_user):
    client.force_login(parent_user)
    assert client.get(reverse("essay_detail", args=[written.pk])).status_code == 404
    assert client.get(reverse("essay_versions", args=[written.pk])).status_code == 404


def test_only_counselor_deletes_essays(client, written, student_user):
    client.force_login(student_user)
    assert client.post(reverse("essay_delete", args=[written.pk])).status_code == 403


def test_viewing_essay_is_audited(client, written, counselor):
    from core.models import AuditLog
    client.force_login(counselor)
    client.get(reverse("essay_detail", args=[written.pk]))
    assert AuditLog.objects.filter(action="view", object_type="Essay", object_id=str(written.pk)).exists()


# ------------------------------------------------------------- prompt library

def test_student_sees_prompts_for_listed_schools_and_general(student, counselor, common_app_uni):
    from portal.forms import prompts_for_student
    other = University.objects.create(name="Other U", country="US")
    deadlines.add_school(student, common_app_uni, YEAR, Round.RD, counselor)
    mine = EssayPrompt.objects.create(university=common_app_uni, entry_year=YEAR, title="Why us", text="...")
    general = EssayPrompt.objects.create(application_system="common_app", entry_year=YEAR, title="PS", text="...")
    EssayPrompt.objects.create(university=other, entry_year=YEAR, title="Not mine", text="...")
    EssayPrompt.objects.create(application_system="ucas", entry_year=YEAR, title="UCAS PS", text="...")
    EssayPrompt.objects.create(university=common_app_uni, entry_year=YEAR - 1, title="Old", text="...")
    assert set(prompts_for_student(student)) == {mine, general}


def test_essay_from_prompt_links_school(client, student, student_user, counselor, common_app_uni):
    app = deadlines.add_school(student, common_app_uni, YEAR, Round.RD, counselor)
    prompt = EssayPrompt.objects.create(university=common_app_uni, entry_year=YEAR, title="Why us", text="...", word_limit=250)
    client.force_login(student_user)
    client.post(reverse("essay_create", args=[student.pk]), {"prompt": prompt.pk})
    essay = Essay.objects.get()
    assert essay.title == "Why us" and essay.application == app and essay.word_limit == 250


def test_prompt_library_counselor_only(client, student_user):
    client.force_login(student_user)
    assert client.get(reverse("prompt_list")).status_code == 403
    assert client.post(reverse("prompt_create"), {}).status_code == 403


# ------------------------------------------------------------- meeting notes

@pytest.fixture
def notes(student, counselor):
    private = MeetingNote.objects.create(student=student, met_on=date(2026, 9, 1), title="Family situation",
                                         body="Private details", author=counselor)
    shared = MeetingNote.objects.create(student=student, met_on=date(2026, 9, 8), title="Next steps",
                                        body="Finish the supplement", shared_with_student=True, author=counselor)
    return private, shared


def test_student_sees_only_shared_notes(client, student, student_user, notes):
    client.force_login(student_user)
    html = client.get(reverse("note_list", args=[student.pk])).content.decode()
    assert "Next steps" in html and "Family situation" not in html
    html = client.get(reverse("student_detail", args=[student.pk])).content.decode()
    assert "Family situation" not in html


def test_counselor_sees_all_notes(client, student, counselor, notes):
    client.force_login(counselor)
    html = client.get(reverse("note_list", args=[student.pk])).content.decode()
    assert "Next steps" in html and "Family situation" in html


def test_students_cannot_write_notes(client, student, student_user, notes):
    client.force_login(student_user)
    assert client.post(reverse("note_create", args=[student.pk]), {"title": "x", "body": "y", "met_on": "2026-10-01"}).status_code == 403
    assert client.post(reverse("note_edit", args=[student.pk, notes[1].pk]), {"title": "x"}).status_code == 403


def test_notes_encrypted_at_rest(notes):
    with connection.cursor() as cursor:
        cursor.execute("SELECT title, body FROM portal_meetingnote")
        for title, body in cursor.fetchall():
            assert title.startswith("enc1:") and body.startswith("enc1:")


# ------------------------------------------------------------- parent summary

def test_parent_summary_shows_progress_not_content(client, parent_user, student, counselor, common_app_uni,
                                                   templates, written, notes):
    deadlines.add_school(student, common_app_uni, YEAR, Round.EA, counselor)
    written.status = Essay.Status.DRAFTING
    written.save()
    client.force_login(parent_user)
    html = client.get(reverse("student_summary", args=[student.pk])).content.decode()
    assert "Sample U" in html                     # schools
    assert "Personal statement" in html           # essay title and status
    assert "Drafting" in html
    assert "feijoada" not in html                 # never essay text
    assert "Family situation" not in html and "Next steps" not in html  # never notes


def test_summary_counts(student, counselor, common_app_uni, templates):
    from portal import summary
    app = deadlines.add_school(student, common_app_uni, YEAR, Round.EA, counselor)
    deadlines.set_task_status(app.tasks.first(), "done")
    data = summary.build(student)
    assert data["tasks_total"] == 2 and data["tasks_done"] == 1
    assert data["schools"][0]["docs_total"] == app.documents.count()

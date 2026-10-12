"""Server-side permission rules. Every view goes through these helpers.

- Counselor: sees and edits everything.
- Student: sees and edits only their own record (school-list changes need approval).
  Students see only the meeting notes the counselor chose to share.
- Parent: read-only progress summary of their own children. No access to the full
  record (essays, grades, notes).
Records a user may not see return 404, so their existence is not revealed.
"""
from functools import wraps

from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404

from .models import Application, DocumentItem, Essay, EssayComment, MeetingNote, StudentProfile, Task


def record_students(user):
    """Students whose full record the user may open."""
    if not user.is_authenticated:
        return StudentProfile.objects.none()
    if user.is_counselor:
        return StudentProfile.objects.all()
    if user.is_student:
        return StudentProfile.objects.filter(user=user)
    return StudentProfile.objects.none()


def summary_students(user):
    """Students whose progress summary the user may open (adds parents' children)."""
    if user.is_authenticated and user.is_parent:
        return StudentProfile.objects.filter(parents=user)
    return record_students(user)


def can_edit_student(user, student):
    return user.is_counselor or (user.is_student and student.user_id == user.id)


def counselor_required(view):
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated or not request.user.is_counselor:
            raise PermissionDenied
        return view(request, *args, **kwargs)

    return wrapper


def _check_edit(user, student, edit):
    if edit and not can_edit_student(user, student):
        raise PermissionDenied


def get_student(user, pk, *, edit=False):
    student = get_object_or_404(record_students(user), pk=pk)
    _check_edit(user, student, edit)
    return student


def get_summary_student(user, pk):
    return get_object_or_404(summary_students(user), pk=pk)


def get_application(user, pk, *, edit=False):
    application = get_object_or_404(
        Application.objects.select_related("student", "university").filter(student__in=record_students(user)), pk=pk
    )
    _check_edit(user, application.student, edit)
    return application


def get_task(user, pk, *, edit=False):
    task = get_object_or_404(Task.objects.select_related("student").filter(student__in=record_students(user)), pk=pk)
    _check_edit(user, task.student, edit)
    return task


def get_document(user, pk, *, edit=False):
    document = get_object_or_404(
        DocumentItem.objects.select_related("application__student", "application__university").filter(
            application__student__in=record_students(user)
        ),
        pk=pk,
    )
    _check_edit(user, document.application.student, edit)
    return document


def get_essay(user, pk, *, edit=False):
    essay = get_object_or_404(
        Essay.objects.select_related("student", "prompt", "application__university").filter(
            student__in=record_students(user)
        ),
        pk=pk,
    )
    _check_edit(user, essay.student, edit)
    return essay


def get_comment(user, pk):
    comment = get_object_or_404(
        EssayComment.objects.select_related("version__essay__student").filter(
            version__essay__student__in=record_students(user)
        ),
        pk=pk,
    )
    _check_edit(user, comment.version.essay.student, True)
    return comment


def visible_notes(user, student):
    notes = MeetingNote.objects.filter(student=student)
    if user.is_counselor:
        return notes
    if user.is_student and student.user_id == user.id:
        return notes.filter(shared_with_student=True)
    return notes.none()


def can_edit_task_details(user, task):
    """Title, owner and due date. Students may only edit tasks they added themselves."""
    if user.is_counselor:
        return True
    return can_edit_student(user, task.student) and task.source == Task.Source.MANUAL

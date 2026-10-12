"""Server-side permission rules. Every view goes through these helpers.

- Counselor: sees and edits everything.
- Student: sees and edits only their own record (school-list changes need approval).
- Parent: read-only view of their own children.
Records a user may not see return 404, so their existence is not revealed.
"""
from functools import wraps

from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404

from .models import Application, DocumentItem, StudentProfile, Task


def visible_students(user):
    if not user.is_authenticated:
        return StudentProfile.objects.none()
    if user.is_counselor:
        return StudentProfile.objects.all()
    if user.is_student:
        return StudentProfile.objects.filter(user=user)
    if user.is_parent:
        return StudentProfile.objects.filter(parents=user)
    return StudentProfile.objects.none()


def can_edit_student(user, student):
    return user.is_counselor or (user.is_student and student.user_id == user.id)


def counselor_required(view):
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated or not request.user.is_counselor:
            raise PermissionDenied
        return view(request, *args, **kwargs)

    return wrapper


def get_student(user, pk, *, edit=False):
    student = get_object_or_404(visible_students(user), pk=pk)
    if edit and not can_edit_student(user, student):
        raise PermissionDenied
    return student


def get_application(user, pk, *, edit=False):
    application = get_object_or_404(
        Application.objects.select_related("student", "university").filter(student__in=visible_students(user)), pk=pk
    )
    if edit and not can_edit_student(user, application.student):
        raise PermissionDenied
    return application


def get_task(user, pk, *, edit=False):
    task = get_object_or_404(Task.objects.select_related("student").filter(student__in=visible_students(user)), pk=pk)
    if edit and not can_edit_student(user, task.student):
        raise PermissionDenied
    return task


def get_document(user, pk, *, edit=False):
    document = get_object_or_404(
        DocumentItem.objects.select_related("application__student", "application__university").filter(
            application__student__in=visible_students(user)
        ),
        pk=pk,
    )
    if edit and not can_edit_student(user, document.application.student):
        raise PermissionDenied
    return document


def can_edit_task_details(user, task):
    """Title, owner and due date. Students may only edit tasks they added themselves."""
    if user.is_counselor:
        return True
    return can_edit_student(user, task.student) and task.source == Task.Source.MANUAL

from django.conf import settings

from .models import AuditLog

Action = AuditLog.Action


def client_ip(request):
    if request is None:
        return None
    if settings.TRUST_PROXY_HEADERS:
        forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
        if forwarded:
            return forwarded.split(",")[0].strip() or None
    return request.META.get("REMOTE_ADDR") or None


def log(request, action, obj=None, *, student=None, detail="", user=None, actor_email=""):
    """Write one audit entry. `student` is the StudentProfile the action concerns."""
    if user is None and request is not None and request.user.is_authenticated:
        user = request.user
    if student is None and obj is not None:
        student = getattr(obj, "audit_student", None)
    return AuditLog.objects.create(
        user=user,
        actor_email=actor_email or (user.email if user else ""),
        action=action,
        object_type=obj.__class__.__name__ if obj is not None else "",
        object_id=str(obj.pk) if obj is not None and obj.pk is not None else "",
        student_id=student.pk if student is not None else None,
        detail=detail[:255],
        ip=client_ip(request),
    )

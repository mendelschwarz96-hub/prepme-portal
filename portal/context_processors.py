from .models import Application


def nav(request):
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated or not user.is_counselor:
        return {}
    pending = Application.objects.filter(
        status__in=[Application.Status.PENDING_ADD, Application.Status.PENDING_REMOVAL]
    ).count()
    return {"pending_approvals": pending}

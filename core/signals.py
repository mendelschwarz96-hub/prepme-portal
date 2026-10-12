from django.contrib.auth.signals import user_logged_in, user_logged_out, user_login_failed
from django.dispatch import receiver

from . import audit


@receiver(user_logged_in)
def on_login(sender, request, user, **kwargs):
    audit.log(request, audit.Action.LOGIN, user=user)


@receiver(user_logged_out)
def on_logout(sender, request, user, **kwargs):
    if user is not None:
        audit.log(request, audit.Action.LOGOUT, user=user)


@receiver(user_login_failed)
def on_login_failed(sender, credentials, request=None, **kwargs):
    audit.log(request, audit.Action.LOGIN_FAILED, actor_email=str(credentials.get("username", ""))[:254])

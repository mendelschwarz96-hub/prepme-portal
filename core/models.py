from django.conf import settings
from django.db import models


class AuditLog(models.Model):
    """Append-only record of who viewed or changed what.

    Never store sensitive values in `detail`; describe the action only.
    """

    class Action(models.TextChoices):
        VIEW = "view", "Viewed"
        CREATE = "create", "Created"
        UPDATE = "update", "Updated"
        DELETE = "delete", "Deleted"
        APPROVE = "approve", "Approved"
        DECLINE = "decline", "Declined"
        INVITE = "invite", "Invited"
        LOGIN = "login", "Logged in"
        LOGIN_FAILED = "login_failed", "Failed login"
        LOGOUT = "logout", "Logged out"
        TWO_FACTOR = "two_factor", "Two-factor"

    at = models.DateTimeField(auto_now_add=True, db_index=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    actor_email = models.CharField(max_length=254, blank=True)
    action = models.CharField(max_length=20, choices=Action.choices)
    object_type = models.CharField(max_length=50, blank=True)
    object_id = models.CharField(max_length=50, blank=True)
    # Plain integer (not a foreign key) so log entries survive if a student record is deleted.
    student_id = models.BigIntegerField(null=True, blank=True, db_index=True)
    detail = models.CharField(max_length=255, blank=True)
    ip = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        ordering = ["-at"]

    def __str__(self):
        return f"{self.at:%Y-%m-%d %H:%M} {self.actor_email} {self.action} {self.object_type} {self.object_id}"

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise ValueError("Audit log entries cannot be changed.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError("Audit log entries cannot be deleted.")

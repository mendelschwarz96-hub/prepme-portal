from django.core.management.base import BaseCommand, CommandError
from django_otp.plugins.otp_static.models import StaticDevice
from django_otp.plugins.otp_totp.models import TOTPDevice

from accounts.models import User
from core.models import AuditLog


class Command(BaseCommand):
    help = "Remove a user's two-factor devices (e.g. lost phone). They set it up again at next login."

    def add_arguments(self, parser):
        parser.add_argument("email")

    def handle(self, *args, email, **options):
        user = User.objects.filter(email__iexact=email).first()
        if user is None:
            raise CommandError(f"No user with email {email}.")
        TOTPDevice.objects.filter(user=user).delete()
        StaticDevice.objects.filter(user=user).delete()
        AuditLog.objects.create(
            user=user, actor_email="(server command)", action=AuditLog.Action.TWO_FACTOR, detail="Two-factor reset by command"
        )
        self.stdout.write(self.style.SUCCESS(f"Two-factor login reset for {email}."))

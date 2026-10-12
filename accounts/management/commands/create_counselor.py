from getpass import getpass

from django.contrib.auth import password_validation
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from accounts.models import User


class Command(BaseCommand):
    help = "Create the counselor (admin) account. Two-factor setup happens at first login."

    def add_arguments(self, parser):
        parser.add_argument("--email", required=True)
        parser.add_argument("--first-name", default="")
        parser.add_argument("--last-name", default="")

    def handle(self, *args, email, first_name, last_name, **options):
        if User.objects.filter(email__iexact=email).exists():
            raise CommandError(f"A user with email {email} already exists.")
        password = getpass("Password: ")
        if password != getpass("Repeat password: "):
            raise CommandError("Passwords do not match.")
        candidate = User(email=email, first_name=first_name, last_name=last_name)
        try:
            password_validation.validate_password(password, candidate)
        except ValidationError as exc:
            raise CommandError(" ".join(exc.messages))
        User.objects.create_user(
            email=email, password=password, first_name=first_name, last_name=last_name, role=User.Role.COUNSELOR
        )
        self.stdout.write(self.style.SUCCESS(f"Counselor {email} created. Log in to set up two-factor login."))

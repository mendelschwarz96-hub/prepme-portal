import hashlib
import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models
from django.utils import timezone


class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create_user(self, email, password, **extra):
        if not email:
            raise ValueError("Email is required.")
        user = self.model(email=self.normalize_email(email).lower(), **extra)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra):
        extra.setdefault("is_staff", False)
        extra.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra)

    def create_superuser(self, email, password=None, **extra):
        extra.update(is_staff=True, is_superuser=True, role=User.Role.COUNSELOR)
        return self._create_user(email, password, **extra)

    def get_by_natural_key(self, email):
        return self.get(email__iexact=email)


class User(AbstractUser):
    class Role(models.TextChoices):
        COUNSELOR = "counselor", "Counselor"
        STUDENT = "student", "Student"
        PARENT = "parent", "Parent"

    username = None
    email = models.EmailField(unique=True)
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.STUDENT)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    objects = UserManager()

    def save(self, *args, **kwargs):
        self.email = self.email.lower()
        super().save(*args, **kwargs)

    def __str__(self):
        return self.get_full_name() or self.email

    @property
    def is_counselor(self):
        return self.role == self.Role.COUNSELOR

    @property
    def is_student(self):
        return self.role == self.Role.STUDENT

    @property
    def is_parent(self):
        return self.role == self.Role.PARENT

    @property
    def requires_two_factor(self):
        return self.is_counselor or self.is_superuser


def _hash_token(raw):
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class Invite(models.Model):
    """A one-time link that lets a student or parent create their login.

    Only a hash of the token is stored, so a database leak cannot be used to accept invites.
    """

    email = models.EmailField()
    role = models.CharField(max_length=20, choices=[(User.Role.STUDENT, "Student"), (User.Role.PARENT, "Parent")])
    student = models.ForeignKey("portal.StudentProfile", on_delete=models.CASCADE, related_name="invites")
    token_hash = models.CharField(max_length=64, unique=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    accepted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    @property
    def audit_student(self):
        return self.student

    @classmethod
    def create(cls, *, email, role, student, created_by):
        raw = secrets.token_urlsafe(32)
        invite = cls.objects.create(
            email=email.lower(),
            role=role,
            student=student,
            token_hash=_hash_token(raw),
            created_by=created_by,
            expires_at=timezone.now() + timedelta(days=settings.INVITE_VALID_DAYS),
        )
        return invite, raw

    @classmethod
    def find_valid(cls, raw):
        return cls.objects.filter(
            token_hash=_hash_token(raw), accepted_at__isnull=True, expires_at__gt=timezone.now()
        ).select_related("student").first()

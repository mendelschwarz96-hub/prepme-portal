"""Settings for the automated tests: in-memory database, fixed test keys."""
import os

os.environ.setdefault("DJANGO_SECRET_KEY", "test-secret-key-not-for-production")
# A fixed, throwaway Fernet key used only by tests.
os.environ.setdefault("FIELD_ENCRYPTION_KEYS", "MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=")
os.environ["DATABASE_URL"] = "sqlite://:memory:"

from .settings import *  # noqa: E402,F401,F403

DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}
DEBUG = False
SECURE_SSL_REDIRECT = False
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
STATIC_ROOT = BASE_DIR / "static"  # noqa: F405  (avoids a WhiteNoise warning; no collectstatic in tests)
STORAGES["staticfiles"] = {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}  # noqa: F405
REQUIRE_COUNSELOR_2FA = False  # turned back on in the 2FA tests
AXES_ENABLED = False

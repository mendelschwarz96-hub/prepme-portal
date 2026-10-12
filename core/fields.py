"""Encrypted model fields.

Values are encrypted with Fernet (AES-128-CBC + HMAC) before they reach the
database, using the keys in settings.FIELD_ENCRYPTION_KEYS. Encrypted columns
cannot be searched or sorted in SQL; filter them in Python instead.
"""
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db import models

PREFIX = "enc1:"


@lru_cache(maxsize=4)
def _fernet(keys):
    try:
        return MultiFernet([Fernet(key) for key in keys])
    except (ValueError, TypeError) as exc:
        raise ImproperlyConfigured("FIELD_ENCRYPTION_KEYS contains an invalid key.") from exc


def get_fernet():
    return _fernet(tuple(settings.FIELD_ENCRYPTION_KEYS))


def encrypt(value: str) -> str:
    return PREFIX + get_fernet().encrypt(value.encode("utf-8")).decode("ascii")


def decrypt(value: str) -> str:
    if not value.startswith(PREFIX):
        raise ValueError("Value is not encrypted with this application's format.")
    try:
        return get_fernet().decrypt(value[len(PREFIX):].encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise ImproperlyConfigured("Could not decrypt a field: check FIELD_ENCRYPTION_KEYS.") from exc


class EncryptedTextField(models.TextField):
    """A text field stored encrypted. Empty strings are stored as-is."""

    def from_db_value(self, value, expression, connection):
        if value is None or value == "":
            return value
        return decrypt(value)

    def get_prep_value(self, value):
        value = super().get_prep_value(value)
        if value is None or value == "":
            return value
        return encrypt(str(value))

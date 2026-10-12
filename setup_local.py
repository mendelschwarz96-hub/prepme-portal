"""Create a .env file with fresh secret keys for local development.

Usage:  .venv\\Scripts\\python.exe setup_local.py
Never commit .env. Production keys are set in the hosting dashboard instead.
"""
import secrets
from pathlib import Path

from cryptography.fernet import Fernet

ENV_PATH = Path(__file__).resolve().parent / ".env"

if ENV_PATH.exists():
    print(f"{ENV_PATH} already exists; leaving it unchanged.")
else:
    ENV_PATH.write_text(
        "\n".join(
            [
                "DJANGO_DEBUG=1",
                f"DJANGO_SECRET_KEY={secrets.token_urlsafe(50)}",
                f"FIELD_ENCRYPTION_KEYS={Fernet.generate_key().decode()}",
                "# Leave DATABASE_URL unset to use a local SQLite file.",
                "# DATABASE_URL=postgresql://user:password@host/dbname?sslmode=require",
                "# Set to 0 to skip two-factor login while testing locally.",
                "REQUIRE_COUNSELOR_2FA=1",
                "",
            ]
        ),
        encoding="utf-8",
    )
    print(f"Created {ENV_PATH}")

# PrepMe Portal

Private college-counseling portal for PrepMe: one counselor, her students, and their parents.
There is no public sign-up. The counselor invites every student and parent.

## Run it on this computer

From `C:\Users\mende\Documents\prepme-portal` in PowerShell:

```powershell
.venv\Scripts\python.exe setup_local.py           # first time only: creates .env with secret keys
.venv\Scripts\python.exe manage.py migrate        # creates / updates the local database
.venv\Scripts\python.exe manage.py load_demo      # optional: sample students, schools, deadlines
.venv\Scripts\python.exe manage.py runserver
```

Then open http://127.0.0.1:8000. Demo logins (password `PrepMeDemo!2026`):

| Email | Role |
|---|---|
| counselor@demo.test | Counselor (asks you to set up an authenticator app at first login) |
| ana@demo.test | Student |
| parent@demo.test | Ana's parent (read-only) |

To skip two-factor login while testing locally, set `REQUIRE_COUNSELOR_2FA=0` in `.env`.
To start over, delete `db.sqlite3` and run `migrate` and `load_demo` again.

## Run the tests

```powershell
.venv\Scripts\python.exe -m pytest
```

## How the deadline engine works

- Each university has deadlines for each entry year (University → Add deadline). A deadline's
  round can be blank, meaning it applies to every round.
- When a school goes on a student's list, every matching deadline becomes a task for that student.
  This happens when the counselor adds it, or when she approves a student's request.
- Editing a university deadline moves that task for every student, except students whose date
  the counselor changed individually. The app marks those "custom date" and offers a "Use school date" button.
- Changing a student's round, or removing the school, hides tasks that no longer apply.
  Completed tasks are never changed.
- UCAS rules: at most 5 UCAS choices per year (pending requests count), and only one of
  Oxford or Cambridge (set the "Oxford or Cambridge" flag on those universities).

## Security notes

- Permissions are checked on the server for every request (`portal/permissions.py`).
- Grades, GPA and test scores are encrypted in the database (`core/fields.py`), with keys from
  `FIELD_ENCRYPTION_KEYS`. **If the key is lost, that data cannot be recovered.** Keep a copy
  of the production key in a password manager.
- Every view of a student record, every change and every login is written to the audit log
  (Audit log page in the counselor menu).
- Logins lock for 1 hour after 5 failed attempts. Counselor login requires an authenticator app.
  If she loses her phone, use a backup code, or run `manage.py reset_2fa <email>`.

## Useful commands

```powershell
.venv\Scripts\python.exe manage.py create_counselor --email someone@example.com --first-name Name --last-name Surname
.venv\Scripts\python.exe manage.py reset_2fa someone@example.com
```

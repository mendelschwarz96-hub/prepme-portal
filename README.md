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
| ana@demo.test | Student (has an essay with comments) |
| pedro@demo.test | Student (has a list waiting for approval) |
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

## Approving school lists

Students request schools one at a time, and the counselor approves them in bulk. "This week"
groups pending requests by student, with every request checked: **Approve selected** handles
one student's whole list, and **Approve all** handles everyone's. The same button is on each
student's page. If one request breaks a UCAS rule (e.g. both Oxford and Cambridge), only that
one is held back and the rest are approved.

## Phase 2: essays, notes, parent view

- **Essays.** Every save creates a new version. Versions can't be edited, so history is complete.
  "History" shows word-level changes between versions, and any version can be restored. If two
  people edit at once, both texts are kept and the second person is warned.
- **Comments.** Select any passage in the essay and add a comment; the passage is highlighted.
  Open comments on older versions stay visible until resolved.
- **Prompt library** (counselor menu → Prompts). A prompt belongs to a university and an entry
  year, or is general for Common App / UCAS. Students see prompts for the schools on their list.
- **Meeting notes.** Private to the counselor unless she ticks "Share with student".
  Parents never see them.
- **Parent view.** Parents see only a progress summary: schools, task and document progress,
  upcoming deadlines, and essay titles, statuses and word counts. They never see essay text,
  grades, scores or notes. Counselor and student can open the same summary from the student page.

## Phase 3: university data

- **U.S. colleges** come from the official U.S. Department of Education **College Scorecard** API
  (Universities → Add from College Scorecard). This provides admit rate, SAT/ACT ranges, test policy,
  cost, tuition, size, share of international students, graduation rate and earnings.
  "Refresh data" (per school, or all at once) re-downloads them. Scorecard figures can lag a
  year or two behind schools' own websites.
- Set a free API key from https://api.data.gov/signup/ as `COLLEGE_SCORECARD_API_KEY` in `.env`.
  Without one, the shared `DEMO_KEY` is used, which allows only a few requests per hour.
- **International fields** aren't in the Scorecard, so the counselor maintains them: need-blind/aware
  for internationals, merit aid, TOEFL/IELTS/Duolingo minimums and international admit rate. Refreshing
  never overwrites them.
- **UK / European universities** are added by hand or by **CSV import** (Universities → Import CSV;
  download the template there). The import shows a preview before anything is saved.
- **Filter and compare**: counselor and students can filter (admit rate, aid policy, merit aid, cost,
  test policy, their own SAT/TOEFL/IELTS) and compare up to 4 schools side by side. Parents can't.
- Application deadlines aren't in the Scorecard either; add them on each university page.

## Phase 4: decisions and benchmarks

- Record each university's decision (admitted / conditional / denied / waitlisted / deferred /
  withdrawn) and any scholarship on the school's page. Students can record their own decisions.
- **How past students did** (link on the student page and each school) compares a student's SAT,
  ACT, IB total (IB students only) and GPA (same high school and scale only) with past PrepMe results.
- Privacy: only past students with an active "anonymized results" **consent** are used. Any group
  under `BENCHMARK_MIN_GROUP` (3) students is hidden. No names, schools or free text are shown, and
  medians are rounded. Parents can't see benchmarks.
- **Import past results** (Students page): one CSV row per application, with optional consent
  columns. Consent is recorded or withdrawn per student under Consent.

## Phase 5: after admission

Mark the admitted school the student will attend. This adds a checklist: deposit, I-20 and F-1 visa
appointment, and housing for U.S. schools; firm choice, CAS, Student visa and accommodation for UCAS.

## Billing

- Counselor menu → **Billing**: balances for every student. On a student, use **Add charge**
  (date, minutes, description; the amount is calculated from the hourly rate if left blank) and
  **Record payment**.
- **Monthly statements** follow PrepMe's invoice layout and can be printed or saved as PDF.
- Students and their parents see the same Billing page, read-only. Company and bank details are
  under Billing → Billing settings.

## Deploying

See [DEPLOY.md](DEPLOY.md).

## Security notes

- Permissions are checked on the server for every request (`portal/permissions.py`).
- Grades, GPA, test scores, essay text, comments and meeting notes are encrypted in the database (`core/fields.py`), with keys from
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

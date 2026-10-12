"""Load sample data for trying the app locally. Refuses to run in production.

All names and deadline dates are made up. Deadline dates are set relative to today
so the dashboard has something to show.
"""
from datetime import date, timedelta
from decimal import Decimal

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from accounts.models import User
from portal import billing, deadlines, essays, scorecard
from portal.models import (
    AcademicRecord,
    Application,
    Charge,
    Consent,
    Payment,
    Curriculum,
    DeadlineKind,
    DeadlineTemplate,
    Essay,
    EssayPrompt,
    MeetingNote,
    Round,
    School,
    StudentProfile,
    TestScore,
    University,
)

DEMO_PASSWORD = "PrepMeDemo!2026"

# College Scorecard IDs (IPEDS unit IDs) of real U.S. colleges used in the demo.
DEMO_SCORECARD_IDS = {
    "northeastern": (167358, "Northeastern University"),
    "boston": (164988, "Boston University"),
    "nyu": (193900, "New York University"),
    "stanford": (243744, "Stanford University"),
    "penn": (215062, "University of Pennsylvania"),
}


class Command(BaseCommand):
    help = "Create demo users, students, universities and deadlines (local testing only)."

    def _scorecard_schools(self):
        """Create the demo U.S. colleges from College Scorecard data; names only if offline."""
        try:
            records = scorecard.fetch([sc_id for sc_id, _ in DEMO_SCORECARD_IDS.values()])
        except scorecard.ScorecardError as exc:
            self.stdout.write(self.style.WARNING(f"{exc} Creating U.S. colleges without figures."))
            records = {}
        schools = {}
        for key, (sc_id, name) in DEMO_SCORECARD_IDS.items():
            university = University(name=name, country="United States", application_system=University.System.COMMON_APP)
            if sc_id in records:
                university.name = records[sc_id].get(scorecard.F["name"]) or name
                university.scorecard_id = sc_id
                scorecard.apply(university, records[sc_id])
            university.save()
            schools[key] = university
        return schools

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("load_demo only runs when DJANGO_DEBUG=1.")
        if User.objects.filter(email="counselor@demo.test").exists():
            raise CommandError("Demo data already loaded. Delete db.sqlite3 and run migrate to start over.")

        today = timezone.localdate()
        year = today.year + 1

        counselor = User.objects.create_user(
            "counselor@demo.test", DEMO_PASSWORD, first_name="Demo", last_name="Counselor", role=User.Role.COUNSELOR
        )
        student_user = User.objects.create_user(
            "ana@demo.test", DEMO_PASSWORD, first_name="Ana", last_name="Souza", role=User.Role.STUDENT
        )
        parent_user = User.objects.create_user(
            "parent@demo.test", DEMO_PASSWORD, first_name="Marcia", last_name="Souza", role=User.Role.PARENT
        )

        school_a = School.objects.create(name="Colégio Exemplo", city="São Paulo", country="Brazil")
        school_b = School.objects.create(name="Escola Internacional Demo", city="Rio de Janeiro", country="Brazil")

        ana = StudentProfile.objects.create(
            user=student_user, first_name="Ana", last_name="Souza", home_country="Brazil", school=school_a,
            curriculum=Curriculum.IB, graduation_year=year, intended_major="Economics", gpa="8.9", gpa_scale="0-10",
        )
        ana.parents.add(parent_user)
        pedro_user = User.objects.create_user(
            "pedro@demo.test", DEMO_PASSWORD, first_name="Pedro", last_name="Lima", role=User.Role.STUDENT
        )
        pedro = StudentProfile.objects.create(
            user=pedro_user, first_name="Pedro", last_name="Lima", home_country="Brazil", school=school_b,
            curriculum=Curriculum.BRAZIL, graduation_year=year, intended_major="Computer Science", gpa="9.2", gpa_scale="0-10",
        )

        TestScore.objects.create(student=ana, test=TestScore.Test.SAT, score="1480", taken_on=today - timedelta(days=60))
        TestScore.objects.create(student=ana, test=TestScore.Test.IB_PREDICTED, score="40")
        TestScore.objects.create(student=ana, test=TestScore.Test.TOEFL, score="110")
        TestScore.objects.create(student=pedro, test=TestScore.Test.ENEM, score="780")
        AcademicRecord.objects.create(student=ana, subject="Economics", level=AcademicRecord.Level.HL,
                                      grade_type=AcademicRecord.GradeType.PREDICTED, grade="7")
        AcademicRecord.objects.create(student=ana, subject="Mathematics AA", level=AcademicRecord.Level.HL,
                                      grade_type=AcademicRecord.GradeType.PREDICTED, grade="6")

        # Real U.S. colleges with official College Scorecard data (one API request).
        us = self._scorecard_schools()
        northeastern, boston, nyu = us["northeastern"], us["boston"], us["nyu"]
        # Real UK universities. Their figures are left blank: the counselor fills those in.
        oxford = University.objects.create(name="University of Oxford", country="United Kingdom", city="Oxford",
                                           application_system=University.System.UCAS, oxbridge=True,
                                           website="https://www.ox.ac.uk/")
        ucl = University.objects.create(name="University College London", country="United Kingdom", city="London",
                                        application_system=University.System.UCAS, website="https://www.ucl.ac.uk/")

        # Deadline DATES are made up (relative to today) so the dashboard has something to show.
        def deadline(university, kind, days, round_=""):
            deadlines.save_template(DeadlineTemplate(
                university=university, entry_year=year, round=round_, kind=kind,
                title=f"{DeadlineKind(kind).label} (sample date)", due_date=today + timedelta(days=days),
            ))

        deadline(northeastern, DeadlineKind.APPLICATION, 3, Round.EA)
        deadline(northeastern, DeadlineKind.APPLICATION, 80, Round.RD)
        deadline(northeastern, DeadlineKind.SUPPLEMENT, 3, Round.EA)
        deadline(northeastern, DeadlineKind.CSS_PROFILE, 5)
        deadline(boston, DeadlineKind.APPLICATION, -2, Round.ED)
        deadline(boston, DeadlineKind.APPLICATION, 60, Round.RD)
        deadline(nyu, DeadlineKind.APPLICATION, 45, Round.RD)
        deadline(oxford, DeadlineKind.APPLICATION, 6, Round.UCAS)
        deadline(oxford, DeadlineKind.ADMISSIONS_TEST, 15, Round.UCAS)
        deadline(ucl, DeadlineKind.APPLICATION, 90, Round.UCAS)

        deadlines.add_school(ana, northeastern, year, Round.EA, counselor)
        deadlines.add_school(ana, oxford, year, Round.UCAS, counselor, course="PPE")
        deadlines.add_school(ana, nyu, year, Round.RD, student_user)  # pending approval
        deadlines.add_school(pedro, boston, year, Round.ED, counselor)
        deadlines.add_school(pedro, northeastern, year, Round.RD, counselor)
        # Pedro has submitted a whole list for approval at once.
        for uni, round_ in [(nyu, Round.RD), (ucl, Round.UCAS), (oxford, Round.UCAS)]:
            deadlines.add_school(pedro, uni, year, round_, pedro_user)

        # Phase 2: prompts, an essay with history and comments, meeting notes.
        ps = EssayPrompt.objects.create(
            application_system=University.System.COMMON_APP, entry_year=year, title="Personal statement",
            text="Sample prompt: share a story about yourself that you think colleges should know.", word_limit=650,
        )
        EssayPrompt.objects.create(
            university=northeastern, entry_year=year, title="Why this university? (sample prompt)",
            text="Sample prompt, not the school's real one: why do you want to attend?", word_limit=250,
        )
        EssayPrompt.objects.create(
            application_system=University.System.UCAS, entry_year=year, title="UCAS personal statement",
            text="Sample prompt: why do you want to study this course?", char_limit=4000,
        )
        essay = Essay.objects.create(
            student=ana, prompt=ps, title="Personal statement", status=Essay.Status.READY_FOR_REVIEW
        )
        essays.save_version(essay, "Every Sunday my grandmother cooked for twenty people.", student_user)
        version, _, _ = essays.save_version(
            essay,
            "Every Sunday my grandmother cooked for twenty people, and I was her only assistant.\n\n"
            "That kitchen taught me how to plan, how to improvise, and how to listen.",
            student_user, note="Added second paragraph",
        )
        essays.add_comment(version, counselor, "Lovely image. Can you show one specific Sunday?", quote="her only assistant")
        MeetingNote.objects.create(
            student=ana, met_on=today - timedelta(days=7), title="Kickoff meeting", author=counselor,
            body="Agreed on an early list. Ana will draft the personal statement this month.", shared_with_student=True,
        )
        MeetingNote.objects.create(
            student=ana, met_on=today - timedelta(days=2), title="Counselor-only note", author=counselor,
            body="Private planning note (not visible to Ana).",
        )

        self.stdout.write(self.style.SUCCESS("Demo data loaded. Log in with any of these (password: %s):" % DEMO_PASSWORD))
        # Billing: Ana's sessions in the format of PrepMe's invoices (sample entries).
        for day, minutes, text in [(9, 60, "Common App Brainstorm"), (15, 60, "Presencial"), (17, 60, "Presencial"),
                                   (25, 60, "Presencial"), (29, 30, "Carta Padre"), (30, 60, "Presencial")]:
            Charge.objects.create(student=ana, date=date(today.year, 6, day), minutes=minutes, description=text,
                                  amount=billing.suggested_amount(minutes), created_by=counselor)
        Charge.objects.create(student=ana, date=today - timedelta(days=3), minutes=60, description="Essay review",
                              amount=billing.suggested_amount(60), created_by=counselor)
        Payment.objects.create(student=ana, date=date(today.year, 7, 5), amount=Decimal("15125.00"),
                               method=Payment.Method.PIX, reference="June", created_by=counselor)

        # Past students (fictional) with consent, so "How past students did" has data.
        past = [("admitted", 1500, 41), ("admitted", 1520, 42), ("admitted", 1480, 40), ("admitted", 1540, 43),
                ("denied", 1400, 36), ("denied", 1420, 37), ("denied", 1380, 35)]
        for n, (outcome, sat, ib) in enumerate(past, start=1):
            p = StudentProfile.objects.create(first_name=f"Past student {n}", last_name="(demo)", home_country="Brazil",
                                              curriculum=Curriculum.IB, graduation_year=today.year - 1, is_active=False)
            TestScore.objects.create(student=p, test=TestScore.Test.SAT, score=str(sat))
            TestScore.objects.create(student=p, test=TestScore.Test.IB_FINAL, score=str(ib))
            Application.objects.create(student=p, university=northeastern, entry_year=today.year - 1, round=Round.RD,
                                       status=Application.Status.ACTIVE, outcome=outcome,
                                       aid_offered=15000 if outcome == "admitted" else None)
            Consent.objects.create(student=p, kind=Consent.Kind.ANONYMIZED_OUTCOMES, given_by=Consent.GivenBy.PARENT,
                                   given_by_name="Demo parent", given_on=date(today.year - 1, 6, 1), recorded_by=counselor)

        self.stdout.write("University figures for U.S. schools are real (College Scorecard); deadline dates and prompts are samples.")
        for email, role in [
            ("counselor@demo.test", "counselor"),
            ("ana@demo.test", "student"),
            ("pedro@demo.test", "student (has a list waiting for approval)"),
            ("parent@demo.test", "parent of Ana"),
        ]:
            self.stdout.write(f"  {email:24} {role}")

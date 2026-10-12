"""Load sample data for trying the app locally. Refuses to run in production.

All names and deadline dates are made up. Deadline dates are set relative to today
so the dashboard has something to show.
"""
from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from accounts.models import User
from portal import deadlines, essays, scorecard
from portal.models import (
    AcademicRecord,
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
        self.stdout.write("University figures for U.S. schools are real (College Scorecard); deadline dates and prompts are samples.")
        for email, role in [
            ("counselor@demo.test", "counselor"),
            ("ana@demo.test", "student"),
            ("pedro@demo.test", "student (has a list waiting for approval)"),
            ("parent@demo.test", "parent of Ana"),
        ]:
            self.stdout.write(f"  {email:24} {role}")

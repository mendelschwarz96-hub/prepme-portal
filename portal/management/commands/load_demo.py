"""Load sample data for trying the app locally. Refuses to run in production.

All names and deadline dates are made up. Deadline dates are set relative to today
so the dashboard has something to show.
"""
from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from accounts.models import User
from portal import deadlines
from portal.models import (
    AcademicRecord,
    Curriculum,
    DeadlineKind,
    DeadlineTemplate,
    Round,
    School,
    StudentProfile,
    TestScore,
    University,
)

DEMO_PASSWORD = "PrepMeDemo!2026"


class Command(BaseCommand):
    help = "Create demo users, students, universities and deadlines (local testing only)."

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
        pedro = StudentProfile.objects.create(
            first_name="Pedro", last_name="Lima", home_country="Brazil", school=school_b,
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

        def uni(name, country, system=University.System.COMMON_APP, oxbridge=False):
            return University.objects.create(name=name, country=country, application_system=system, oxbridge=oxbridge)

        sample_a = uni("Sample University (demo)", "United States")
        sample_b = uni("Demo College of the Arts (demo)", "United States")
        sample_eu = uni("Example European University (demo)", "Netherlands")
        sample_ox = uni("Sample Oxbridge College (demo)", "United Kingdom", University.System.UCAS, oxbridge=True)
        sample_uk = uni("Sample London University (demo)", "United Kingdom", University.System.UCAS)

        def deadline(university, kind, days, round_=""):
            deadlines.save_template(DeadlineTemplate(
                university=university, entry_year=year, round=round_, kind=kind, due_date=today + timedelta(days=days)
            ))

        deadline(sample_a, DeadlineKind.APPLICATION, 3, Round.EA)
        deadline(sample_a, DeadlineKind.APPLICATION, 80, Round.RD)
        deadline(sample_a, DeadlineKind.SUPPLEMENT, 3, Round.EA)
        deadline(sample_a, DeadlineKind.CSS_PROFILE, 5)
        deadline(sample_b, DeadlineKind.APPLICATION, -2, Round.ED)
        deadline(sample_b, DeadlineKind.APPLICATION, 60, Round.RD)
        deadline(sample_eu, DeadlineKind.APPLICATION, 45)
        deadline(sample_ox, DeadlineKind.APPLICATION, 6, Round.UCAS)
        deadline(sample_ox, DeadlineKind.ADMISSIONS_TEST, 15, Round.UCAS)
        deadline(sample_uk, DeadlineKind.APPLICATION, 90, Round.UCAS)

        deadlines.add_school(ana, sample_a, year, Round.EA, counselor)
        deadlines.add_school(ana, sample_ox, year, Round.UCAS, counselor, course="PPE")
        deadlines.add_school(ana, sample_eu, year, Round.RD, student_user)  # pending approval
        deadlines.add_school(pedro, sample_b, year, Round.ED, counselor)
        deadlines.add_school(pedro, sample_a, year, Round.RD, counselor)

        self.stdout.write(self.style.SUCCESS("Demo data loaded. Log in with any of these (password: %s):" % DEMO_PASSWORD))
        for email, role in [
            ("counselor@demo.test", "counselor"),
            ("ana@demo.test", "student"),
            ("parent@demo.test", "parent of Ana"),
        ]:
            self.stdout.write(f"  {email:24} {role}")

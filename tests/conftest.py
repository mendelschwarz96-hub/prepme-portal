from datetime import date

import pytest

from accounts.models import User
from portal.models import Curriculum, DeadlineKind, DeadlineTemplate, Round, StudentProfile, University
from portal import deadlines

YEAR = 2027


@pytest.fixture
def counselor(db):
    return User.objects.create_user("counselor@test.dev", "pw", role=User.Role.COUNSELOR, first_name="Coun")


@pytest.fixture
def student_user(db):
    return User.objects.create_user("ana@test.dev", "pw", role=User.Role.STUDENT, first_name="Ana")


@pytest.fixture
def other_student_user(db):
    return User.objects.create_user("bia@test.dev", "pw", role=User.Role.STUDENT, first_name="Bia")


@pytest.fixture
def parent_user(db):
    return User.objects.create_user("mom@test.dev", "pw", role=User.Role.PARENT, first_name="Mom")


@pytest.fixture
def student(student_user, parent_user):
    s = StudentProfile.objects.create(
        user=student_user, first_name="Ana", last_name="Souza", home_country="Brazil",
        curriculum=Curriculum.IB, graduation_year=YEAR,
    )
    s.parents.add(parent_user)
    return s


@pytest.fixture
def other_student(other_student_user):
    return StudentProfile.objects.create(
        user=other_student_user, first_name="Bia", last_name="Lima", home_country="Brazil",
        curriculum=Curriculum.BRAZIL, graduation_year=YEAR,
    )


@pytest.fixture
def common_app_uni(db):
    return University.objects.create(name="Sample U", country="United States")


@pytest.fixture
def ucas_uni(db):
    return University.objects.create(name="Sample UK", country="United Kingdom", application_system=University.System.UCAS)


def make_template(university, kind=DeadlineKind.APPLICATION, due=date(2026, 11, 1), round_="", year=YEAR, title=""):
    return deadlines.save_template(
        DeadlineTemplate(university=university, entry_year=year, round=round_, kind=kind, due_date=due, title=title)
    )


@pytest.fixture
def templates(common_app_uni):
    """EA application, RD application, and a financial-aid deadline that applies to every round."""
    return {
        "ea": make_template(common_app_uni, due=date(2026, 11, 1), round_=Round.EA),
        "rd": make_template(common_app_uni, due=date(2027, 1, 5), round_=Round.RD),
        "aid": make_template(common_app_uni, kind=DeadlineKind.CSS_PROFILE, due=date(2026, 11, 15)),
    }

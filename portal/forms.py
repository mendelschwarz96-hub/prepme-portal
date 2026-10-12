from datetime import date

from django import forms
from django.db.models import Q

from accounts.models import User

from .models import (
    AcademicRecord,
    DeadlineTemplate,
    DocumentItem,
    Round,
    School,
    StudentProfile,
    Task,
    TestScore,
    University,
    rounds_for_system,
)


class DateInput(forms.DateInput):
    input_type = "date"

    def __init__(self, **kwargs):
        super().__init__(format="%Y-%m-%d", **kwargs)


class StudentProfileForm(forms.ModelForm):
    class Meta:
        model = StudentProfile
        fields = [
            "first_name",
            "last_name",
            "home_country",
            "school",
            "curriculum",
            "graduation_year",
            "intended_major",
            "gpa",
            "gpa_scale",
            "is_active",
        ]
        widgets = {"gpa": forms.TextInput()}


class StudentSelfForm(StudentProfileForm):
    class Meta(StudentProfileForm.Meta):
        fields = [f for f in StudentProfileForm.Meta.fields if f != "is_active"]


class SchoolForm(forms.ModelForm):
    class Meta:
        model = School
        fields = ["name", "city", "country"]


class AcademicRecordForm(forms.ModelForm):
    class Meta:
        model = AcademicRecord
        fields = ["subject", "level", "grade_type", "period", "grade"]
        widgets = {"grade": forms.TextInput()}


class TestScoreForm(forms.ModelForm):
    class Meta:
        model = TestScore
        fields = ["test", "label", "score", "taken_on"]
        widgets = {"score": forms.TextInput(), "taken_on": DateInput()}


class UniversityForm(forms.ModelForm):
    class Meta:
        model = University
        fields = ["name", "country", "city", "application_system", "oxbridge", "website"]


class DeadlineTemplateForm(forms.ModelForm):
    class Meta:
        model = DeadlineTemplate
        fields = ["entry_year", "round", "kind", "title", "due_date"]
        widgets = {"due_date": DateInput()}

    def __init__(self, *args, university, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance.university = university
        allowed = rounds_for_system(university.application_system)
        self.fields["round"].choices = [("", "All rounds")] + [(r.value, r.label) for r in allowed]
        if self.instance.pk:
            # Moving a deadline to another year would orphan tasks; create a new one instead.
            self.fields["entry_year"].disabled = True
        else:
            self.fields["entry_year"].initial = date.today().year + 1


class AddSchoolForm(forms.Form):
    university = forms.ModelChoiceField(queryset=University.objects.all())
    entry_year = forms.IntegerField(min_value=2020, max_value=2100, help_text="Year the student would start university.")
    round = forms.ChoiceField(choices=Round.choices)
    course = forms.CharField(max_length=150, required=False, help_text="UCAS only: course name or code.")

    def clean(self):
        cleaned = super().clean()
        university, round_ = cleaned.get("university"), cleaned.get("round")
        if university and round_ and round_ not in rounds_for_system(university.application_system):
            if university.application_system == University.System.UCAS:
                self.add_error("round", f"{university} uses UCAS. Choose the UCAS round.")
            else:
                self.add_error("round", f"{university} does not use UCAS. Choose ED, EA, RD, etc.")
        return cleaned


class ChangeRoundForm(forms.Form):
    round = forms.ChoiceField(choices=Round.choices)

    def __init__(self, *args, application, **kwargs):
        super().__init__(*args, **kwargs)
        allowed = rounds_for_system(application.university.application_system)
        self.fields["round"].choices = [(r.value, r.label) for r in allowed]
        self.fields["round"].initial = application.round


def task_owner_choices(student):
    return User.objects.filter(
        Q(role=User.Role.COUNSELOR) | Q(pk=student.user_id) | Q(children=student), is_active=True
    ).distinct()


class CounselorTaskForm(forms.ModelForm):
    class Meta:
        model = Task
        fields = ["title", "owner", "due_date", "status"]
        widgets = {"due_date": DateInput()}

    def __init__(self, *args, student, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["owner"].queryset = task_owner_choices(student)
        if self.instance.pk and self.instance.template_id:
            self.fields["due_date"].help_text = (
                f"School deadline: {self.instance.template.due_date:%b %d, %Y}. "
                "Changing it here affects only this student."
            )


class StudentTaskForm(forms.ModelForm):
    class Meta:
        model = Task
        fields = ["title", "due_date", "status"]
        widgets = {"due_date": DateInput()}


class DocumentForm(forms.ModelForm):
    class Meta:
        model = DocumentItem
        fields = ["doc_type", "label", "status", "link"]


class InviteForm(forms.Form):
    email = forms.EmailField()
    role = forms.ChoiceField(choices=[(User.Role.STUDENT, "Student"), (User.Role.PARENT, "Parent")])

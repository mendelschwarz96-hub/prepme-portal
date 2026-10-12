from datetime import date

from django import forms
from django.db.models import Q

from accounts.models import User

from .models import (
    AcademicRecord,
    Application,
    DeadlineTemplate,
    DocumentItem,
    Essay,
    EssayPrompt,
    MeetingNote,
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


class EssayPromptForm(forms.ModelForm):
    class Meta:
        model = EssayPrompt
        fields = ["university", "application_system", "entry_year", "title", "text", "word_limit", "char_limit", "required"]
        widgets = {"text": forms.Textarea(attrs={"rows": 5})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["application_system"].choices = [("", "—")] + list(University.System.choices)
        if not self.instance.pk:
            self.fields["entry_year"].initial = date.today().year + 1


def prompts_for_student(student):
    """Prompts for the schools on the student's list, plus general prompts for their application systems."""
    listed = student.applications.filter(status__in=Application.LISTED).select_related("university")
    years = {a.entry_year for a in listed} or {student.graduation_year}
    systems = {a.university.application_system for a in listed}
    universities = {a.university_id for a in listed}
    return (
        EssayPrompt.objects.filter(entry_year__in=years)
        .filter(Q(university_id__in=universities) | Q(university__isnull=True, application_system__in=systems))
        .select_related("university")
    )


class EssayCreateForm(forms.ModelForm):
    class Meta:
        model = Essay
        fields = ["prompt", "application", "title"]

    def __init__(self, *args, student, **kwargs):
        super().__init__(*args, **kwargs)
        self.student = student
        self.fields["prompt"].queryset = prompts_for_student(student)
        self.fields["prompt"].required = False
        self.fields["prompt"].empty_label = "No prompt / other essay"
        self.fields["application"].queryset = student.applications.filter(
            status__in=Application.LISTED
        ).select_related("university")
        self.fields["application"].label = "School"
        self.fields["title"].required = False
        self.fields["title"].help_text = "Leave blank to use the prompt's title."

    def clean(self):
        cleaned = super().clean()
        prompt, application = cleaned.get("prompt"), cleaned.get("application")
        if not cleaned.get("title"):
            if not prompt:
                self.add_error("title", "Give the essay a title or choose a prompt.")
            else:
                cleaned["title"] = prompt.title
                self.instance.title = prompt.title
        if prompt and prompt.university_id and not application:
            match = self.fields["application"].queryset.filter(university_id=prompt.university_id).first()
            cleaned["application"] = match
            self.instance.application = match
        return cleaned


class EssayEditForm(forms.Form):
    body = forms.CharField(
        label="Essay", required=False, strip=False,
        widget=forms.Textarea(attrs={"rows": 18, "class": "essay-editor", "spellcheck": "true"}),
    )
    note = forms.CharField(label="What changed? (optional)", max_length=120, required=False)
    base_number = forms.IntegerField(widget=forms.HiddenInput, required=False)


class EssayStatusForm(forms.ModelForm):
    class Meta:
        model = Essay
        fields = ["status"]


class CommentForm(forms.Form):
    body = forms.CharField(label="Comment", widget=forms.Textarea(attrs={"rows": 3}), max_length=4000)
    start = forms.IntegerField(widget=forms.HiddenInput, required=False, min_value=0)
    end = forms.IntegerField(widget=forms.HiddenInput, required=False, min_value=0)
    quote = forms.CharField(widget=forms.HiddenInput, required=False, strip=False, max_length=2000)


class MeetingNoteForm(forms.ModelForm):
    class Meta:
        model = MeetingNote
        fields = ["met_on", "title", "body", "shared_with_student"]
        widgets = {
            "met_on": DateInput(),
            "title": forms.TextInput(),
            "body": forms.Textarea(attrs={"rows": 10}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.instance.pk:
            self.fields["met_on"].initial = date.today()


class InviteForm(forms.Form):
    email = forms.EmailField()
    role = forms.ChoiceField(choices=[(User.Role.STUDENT, "Student"), (User.Role.PARENT, "Parent")])

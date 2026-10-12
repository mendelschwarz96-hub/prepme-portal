from datetime import date
from decimal import Decimal

from django import forms
from django.db import models
from django.db.models import Q

from accounts.models import User

from .models import (
    AcademicRecord,
    Application,
    BillingProfile,
    Charge,
    Consent,
    DeadlineTemplate,
    Payment,
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


class PercentField(forms.DecimalField):
    """Shows and accepts a percentage (12.5) for a value stored as a fraction (0.125)."""

    def __init__(self, **kwargs):
        kwargs.setdefault("min_value", 0)
        kwargs.setdefault("max_value", 100)
        kwargs.setdefault("decimal_places", 2)
        kwargs.setdefault("required", False)
        super().__init__(**kwargs)

    def prepare_value(self, value):
        if isinstance(value, Decimal) or isinstance(value, float):
            return (Decimal(str(value)) * 100).normalize()
        return value

    def clean(self, value):
        if self.disabled:
            return value  # Django passes the stored fraction for read-only fields; keep it as is.
        value = super().clean(value)
        return (value / 100).quantize(Decimal("0.0001")) if value is not None else None


PERCENT_FIELDS = ("admit_rate", "intl_admit_rate", "intl_student_share", "grad_rate")

UNIVERSITY_FIELDS = [
    "name", "country", "city", "state", "application_system", "oxbridge", "website",
    "ownership", "undergrad_size", "admit_rate", "intl_admit_rate", "sat_25", "sat_75", "act_25", "act_75",
    "test_policy", "intl_student_share", "cost_of_attendance", "tuition", "cost_currency", "grad_rate",
    "median_earnings", "intl_aid_policy", "merit_aid", "toefl_min", "ielts_min", "duolingo_min", "english_notes",
]


class UniversityForm(forms.ModelForm):
    class Meta:
        model = University
        fields = UNIVERSITY_FIELDS

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in PERCENT_FIELDS:
            model_field = University._meta.get_field(name)
            self.fields[name] = PercentField(label=f"{model_field.verbose_name[0].upper()}{model_field.verbose_name[1:]} (%)")
        if self.instance.pk and self.instance.from_scorecard:
            # Kept in sync with the College Scorecard; edit them there, not here.
            for name in University.SCORECARD_FIELDS:
                self.fields[name].disabled = True
                self.fields[name].help_text = "From the College Scorecard."
            self.fields["name"].help_text = "Linked to the College Scorecard."

    def clean(self):
        cleaned = super().clean()
        # Read-only (Scorecard) fields keep their stored values exactly.
        for name, field in self.fields.items():
            if field.disabled and self.instance.pk:
                cleaned[name] = getattr(self.instance, name)
        for low, high in (("sat_25", "sat_75"), ("act_25", "act_75")):
            if cleaned.get(low) and cleaned.get(high) and cleaned[low] > cleaned[high]:
                self.add_error(high, "Must be at least the 25th percentile.")
        if cleaned.get("cost_currency"):
            cleaned["cost_currency"] = cleaned["cost_currency"].upper()
        return cleaned


class UniversityFilterForm(forms.Form):
    SORTS = [("name", "Name"), ("admit_rate", "Admit rate (lowest first)"),
             ("cost", "Cost (lowest first)"), ("-sat_75", "SAT (highest first)")]

    q = forms.CharField(label="Name", required=False)
    country = forms.ChoiceField(required=False)
    system = forms.ChoiceField(label="Applies via", required=False,
                               choices=[("", "Any")] + list(University.System.choices))
    max_admit = forms.DecimalField(label="Admit rate at most (%)", required=False, min_value=0, max_value=100)
    aid = forms.ChoiceField(label="Need-based aid for internationals", required=False, choices=[
        ("", "Any"), ("any", "Need-blind or need-aware"), ("need_blind", "Need-blind only")])
    merit = forms.BooleanField(label="Offers merit aid to internationals", required=False)
    max_cost = forms.IntegerField(label="Cost of attendance at most (USD)", required=False, min_value=0)
    test_optional = forms.BooleanField(label="SAT/ACT not required", required=False)
    sat = forms.IntegerField(label="My SAT", required=False, min_value=400, max_value=1600,
                             help_text="Shows schools where this is at or above the 25th percentile.")
    toefl = forms.IntegerField(label="My TOEFL", required=False, min_value=0, max_value=120,
                               help_text="Hides schools whose minimum is higher.")
    ielts = forms.DecimalField(label="My IELTS", required=False, min_value=0, max_value=9)
    sort = forms.ChoiceField(choices=SORTS, required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        countries = University.objects.order_by("country").values_list("country", flat=True).distinct()
        self.fields["country"].choices = [("", "Any")] + [(c, c) for c in countries]

    def apply(self, qs):
        if not self.is_bound or not self.is_valid():
            return qs.order_by("name")
        d = self.cleaned_data
        if d["q"]:
            qs = qs.filter(name__icontains=d["q"])
        if d["country"]:
            qs = qs.filter(country=d["country"])
        if d["system"]:
            qs = qs.filter(application_system=d["system"])
        if d["max_admit"] is not None:
            qs = qs.filter(admit_rate__lte=d["max_admit"] / 100)
        if d["aid"] == "need_blind":
            qs = qs.filter(intl_aid_policy=University.AidPolicy.NEED_BLIND)
        elif d["aid"] == "any":
            qs = qs.filter(intl_aid_policy__in=[University.AidPolicy.NEED_BLIND, University.AidPolicy.NEED_AWARE])
        if d["merit"]:
            qs = qs.filter(merit_aid__in=[University.MeritAid.YES, University.MeritAid.LIMITED])
        if d["max_cost"] is not None:
            qs = qs.filter(cost_currency="USD", cost_of_attendance__lte=d["max_cost"])
        if d["test_optional"]:
            qs = qs.filter(test_policy__in=[University.TestPolicy.CONSIDERED, University.TestPolicy.NEITHER])
        if d["sat"] is not None:
            qs = qs.filter(sat_25__lte=d["sat"])
        # English minimums: schools with no minimum recorded are kept (unknown, not excluded).
        if d["toefl"] is not None:
            qs = qs.filter(Q(toefl_min__isnull=True) | Q(toefl_min__lte=d["toefl"]))
        if d["ielts"] is not None:
            qs = qs.filter(Q(ielts_min__isnull=True) | Q(ielts_min__lte=d["ielts"]))
        sort = d["sort"] or "name"
        order = {"cost": "cost_of_attendance"}.get(sort, sort)
        field = order.lstrip("-")
        nulls_last = models.F(field).desc(nulls_last=True) if order.startswith("-") else models.F(field).asc(nulls_last=True)
        return qs.order_by(nulls_last, "name")


class CSVUploadForm(forms.Form):
    file = forms.FileField(label="CSV file", required=False)
    content = forms.CharField(widget=forms.HiddenInput, required=False)

    MAX_BYTES = 1_000_000

    def clean(self):
        cleaned = super().clean()
        upload = cleaned.get("file")
        if upload:
            if upload.size > self.MAX_BYTES:
                raise forms.ValidationError("The file is too large (1 MB maximum).")
            try:
                cleaned["content"] = upload.read().decode("utf-8-sig")
            except UnicodeDecodeError:
                raise forms.ValidationError("Save the file as CSV UTF-8 and try again.")
        if not cleaned.get("content"):
            raise forms.ValidationError("Choose a CSV file.")
        return cleaned


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


class ChargeForm(forms.ModelForm):
    class Meta:
        model = Charge
        fields = ["date", "minutes", "description", "amount", "currency"]
        widgets = {"date": DateInput(), "description": forms.TextInput()}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        profile = BillingProfile.get()
        self.profile = profile
        self.fields["amount"].required = False
        self.fields["amount"].help_text = (
            f"Leave blank to calculate from the time at {profile.currency} {profile.hourly_rate:,.2f} per hour."
        )
        if not self.instance.pk:
            self.fields["date"].initial = date.today()
            self.fields["minutes"].initial = 60
            self.fields["currency"].initial = profile.currency

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("amount") is None:
            if cleaned.get("minutes"):
                from .billing import suggested_amount
                cleaned["amount"] = suggested_amount(cleaned["minutes"], self.profile)
                self.instance.amount = cleaned["amount"]
            else:
                self.add_error("amount", "Enter an amount, or the time so it can be calculated.")
        if cleaned.get("currency"):
            cleaned["currency"] = cleaned["currency"].upper()
        return cleaned


class PaymentForm(forms.ModelForm):
    class Meta:
        model = Payment
        fields = ["date", "amount", "currency", "method", "reference"]
        widgets = {"date": DateInput()}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.instance.pk:
            self.fields["date"].initial = date.today()
            self.fields["currency"].initial = BillingProfile.get().currency


class BillingProfileForm(forms.ModelForm):
    class Meta:
        model = BillingProfile
        fields = ["company_name", "tax_id", "payment_details", "hourly_rate", "currency"]
        widgets = {"payment_details": forms.Textarea(attrs={"rows": 4})}


class OutcomeForm(forms.ModelForm):
    class Meta:
        model = Application
        fields = ["outcome", "aid_offered", "aid_currency"]


class ConsentForm(forms.ModelForm):
    class Meta:
        model = Consent
        fields = ["kind", "given_by", "given_by_name", "given_on", "text_version"]
        widgets = {"given_on": DateInput()}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.instance.pk:
            self.fields["given_on"].initial = date.today()


class InviteForm(forms.Form):
    email = forms.EmailField()
    role = forms.ChoiceField(choices=[(User.Role.STUDENT, "Student"), (User.Role.PARENT, "Parent")])

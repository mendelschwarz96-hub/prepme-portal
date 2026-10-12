from decimal import Decimal
from urllib.parse import urlparse

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from core.fields import EncryptedTextField


class Curriculum(models.TextChoices):
    IB = "ib", "IB Diploma"
    A_LEVELS = "a_levels", "A-levels"
    US = "us", "U.S. / AP"
    BRAZIL = "brazil", "Brazilian national (ENEM)"
    OTHER_NATIONAL = "other_national", "Other national system"


class School(models.Model):
    """A high school. Kept as a list so students from the same school match exactly."""

    name = models.CharField(max_length=200)
    city = models.CharField(max_length=100, blank=True)
    country = models.CharField(max_length=80)

    class Meta:
        ordering = ["name"]
        constraints = [models.UniqueConstraint(fields=["name", "city", "country"], name="unique_school")]

    def __str__(self):
        return f"{self.name} ({self.city})" if self.city else self.name


class StudentProfile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="student_profile"
    )
    parents = models.ManyToManyField(settings.AUTH_USER_MODEL, blank=True, related_name="children")
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    home_country = models.CharField(max_length=80)
    school = models.ForeignKey(School, null=True, blank=True, on_delete=models.PROTECT, related_name="students")
    curriculum = models.CharField(max_length=20, choices=Curriculum.choices)
    graduation_year = models.PositiveSmallIntegerField()
    intended_major = models.CharField(max_length=120, blank=True)
    gpa = EncryptedTextField("GPA / grade average", blank=True)
    gpa_scale = models.CharField("GPA scale", max_length=30, blank=True, help_text="For example: 0-10, 0-100, 4.0")
    is_active = models.BooleanField(default=True, help_text="Uncheck when the student has finished with PrepMe.")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["last_name", "first_name"]

    def __str__(self):
        return f"{self.first_name} {self.last_name}"

    @property
    def audit_student(self):
        return self


class AcademicRecord(models.Model):
    class Level(models.TextChoices):
        HL = "hl", "IB Higher Level"
        SL = "sl", "IB Standard Level"
        A_LEVEL = "a_level", "A-level"
        AS_LEVEL = "as_level", "AS-level"
        AP = "ap", "AP"
        STANDARD = "standard", "Standard"

    class GradeType(models.TextChoices):
        PREDICTED = "predicted", "Predicted"
        FINAL = "final", "Final"
        TERM = "term", "Term / semester"

    student = models.ForeignKey(StudentProfile, on_delete=models.CASCADE, related_name="academic_records")
    subject = models.CharField(max_length=100)
    level = models.CharField(max_length=20, choices=Level.choices, blank=True)
    grade_type = models.CharField(max_length=20, choices=GradeType.choices, default=GradeType.FINAL)
    period = models.CharField(max_length=40, blank=True, help_text="For example: 2025, Year 12, 2nd semester")
    grade = EncryptedTextField()

    class Meta:
        ordering = ["subject"]

    def __str__(self):
        return self.subject

    @property
    def audit_student(self):
        return self.student


class TestScore(models.Model):
    __test__ = False  # not a pytest test class

    class Test(models.TextChoices):
        SAT = "sat", "SAT (total)"
        ACT = "act", "ACT (composite)"
        IB_PREDICTED = "ib_predicted", "IB predicted total"
        IB_FINAL = "ib_final", "IB final total"
        TOEFL = "toefl", "TOEFL iBT"
        IELTS = "ielts", "IELTS (overall)"
        DUOLINGO = "duolingo", "Duolingo English Test"
        AP = "ap", "AP exam"
        ENEM = "enem", "ENEM (average)"
        UCAT = "ucat", "UCAT"
        LNAT = "lnat", "LNAT"
        TMUA = "tmua", "TMUA"
        ESAT = "esat", "ESAT"
        OTHER = "other", "Other"

    # Allowed numeric range for tests that have one.
    RANGES = {
        Test.SAT: (400, 1600),
        Test.ACT: (1, 36),
        Test.IB_PREDICTED: (0, 45),
        Test.IB_FINAL: (0, 45),
        Test.TOEFL: (0, 120),
        Test.IELTS: (0, 9),
        Test.DUOLINGO: (10, 160),
        Test.ENEM: (0, 1000),
    }

    student = models.ForeignKey(StudentProfile, on_delete=models.CASCADE, related_name="test_scores")
    test = models.CharField(max_length=20, choices=Test.choices)
    label = models.CharField(max_length=60, blank=True, help_text="AP subject or other test name, if needed.")
    score = EncryptedTextField()
    taken_on = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ["test", "-taken_on"]

    def __str__(self):
        return self.get_test_display()

    @property
    def audit_student(self):
        return self.student

    def clean(self):
        bounds = self.RANGES.get(self.test)
        if bounds and self.score not in (None, ""):
            try:
                value = float(str(self.score).replace(",", "."))
            except ValueError:
                raise ValidationError({"score": "Enter a number."})
            low, high = bounds
            if not low <= value <= high:
                raise ValidationError({"score": f"{self.get_test_display()} scores must be between {low} and {high}."})


class University(models.Model):
    class System(models.TextChoices):
        COMMON_APP = "common_app", "Common App"
        UCAS = "ucas", "UCAS"
        DIRECT = "direct", "Direct / other"

    name = models.CharField(max_length=200)
    country = models.CharField(max_length=80)
    city = models.CharField(max_length=100, blank=True)
    application_system = models.CharField(max_length=20, choices=System.choices, default=System.COMMON_APP)
    oxbridge = models.BooleanField(
        "Oxford or Cambridge",
        default=False,
        help_text="UCAS allows only one of Oxford or Cambridge per year.",
    )
    website = models.URLField(blank=True)

    # ---- Phase 3: profile data. Fields in SCORECARD_FIELDS are filled from the U.S.
    # College Scorecard for linked schools; all others are entered by the counselor.
    class Ownership(models.TextChoices):
        PUBLIC = "public", "Public"
        PRIVATE_NONPROFIT = "private_nonprofit", "Private nonprofit"
        PRIVATE_FOR_PROFIT = "private_for_profit", "Private for-profit"

    class TestPolicy(models.TextChoices):
        REQUIRED = "required", "Required"
        RECOMMENDED = "recommended", "Recommended"
        CONSIDERED = "considered", "Considered but not required (test-optional)"
        NEITHER = "neither", "Not required or recommended"

    class AidPolicy(models.TextChoices):
        NEED_BLIND = "need_blind", "Need-blind for internationals"
        NEED_AWARE = "need_aware", "Need-aware for internationals"
        NO_NEED_AID = "no_need_aid", "No need-based aid for internationals"

    class MeritAid(models.TextChoices):
        YES = "yes", "Yes"
        LIMITED = "limited", "Limited"
        NO = "no", "No"

    scorecard_id = models.PositiveIntegerField("College Scorecard ID", null=True, blank=True, unique=True)
    scorecard_synced_at = models.DateTimeField(null=True, blank=True)
    state = models.CharField(max_length=50, blank=True)
    ownership = models.CharField(max_length=20, choices=Ownership.choices, blank=True)
    undergrad_size = models.PositiveIntegerField("Undergraduates", null=True, blank=True)
    admit_rate = models.DecimalField("Admit rate (overall)", max_digits=5, decimal_places=4, null=True, blank=True,
                                     help_text="As a fraction, e.g. 0.12 for 12%.")
    intl_admit_rate = models.DecimalField("International admit rate", max_digits=5, decimal_places=4, null=True,
                                          blank=True, help_text="As a fraction, e.g. 0.05 for 5%. Only if published.")
    sat_25 = models.PositiveSmallIntegerField("SAT 25th percentile", null=True, blank=True)
    sat_75 = models.PositiveSmallIntegerField("SAT 75th percentile", null=True, blank=True)
    act_25 = models.PositiveSmallIntegerField("ACT 25th percentile", null=True, blank=True)
    act_75 = models.PositiveSmallIntegerField("ACT 75th percentile", null=True, blank=True)
    test_policy = models.CharField("SAT/ACT policy", max_length=20, choices=TestPolicy.choices, blank=True)
    intl_student_share = models.DecimalField("Share of international undergraduates", max_digits=5,
                                             decimal_places=4, null=True, blank=True)
    cost_of_attendance = models.PositiveIntegerField("Cost of attendance per year", null=True, blank=True,
                                                     help_text="Tuition, housing, food and other costs.")
    tuition = models.PositiveIntegerField("Tuition per year (international / out-of-state)", null=True, blank=True)
    cost_currency = models.CharField(max_length=3, default="USD", help_text="USD, GBP, EUR...")
    grad_rate = models.DecimalField("Graduation rate (6 years)", max_digits=5, decimal_places=4, null=True, blank=True)
    median_earnings = models.PositiveIntegerField("Median earnings 10 years after entry (USD)", null=True, blank=True)
    intl_aid_policy = models.CharField("Need-based aid for internationals", max_length=20,
                                       choices=AidPolicy.choices, blank=True)
    merit_aid = models.CharField("Merit aid for internationals", max_length=10, choices=MeritAid.choices, blank=True)
    toefl_min = models.PositiveSmallIntegerField("TOEFL iBT minimum", null=True, blank=True)
    ielts_min = models.DecimalField("IELTS minimum", max_digits=3, decimal_places=1, null=True, blank=True)
    duolingo_min = models.PositiveSmallIntegerField("Duolingo minimum", null=True, blank=True)
    english_notes = models.CharField("English test notes", max_length=200, blank=True,
                                     help_text="E.g. waived for IB English A, subscores required.")
    profile_updated_at = models.DateTimeField(null=True, blank=True)

    SCORECARD_FIELDS = (
        "city", "state", "website", "ownership", "undergrad_size", "admit_rate", "sat_25", "sat_75",
        "act_25", "act_75", "test_policy", "intl_student_share", "cost_of_attendance", "tuition",
        "grad_rate", "median_earnings",
    )

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "universities"
        constraints = [models.UniqueConstraint(fields=["name", "country"], name="unique_university")]

    def __str__(self):
        return self.name

    @property
    def from_scorecard(self):
        return self.scorecard_id is not None


class Round(models.TextChoices):
    ED = "ed", "Early Decision"
    ED2 = "ed2", "Early Decision II"
    EA = "ea", "Early Action"
    REA = "rea", "Restrictive Early Action"
    RD = "rd", "Regular Decision"
    ROLLING = "rolling", "Rolling"
    UCAS = "ucas", "UCAS"


def rounds_for_system(system):
    if system == University.System.UCAS:
        return [Round.UCAS]
    return [r for r in Round if r != Round.UCAS]


class DeadlineKind(models.TextChoices):
    APPLICATION = "application", "Application"
    SUPPLEMENT = "supplement", "Supplemental essays"
    CSS_PROFILE = "css_profile", "CSS Profile"
    AID_FORM = "aid_form", "Financial aid form (school's own / ISFAA)"
    ADMISSIONS_TEST = "admissions_test", "Admissions test (UCAT, LNAT, TMUA, ESAT...)"
    TEST_SCORES = "test_scores", "Send test scores"
    INTERVIEW = "interview", "Interview"
    SCHOLARSHIP = "scholarship", "Scholarship application"
    OTHER = "other", "Other"


class DeadlineTemplate(models.Model):
    """A university's deadline for one entry year. Adding the school to a student's list copies these into tasks."""

    university = models.ForeignKey(University, on_delete=models.CASCADE, related_name="deadlines")
    entry_year = models.PositiveSmallIntegerField(help_text="Year the student would start university, e.g. 2027.")
    round = models.CharField(
        max_length=10, choices=Round.choices, blank=True, help_text="Leave blank if it applies to every round."
    )
    kind = models.CharField(max_length=20, choices=DeadlineKind.choices)
    title = models.CharField(max_length=150, blank=True, help_text="Optional. Defaults to the deadline type.")
    due_date = models.DateField()
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["entry_year", "due_date"]

    def __str__(self):
        return self.task_title()

    def task_title(self):
        return f"{self.university.name}: {self.title or self.get_kind_display()}"

    def clean(self):
        if self.round and self.university_id and self.round not in rounds_for_system(self.university.application_system):
            raise ValidationError({"round": f"{self.get_round_display()} is not a round for {self.university}."})


class Application(models.Model):
    """One school on one student's list."""

    class Status(models.TextChoices):
        PENDING_ADD = "pending_add", "Waiting for approval"
        ACTIVE = "active", "On list"
        PENDING_REMOVAL = "pending_removal", "Removal requested"
        REMOVED = "removed", "Removed"
        DECLINED = "declined", "Request declined"

    LISTED = (Status.ACTIVE, Status.PENDING_REMOVAL)  # counts as on the student's list
    OPEN = (Status.PENDING_ADD, Status.ACTIVE, Status.PENDING_REMOVAL)

    student = models.ForeignKey(StudentProfile, on_delete=models.CASCADE, related_name="applications")
    university = models.ForeignKey(University, on_delete=models.PROTECT, related_name="applications")
    entry_year = models.PositiveSmallIntegerField()
    round = models.CharField(max_length=10, choices=Round.choices)
    course = models.CharField(max_length=150, blank=True, help_text="UCAS course name or code.")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING_ADD)
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    # ---- Phase 4: the university's decision
    class Outcome(models.TextChoices):
        ADMITTED = "admitted", "Admitted"
        CONDITIONAL = "conditional", "Conditional offer (UCAS)"
        DENIED = "denied", "Denied"
        WAITLISTED = "waitlisted", "Waitlisted"
        DEFERRED = "deferred", "Deferred"
        WITHDRAWN = "withdrawn", "Withdrawn by student"

    ADMIT_OUTCOMES = (Outcome.ADMITTED, Outcome.CONDITIONAL)

    outcome = models.CharField(max_length=20, choices=Outcome.choices, blank=True)
    aid_offered = models.PositiveIntegerField("Aid offered per year", null=True, blank=True,
                                              help_text="Scholarships and grants per year (not loans).")
    aid_currency = models.CharField(max_length=3, default="USD")
    attending = models.BooleanField(default=False, help_text="The student accepted this offer.")

    class Meta:
        ordering = ["university__name"]
        constraints = [
            models.UniqueConstraint(
                fields=["student", "university", "entry_year"],
                condition=Q(status__in=["pending_add", "active", "pending_removal"]),
                name="one_open_application_per_school_and_year",
            )
        ]

    def __str__(self):
        return f"{self.student} - {self.university} ({self.get_round_display()})"

    @property
    def audit_student(self):
        return self.student

    @property
    def is_listed(self):
        return self.status in self.LISTED

    @property
    def is_admitted(self):
        return self.outcome in self.ADMIT_OUTCOMES

    def clean(self):
        if self.university_id and self.round and self.round not in rounds_for_system(self.university.application_system):
            raise ValidationError({"round": f"{self.get_round_display()} is not a round for {self.university}."})


class Task(models.Model):
    class Status(models.TextChoices):
        TODO = "todo", "To do"
        IN_PROGRESS = "in_progress", "In progress"
        DONE = "done", "Done"

    class Source(models.TextChoices):
        AUTO = "auto", "From school deadline"
        MANUAL = "manual", "Added by hand"
        AFTER_ADMISSION = "after_admission", "After-admission checklist"

    student = models.ForeignKey(StudentProfile, on_delete=models.CASCADE, related_name="tasks")
    application = models.ForeignKey(Application, null=True, blank=True, on_delete=models.CASCADE, related_name="tasks")
    template = models.ForeignKey(
        DeadlineTemplate, null=True, blank=True, on_delete=models.SET_NULL, related_name="tasks"
    )
    source = models.CharField(max_length=20, choices=Source.choices, default=Source.MANUAL)
    title = models.CharField(max_length=200)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="owned_tasks"
    )
    due_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.TODO)
    date_overridden = models.BooleanField(
        default=False, help_text="The counselor changed this date, so school-wide deadline edits no longer move it."
    )
    archived = models.BooleanField(default=False, help_text="Hidden because the school was removed or the round changed.")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = [models.F("due_date").asc(nulls_last=True), "title"]
        constraints = [
            models.UniqueConstraint(
                fields=["application", "template"],
                condition=Q(template__isnull=False),
                name="one_task_per_application_deadline",
            )
        ]

    def __str__(self):
        return self.title

    @property
    def audit_student(self):
        return self.student

    @property
    def is_done(self):
        return self.status == self.Status.DONE


def validate_google_link(value):
    if not value:
        return
    parsed = urlparse(value)
    if parsed.scheme != "https" or parsed.hostname not in ("docs.google.com", "drive.google.com"):
        raise ValidationError("Use a Google Docs or Google Drive link (https://docs.google.com/... or https://drive.google.com/...).")


class DocumentItem(models.Model):
    class DocType(models.TextChoices):
        TRANSCRIPT = "transcript", "Transcript"
        TRANSLATION = "translation", "Transcript translation"
        CREDENTIAL_EVALUATION = "credential_evaluation", "Credential evaluation"
        COUNSELOR_REC = "counselor_rec", "Counselor recommendation / school report"
        TEACHER_REC = "teacher_rec", "Teacher recommendation"
        UCAS_REFERENCE = "ucas_reference", "UCAS reference & predicted grades"
        TEST_SCORES = "test_scores", "Official test scores"
        ENGLISH_TEST = "english_test", "English test scores (TOEFL / IELTS / Duolingo)"
        OTHER = "other", "Other"

    class Status(models.TextChoices):
        NOT_STARTED = "not_started", "Not started"
        REQUESTED = "requested", "Requested"
        IN_PROGRESS = "in_progress", "In progress"
        READY = "ready", "Ready"
        SUBMITTED = "submitted", "Submitted"
        NOT_NEEDED = "not_needed", "Not needed"

    application = models.ForeignKey(Application, on_delete=models.CASCADE, related_name="documents")
    doc_type = models.CharField("Document", max_length=30, choices=DocType.choices)
    label = models.CharField(max_length=100, blank=True, help_text="For example: Math teacher")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.NOT_STARTED)
    link = models.URLField(
        "Google Docs / Drive link", max_length=500, blank=True, validators=[validate_google_link]
    )
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        ordering = ["doc_type", "label"]

    def __str__(self):
        name = self.get_doc_type_display()
        return f"{name} ({self.label})" if self.label else name

    @property
    def audit_student(self):
        return self.application.student


# ===================================================================== Phase 2: essays & notes

def count_words(text):
    return len(text.split()) if text else 0


class EssayPrompt(models.Model):
    """Prompt library. A prompt belongs to one university, or is general for an
    application system (e.g. the Common App personal statement, the UCAS personal statement)."""

    university = models.ForeignKey(
        University, null=True, blank=True, on_delete=models.CASCADE, related_name="prompts",
        help_text="Leave blank for a general prompt (e.g. Common App personal statement).",
    )
    application_system = models.CharField(
        max_length=20, choices=University.System.choices, blank=True,
        help_text="For general prompts only: which applications it is for.",
    )
    entry_year = models.PositiveSmallIntegerField()
    title = models.CharField(max_length=150)
    text = models.TextField("Prompt")
    word_limit = models.PositiveIntegerField(null=True, blank=True)
    char_limit = models.PositiveIntegerField("Character limit", null=True, blank=True)
    required = models.BooleanField(default=True)

    class Meta:
        ordering = ["-entry_year", "university__name", "title"]

    def __str__(self):
        owner = self.university.name if self.university else self.get_application_system_display() or "General"
        return f"{owner}: {self.title} ({self.entry_year})"

    def clean(self):
        if self.university_id and self.application_system:
            raise ValidationError("Choose a university or an application system, not both.")
        if not self.university_id and not self.application_system:
            raise ValidationError("Choose the university this prompt belongs to, or an application system for a general prompt.")


class Essay(models.Model):
    class Status(models.TextChoices):
        BRAINSTORMING = "brainstorming", "Brainstorming"
        DRAFTING = "drafting", "Drafting"
        READY_FOR_REVIEW = "ready_for_review", "Ready for review"
        REVISING = "revising", "Revising"
        FINAL = "final", "Final"
        SUBMITTED = "submitted", "Submitted"

    student = models.ForeignKey(StudentProfile, on_delete=models.CASCADE, related_name="essays")
    prompt = models.ForeignKey(EssayPrompt, null=True, blank=True, on_delete=models.SET_NULL, related_name="essays")
    application = models.ForeignKey(
        Application, null=True, blank=True, on_delete=models.SET_NULL, related_name="essays",
        help_text="Optional: the school this essay is for.",
    )
    title = models.CharField(max_length=150)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.BRAINSTORMING)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self):
        return self.title

    @property
    def audit_student(self):
        return self.student

    @property
    def latest_version(self):
        return self.versions.order_by("-number").first()

    @property
    def word_limit(self):
        return self.prompt.word_limit if self.prompt else None

    @property
    def char_limit(self):
        return self.prompt.char_limit if self.prompt else None


class EssayVersion(models.Model):
    """Every save is a new version; versions are never edited, so history is complete."""

    essay = models.ForeignKey(Essay, on_delete=models.CASCADE, related_name="versions")
    number = models.PositiveIntegerField()
    body = EncryptedTextField(blank=True)
    word_count = models.PositiveIntegerField(default=0)
    char_count = models.PositiveIntegerField(default=0)
    note = models.CharField(max_length=120, blank=True, help_text="Optional: what changed in this version.")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-number"]
        constraints = [models.UniqueConstraint(fields=["essay", "number"], name="unique_essay_version")]

    def __str__(self):
        return f"{self.essay} v{self.number}"

    @property
    def audit_student(self):
        return self.essay.student

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise ValueError("Essay versions cannot be changed; save a new version instead.")
        self.word_count = count_words(self.body)
        self.char_count = len(self.body or "")
        super().save(*args, **kwargs)


class EssayComment(models.Model):
    """A comment on a version, optionally anchored to a passage (start/end are character offsets)."""

    version = models.ForeignKey(EssayVersion, on_delete=models.CASCADE, related_name="comments")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    start = models.PositiveIntegerField(null=True, blank=True)
    end = models.PositiveIntegerField(null=True, blank=True)
    quote = EncryptedTextField(blank=True)
    body = EncryptedTextField()
    resolved = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    @property
    def audit_student(self):
        return self.version.essay.student

    @property
    def is_anchored(self):
        return self.start is not None and self.end is not None


class MeetingNote(models.Model):
    student = models.ForeignKey(StudentProfile, on_delete=models.CASCADE, related_name="meeting_notes")
    met_on = models.DateField("Meeting date")
    title = EncryptedTextField("Topic")
    body = EncryptedTextField("Notes")
    shared_with_student = models.BooleanField(
        default=False, help_text="If checked, the student can read this note. Parents never see meeting notes."
    )
    author = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-met_on", "-created_at"]

    def __str__(self):
        return f"Meeting {self.met_on:%Y-%m-%d}"

    @property
    def audit_student(self):
        return self.student


# ===================================================================== Phase 4: consent

class Consent(models.Model):
    """Permission to use a student's data. Benchmarks only use students with an active
    ANONYMIZED_OUTCOMES consent. For minors, consent is given by a parent or guardian."""

    class Kind(models.TextChoices):
        DATA_PROCESSING = "data_processing", "Use of data for counseling services"
        ANONYMIZED_OUTCOMES = "anonymized_outcomes", "Anonymized results used to guide future students"

    class GivenBy(models.TextChoices):
        STUDENT = "student", "Student (18 or older)"
        PARENT = "parent", "Parent or legal guardian"

    student = models.ForeignKey(StudentProfile, on_delete=models.CASCADE, related_name="consents")
    kind = models.CharField(max_length=30, choices=Kind.choices)
    given_by = models.CharField(max_length=10, choices=GivenBy.choices)
    given_by_name = models.CharField("Name of the person consenting", max_length=150)
    given_on = models.DateField()
    text_version = models.CharField("Consent text version", max_length=30, default="2026-1",
                                    help_text="Which version of your consent wording was signed.")
    withdrawn_on = models.DateField(null=True, blank=True)
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-given_on"]

    def __str__(self):
        return f"{self.get_kind_display()} ({self.given_on:%Y-%m-%d})"

    @property
    def audit_student(self):
        return self.student

    @property
    def is_active(self):
        return self.withdrawn_on is None


# ===================================================================== Billing

class BillingProfile(models.Model):
    """The counselor's billing details, printed on every statement (one row only)."""

    company_name = models.CharField(max_length=150, default="Prepme Servicos Educacionais Eireli")
    tax_id = models.CharField("CNPJ", max_length=30, blank=True)
    payment_details = models.TextField(
        blank=True, help_text="Bank, branch, account, PIX key... printed at the bottom of statements."
    )
    hourly_rate = models.DecimalField("Hourly rate", max_digits=10, decimal_places=2, default=Decimal("2750.00"),
                                      help_text="Used to suggest the amount from the session length.")
    currency = models.CharField(max_length=3, default="BRL")

    def __str__(self):
        return self.company_name

    @classmethod
    def get(cls):
        return cls.objects.order_by("pk").first() or cls.objects.create()


class Charge(models.Model):
    student = models.ForeignKey(StudentProfile, on_delete=models.CASCADE, related_name="charges")
    date = models.DateField()
    minutes = models.PositiveIntegerField("Time (minutes)", null=True, blank=True)
    description = EncryptedTextField()
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=3, default="BRL")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["date", "pk"]

    def __str__(self):
        return f"{self.date:%d/%m/%Y} {self.description}"

    @property
    def audit_student(self):
        return self.student


class Payment(models.Model):
    class Method(models.TextChoices):
        PIX = "pix", "PIX"
        TRANSFER = "transfer", "Bank transfer"
        BOLETO = "boleto", "Boleto"
        CARD = "card", "Card"
        CASH = "cash", "Cash"
        OTHER = "other", "Other"

    student = models.ForeignKey(StudentProfile, on_delete=models.CASCADE, related_name="payments")
    date = models.DateField()
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=3, default="BRL")
    method = models.CharField(max_length=10, choices=Method.choices, default=Method.PIX)
    reference = models.CharField(max_length=100, blank=True, help_text="Optional, e.g. the statement month it pays.")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["date", "pk"]

    def __str__(self):
        return f"Payment {self.date:%d/%m/%Y}"

    @property
    def audit_student(self):
        return self.student

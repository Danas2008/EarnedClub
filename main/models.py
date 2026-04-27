from django.contrib.auth.models import User
from django.conf import settings
from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.urls import reverse
from django.utils.text import slugify


RANK_TIERS = [
    {
        "name": "Beginner",
        "min_reps": 0,
        "max_reps": 19,
        "benchmark": "Foundation tier",
        "description": "You are in the game. Build strict form and consistency first.",
    },
    {
        "name": "Intermediate",
        "min_reps": 20,
        "max_reps": 39,
        "benchmark": "Rising tier",
        "description": "Strong baseline capacity. Clean technique and pacing now matter.",
    },
    {
        "name": "Advanced",
        "min_reps": 40,
        "max_reps": 59,
        "benchmark": "Performance tier",
        "description": "You are above average and starting to stand out on the board.",
    },
    {
        "name": "Elite",
        "min_reps": 60,
        "max_reps": 79,
        "benchmark": "Top 10% benchmark",
        "description": "This is the serious competitor tier and the first real status bracket.",
    },
    {
        "name": "Earned Legend",
        "min_reps": 80,
        "max_reps": None,
        "benchmark": "Top 1% benchmark",
        "description": "Reserved for exceptional performances that feel rare, public, and earned.",
    },
]


def get_rank_tier(reps):
    for tier in RANK_TIERS:
        max_reps = tier["max_reps"]
        if reps >= tier["min_reps"] and (max_reps is None or reps <= max_reps):
            return tier
    return RANK_TIERS[0]


def get_submission_identity(submission):
    if submission.user_id:
        return ("user", submission.user_id)
    if submission.email:
        return ("email", submission.email.lower())
    return ("submission", submission.pk)


def get_official_verified_submissions():
    official = {}
    submissions = (
        Submission.objects.filter(status=Submission.STATUS_VERIFIED)
        .select_related("user", "user__profile")
        .order_by("-reps", "created_at")
    )
    for submission in submissions:
        identity = get_submission_identity(submission)
        if identity not in official:
            official[identity] = submission
    return list(official.values())


def get_best_verified_submission_for_user(user):
    return user.submission_set.filter(status=Submission.STATUS_VERIFIED).order_by("-reps", "created_at").first()


def get_official_rank_for_submission(submission):
    if not submission:
        return None
    return sum(1 for item in get_official_verified_submissions() if item.reps > submission.reps) + 1


class Submission(models.Model):
    STATUS_UNVERIFIED = "unverified"
    STATUS_PENDING = "pending"
    STATUS_VERIFIED = "verified"
    STATUS_REJECTED = "rejected"
    STATUS_CHOICES = [
        (STATUS_UNVERIFIED, "Unverified"),
        (STATUS_PENDING, "Pending"),
        (STATUS_VERIFIED, "Verified"),
        (STATUS_REJECTED, "Rejected"),
    ]

    user = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL)
    name = models.CharField(max_length=100)
    email = models.EmailField(blank=True)
    reps = models.IntegerField()
    video_link = models.URLField(blank=True)
    video_file = models.FileField(upload_to="submission_videos/", blank=True)
    video_storage_path = models.CharField(max_length=255, blank=True)
    verified = models.BooleanField(default=False)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_PENDING)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-reps", "created_at")

    def __str__(self):
        return f"{self.name} - {self.reps}"

    def save(self, *args, **kwargs):
        previous = None
        if self.pk:
            previous = Submission.objects.filter(pk=self.pk).only("status", "verified", "user_id").first()

        status_changed = previous is not None and self.status != previous.status
        verified_changed = previous is not None and self.verified != previous.verified
        old_status = previous.status if previous else None
        old_user_id = previous.user_id if previous else None

        if previous is None:
            if self.verified and self.status in {self.STATUS_PENDING, self.STATUS_UNVERIFIED}:
                self.status = self.STATUS_VERIFIED
            elif self.status == self.STATUS_PENDING and not self.has_proof:
                self.status = self.STATUS_UNVERIFIED
            self.verified = self.status == self.STATUS_VERIFIED
        elif status_changed:
            if self.status == self.STATUS_PENDING and not self.has_proof:
                self.status = self.STATUS_UNVERIFIED
            self.verified = self.status == self.STATUS_VERIFIED
        elif verified_changed:
            self.status = self.STATUS_VERIFIED if self.verified else (
                self.STATUS_PENDING if self.has_proof else self.STATUS_UNVERIFIED
            )
        else:
            if self.status == self.STATUS_PENDING and not self.has_proof:
                self.status = self.STATUS_UNVERIFIED
            self.verified = self.status == self.STATUS_VERIFIED

        if kwargs.get("update_fields") is not None:
            kwargs["update_fields"] = set(kwargs["update_fields"]) | {"status", "verified"}

        super().save(*args, **kwargs)

        affected_user_ids = {user_id for user_id in (old_user_id, self.user_id) if user_id}
        refresh_all_ranks = old_status == self.STATUS_VERIFIED or self.status == self.STATUS_VERIFIED
        refresh_profile_stats(affected_user_ids, refresh_all_ranks=refresh_all_ranks)

    @property
    def is_verified(self):
        return self.status == self.STATUS_VERIFIED

    @property
    def public_status_label(self):
        if self.status == self.STATUS_VERIFIED:
            return "Verified"
        if self.status == self.STATUS_PENDING:
            return "Pending"
        if self.status == self.STATUS_REJECTED:
            return "Rejected"
        return "Unverified"

    @property
    def rank_tier(self):
        return get_rank_tier(self.reps)

    @property
    def rank_name(self):
        return self.rank_tier["name"]

    @property
    def benchmark_label(self):
        return self.rank_tier["benchmark"]

    @property
    def rank_description(self):
        return self.rank_tier["description"]

    @property
    def proof_url(self):
        if self.video_storage_path and settings.SUPABASE_URL:
            from .supabase_storage import create_signed_object_url

            return create_signed_object_url(settings.SUPABASE_SUBMISSION_BUCKET, self.video_storage_path)
        if self.video_file:
            return self.video_file.url
        return self.video_link

    @property
    def proof_label(self):
        if self.video_storage_path or self.video_file:
            return "Open uploaded video"
        if self.video_link:
            return "Open proof link"
        return ""

    @property
    def has_proof(self):
        return bool(self.video_link or self.video_storage_path or self.video_file)


class VerificationEvent(models.Model):
    ACTION_SUBMITTED = "submitted"
    ACTION_PROOF_ADDED = "proof_added"
    ACTION_APPROVED = "approved"
    ACTION_REJECTED = "rejected"
    ACTION_CHOICES = [
        (ACTION_SUBMITTED, "Submitted"),
        (ACTION_PROOF_ADDED, "Proof added"),
        (ACTION_APPROVED, "Approved"),
        (ACTION_REJECTED, "Rejected"),
    ]

    submission = models.ForeignKey(Submission, related_name="verification_events", on_delete=models.CASCADE)
    reviewer = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL)
    action = models.CharField(max_length=24, choices=ACTION_CHOICES)
    note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        return f"{self.get_action_display()} - {self.submission.name}"


class Profile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    display_name = models.CharField(max_length=100)
    slug = models.SlugField(max_length=120, unique=True, blank=True)
    profile_photo = models.URLField(blank=True)
    profile_image = models.FileField(upload_to="profile_photos/", blank=True)
    profile_storage_path = models.CharField(max_length=255, blank=True)
    country = models.CharField(max_length=80, blank=True)
    age = models.PositiveSmallIntegerField(null=True, blank=True)
    bio = models.TextField(blank=True)
    current_rank = models.PositiveIntegerField(null=True, blank=True)
    personal_best_reps = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("display_name",)

    def __str__(self):
        return self.display_name

    def save(self, *args, **kwargs):
        if not self.display_name:
            self.display_name = self.user.get_full_name() or self.user.username
        if not self.slug:
            self.slug = self._build_unique_slug()
        super().save(*args, **kwargs)

    def _build_unique_slug(self):
        base_slug = slugify(self.display_name) or slugify(self.user.username) or "athlete"
        candidate = base_slug
        suffix = 2
        while Profile.objects.filter(slug=candidate).exclude(pk=self.pk).exists():
            candidate = f"{base_slug}-{suffix}"
            suffix += 1
        return candidate

    def refresh_verified_stats(self):
        best_submission = get_best_verified_submission_for_user(self.user)
        self.personal_best_reps = best_submission.reps if best_submission else 0
        self.current_rank = get_official_rank_for_submission(best_submission)
        self.save(update_fields=["personal_best_reps", "current_rank", "updated_at"])

    @property
    def profile_image_url(self):
        if self.profile_storage_path and settings.SUPABASE_URL:
            from .supabase_storage import get_public_object_url

            return get_public_object_url(settings.SUPABASE_PROFILE_BUCKET, self.profile_storage_path)
        if self.profile_image:
            return self.profile_image.url
        return self.profile_photo

    @property
    def earned_badges(self):
        badges = []
        if self.personal_best_reps >= 40:
            badges.append({"name": "40 Club", "description": "Hit at least 40 verified strict push-ups."})
        if self.personal_best_reps >= 60:
            badges.append({"name": "Elite Line", "description": "Reached the Elite benchmark."})
        if self.personal_best_reps >= 80:
            badges.append({"name": "Earned Legend", "description": "Reached the top public benchmark."})
        if self.current_rank and self.current_rank <= 10:
            badges.append({"name": "Top 10", "description": "Ranked inside the verified top 10."})
        if self.user.submission_set.filter(status=Submission.STATUS_VERIFIED).count() >= 3:
            badges.append({"name": "Consistent", "description": "Built a verified history."})
        return badges


class Follow(models.Model):
    follower = models.ForeignKey(User, related_name="following_links", on_delete=models.CASCADE)
    following = models.ForeignKey(User, related_name="follower_links", on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("follower", "following")
        ordering = ("-created_at",)

    def __str__(self):
        return f"{self.follower} follows {self.following}"


class Goal(models.Model):
    GOAL_PUSHUPS = "pushups"
    GOAL_RANK = "rank"
    GOAL_CHOICES = [
        (GOAL_PUSHUPS, "Push-up target"),
        (GOAL_RANK, "Rank target"),
    ]

    user = models.ForeignKey(User, related_name="goals", on_delete=models.CASCADE)
    goal_type = models.CharField(max_length=16, choices=GOAL_CHOICES, default=GOAL_PUSHUPS)
    target_value = models.PositiveIntegerField()
    note = models.CharField(max_length=180, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-is_active", "-created_at")

    def __str__(self):
        return f"{self.user} goal {self.target_value}"


class WorkoutTemplate(models.Model):
    DIFFICULTY_BEGINNER = "beginner"
    DIFFICULTY_INTERMEDIATE = "intermediate"
    DIFFICULTY_ADVANCED = "advanced"
    DIFFICULTY_CHOICES = [
        (DIFFICULTY_BEGINNER, "Beginner"),
        (DIFFICULTY_INTERMEDIATE, "Intermediate"),
        (DIFFICULTY_ADVANCED, "Advanced"),
    ]

    user = models.ForeignKey(User, null=True, blank=True, related_name="workout_templates", on_delete=models.CASCADE)
    name = models.CharField(max_length=120)
    difficulty = models.CharField(max_length=24, choices=DIFFICULTY_CHOICES, default=DIFFICULTY_BEGINNER)
    notes = models.TextField(blank=True)
    is_system = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("is_system", "difficulty", "name")

    def __str__(self):
        return self.name


class Workout(models.Model):
    user = models.ForeignKey(User, related_name="workouts", on_delete=models.CASCADE)
    template = models.ForeignKey(WorkoutTemplate, null=True, blank=True, on_delete=models.SET_NULL)
    title = models.CharField(max_length=120)
    slug = models.SlugField(max_length=140, unique=True, blank=True)
    notes = models.TextField(blank=True)
    duration_minutes = models.PositiveIntegerField(null=True, blank=True)
    is_public = models.BooleanField(default=False)
    highlighted_on_profile = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = self._build_unique_slug()
        super().save(*args, **kwargs)

    def _build_unique_slug(self):
        owner = getattr(getattr(self.user, "profile", None), "slug", self.user.username if self.user_id else "athlete")
        base_slug = slugify(f"{owner}-{self.title}") or "workout"
        candidate = base_slug
        suffix = 2
        while Workout.objects.filter(slug=candidate).exclude(pk=self.pk).exists():
            candidate = f"{base_slug}-{suffix}"
            suffix += 1
        return candidate

    def get_absolute_url(self):
        return reverse("workout_detail", args=[self.slug])


class WorkoutExercise(models.Model):
    TYPE_STRENGTH = "strength"
    TYPE_CARDIO = "cardio"
    TYPE_MOBILITY = "mobility"
    TYPE_CHOICES = [
        (TYPE_STRENGTH, "Strength"),
        (TYPE_CARDIO, "Cardio"),
        (TYPE_MOBILITY, "Mobility"),
    ]

    workout = models.ForeignKey(Workout, related_name="exercises", on_delete=models.CASCADE)
    name = models.CharField(max_length=120)
    exercise_type = models.CharField(max_length=24, choices=TYPE_CHOICES, default=TYPE_STRENGTH)
    body_part = models.CharField(max_length=80, blank=True)
    sets = models.PositiveIntegerField(default=1)
    reps = models.PositiveIntegerField(null=True, blank=True)
    seconds = models.PositiveIntegerField(null=True, blank=True)
    notes = models.CharField(max_length=180, blank=True)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ("order", "id")

    def __str__(self):
        return self.name


class ContentEnginePrompt(models.Model):
    ENGINE_LEVEL = "level"
    ENGINE_CHALLENGE = "challenge"
    ENGINE_COMPARE = "compare"
    ENGINE_PROGRESS = "progress"
    ENGINE_CHOICES = [
        (ENGINE_LEVEL, "What's your level?"),
        (ENGINE_CHALLENGE, "Can you beat this?"),
        (ENGINE_COMPARE, "Rank comparison"),
        (ENGINE_PROGRESS, "Fake vs real progress"),
    ]

    title = models.CharField(max_length=120)
    engine_type = models.CharField(max_length=24, choices=ENGINE_CHOICES)
    prompt = models.TextField()
    cta = models.CharField(max_length=180, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("engine_type", "-created_at")

    def __str__(self):
        return self.title


@receiver(post_save, sender=User)
def ensure_user_profile(sender, instance, created, **kwargs):
    if created:
        Profile.objects.create(
            user=instance,
            display_name=instance.get_full_name() or instance.username,
        )


def refresh_profile_stats(user_ids=None, refresh_all_ranks=False):
    profile_ids = set()
    if user_ids:
        profile_ids.update(Profile.objects.filter(user_id__in=user_ids).values_list("id", flat=True))
    if refresh_all_ranks:
        profile_ids.update(
            Profile.objects.filter(user__submission__status=Submission.STATUS_VERIFIED)
            .distinct()
            .values_list("id", flat=True)
        )

    for profile in Profile.objects.filter(id__in=profile_ids):
        profile.refresh_verified_stats()


class NewsletterSubscriber(models.Model):
    email = models.EmailField(unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        return self.email

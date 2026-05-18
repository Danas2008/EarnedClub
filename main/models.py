from django.contrib.auth.models import User
from django.conf import settings
from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify
from django.utils.crypto import get_random_string


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

DISCIPLINE_PUSHUPS = "pushups"
DISCIPLINE_PULLUPS = "pullups"
DISCIPLINE_5K = "run_5k"
DISCIPLINE_10K = "run_10k"

DISCIPLINE_CHOICES = [
    (DISCIPLINE_PUSHUPS, "Push-ups"),
    (DISCIPLINE_PULLUPS, "Pull-ups"),
    (DISCIPLINE_5K, "5K run"),
    (DISCIPLINE_10K, "10K run"),
]

DISCIPLINE_CONFIG = {
    DISCIPLINE_PUSHUPS: {
        "key": DISCIPLINE_PUSHUPS,
        "label": "Push-ups",
        "title": "Push-Up Leaderboard",
        "short_label": "Push-ups",
        "score_type": "reps",
        "unit": "reps",
        "higher_is_better": True,
        "input_label": "Max clean push-ups",
        "placeholder": "42",
        "elite_threshold": 60,
        "world_record": None,
        "proof_label": "Proof video or result link",
        "points_target": 80,
    },
    DISCIPLINE_PULLUPS: {
        "key": DISCIPLINE_PULLUPS,
        "label": "Pull-ups",
        "title": "Pull-Up Leaderboard",
        "short_label": "Pull-ups",
        "score_type": "reps",
        "unit": "reps",
        "higher_is_better": True,
        "input_label": "Max clean pull-ups",
        "placeholder": "12",
        "elite_threshold": 20,
        "world_record": 82,
        "proof_label": "Proof video or result link",
        "points_target": 30,
    },
    DISCIPLINE_5K: {
        "key": DISCIPLINE_5K,
        "label": "5K run",
        "title": "5K Leaderboard",
        "short_label": "5K",
        "score_type": "time",
        "unit": "time",
        "higher_is_better": False,
        "input_label": "5K time",
        "placeholder": "00:21:34 or 21:34",
        "elite_threshold": 18 * 60,
        "world_record": 12 * 60 + 49,
        "proof_label": "Race or Strava result link",
        "points_floor": 40 * 60,
    },
    DISCIPLINE_10K: {
        "key": DISCIPLINE_10K,
        "label": "10K run",
        "title": "10K Leaderboard",
        "short_label": "10K",
        "score_type": "time",
        "unit": "time",
        "higher_is_better": False,
        "input_label": "10K time",
        "placeholder": "00:44:20 or 44:20",
        "elite_threshold": 38 * 60,
        "world_record": 26 * 60 + 24,
        "proof_label": "Race or Strava result link",
        "points_floor": 75 * 60,
    },
}

DISCIPLINE_POINT_CURVES = {
    DISCIPLINE_PUSHUPS: [
        (0, 0),
        (20, 250),
        (40, 450),
        (50, 600),
        (70, 850),
        (85, 950),
        (100, 1000),
    ],
    DISCIPLINE_PULLUPS: [
        (0, 0),
        (5, 250),
        (10, 500),
        (15, 675),
        (20, 800),
        (30, 950),
        (35, 1000),
    ],
    DISCIPLINE_5K: [
        (40 * 60, 0),
        (30 * 60, 250),
        (25 * 60, 450),
        (22 * 60, 600),
        (18 * 60, 850),
        (16 * 60, 950),
        (15 * 60, 1000),
    ],
    DISCIPLINE_10K: [
        (75 * 60, 0),
        (60 * 60, 250),
        (50 * 60, 450),
        (44 * 60, 600),
        (38 * 60, 800),
        (34 * 60, 900),
        (32 * 60, 950),
        (30 * 60, 1000),
    ],
}

DISCIPLINE_ALIASES = {
    "5k": DISCIPLINE_5K,
    "10k": DISCIPLINE_10K,
}

HYBRID_RANKS = [
    {
        "name": "Beginner Hybrid",
        "min_score": 0,
        "description": "Building the first verified pieces of a hybrid profile.",
        "intensity": "beginner",
    },
    {
        "name": "Intermediate Hybrid",
        "min_score": 350,
        "description": "A balanced athlete base is starting to show.",
        "intensity": "intermediate",
    },
    {
        "name": "Advanced Hybrid",
        "min_score": 550,
        "description": "Strong verified capability across more than one lane.",
        "intensity": "advanced",
    },
    {
        "name": "Elite Hybrid Athlete",
        "min_score": 750,
        "description": "High-level verified performance with real hybrid range.",
        "intensity": "elite",
    },
    {
        "name": "Earned Legend",
        "min_score": 900,
        "description": "Rare overall athletic status across the Earned Club board.",
        "intensity": "legend",
    },
]


def get_discipline_config(discipline):
    discipline = DISCIPLINE_ALIASES.get(discipline, discipline)
    return DISCIPLINE_CONFIG.get(discipline, DISCIPLINE_CONFIG[DISCIPLINE_PUSHUPS])


def normalize_discipline(discipline):
    return get_discipline_config(discipline)["key"]


def format_duration(seconds):
    minutes, remaining_seconds = divmod(max(0, int(seconds)), 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{remaining_seconds:02d}"
    return f"{minutes}:{remaining_seconds:02d}"


def get_rank_tier(reps):
    for tier in RANK_TIERS:
        max_reps = tier["max_reps"]
        if reps >= tier["min_reps"] and (max_reps is None or reps <= max_reps):
            return tier
    return RANK_TIERS[0]


def get_hybrid_rank(score):
    rank = HYBRID_RANKS[0]
    for candidate in HYBRID_RANKS:
        if score >= candidate["min_score"]:
            rank = candidate
    return rank


def interpolate_points(value, low_value, low_points, high_value, high_points):
    if high_value == low_value:
        return high_points
    ratio = (value - low_value) / (high_value - low_value)
    return round(low_points + ratio * (high_points - low_points))


def calculate_submission_points(submission):
    discipline = submission.normalized_discipline
    config = submission.discipline_config
    curve = DISCIPLINE_POINT_CURVES[discipline]
    value = submission.reps

    if config["higher_is_better"]:
        if value <= curve[0][0]:
            return curve[0][1]
        for index in range(1, len(curve)):
            high_value, high_points = curve[index]
            low_value, low_points = curve[index - 1]
            if value <= high_value:
                return min(1000, max(0, interpolate_points(value, low_value, low_points, high_value, high_points)))
        return 1000

    if value >= curve[0][0]:
        return curve[0][1]
    for index in range(1, len(curve)):
        high_value, high_points = curve[index]
        low_value, low_points = curve[index - 1]
        if value >= high_value:
            return min(1000, max(0, interpolate_points(value, low_value, low_points, high_value, high_points)))
    return 1000


def get_pullup_rank_tier(reps):
    if reps >= 30:
        return {
            "name": "Earned Legend",
            "benchmark": "30+ strict pull-ups",
            "description": "Exceptional pulling strength that needs proof to count.",
        }
    if reps >= 20:
        return {
            "name": "Elite",
            "benchmark": "20+ strict pull-ups",
            "description": "Elite pull-up strength. Proof is required for official rank.",
        }
    if reps >= 10:
        return {
            "name": "Advanced",
            "benchmark": "10-19 strict pull-ups",
            "description": "Strong pulling capacity with room to chase elite status.",
        }
    if reps >= 5:
        return {
            "name": "Intermediate",
            "benchmark": "5-9 strict pull-ups",
            "description": "A real baseline for strict pull-up performance.",
        }
    return {
        "name": "Beginner",
        "benchmark": "0-4 strict pull-ups",
        "description": "Build clean reps before chasing the top of the board.",
    }


def get_running_rank_tier(seconds, discipline):
    if discipline == DISCIPLINE_5K:
        if seconds < 16 * 60:
            return {"name": "Earned Legend", "benchmark": "Sub-16 5K", "description": "Rare 5K performance. Proof is required for official rank."}
        if seconds < 18 * 60:
            return {"name": "Elite", "benchmark": "Sub-18 5K", "description": "Elite 5K standard. Proof is required for official rank."}
        if seconds < 25 * 60:
            return {"name": "Advanced", "benchmark": "Sub-25 5K", "description": "Strong recreational race performance."}
        if seconds < 30 * 60:
            return {"name": "Intermediate", "benchmark": "Sub-30 5K", "description": "Solid 5K fitness with a clear next target."}
        return {"name": "Beginner", "benchmark": "30:00+ 5K", "description": "You are on the board. Keep building the engine."}
    if seconds < 32 * 60:
        return {"name": "Earned Legend", "benchmark": "Sub-32 10K", "description": "Rare 10K performance. Proof is required for official rank."}
    if seconds < 38 * 60:
        return {"name": "Elite", "benchmark": "Sub-38 10K", "description": "Elite 10K standard. Proof is required for official rank."}
    if seconds < 50 * 60:
        return {"name": "Advanced", "benchmark": "Sub-50 10K", "description": "Strong 10K race performance."}
    if seconds < 60 * 60:
        return {"name": "Intermediate", "benchmark": "Sub-60 10K", "description": "Solid 10K fitness with a clear next target."}
    return {"name": "Beginner", "benchmark": "60:00+ 10K", "description": "You are on the board. Keep building the engine."}


def get_submission_identity(submission):
    if submission.user_id:
        return ("user", submission.user_id)
    if submission.email:
        return ("email", submission.email.lower())
    return ("submission", submission.pk)


def get_official_verified_submissions(discipline=DISCIPLINE_PUSHUPS):
    official = {}
    submissions = (
        Submission.objects.filter(status=Submission.STATUS_VERIFIED, discipline=normalize_discipline(discipline))
        .select_related("user", "user__profile")
        .order_by("-reps" if get_discipline_config(discipline)["higher_is_better"] else "reps", "created_at")
    )
    for submission in submissions:
        identity = get_submission_identity(submission)
        if identity not in official:
            official[identity] = submission
    return list(official.values())


def get_best_verified_submission_for_user(user, discipline=DISCIPLINE_PUSHUPS):
    discipline = normalize_discipline(discipline)
    order = "-reps" if get_discipline_config(discipline)["higher_is_better"] else "reps"
    return user.submission_set.filter(status=Submission.STATUS_VERIFIED, discipline=discipline).order_by(order, "created_at").first()


def get_official_rank_for_submission(submission):
    if not submission:
        return None
    config = get_discipline_config(submission.discipline)
    if config["higher_is_better"]:
        return sum(1 for item in get_official_verified_submissions(submission.discipline) if item.reps > submission.reps) + 1
    return sum(1 for item in get_official_verified_submissions(submission.discipline) if item.reps < submission.reps) + 1


class Submission(models.Model):
    DISCIPLINE_PUSHUPS = DISCIPLINE_PUSHUPS
    DISCIPLINE_PULLUPS = DISCIPLINE_PULLUPS
    DISCIPLINE_5K = DISCIPLINE_5K
    DISCIPLINE_10K = DISCIPLINE_10K
    DISCIPLINE_CHOICES = DISCIPLINE_CHOICES

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
    discipline = models.CharField(max_length=16, choices=DISCIPLINE_CHOICES, default=DISCIPLINE_PUSHUPS)
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
        return f"{self.name} - {self.discipline_label}: {self.display_score}"

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
        if self.discipline == self.DISCIPLINE_PULLUPS:
            return get_pullup_rank_tier(self.reps)
        if self.discipline in {self.DISCIPLINE_5K, self.DISCIPLINE_10K}:
            return get_running_rank_tier(self.reps, self.discipline)
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

    @property
    def discipline_config(self):
        return get_discipline_config(self.discipline)

    @property
    def normalized_discipline(self):
        return self.discipline_config["key"]

    @property
    def discipline_label(self):
        return self.discipline_config["label"]

    @property
    def is_time_based(self):
        return self.discipline_config["score_type"] == "time"

    @property
    def display_score(self):
        if self.is_time_based:
            return format_duration(self.reps)
        return f"{self.reps} reps"

    @property
    def compact_score(self):
        if self.is_time_based:
            return format_duration(self.reps)
        return str(self.reps)

    @property
    def score_heading(self):
        return "Time" if self.is_time_based else "Reps"

    @property
    def hybrid_points(self):
        return calculate_submission_points(self)


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
        verified = list(self.user.submission_set.filter(status=Submission.STATUS_VERIFIED))
        verified_disciplines = {submission.normalized_discipline for submission in verified}
        strength_verified = bool(verified_disciplines & {DISCIPLINE_PUSHUPS, DISCIPLINE_PULLUPS})
        running_verified = bool(verified_disciplines & {DISCIPLINE_5K, DISCIPLINE_10K})
        best_by_discipline = {}
        for submission in verified:
            current = best_by_discipline.get(submission.normalized_discipline)
            if current is None:
                best_by_discipline[submission.normalized_discipline] = submission
            elif submission.discipline_config["higher_is_better"] and submission.reps > current.reps:
                best_by_discipline[submission.normalized_discipline] = submission
            elif not submission.discipline_config["higher_is_better"] and submission.reps < current.reps:
                best_by_discipline[submission.normalized_discipline] = submission
        points = [submission.hybrid_points for submission in best_by_discipline.values()]
        hybrid_score = round(sum(points) / len(points)) if points else 0

        def badge(key, name, icon, description, reason, tier="standard"):
            badges.append(
                {
                    "key": key,
                    "name": name,
                    "icon": icon,
                    "description": description,
                    "earned_reason": reason,
                    "tier": tier,
                }
            )

        if verified:
            badge("verified-athlete", "Verified Athlete", "V", "At least one verified performance is official.", "First verified result accepted.")
        if len(verified_disciplines) >= 2:
            badge("hybrid-starter", "Hybrid Starter", "H", "Verified performances in at least two disciplines.", f"{len(verified_disciplines)} disciplines verified.")
        if strength_verified and running_verified:
            badge("balanced-athlete", "Balanced Athlete", "B", "Verified strength and running performance.", "Strength and running are both on the board.", "premium")
        if any(submission.normalized_discipline == DISCIPLINE_PUSHUPS and submission.rank_name in {"Advanced", "Elite", "Earned Legend"} for submission in verified):
            badge("pushup-advanced", "Push-Up Advanced", "P", "Advanced or better verified push-up performance.", "Verified push-up result reached Advanced tier.")
        if any(submission.normalized_discipline == DISCIPLINE_PULLUPS and submission.rank_name in {"Advanced", "Elite", "Earned Legend"} for submission in verified):
            badge("pullup-advanced", "Pull-Up Advanced", "U", "Advanced or better verified pull-up performance.", "Verified pull-up result reached Advanced tier.")
        if any(submission.normalized_discipline == DISCIPLINE_5K and submission.rank_name in {"Advanced", "Elite", "Earned Legend"} for submission in verified):
            badge("fivek-advanced", "5K Advanced", "5", "Advanced or better verified 5K performance.", "Verified 5K result reached Advanced tier.")
        if any(submission.normalized_discipline == DISCIPLINE_10K and submission.rank_name in {"Advanced", "Elite", "Earned Legend"} for submission in verified):
            badge("tenk-advanced", "10K Advanced", "10", "Advanced or better verified 10K performance.", "Verified 10K result reached Advanced tier.")
        if hybrid_score >= 750:
            badge("elite-hybrid", "Elite Hybrid", "E", "Hybrid Score reached Elite range.", f"Official Hybrid Score is {hybrid_score}.", "legend")
        if self.current_rank and self.current_rank <= 10:
            badge("top-10", "Top 10", "#", "Ranked inside the verified push-up top 10.", f"Current push-up rank is #{self.current_rank}.", "premium")
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


class ChallengeRoom(models.Model):
    FOCUS_HYBRID = "hybrid"
    FOCUS_PUSHUPS = DISCIPLINE_PUSHUPS
    FOCUS_PULLUPS = DISCIPLINE_PULLUPS
    FOCUS_5K = DISCIPLINE_5K
    FOCUS_CHOICES = [
        (FOCUS_HYBRID, "Hybrid Score"),
        (FOCUS_PUSHUPS, "Push-ups"),
        (FOCUS_PULLUPS, "Pull-ups"),
        (FOCUS_5K, "5K"),
    ]

    title = models.CharField(max_length=140, blank=True)
    description = models.TextField(blank=True)
    focus = models.CharField(max_length=16, choices=FOCUS_CHOICES, default=FOCUS_HYBRID)
    token = models.SlugField(max_length=32, unique=True, blank=True)
    created_by = models.ForeignKey(User, null=True, blank=True, related_name="challenge_rooms", on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        return self.title or "EarnedClub challenge"

    def save(self, *args, **kwargs):
        if not self.token:
            self.token = self._build_unique_token()
        super().save(*args, **kwargs)

    def _build_unique_token(self):
        token = get_random_string(10).lower()
        while ChallengeRoom.objects.filter(token=token).exists():
            token = get_random_string(10).lower()
        return token

    @property
    def display_title(self):
        return self.title or "EarnedClub challenge room"

    @property
    def focus_label(self):
        return dict(self.FOCUS_CHOICES).get(self.focus, "Hybrid Score")

    @property
    def is_hybrid(self):
        return self.focus == self.FOCUS_HYBRID


class ChallengeRoomEntry(models.Model):
    room = models.ForeignKey(ChallengeRoom, related_name="entries", on_delete=models.CASCADE)
    submission = models.ForeignKey(Submission, related_name="challenge_room_entries", on_delete=models.CASCADE)
    participant_key = models.CharField(max_length=80, blank=True, db_index=True)
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("joined_at",)
        constraints = [
            models.UniqueConstraint(fields=["room", "submission"], name="unique_submission_per_challenge_room"),
        ]

    def __str__(self):
        return f"{self.room} - {self.submission}"


class Goal(models.Model):
    GOAL_PUSHUPS = "pushups"
    GOAL_PULLUPS = "pullups"
    GOAL_5K = "run_5k"
    GOAL_10K = "run_10k"
    GOAL_HYBRID_SCORE = "hybrid_score"
    GOAL_RANK = "rank"
    GOAL_CHOICES = [
        (GOAL_PUSHUPS, "Push-up target"),
        (GOAL_PULLUPS, "Pull-up target"),
        (GOAL_5K, "5K target"),
        (GOAL_10K, "10K target"),
        (GOAL_HYBRID_SCORE, "Hybrid Score target"),
        (GOAL_RANK, "Rank target"),
    ]

    user = models.ForeignKey(User, related_name="goals", on_delete=models.CASCADE)
    goal_type = models.CharField(max_length=16, choices=GOAL_CHOICES, default=GOAL_PUSHUPS)
    target_value = models.PositiveIntegerField()
    note = models.CharField(max_length=180, blank=True)
    is_active = models.BooleanField(default=True)
    is_public = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-is_active", "-created_at")

    def __str__(self):
        return f"{self.user} goal {self.target_value}"

    @property
    def is_time_goal(self):
        return self.goal_type in {self.GOAL_5K, self.GOAL_10K}

    @property
    def display_target(self):
        if self.is_time_goal:
            return format_duration(self.target_value)
        if self.goal_type == self.GOAL_HYBRID_SCORE:
            return f"{self.target_value} score"
        if self.goal_type == self.GOAL_RANK:
            return f"{self.target_value}+ reps"
        return f"{self.target_value} reps"


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
    rest_interval_seconds = models.PositiveIntegerField(default=60)
    is_public = models.BooleanField(default=False)
    highlighted_on_profile = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)
        constraints = [
            models.UniqueConstraint(
                fields=["user"],
                condition=models.Q(highlighted_on_profile=True),
                name="unique_highlighted_workout_per_user",
            )
        ]

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = self._build_unique_slug()
        super().save(*args, **kwargs)
        if self.highlighted_on_profile:
            self.user.workouts.exclude(pk=self.pk).update(highlighted_on_profile=False)

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


class WorkoutSession(models.Model):
    STATUS_ACTIVE = "active"
    STATUS_COMPLETED = "completed"
    STATUS_CHOICES = [
        (STATUS_ACTIVE, "Active"),
        (STATUS_COMPLETED, "Completed"),
    ]

    user = models.ForeignKey(User, related_name="workout_sessions", on_delete=models.CASCADE)
    workout = models.ForeignKey(Workout, related_name="sessions", on_delete=models.CASCADE)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_ACTIVE)
    started_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-started_at",)

    def __str__(self):
        return f"{self.user} - {self.workout.title} ({self.status})"

    @property
    def completed_exercise_count(self):
        return self.exercise_sessions.filter(completed_sets__gte=models.F("target_sets")).count()

    @property
    def total_exercise_count(self):
        return self.exercise_sessions.count()


class WorkoutSessionExercise(models.Model):
    session = models.ForeignKey(WorkoutSession, related_name="exercise_sessions", on_delete=models.CASCADE)
    workout_exercise = models.ForeignKey(WorkoutExercise, related_name="session_entries", on_delete=models.CASCADE)
    name = models.CharField(max_length=120)
    exercise_type = models.CharField(max_length=24, choices=WorkoutExercise.TYPE_CHOICES, default=WorkoutExercise.TYPE_STRENGTH)
    body_part = models.CharField(max_length=80, blank=True)
    target_sets = models.PositiveIntegerField(default=1)
    target_reps = models.PositiveIntegerField(null=True, blank=True)
    target_seconds = models.PositiveIntegerField(null=True, blank=True)
    completed_sets = models.PositiveIntegerField(default=0)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ("order", "id")

    def __str__(self):
        return f"{self.name} ({self.completed_sets}/{self.target_sets})"

    @property
    def is_complete(self):
        return self.completed_sets >= self.target_sets


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
    unsubscribe_token = models.CharField(max_length=48, unique=True, blank=True)
    unsubscribed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        return self.email

    def save(self, *args, **kwargs):
        if not self.unsubscribe_token:
            token = get_random_string(32)
            while NewsletterSubscriber.objects.filter(unsubscribe_token=token).exclude(pk=self.pk).exists():
                token = get_random_string(32)
            self.unsubscribe_token = token
        super().save(*args, **kwargs)

    @property
    def is_subscribed(self):
        return self.unsubscribed_at is None

    def unsubscribe(self):
        self.unsubscribed_at = timezone.now()
        self.save(update_fields=["unsubscribed_at"])


class NewsletterCampaign(models.Model):
    week_number = models.PositiveIntegerField()
    subject = models.CharField(max_length=180)
    body = models.TextField()
    sent_at = models.DateTimeField(null=True, blank=True)
    sent_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-week_number", "-created_at")

    def __str__(self):
        return f"Week {self.week_number}: {self.subject}"


class NewsletterSegment(models.Model):
    name = models.CharField(max_length=120, unique=True)
    subscribers = models.ManyToManyField(NewsletterSubscriber, related_name="segments", blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("name",)

    def __str__(self):
        return self.name


class NewsletterSendEvent(models.Model):
    subscriber = models.ForeignKey(NewsletterSubscriber, related_name="send_events", on_delete=models.CASCADE)
    campaign = models.ForeignKey(NewsletterCampaign, related_name="send_events", null=True, blank=True, on_delete=models.SET_NULL)
    subject = models.CharField(max_length=180)
    sent_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-sent_at",)

    def __str__(self):
        return f"{self.subscriber.email} - {self.subject}"

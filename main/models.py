from django.contrib.auth.models import User
from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver
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


class Submission(models.Model):
    STATUS_PENDING = "pending"
    STATUS_VERIFIED = "verified"
    STATUS_REJECTED = "rejected"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_VERIFIED, "Verified"),
        (STATUS_REJECTED, "Rejected"),
    ]

    user = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL)
    name = models.CharField(max_length=100)
    email = models.EmailField(blank=True)
    reps = models.IntegerField()
    video_link = models.URLField(blank=True)
    verified = models.BooleanField(default=False)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_PENDING)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-reps", "created_at")

    def __str__(self):
        return f"{self.name} - {self.reps}"

    def save(self, *args, **kwargs):
        if self.verified and self.status == self.STATUS_PENDING:
            self.status = self.STATUS_VERIFIED
        if self.status == self.STATUS_VERIFIED:
            self.verified = True
        elif self.status in {self.STATUS_PENDING, self.STATUS_REJECTED}:
            self.verified = False
        super().save(*args, **kwargs)
        if self.user_id and hasattr(self.user, "profile"):
            self.user.profile.refresh_verified_stats()

    @property
    def is_verified(self):
        return self.status == self.STATUS_VERIFIED

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


class Profile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    display_name = models.CharField(max_length=100)
    slug = models.SlugField(max_length=120, unique=True, blank=True)
    profile_photo = models.URLField(blank=True)
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
        verified_submissions = self.user.submission_set.filter(status=Submission.STATUS_VERIFIED)
        best_submission = verified_submissions.order_by("-reps", "created_at").first()
        self.personal_best_reps = best_submission.reps if best_submission else 0
        if best_submission:
            self.current_rank = (
                Submission.objects.filter(status=Submission.STATUS_VERIFIED, reps__gt=best_submission.reps).count()
                + 1
            )
        else:
            self.current_rank = None
        self.save(update_fields=["personal_best_reps", "current_rank", "updated_at"])


@receiver(post_save, sender=User)
def ensure_user_profile(sender, instance, created, **kwargs):
    if created:
        Profile.objects.create(
            user=instance,
            display_name=instance.get_full_name() or instance.username,
        )


class NewsletterSubscriber(models.Model):
    email = models.EmailField(unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        return self.email

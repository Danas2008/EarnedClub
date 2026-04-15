from django.db import models


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
    name = models.CharField(max_length=100)
    reps = models.IntegerField()
    video_link = models.URLField()
    verified = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-reps", "created_at")

    def __str__(self):
        return f"{self.name} - {self.reps}"

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


class NewsletterSubscriber(models.Model):
    email = models.EmailField(unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        return self.email

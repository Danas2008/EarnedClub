import json
import logging
import random
from datetime import timedelta
from xml.etree.ElementTree import Element, SubElement, indent, register_namespace, tostring
from xml.sax.saxutils import quoteattr
from urllib.parse import urlencode, urljoin

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.decorators import user_passes_test
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.models import User
from django.core.mail import send_mail
from django.core.serializers.json import DjangoJSONEncoder
from django.http import HttpResponse
from django.db import IntegrityError
from django.core.paginator import Paginator
from django.db.models import F, Q
from django.views.decorators.http import require_POST
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.safestring import mark_safe

from .countries import COUNTRY_CHOICES
from .forms import FlexibleUsernameCreationForm
from .models import (
    ContentEnginePrompt,
    Follow,
    Goal,
    NewsletterCampaign,
    NewsletterSendEvent,
    NewsletterSegment,
    NewsletterSubscriber,
    Profile,
    RANK_TIERS,
    Submission,
    VerificationEvent,
    Workout,
    WorkoutExercise,
    WorkoutSession,
    WorkoutSessionExercise,
    WorkoutTemplate,
    get_best_verified_submission_for_user,
    get_official_rank_for_submission,
    get_official_verified_submissions,
    get_rank_tier,
    get_submission_identity,
)
from .media_utils import store_profile_image, store_submission_video


DEFAULT_EXERCISES = [
    {"name": "Push-ups", "type": "strength", "body_part": "Chest"},
    {"name": "Bench press", "type": "strength", "body_part": "Chest"},
    {"name": "Dumbbell press", "type": "strength", "body_part": "Chest"},
    {"name": "Chest fly", "type": "strength", "body_part": "Chest"},
    {"name": "Incline dumbbell press", "type": "strength", "body_part": "Chest"},
    {"name": "Pull-ups", "type": "strength", "body_part": "Back"},
    {"name": "Chin-ups", "type": "strength", "body_part": "Back"},
    {"name": "Lat pulldown", "type": "strength", "body_part": "Back"},
    {"name": "Seated row", "type": "strength", "body_part": "Back"},
    {"name": "Dips", "type": "strength", "body_part": "Triceps"},
    {"name": "Triceps pushdown", "type": "strength", "body_part": "Triceps"},
    {"name": "Skull crushers", "type": "strength", "body_part": "Triceps"},
    {"name": "Squats", "type": "strength", "body_part": "Legs"},
    {"name": "Deadlift", "type": "strength", "body_part": "Legs"},
    {"name": "Bulgarian split squat", "type": "strength", "body_part": "Legs"},
    {"name": "Leg press", "type": "strength", "body_part": "Legs"},
    {"name": "Romanian deadlift", "type": "strength", "body_part": "Legs"},
    {"name": "Lunges", "type": "strength", "body_part": "Legs"},
    {"name": "Plank", "type": "strength", "body_part": "Core"},
    {"name": "Hanging knee raise", "type": "strength", "body_part": "Core"},
    {"name": "Sit-ups", "type": "strength", "body_part": "Core"},
    {"name": "Burpees", "type": "cardio", "body_part": "Full body"},
    {"name": "Running", "type": "cardio", "body_part": "Cardio"},
    {"name": "Cycling", "type": "cardio", "body_part": "Cardio"},
    {"name": "Jump rope", "type": "cardio", "body_part": "Cardio"},
    {"name": "Rowing machine", "type": "cardio", "body_part": "Cardio"},
    {"name": "Shoulder press", "type": "strength", "body_part": "Shoulders"},
    {"name": "Lateral raise", "type": "strength", "body_part": "Shoulders"},
    {"name": "Rear delt raise", "type": "strength", "body_part": "Shoulders"},
    {"name": "Rows", "type": "strength", "body_part": "Back"},
    {"name": "Dead bug", "type": "mobility", "body_part": "Core"},
    {"name": "Hip mobility flow", "type": "mobility", "body_part": "Legs"},
    {"name": "Shoulder mobility flow", "type": "mobility", "body_part": "Shoulders"},
    {"name": "Glute bridge", "type": "strength", "body_part": "Legs"},
    {"name": "Calf raises", "type": "strength", "body_part": "Legs"},
    {"name": "Mountain climbers", "type": "cardio", "body_part": "Full body"},
    {"name": "Pike push-ups", "type": "strength", "body_part": "Shoulders"},
    {"name": "Superman hold", "type": "strength", "body_part": "Back"},
    {"name": "Side plank", "type": "strength", "body_part": "Core"},
]

BODY_PARTS = sorted({exercise["body_part"] for exercise in DEFAULT_EXERCISES})
EXERCISE_LOOKUP = {exercise["name"]: exercise for exercise in DEFAULT_EXERCISES}

SYSTEM_WORKOUT_TEMPLATES = [
    {
        "name": "Push Day",
        "difficulty": WorkoutTemplate.DIFFICULTY_BEGINNER,
        "notes": "Balanced push practice with shoulder and core support.",
        "exercises": [("Push-ups", 3, 10, None), ("Dips", 3, 8, None), ("Pike push-ups", 2, 8, None), ("Plank", 3, None, 35)],
    },
    {
        "name": "Leg Day",
        "difficulty": WorkoutTemplate.DIFFICULTY_BEGINNER,
        "notes": "Simple lower-body session for consistency and conditioning.",
        "exercises": [("Squats", 3, 12, None), ("Lunges", 3, 10, None), ("Glute bridge", 3, 12, None), ("Calf raises", 2, 15, None), ("Plank", 2, None, 35)],
    },
    {
        "name": "Pull Strength",
        "difficulty": WorkoutTemplate.DIFFICULTY_INTERMEDIATE,
        "notes": "Back and biceps work to balance push-up volume.",
        "exercises": [("Pull-ups", 3, 6, None), ("Rows", 3, 10, None), ("Rear delt raise", 2, 12, None), ("Superman hold", 2, None, 30), ("Dead bug", 3, None, 35)],
    },
    {
        "name": "Full Body Base",
        "difficulty": WorkoutTemplate.DIFFICULTY_INTERMEDIATE,
        "notes": "A practical whole-body session for steady weekly training.",
        "exercises": [("Push-ups", 3, 12, None), ("Squats", 3, 12, None), ("Rows", 3, 10, None), ("Lunges", 2, 10, None), ("Jump rope", 1, None, 180), ("Side plank", 2, None, 25)],
    },
    {
        "name": "Elite Push Builder",
        "difficulty": WorkoutTemplate.DIFFICULTY_ADVANCED,
        "notes": "Higher volume for athletes chasing 60+ strict push-ups.",
        "exercises": [("Push-ups", 4, 14, None), ("Dips", 3, 10, None), ("Pike push-ups", 3, 8, None), ("Rows", 3, 12, None), ("Plank", 3, None, 45)],
    },
    {
        "name": "Legend Density",
        "difficulty": WorkoutTemplate.DIFFICULTY_ADVANCED,
        "notes": "Dense push volume with conditioning for high-rep athletes.",
        "exercises": [("Push-ups", 5, 12, None), ("Burpees", 3, 10, None), ("Rows", 3, 12, None), ("Mountain climbers", 2, None, 40), ("Side plank", 3, None, 35)],
    },
]

ADMIN_SUBMISSION_EMAIL = "daniel.havlicek1@seznam.cz"
NEWSLETTER_FROM_EMAIL = "Earned Club <earnedclub1@gmail.com>"
logger = logging.getLogger(__name__)


SITEMAP_NAMESPACE = "http://www.sitemaps.org/schemas/sitemap/0.9"
register_namespace("", SITEMAP_NAMESPACE)

SITEMAP_STATIC_PAGES = [
    {"view_name": "home", "changefreq": "daily", "priority": "1.0"},
    {"view_name": "level_test", "changefreq": "weekly", "priority": "0.9"},
    {"view_name": "challenge", "changefreq": "weekly", "priority": "0.9"},
    {"view_name": "leaderboard", "changefreq": "daily", "priority": "0.9"},
    {"view_name": "profiles", "changefreq": "daily", "priority": "0.8"},
    {"view_name": "calculators", "changefreq": "monthly", "priority": "0.6"},
    {"view_name": "register", "changefreq": "monthly", "priority": "0.5"},
    {"view_name": "login", "changefreq": "monthly", "priority": "0.3"},
    {"view_name": "privacy", "changefreq": "yearly", "priority": "0.2"},
    {"view_name": "terms", "changefreq": "yearly", "priority": "0.2"},
]

LEADERBOARD_MODES = [
    {
        "key": "all",
        "label": "Open Board",
        "description": "Verified and pending entries ranked by reps.",
    },
    {
        "key": "verified",
        "label": "Verified Only",
        "description": "Official ranked results only.",
    },
    {
        "key": "week",
        "label": "This Week",
        "description": "Fresh entries from the past 7 days.",
    },
    {
        "key": "month",
        "label": "This Month",
        "description": "Momentum from the past 30 days.",
    },
    {
        "key": "pending",
        "label": "Pending",
        "description": "Strong attempts waiting for review.",
    },
    {
        "key": "unverified",
        "label": "Unverified",
        "description": "Saved attempts that still need proof.",
    },
]
LEADERBOARD_MODE_LOOKUP = {mode["key"]: mode for mode in LEADERBOARD_MODES}


def build_leaderboard_rows(submissions):
    rows = []
    for index, submission in enumerate(submissions, start=1):
        profile = None
        if submission.user_id:
            profile = getattr(submission.user, "profile", None)
        verified_position = None
        if submission.status == Submission.STATUS_VERIFIED:
            verified_position = get_official_rank_for_submission(submission)
        elif submission.user_id:
            verified_position = get_official_rank_for_submission(get_best_verified_submission_for_user(submission.user))
        rows.append(
            {
                "position": index,
                "medal_place": index if index <= 3 else None,
                "verified_position": verified_position,
                "submission": submission,
                "profile": profile,
            }
        )
    return rows


def ensure_system_workout_templates():
    for template in SYSTEM_WORKOUT_TEMPLATES:
        WorkoutTemplate.objects.get_or_create(
            user=None,
            is_system=True,
            name=template["name"],
            defaults={
                "difficulty": template["difficulty"],
                "notes": template["notes"],
            },
        )


def get_template_exercises(template):
    for preset in SYSTEM_WORKOUT_TEMPLATES:
        if preset["name"] == template.name:
            return preset["exercises"]
    return [("Push-ups", 3, 10, None)]


def estimate_workout_minutes(exercises):
    total_seconds = 0
    for _name, sets, reps, seconds in exercises:
        set_count = sets or 1
        if seconds:
            work_seconds = seconds
        else:
            work_seconds = (reps or 10) * 3
        total_seconds += set_count * work_seconds
        total_seconds += max(0, set_count - 1) * 60
    return max(8, round(total_seconds / 60) + 3)


def build_template_cards(templates):
    cards = []
    for template in templates:
        exercises = get_template_exercises(template)
        cards.append(
            {
                "template": template,
                "exercises": exercises,
                "minutes": estimate_workout_minutes(exercises),
            }
        )
    return cards


def build_template_payload(cards):
    return [
        {
            "id": card["template"].id,
            "name": card["template"].name,
            "minutes": card["minutes"],
            "exercises": [
                {
                    "name": name,
                    "sets": sets or "",
                    "reps": reps or "",
                    "seconds": seconds or "",
                    "type": get_default_exercise(name).get("type", WorkoutExercise.TYPE_STRENGTH),
                    "body_part": get_default_exercise(name).get("body_part", ""),
                }
                for name, sets, reps, seconds in card["exercises"]
            ],
        }
        for card in cards
    ]


def notify_user_email(user, subject, message):
    if not user or not user.email:
        return
    send_mail(subject, message, getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@earnedclub.club"), [user.email], fail_silently=True)


def notify_admin_submission(submission, event_label):
    proof = submission.proof_url or "No proof attached"
    send_mail(
        f"Earned Club result submitted: {submission.reps} reps",
        (
            f"{event_label}\n\n"
            f"Name: {submission.name}\n"
            f"Email: {submission.email or 'No email'}\n"
            f"Reps: {submission.reps}\n"
            f"Status: {submission.public_status_label}\n"
            f"Proof: {proof}"
        ),
        getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@earnedclub.club"),
        [ADMIN_SUBMISSION_EMAIL],
        fail_silently=True,
    )


def get_profile_share_message(profile, request):
    url = request.build_absolute_uri(reverse("athlete_profile", args=[profile.slug]))
    return f"Check out {profile.display_name}'s EarnedClub profile: {url}"


def get_pr_share_message(profile, request):
    url = request.build_absolute_uri(reverse("athlete_profile", args=[profile.slug]))
    return f"Hey, I just did {profile.personal_best_reps} push-ups on earnedclub.club. Can you beat it? {url}"


def get_daily_suggestion(profile, verified_count, workout_count):
    quotes = [
        "Small proof beats loud claims.",
        "Make today's set clean enough to count.",
        "Consistency is the quiet part of status.",
        "Train the rep you want verified.",
        "Good training is boring until the numbers move.",
        "Win today's clean set.",
    ]
    if profile.personal_best_reps >= 80:
        tasks = [
            "Keep today submax: push, pull, core, then stop before form breaks.",
            "Do a quality density session with no failed reps.",
            "Train recovery and shoulder stability so your next test is sharp.",
            "Run a balanced full-body workout instead of another max push day.",
        ]
    elif profile.personal_best_reps >= 60:
        tasks = [
            "Do 4 controlled push-up sets at about 65% of your PR.",
            "Pair push-ups with rows and core so your shoulders stay balanced.",
            "Use an advanced workout today, but leave one rep in reserve.",
            "Retest one strong set only if you feel sharp.",
        ]
    elif profile.personal_best_reps >= 40:
        tasks = [
            "Do 4 push-up sets at 60-70% of your PR.",
            "Add one pull exercise today.",
            "Try a clean 40-rep pace set.",
            "Start your highlighted workout and finish every set.",
            "Use a shorter recovery workout and protect form.",
        ]
    elif workout_count:
        tasks = [
            "Repeat your last workout and add one clean rep.",
            "Quick log one exercise now.",
            "Do push-ups, rows, and core.",
            "Start one saved workout and complete every planned set.",
            "Pick a random recommended session and finish it today.",
        ]
    else:
        tasks = [
            "Test push-ups today.",
            "Start with Push Day.",
            "Log one honest set.",
            "Open a beginner workout and finish the first round.",
            "Build one simple 15-minute session and complete it.",
        ]
    task = random.choice(tasks)
    quote = random.choice(quotes)
    return f"{task} {quote}"


def verified_submission_queryset():
    return Submission.objects.filter(status=Submission.STATUS_VERIFIED)


def public_submission_queryset(since=None):
    visible = {}
    if since:
        verified_pool = (
            Submission.objects.filter(status=Submission.STATUS_VERIFIED, created_at__gte=since)
            .select_related("user", "user__profile")
            .order_by("-reps", "created_at")
        )
    else:
        verified_pool = get_official_verified_submissions()
    for submission in verified_pool:
        identity = get_submission_identity(submission)
        current = visible.get(identity)
        if current is None or submission.reps > current.reps:
            visible[identity] = submission

    pending_submissions = (
        Submission.objects.filter(status=Submission.STATUS_PENDING)
        .select_related("user", "user__profile")
        .order_by("-reps", "created_at")
    )
    if since:
        pending_submissions = pending_submissions.filter(created_at__gte=since)
    for submission in pending_submissions:
        identity = get_submission_identity(submission)
        current = visible.get(identity)
        if current is None or submission.reps > current.reps:
            visible[identity] = submission

    return sorted(visible.values(), key=lambda item: (-item.reps, item.created_at))


def pending_submission_queryset():
    return Submission.objects.filter(status=Submission.STATUS_PENDING)


def active_submission_queryset():
    return Submission.objects.filter(status__in=[Submission.STATUS_UNVERIFIED, Submission.STATUS_PENDING])


def blocking_submission_queryset():
    recent_cutoff = timezone.now() - timedelta(minutes=1)
    return Submission.objects.filter(
        Q(status=Submission.STATUS_PENDING) |
        Q(status=Submission.STATUS_UNVERIFIED, created_at__gte=recent_cutoff)
    )


def estimate_verified_position(reps):
    equal_or_better = sum(1 for item in get_official_verified_submissions() if item.reps >= reps)
    return equal_or_better + 1


def user_display_name(user):
    profile = getattr(user, "profile", None)
    if profile:
        return profile.display_name
    return user.get_full_name() or user.username


def get_progress_data(submissions):
    ordered = list(submissions.order_by("created_at", "id"))
    best_so_far = 0
    data = []
    for submission in ordered:
        previous_best = best_so_far
        best_so_far = max(best_so_far, submission.reps)
        data.append(
        {
            "date": submission.created_at.strftime("%Y-%m-%d"),
            "time": submission.created_at.strftime("%H:%M"),
            "label": submission.created_at.strftime("%b %d, %H:%M"),
            "reps": submission.reps,
            "best": best_so_far,
            "gain": submission.reps - previous_best if previous_best else 0,
        }
        )
    return data


def get_progress_summary(submissions):
    data = get_progress_data(submissions)
    if not data:
        return {"attempts": 0, "best": 0, "first": 0, "gain": 0, "average": 0}
    reps = [point["reps"] for point in data]
    return {
        "attempts": len(data),
        "best": max(reps),
        "first": reps[0],
        "gain": max(reps) - reps[0],
        "average": round(sum(reps) / len(reps), 1),
    }


def paginate_items(request, items, per_page=10, page_param="page"):
    paginator = Paginator(items, per_page)
    return paginator.get_page(request.GET.get(page_param))


def search_submissions(submissions, query):
    if not query:
        return submissions
    lowered = query.lower()
    return [
        submission for submission in submissions
        if lowered in submission.name.lower()
        or (submission.user_id and lowered in submission.user.username.lower())
        or (
            submission.user_id
            and hasattr(submission.user, "profile")
            and lowered in submission.user.profile.display_name.lower()
        )
    ]


def get_current_streak(submissions):
    weeks = {
        submission.created_at.isocalendar()[:2]
        for submission in submissions
    }
    if not weeks:
        return 0

    streak = 0
    cursor = timezone.now().date()
    while True:
        key = cursor.isocalendar()[:2]
        if key not in weeks:
            break
        streak += 1
        cursor -= timedelta(days=7)
    return streak


def get_weekly_window():
    return timezone.now() - timedelta(days=7)


def get_monthly_window():
    return timezone.now() - timedelta(days=30)


def get_leaderboard_mode(request):
    requested_mode = (request.GET.get("mode") or "all").strip().lower()
    return LEADERBOARD_MODE_LOOKUP.get(requested_mode, LEADERBOARD_MODE_LOOKUP["all"])


def get_leaderboard_submissions(mode_key):
    if mode_key == "verified":
        return get_official_verified_submissions()
    if mode_key == "week":
        return public_submission_queryset(since=get_weekly_window())
    if mode_key == "month":
        return public_submission_queryset(since=get_monthly_window())
    if mode_key == "pending":
        return pending_submission_queryset().select_related("user", "user__profile").order_by("-reps", "created_at")
    if mode_key == "unverified":
        return Submission.objects.filter(status=Submission.STATUS_UNVERIFIED).select_related("user", "user__profile").order_by("-reps", "created_at")
    return public_submission_queryset()


def build_querystring(**params):
    return urlencode({key: value for key, value in params.items() if value not in ("", None)})


def build_absolute_url(request, view_name, *args):
    return urljoin(f"{settings.SITE_URL}/", reverse(view_name, args=args).lstrip("/"))


def build_public_url(path):
    return urljoin(f"{settings.SITE_URL}/", path.lstrip("/"))


def json_ld(data):
    return mark_safe(json.dumps(data, cls=DjangoJSONEncoder).replace("</", "<\\/"))


def create_verification_event(submission, action, reviewer=None, note=""):
    return VerificationEvent.objects.create(
        submission=submission,
        reviewer=reviewer if reviewer and reviewer.is_authenticated else None,
        action=action,
        note=note,
    )


def get_submission_recipient(submission):
    if submission.user_id and submission.user.email:
        return submission.user.email
    return submission.email


def send_submission_notification(submission, subject, message):
    recipient = get_submission_recipient(submission)
    if not recipient:
        return
    send_mail(
        subject,
        message,
        settings.DEFAULT_FROM_EMAIL,
        [recipient],
        fail_silently=True,
    )


def find_proof_link_blocker(video_link, exclude_pk=None):
    if not video_link:
        return ""
    proof_matches = Submission.objects.filter(video_link__iexact=video_link)
    if exclude_pk:
        proof_matches = proof_matches.exclude(pk=exclude_pk)
    if proof_matches.exists():
        return "This proof is already attached to a submission."
    return ""


def find_submission_blocker(request, name, email, reps, video_link):
    if request.POST.get("website"):
        return "silent"

    proof_blocker = find_proof_link_blocker(video_link)
    if proof_blocker:
        return proof_blocker

    cooldown = timezone.now() - timedelta(minutes=1)
    recent_duplicate = Submission.objects.filter(created_at__gte=cooldown, reps=reps)
    if request.user.is_authenticated:
        recent_duplicate = recent_duplicate.filter(user=request.user)
    else:
        recent_duplicate = recent_duplicate.filter(Q(email__iexact=email) | Q(name__iexact=name))
    if recent_duplicate.exists():
        return "That looks like a duplicate of a recent submission. Give it a few minutes or update your active entry with proof."

    return ""


def build_profile_schema(profile, best_submission):
    image_url = profile.profile_image_url
    schema = {
        "@context": "https://schema.org",
        "@type": "Person",
        "name": profile.display_name,
        "url": build_public_url(reverse("athlete_profile", args=[profile.slug])),
        "description": (
            f"{profile.display_name} has a verified Earned Club push-up PR of "
            f"{profile.personal_best_reps} reps."
        ),
        "memberOf": {
            "@type": "SportsOrganization",
            "name": "Earned Club",
            "url": settings.SITE_URL,
        },
    }
    if profile.country:
        schema["nationality"] = profile.country
    if image_url:
        schema["image"] = build_public_url(image_url) if image_url.startswith("/") else image_url
    if best_submission:
        schema["knowsAbout"] = [
            f"Verified strict push-up personal record: {best_submission.reps} reps",
            f"Earned Club rank tier: {best_submission.rank_name}",
        ]
    return schema


def parse_positive_int(value):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def profile_completion_items(user):
    profile = user.profile
    items = [
        {"label": "Add profile photo", "done": bool(profile.profile_image_url), "url": reverse("dashboard")},
        {"label": "Add country", "done": bool(profile.country), "url": reverse("dashboard")},
        {"label": "Add bio", "done": bool(profile.bio), "url": reverse("dashboard")},
        {"label": "Get first verified push-up attempt", "done": user.submission_set.filter(status=Submission.STATUS_VERIFIED).exists(), "url": reverse("challenge")},
        {"label": "Publish one workout", "done": user.workouts.filter(is_public=True).exists(), "url": reverse("workouts")},
    ]
    completed = sum(1 for item in items if item["done"])
    return items, round((completed / len(items)) * 100)


def build_onboarding_checklist(user):
    return [
        {"label": "Test your push-up level", "done": user.submission_set.exists(), "url": reverse("level_test")},
        {"label": "Submit proof", "done": user.submission_set.filter(status__in=[Submission.STATUS_PENDING, Submission.STATUS_VERIFIED]).exists(), "url": reverse("challenge")},
        {"label": "Create a workout", "done": user.workouts.exists(), "url": reverse("workouts")},
        {"label": "Set a goal", "done": user.goals.exists(), "url": reverse("dashboard")},
        {"label": "Share your profile", "done": bool(user.profile.personal_best_reps), "url": reverse("athlete_profile", args=[user.profile.slug])},
    ]


def build_next_action(user):
    if not user.submission_set.exists():
        return {"label": "Test your push-up level", "url": reverse("level_test"), "text": "Start with a quick push-up level test."}
    if user.submission_set.filter(status=Submission.STATUS_UNVERIFIED).exists():
        return {"label": "Add proof", "url": reverse("dashboard"), "text": "Upload proof so your push-up result can be reviewed."}
    if not user.workouts.exists():
        return {"label": "Create workout", "url": reverse("workouts"), "text": "Build a push-up workout plan for the next 14 days."}
    if not user.goals.exists():
        return {"label": "Set goal", "url": reverse("dashboard"), "text": "Pick the next push-up number you want to reach."}
    return {"label": "Share profile", "url": reverse("athlete_profile", args=[user.profile.slug]), "text": "Share your public profile and keep building proof."}


def send_newsletter_to_subscribers(subject, body, subscribers, campaign=None, request=None):
    sent_count = 0
    for subscriber in subscribers:
        if not subscriber.is_subscribed:
            continue
        message = body
        if request:
            unsubscribe_url = request.build_absolute_uri(reverse("newsletter_unsubscribe", args=[subscriber.unsubscribe_token]))
            message = f"{body}\n\nUnsubscribe: {unsubscribe_url}"
        sent_count += send_mail(subject, message, NEWSLETTER_FROM_EMAIL, [subscriber.email], fail_silently=True)
        NewsletterSendEvent.objects.create(subscriber=subscriber, campaign=campaign, subject=subject)
    return sent_count


def newsletter_auto_segment_subscribers(key):
    if key == "verified":
        return NewsletterSubscriber.objects.filter(email__in=Submission.objects.filter(status=Submission.STATUS_VERIFIED).exclude(email="").values("email"))
    if key == "unverified":
        return NewsletterSubscriber.objects.filter(email__in=Submission.objects.filter(status=Submission.STATUS_UNVERIFIED).exclude(email="").values("email"))
    if key == "no-submission":
        return NewsletterSubscriber.objects.exclude(email__in=Submission.objects.exclude(email="").values("email"))
    if key == "high-rank":
        return NewsletterSubscriber.objects.filter(email__in=Submission.objects.filter(status=Submission.STATUS_VERIFIED, reps__gte=60).exclude(email="").values("email"))
    return NewsletterSubscriber.objects.none()


def get_default_exercise(name):
    return EXERCISE_LOOKUP.get((name or "").strip(), {})


def create_workout_from_request(request):
    title = (request.POST.get("title") or "").strip()
    duration_value = parse_positive_int(request.POST.get("duration_minutes"))
    rest_interval = parse_positive_int(request.POST.get("rest_interval_seconds")) or 60
    notes = (request.POST.get("notes") or "").strip()
    is_public = request.POST.get("is_public") == "on"
    highlighted = request.POST.get("highlighted_on_profile") == "on"
    template_id = request.POST.get("template_id")
    template = None
    if template_id:
        template = WorkoutTemplate.objects.filter(Q(user=request.user) | Q(is_system=True), pk=template_id).first()
    if not title and template:
        title = template.name
    if not duration_value and template:
        duration_value = estimate_workout_minutes(get_template_exercises(template))
    if not title:
        return None, "Workout title is required."
    if highlighted and is_public:
        request.user.workouts.update(highlighted_on_profile=False)
    workout = Workout.objects.create(
        user=request.user,
        template=template,
        title=title,
        duration_minutes=duration_value,
        rest_interval_seconds=rest_interval,
        notes=notes,
        is_public=is_public,
        highlighted_on_profile=highlighted and is_public,
    )
    names = request.POST.getlist("exercise_name")
    types = request.POST.getlist("exercise_type")
    body_parts = request.POST.getlist("body_part")
    sets_values = request.POST.getlist("exercise_sets")
    reps_values = request.POST.getlist("exercise_reps")
    seconds_values = request.POST.getlist("exercise_seconds")
    exercise_created = False
    for index, exercise_name in enumerate(names):
        exercise_name = (exercise_name or "").strip()
        if not exercise_name:
            continue
        default_exercise = get_default_exercise(exercise_name)
        exercise_type = default_exercise.get("type") or (
            types[index] if index < len(types) and types[index] else WorkoutExercise.TYPE_STRENGTH
        )
        WorkoutExercise.objects.create(
            workout=workout,
            name=exercise_name,
            exercise_type=exercise_type,
            body_part=(body_parts[index] if index < len(body_parts) and body_parts[index] else default_exercise.get("body_part", "")).strip(),
            sets=parse_positive_int(sets_values[index] if index < len(sets_values) else "") or 1,
            reps=parse_positive_int(reps_values[index] if index < len(reps_values) else ""),
            seconds=parse_positive_int(seconds_values[index] if index < len(seconds_values) else ""),
            order=index,
        )
        exercise_created = True
    if not exercise_created and template:
        for index, (name, sets, reps, seconds) in enumerate(get_template_exercises(template)):
            WorkoutExercise.objects.create(workout=workout, name=name, sets=sets, reps=reps, seconds=seconds, order=index)
    if workout.highlighted_on_profile:
        request.user.workouts.exclude(pk=workout.pk).update(highlighted_on_profile=False)
    return workout, ""


def pick_exercises_for_body_parts(body_parts, duration_minutes, personal_best):
    body_parts = [part for part in body_parts if part in BODY_PARTS]
    selected_body_parts = bool(body_parts)
    if not selected_body_parts:
        body_parts = ["Chest", "Back", "Legs", "Core"]
    target_count = 4
    if duration_minutes >= 35:
        target_count = 6
    elif duration_minutes >= 25:
        target_count = 5

    reps = 10
    sets = 2
    if personal_best >= 60:
        reps = 12
        sets = 3
    elif personal_best >= 20:
        reps = 10
        sets = 3

    chosen = []
    for part in body_parts:
        candidates = [exercise for exercise in DEFAULT_EXERCISES if exercise["body_part"] == part]
        strength = [exercise for exercise in candidates if exercise["type"] == WorkoutExercise.TYPE_STRENGTH]
        chosen.extend(strength[:target_count] or candidates[:target_count])

    unique_chosen = []
    seen_names = set()
    for exercise in chosen:
        if exercise["name"] in seen_names:
            continue
        seen_names.add(exercise["name"])
        unique_chosen.append(exercise)
    chosen = unique_chosen

    if "Chest" in body_parts and not any(item["name"] == "Push-ups" for item in chosen):
        chosen.insert(0, get_default_exercise("Push-ups") | {"name": "Push-ups"})
    if not selected_body_parts and len(chosen) < target_count:
        for fallback in ("Rows", "Squats", "Plank", "Jump rope", "Dead bug", "Side plank"):
            exercise = get_default_exercise(fallback)
            if exercise and exercise not in chosen:
                chosen.append(exercise | {"name": fallback})
            if len(chosen) >= target_count:
                break

    plan = []
    for index, exercise in enumerate(chosen[:target_count]):
        name = exercise["name"]
        exercise_type = exercise["type"]
        if exercise_type == WorkoutExercise.TYPE_CARDIO:
            plan.append((name, 1 if duration_minutes < 25 else 2, None, 90 if duration_minutes < 25 else 120))
        elif exercise_type == WorkoutExercise.TYPE_MOBILITY:
            plan.append((name, 2, None, 30))
        elif name in {"Plank", "Side plank", "Superman hold"}:
            plan.append((name, 2 if personal_best < 60 else 3, None, 30 if personal_best < 60 else 40))
        else:
            plan.append((name, sets, reps if index else max(8, reps - 2), None))
    return plan


def create_generated_workout(request):
    duration = parse_positive_int(request.POST.get("builder_minutes")) or 20
    duration = min(60, max(10, duration))
    body_parts = [part for part in request.POST.getlist("builder_body_parts") if part in BODY_PARTS]
    difficulty = request.POST.get("builder_difficulty") or ""
    personal_best = request.user.profile.personal_best_reps
    if difficulty == WorkoutTemplate.DIFFICULTY_BEGINNER:
        personal_best = 0
    elif difficulty == WorkoutTemplate.DIFFICULTY_INTERMEDIATE:
        personal_best = 25
    elif difficulty == WorkoutTemplate.DIFFICULTY_ADVANCED:
        personal_best = 60
    rest_interval = parse_positive_int(request.POST.get("builder_rest_interval_seconds")) or 60
    exercises = pick_exercises_for_body_parts(body_parts, duration, personal_best)
    title_parts = ", ".join(body_parts) if body_parts else "Full body"
    workout = Workout.objects.create(
        user=request.user,
        title=f"{title_parts} {duration}-minute custom workout",
        duration_minutes=duration,
        rest_interval_seconds=rest_interval,
        notes="Generated from your selected body parts and available time.",
    )
    for index, (name, sets, reps, seconds) in enumerate(exercises):
        default_exercise = get_default_exercise(name)
        WorkoutExercise.objects.create(
            workout=workout,
            name=name,
            exercise_type=default_exercise.get("type", WorkoutExercise.TYPE_STRENGTH),
            body_part=default_exercise.get("body_part", ""),
            sets=sets,
            reps=reps,
            seconds=seconds,
            order=index,
        )
    return workout


def build_newsletter_draft(week_number):
    return {
        "subject": f"Earned Club Week {week_number}: leaderboard, training, proof",
        "body": (
            f"Week {week_number} update from Earned Club\n\n"
            "1. Leaderboard movement\n"
            "The board is moving. Submit a clean set if you want your rank to count.\n\n"
            "2. Training focus\n"
            "Keep this week balanced: push work, one pull movement, legs, and core.\n\n"
            "3. Challenge\n"
            "Film one honest attempt or complete one saved workout before the week ends.\n\n"
            "Earn it,\n"
            "Earned Club"
        ),
    }


def clone_workout(source, *, user, title=None, is_public=False):
    workout = Workout.objects.create(
        user=user,
        template=source.template,
        title=title or source.title,
        notes=source.notes,
        duration_minutes=source.duration_minutes,
        is_public=is_public,
    )
    for exercise in source.exercises.all():
        WorkoutExercise.objects.create(
            workout=workout,
            name=exercise.name,
            exercise_type=exercise.exercise_type,
            body_part=exercise.body_part,
            sets=exercise.sets,
            reps=exercise.reps,
            seconds=exercise.seconds,
            notes=exercise.notes,
            order=exercise.order,
        )
    return workout


def create_workout_from_template(template, user):
    workout = Workout.objects.create(
        user=user,
        template=template,
        title=template.name,
        notes=template.notes,
        duration_minutes=estimate_workout_minutes(get_template_exercises(template)),
        is_public=False,
    )
    for index, (name, sets, reps, seconds) in enumerate(get_template_exercises(template)):
        default_exercise = get_default_exercise(name)
        WorkoutExercise.objects.create(
            workout=workout,
            name=name,
            exercise_type=default_exercise.get("type", WorkoutExercise.TYPE_STRENGTH),
            body_part=default_exercise.get("body_part", ""),
            sets=sets,
            reps=reps,
            seconds=seconds,
            order=index,
        )
    return workout


def start_workout_session_for_user(user, workout):
    session = WorkoutSession.objects.create(user=user, workout=workout)
    for exercise in workout.exercises.all():
        WorkoutSessionExercise.objects.create(
            session=session,
            workout_exercise=exercise,
            name=exercise.name,
            exercise_type=exercise.exercise_type,
            body_part=exercise.body_part,
            target_sets=exercise.sets or 1,
            target_reps=exercise.reps,
            target_seconds=exercise.seconds,
            order=exercise.order,
        )
    return session


def format_sitemap_date(value):
    if not value:
        return ""
    if hasattr(value, "date"):
        if timezone.is_aware(value):
            value = timezone.localtime(value)
        value = value.date()
    return value.isoformat()


def build_sitemap_entries(request):
    entries = [
        {
            "loc": build_absolute_url(request, page["view_name"]),
            "changefreq": page["changefreq"],
            "priority": page["priority"],
        }
        for page in SITEMAP_STATIC_PAGES
    ]
    entries.extend(
        {
            "loc": build_absolute_url(request, "athlete_profile", profile.slug),
            "lastmod": format_sitemap_date(profile.updated_at),
            "changefreq": "weekly",
            "priority": "0.7",
        }
        for profile in Profile.objects.filter(personal_best_reps__gt=0).only("slug", "updated_at").order_by("slug")
    )
    entries.extend(
        {
            "loc": build_absolute_url(request, "workout_detail", workout.slug),
            "lastmod": format_sitemap_date(workout.created_at),
            "changefreq": "monthly",
            "priority": "0.5",
        }
        for workout in Workout.objects.filter(is_public=True).only("slug", "created_at").order_by("slug")
    )
    return entries


def build_sitemap_xml(entries, stylesheet_url):
    urlset = Element(f"{{{SITEMAP_NAMESPACE}}}urlset")
    for entry in entries:
        url = SubElement(urlset, f"{{{SITEMAP_NAMESPACE}}}url")
        for key in ("loc", "lastmod", "changefreq", "priority"):
            value = entry.get(key)
            if value:
                SubElement(url, f"{{{SITEMAP_NAMESPACE}}}{key}").text = str(value)

    indent(urlset, space="  ")
    body = tostring(urlset, encoding="unicode")
    return "\n".join(
        [
            '<?xml version="1.0" encoding="UTF-8"?>',
            f'<?xml-stylesheet type="text/xsl" href={quoteattr(stylesheet_url)}?>',
            body,
        ]
    )


def home(request):
    verified_submissions = get_official_verified_submissions()
    public_submissions = list(public_submission_queryset())
    leaderboard_rows = build_leaderboard_rows(public_submissions)
    weekly_cutoff = get_weekly_window()
    weekly_rows = build_leaderboard_rows(public_submission_queryset(since=weekly_cutoff))

    context = {
        "rank_tiers": RANK_TIERS,
        "total_verified": len(verified_submissions),
        "total_submissions": len(public_submissions),
        "top_three": leaderboard_rows[:3],
        "weekly_top_five": weekly_rows[:5],
        "overall_top_five": leaderboard_rows[:5],
    }
    return render(request, "home.html", context)


def level_test(request):
    verified_submissions = get_official_verified_submissions()
    return render(
        request,
        "test_landing.html",
        {
            "rank_tiers": RANK_TIERS,
            "total_verified": len(verified_submissions),
            "total_submissions": len(public_submission_queryset()),
        },
    )


def sitemap_xml(request):
    xml = build_sitemap_xml(
        build_sitemap_entries(request),
        reverse("sitemap_xsl"),
    )
    return HttpResponse(xml, content_type="application/xml; charset=utf-8")


def sitemap_xsl(request):
    return render(request, "sitemap.xsl", content_type="text/xsl; charset=utf-8")



def robots_txt(request):
    lines = [
        "User-agent: *",
        "Allow: /",
        "Disallow: /admin/",
        f"Sitemap: {build_public_url(reverse('sitemap_xml'))}",
    ]
    return HttpResponse("\n".join(lines), content_type="text/plain")


def leaderboard(request):
    query = (request.GET.get("q") or "").strip()
    active_mode = get_leaderboard_mode(request)
    verified_submissions = get_official_verified_submissions()
    public_submissions = list(get_leaderboard_submissions(active_mode["key"]))
    public_submissions = search_submissions(public_submissions, query)
    weekly_cutoff = get_weekly_window()
    monthly_cutoff = get_monthly_window()

    leaderboard_rows = build_leaderboard_rows(public_submissions)
    leaderboard_page = paginate_items(request, leaderboard_rows, per_page=10)

    context = {
        "leaderboard_rows": leaderboard_page,
        "leaderboard_pages": leaderboard_page.paginator.get_elided_page_range(
            number=leaderboard_page.number,
            on_each_side=1,
            on_ends=1,
        ),
        "leaderboard_modes": LEADERBOARD_MODES,
        "active_mode": active_mode,
        "weekly_cutoff": weekly_cutoff.isoformat(),
        "monthly_cutoff": monthly_cutoff.isoformat(),
        "rank_tiers": RANK_TIERS,
        "verified_count": len(verified_submissions),
        "submission_count": len(public_submissions),
        "pending_count": pending_submission_queryset().count(),
        "weekly_count": len(public_submission_queryset(since=weekly_cutoff)),
        "query": query,
    }
    return render(request, "leaderboard.html", context)


def register(request):
    if request.user.is_authenticated:
        return redirect("dashboard")

    if request.method == "POST":
        form = FlexibleUsernameCreationForm(request.POST)
        email = (request.POST.get("email") or "").strip().lower()
        if form.is_valid():
            user = form.save(commit=False)
            user.email = email
            user.save()
            profile = user.profile
            profile.display_name = user.username
            profile.slug = ""
            profile.save()
            login(request, user)
            messages.success(request, "Account created. Your athlete profile is ready.")
            return redirect("dashboard")
    else:
        form = FlexibleUsernameCreationForm()

    return render(
        request,
        "register.html",
        {
            "form": form,
            "prefill_username": (request.GET.get("name") or "").strip(),
            "prefill_email": (request.GET.get("email") or "").strip(),
        },
    )


def login_view(request):
    if request.user.is_authenticated:
        return redirect("dashboard")

    form = AuthenticationForm(request, data=request.POST or None)
    if request.method == "POST" and form.is_valid():
        login(request, form.get_user())
        messages.success(request, "Welcome back.")
        next_url = request.GET.get("next") or "dashboard"
        return redirect(next_url)

    return render(request, "login.html", {"form": form})


def logout_view(request):
    logout(request)
    messages.info(request, "You are logged out.")
    return redirect("home")


@login_required
def dashboard(request):
    profile = request.user.profile
    if request.method == "POST":
        form_type = request.POST.get("form_type", "profile")

        if form_type == "goal":
            goal_type = request.POST.get("goal_type") or Goal.GOAL_PUSHUPS
            target_value = request.POST.get("target_value")
            note = (request.POST.get("note") or "").strip()
            is_public = request.POST.get("is_public") == "on"
            try:
                target_value = int(target_value)
            except (TypeError, ValueError):
                messages.error(request, "Goal target must be a whole number.")
                return redirect("dashboard")
            if target_value <= 0:
                messages.error(request, "Goal target must be greater than zero.")
                return redirect("dashboard")
            Goal.objects.create(user=request.user, goal_type=goal_type, target_value=target_value, note=note, is_public=is_public)
            messages.success(request, "Goal saved.")
            return redirect("dashboard")

        if form_type == "workout":
            workout, error = create_workout_from_request(request)
            if error:
                messages.error(request, error)
            else:
                messages.success(request, "Workout saved.")
            return redirect("dashboard")

        if form_type == "quick_result":
            exercise_name = (request.POST.get("quick_exercise") or "Quick result").strip()
            reps = parse_positive_int(request.POST.get("quick_reps"))
            seconds = parse_positive_int(request.POST.get("quick_seconds"))
            if not reps and not seconds:
                messages.error(request, "Add reps or time for quick log.")
                return redirect("dashboard")
            workout = Workout.objects.create(user=request.user, title=f"Quick log - {exercise_name}")
            WorkoutExercise.objects.create(workout=workout, name=exercise_name, reps=reps, seconds=seconds)
            messages.success(request, "Quick log saved.")
            return redirect("dashboard")

        username = (request.POST.get("username") or "").strip()
        email = (request.POST.get("email") or "").strip().lower()
        profile_photo = (request.POST.get("profile_photo") or profile.profile_photo or "").strip()
        profile_image = request.FILES.get("profile_image")
        country = (request.POST.get("country") or "").strip()
        age = (request.POST.get("age") or "").strip()
        bio = (request.POST.get("bio") or "").strip()

        if username and User.objects.filter(username=username).exclude(pk=request.user.pk).exists():
            messages.error(request, "This username is already taken.")
            return redirect("dashboard")

        if age:
            try:
                age_value = int(age)
            except ValueError:
                messages.error(request, "Age must be a whole number.")
                return redirect("dashboard")
            if age_value < 13 or age_value > 100:
                messages.error(request, "Age must be between 13 and 100.")
                return redirect("dashboard")
        else:
            age_value = None

        if username:
            request.user.username = username
        request.user.email = email
        request.user.save(update_fields=["username", "email"])

        profile.display_name = request.user.username
        profile.profile_photo = profile_photo
        if profile_image:
            stored_image = store_profile_image(profile, profile_image)
            profile.profile_storage_path = stored_image["storage_path"]
            profile.profile_image = stored_image["local_file"] or ""
            profile.profile_photo = stored_image["public_url"] or ""
        profile.country = country
        profile.age = age_value
        profile.bio = bio
        profile.save(
            update_fields=[
                "display_name",
                "profile_photo",
                "profile_image",
                "profile_storage_path",
                "country",
                "age",
                "bio",
                "updated_at",
            ]
        )
        messages.success(request, "Profile updated.")
        return redirect("dashboard")

    verified_submissions = request.user.submission_set.filter(status=Submission.STATUS_VERIFIED)
    pending_submissions = request.user.submission_set.filter(status=Submission.STATUS_PENDING)
    unverified_submissions = request.user.submission_set.filter(status=Submission.STATUS_UNVERIFIED)
    rejected_submissions = request.user.submission_set.filter(status=Submission.STATUS_REJECTED)
    best_submission = get_best_verified_submission_for_user(request.user)
    first_submission = request.user.submission_set.order_by("created_at").first()
    current_rank = None
    current_tier = get_rank_tier(0)

    if best_submission:
        current_rank = get_official_rank_for_submission(best_submission)
        current_tier = best_submission.rank_tier

    weeks_active = 0
    if first_submission:
        weeks_active = max(1, ((timezone.now() - first_submission.created_at).days // 7) + 1)

    ensure_system_workout_templates()
    workouts = request.user.workouts.prefetch_related("exercises").order_by("-created_at")
    active_workout_session = request.user.workout_sessions.filter(status=WorkoutSession.STATUS_ACTIVE).select_related("workout").prefetch_related("exercise_sessions").first()
    progress_summary = get_progress_summary(verified_submissions)
    recommendation = get_daily_suggestion(profile, verified_submissions.count(), workouts.count())
    active_goals = request.user.goals.filter(is_active=True)[:5]
    current_pr = best_submission.reps if best_submission else 0
    completed_goals = [
        goal
        for goal in active_goals
        if (
            (goal.goal_type == Goal.GOAL_PUSHUPS and current_pr >= goal.target_value)
            or (goal.goal_type == Goal.GOAL_RANK and current_pr >= goal.target_value)
        )
    ]
    history_submissions = paginate_items(request, request.user.submission_set.order_by("-created_at"), per_page=5)
    workout_page = paginate_items(request, workouts, per_page=5, page_param="workout_page")
    profile_completion, profile_completion_percent = profile_completion_items(request.user)

    context = {
        "profile": profile,
        "best_submission": best_submission,
        "current_pr": current_pr,
        "all_time_pr": current_pr,
        "current_rank": current_rank,
        "current_tier": current_tier,
        "rank_movement": "New season baseline",
        "total_submissions": request.user.submission_set.count(),
        "total_verified": verified_submissions.count(),
        "total_pending": pending_submissions.count(),
        "total_unverified": unverified_submissions.count(),
        "weeks_active": weeks_active,
        "verified_streak": get_current_streak(verified_submissions),
        "pending_submissions": pending_submissions.order_by("-created_at"),
        "unverified_submissions": unverified_submissions.order_by("-created_at"),
        "history_submissions": history_submissions,
        "history_submission_pages": history_submissions.paginator.get_elided_page_range(
            number=history_submissions.number,
            on_each_side=1,
            on_ends=1,
        ),
        "rejected_count": rejected_submissions.count(),
        "progress_data": get_progress_data(verified_submissions),
        "progress_summary": progress_summary,
        "country_choices": COUNTRY_CHOICES,
        "badges": profile.earned_badges,
        "followers_count": request.user.follower_links.count(),
        "following_count": request.user.following_links.count(),
        "workouts": workout_page,
        "workout_pages": workout_page.paginator.get_elided_page_range(
            number=workout_page.number,
            on_each_side=1,
            on_ends=1,
        ),
        "active_workout_session": active_workout_session,
        "active_goals": active_goals,
        "completed_goals": completed_goals,
        "rank_goal_options": [
            {
                "value": tier["min_reps"],
                "label": tier["name"],
                "distance": max(0, tier["min_reps"] - (best_submission.reps if best_submission else 0)),
            }
            for tier in RANK_TIERS
        ],
        "daily_suggestion": recommendation,
        "profile_completion": profile_completion,
        "profile_completion_percent": profile_completion_percent,
        "onboarding_checklist": build_onboarding_checklist(request.user),
        "next_action": build_next_action(request.user),
        "profile_share_message": get_profile_share_message(profile, request),
        "pr_share_message": get_pr_share_message(profile, request),
    }
    return render(request, "dashboard.html", context)


@require_POST
@login_required
def delete_goal(request, goal_id):
    goal = get_object_or_404(Goal, pk=goal_id, user=request.user)
    goal.delete()
    messages.success(request, "Goal deleted.")
    return redirect("dashboard")


def profiles(request):
    query = (request.GET.get("q") or "").strip()
    profiles_with_scores = Profile.objects.all().order_by(
        F("current_rank").asc(nulls_last=True), "-personal_best_reps", "display_name"
    )
    if query:
        profiles_with_scores = profiles_with_scores.filter(
            Q(display_name__icontains=query)
            | Q(user__username__icontains=query)
            | Q(country__icontains=query)
        )
    return render(
        request,
        "profiles.html",
        {
            "profiles": paginate_items(request, profiles_with_scores, per_page=10),
            "query": query,
        },
    )


def athlete_profile(request, slug):
    profile = get_object_or_404(Profile, slug=slug)
    verified_submissions = profile.user.submission_set.filter(status=Submission.STATUS_VERIFIED)
    best_submission = get_best_verified_submission_for_user(profile.user)
    profile.refresh_verified_stats()
    profile_description = (
        f"{profile.display_name} has a verified Earned Club push-up PR of "
        f"{profile.personal_best_reps} reps"
        + (f" and is ranked #{profile.current_rank}" if profile.current_rank else "")
        + "."
    )
    is_following = False
    compare_profile = None
    comparison = None
    if request.user.is_authenticated:
        is_following = Follow.objects.filter(follower=request.user, following=profile.user).exists()
        if request.user != profile.user:
            my_profile = request.user.profile
            my_best = get_best_verified_submission_for_user(request.user)
            compare_profile = my_profile
            comparison = {
                "my_reps": my_profile.personal_best_reps,
                "their_reps": profile.personal_best_reps,
                "rep_delta": my_profile.personal_best_reps - profile.personal_best_reps,
                "my_rank": get_official_rank_for_submission(my_best) if my_best else None,
                "their_rank": profile.current_rank,
            }
    verified_history = paginate_items(request, verified_submissions.order_by("-created_at"), per_page=5)
    context = {
        "profile": profile,
        "best_submission": best_submission,
        "current_tier": best_submission.rank_tier if best_submission else get_rank_tier(0),
        "verified_submissions": verified_history,
        "verified_history_pages": verified_history.paginator.get_elided_page_range(
            number=verified_history.number,
            on_each_side=1,
            on_ends=1,
        ),
        "progress_data": get_progress_data(verified_submissions),
        "profile_description": profile_description,
        "profile_schema_json": json_ld(build_profile_schema(profile, best_submission)),
        "profile_og_image": build_public_url(profile.profile_image_url) if profile.profile_image_url and profile.profile_image_url.startswith("/") else (profile.profile_image_url or ""),
        "badges": profile.earned_badges,
        "followers_count": profile.user.follower_links.count(),
        "following_count": profile.user.following_links.count(),
        "public_workouts": profile.user.workouts.filter(is_public=True, highlighted_on_profile=False).prefetch_related("exercises")[:4],
        "highlighted_workout": profile.user.workouts.filter(is_public=True, highlighted_on_profile=True).prefetch_related("exercises").first(),
        "public_goals": profile.user.goals.filter(is_active=True, is_public=True)[:3],
        "is_following": is_following,
        "compare_profile": compare_profile,
        "comparison": comparison,
        "profile_share_message": get_profile_share_message(profile, request),
        "pr_share_message": get_pr_share_message(profile, request),
    }
    return render(request, "athlete_profile.html", context)


def social_list(request, slug, kind):
    profile = get_object_or_404(Profile, slug=slug)
    if kind == "following":
        users = User.objects.filter(follower_links__follower=profile.user).select_related("profile").order_by("profile__display_name")
        title = f"{profile.display_name} follows"
    elif kind == "followers":
        users = User.objects.filter(following_links__following=profile.user).select_related("profile").order_by("profile__display_name")
        title = f"{profile.display_name}'s followers"
    else:
        return redirect("athlete_profile", slug=profile.slug)
    return render(request, "social_list.html", {"profile": profile, "users": users, "kind": kind, "title": title})


def comparison(request, left, right):
    left_profile = get_object_or_404(Profile, slug=left)
    right_profile = get_object_or_404(Profile, slug=right)
    left_best = get_best_verified_submission_for_user(left_profile.user)
    right_best = get_best_verified_submission_for_user(right_profile.user)
    return render(
        request,
        "comparison.html",
        {
            "left_profile": left_profile,
            "right_profile": right_profile,
            "left_best": left_best,
            "right_best": right_best,
            "left_tier": left_best.rank_tier if left_best else get_rank_tier(0),
            "right_tier": right_best.rank_tier if right_best else get_rank_tier(0),
            "rep_delta": left_profile.personal_best_reps - right_profile.personal_best_reps,
        },
    )


@require_POST
@login_required
def toggle_follow(request, slug):
    profile = get_object_or_404(Profile, slug=slug)
    if profile.user == request.user:
        messages.error(request, "You cannot follow your own profile.")
        return redirect("athlete_profile", slug=slug)
    follow, created = Follow.objects.get_or_create(follower=request.user, following=profile.user)
    if created:
        messages.success(request, f"You are now following {profile.display_name}.")
    else:
        follow.delete()
        messages.info(request, f"You unfollowed {profile.display_name}.")
    return redirect("athlete_profile", slug=slug)


def challenge(request):
    verified_submissions = get_official_verified_submissions()
    context = {
        "rank_tiers": RANK_TIERS,
        "verified_count": len(verified_submissions),
        "leaderboard_preview": build_leaderboard_rows(list(public_submission_queryset())[:3]),
        "form_data": request.GET,
        "show_submit_help": False,
    }
    if request.user.is_authenticated:
        context["profile"] = request.user.profile
        context["active_submission"] = blocking_submission_queryset().filter(user=request.user).order_by("-created_at").first()

    if request.method == "POST":
        name = (request.POST.get("name") or "").strip()
        email = (request.POST.get("email") or "").strip().lower()
        reps = (request.POST.get("reps") or "").strip()
        video_link = (request.POST.get("video_link") or "").strip()
        video_file = request.FILES.get("video_file")

        if request.user.is_authenticated:
            name = user_display_name(request.user)
            email = request.user.email

        if request.POST.get("website"):
            messages.success(request, "Submission received. If it passes review, it will appear on the leaderboard.")
            return redirect("challenge")

        if not name or not reps or (not request.user.is_authenticated and not email):
            messages.error(request, "Please fill in your name, email, and reps before submitting.")
            context["form_data"] = request.POST
            context["show_submit_help"] = True
            return render(request, "challenge.html", context)

        try:
            reps_value = int(reps)
        except ValueError:
            messages.error(request, "Reps must be a whole number.")
            context["form_data"] = request.POST
            context["show_submit_help"] = True
            return render(request, "challenge.html", context)

        if reps_value <= 0:
            messages.error(request, "Reps must be greater than zero.")
            context["form_data"] = request.POST
            context["show_submit_help"] = True
            return render(request, "challenge.html", context)

        if not request.user.is_authenticated and reps_value > 40:
            messages.error(request, "Anonymous submissions are capped at 40 push-ups. Log in and add video proof to submit more.")
            context["form_data"] = request.POST
            context["show_submit_help"] = True
            return render(request, "challenge.html", context)

        if request.user.is_authenticated and reps_value > 60 and not (video_link or video_file):
            messages.error(request, "Scores above 60 need video proof.")
            context["form_data"] = request.POST
            context["show_submit_help"] = True
            return render(request, "challenge.html", context)

        active_filter = blocking_submission_queryset()
        if request.user.is_authenticated:
            active_submission = active_filter.filter(user=request.user).first()
        else:
            active_submission = active_filter.filter(email=email).first()

        if active_submission:
            if active_submission.status == Submission.STATUS_UNVERIFIED and (video_link or video_file):
                proof_blocker = find_proof_link_blocker(video_link, exclude_pk=active_submission.pk)
                if proof_blocker:
                    messages.error(request, proof_blocker)
                    context["form_data"] = request.POST
                    context["active_submission"] = active_submission
                    context["show_submit_help"] = True
                    return render(request, "challenge.html", context)
                active_submission.name = name
                active_submission.email = email
                active_submission.reps = reps_value
                active_submission.video_link = video_link
                if video_file:
                    stored_video = store_submission_video(active_submission, video_file)
                    active_submission.video_storage_path = stored_video["storage_path"]
                    active_submission.video_file = stored_video["local_file"] or ""
                else:
                    active_submission.video_storage_path = ""
                    active_submission.video_file = ""
                active_submission.status = Submission.STATUS_PENDING
                active_submission.verified = False
                active_submission.save(
                    update_fields=[
                        "name",
                        "email",
                        "reps",
                        "video_link",
                        "video_storage_path",
                        "video_file",
                        "status",
                        "verified",
                    ]
                )
                create_verification_event(active_submission, VerificationEvent.ACTION_PROOF_ADDED)
                notify_admin_submission(active_submission, "Proof was added to an existing result.")
                estimated_position = estimate_verified_position(reps_value)
                send_submission_notification(
                    active_submission,
                    "Earned Club proof received",
                    (
                        f"Your proof for {active_submission.reps} reps was added and is now waiting for review. "
                        f"If verified, it would currently rank #{estimated_position}."
                    ),
                )
                messages.success(
                    request,
                    f"Proof added. If verified, this result would currently rank #{estimated_position} on the verified leaderboard.",
                )
                messages.info(request, "Next: retest your strict push-ups in 14 days or start a support workout today.")
                return redirect("challenge")

            messages.error(
                request,
                "You already have an active submission. Add proof to your current entry or wait until it is reviewed before submitting again.",
            )
            context["form_data"] = request.POST
            context["active_submission"] = active_submission
            context["show_submit_help"] = True
            return render(request, "challenge.html", context)

        blocker = find_submission_blocker(request, name, email, reps_value, video_link)
        if blocker == "silent":
            messages.success(request, "Submission received. If it passes review, it will appear on the leaderboard.")
            return redirect("challenge")
        if blocker:
            messages.error(request, blocker)
            context["form_data"] = request.POST
            context["show_submit_help"] = True
            return render(request, "challenge.html", context)

        estimated_position = estimate_verified_position(reps_value)
        submission = Submission.objects.create(
            user=request.user if request.user.is_authenticated else None,
            name=name,
            email=email,
            reps=reps_value,
            video_link=video_link,
            status=Submission.STATUS_PENDING if (video_link or video_file) else Submission.STATUS_UNVERIFIED,
        )
        if video_file:
            stored_video = store_submission_video(submission, video_file)
            submission.video_storage_path = stored_video["storage_path"]
            submission.video_file = stored_video["local_file"] or ""
            submission.status = Submission.STATUS_PENDING
            submission.save(update_fields=["video_storage_path", "video_file", "status"])

        create_verification_event(submission, VerificationEvent.ACTION_SUBMITTED)
        notify_admin_submission(submission, "A new result was submitted.")
        send_submission_notification(
            submission,
            "Earned Club submission received",
            (
                f"Your Earned Club submission for {submission.reps} reps was received. "
                + (
                    f"It is waiting for verification and would currently rank #{estimated_position} if approved."
                    if submission.has_proof else
                    "Upload proof from your profile dashboard to move it into review."
                )
            ),
        )

        for subscriber in NewsletterSubscriber.objects.exclude(email=email)[:50]:
            send_mail(
                "New EarnedClub challenge result",
                f"{name} just submitted {reps_value} push-ups. Check the leaderboard to see if you can beat it.",
                getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@earnedclub.club"),
                [subscriber.email],
                fail_silently=True,
            )

        messages.success(
            request,
            (
                f"Submission received. If verified, this result would currently rank #{estimated_position} on the verified leaderboard."
                if submission.has_proof else
                "Submission saved as unverified. Upload a proof video from your profile to move it into pending review."
            ),
        )
        messages.info(request, "Next: open your dashboard to track review status, then retest your strict push-ups in 14 days.")
        return redirect("challenge")

    return render(request, "challenge.html", context)


@require_POST
@login_required
def add_submission_proof(request, submission_id):
    submission = get_object_or_404(Submission, pk=submission_id, user=request.user)
    video_link = (request.POST.get("video_link") or "").strip()
    video_file = request.FILES.get("video_file")

    if submission.status != Submission.STATUS_UNVERIFIED:
        messages.error(request, "Proof can only be added to unverified submissions.")
        return redirect("dashboard")

    if pending_submission_queryset().filter(user=request.user).exclude(pk=submission.pk).exists():
        messages.error(request, "You already have a submission waiting for verification.")
        return redirect("dashboard")

    if not video_link and not video_file:
        messages.error(request, "Upload a proof video file.")
        return redirect("dashboard")

    proof_blocker = find_proof_link_blocker(video_link, exclude_pk=submission.pk)
    if proof_blocker:
        messages.error(request, proof_blocker)
        return redirect("dashboard")

    submission.video_link = video_link
    if video_file:
        stored_video = store_submission_video(submission, video_file)
        submission.video_storage_path = stored_video["storage_path"]
        submission.video_file = stored_video["local_file"] or ""
    submission.status = Submission.STATUS_PENDING
    submission.verified = False
    submission.save(update_fields=["video_link", "video_storage_path", "video_file", "status", "verified"])
    create_verification_event(submission, VerificationEvent.ACTION_PROOF_ADDED)
    notify_admin_submission(submission, "Proof was added from the dashboard.")
    send_submission_notification(
        submission,
        "Earned Club proof received",
        f"Your proof video for {submission.reps} reps was added. The submission is now waiting for review.",
    )
    messages.success(request, "Proof added. Your submission is back in pending review.")
    return redirect("dashboard")


@require_POST
@login_required
def delete_submission(request, submission_id):
    submission = get_object_or_404(Submission, pk=submission_id, user=request.user)
    if submission.status == Submission.STATUS_VERIFIED:
        messages.error(request, "Verified attempts stay in the official record. Ask admin if something is wrong.")
        return redirect("dashboard")
    submission.delete()
    messages.success(request, "Attempt deleted.")
    return redirect("dashboard")


def is_app_admin(user):
    return user.is_authenticated and user.is_staff


@user_passes_test(is_app_admin, login_url="login")
def admin_menu(request):
    recent_errors = []
    for path in ("runserver.err.log",):
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as handle:
                recent_errors = [line.strip() for line in handle.readlines()[-5:] if line.strip()]
        except OSError:
            recent_errors = []
    return render(
        request,
        "admin_menu.html",
        {
            "pending_count": pending_submission_queryset().count(),
            "subscriber_count": NewsletterSubscriber.objects.count(),
            "prompt_count": ContentEnginePrompt.objects.count(),
            "site_health": {
                "email_backend": settings.EMAIL_BACKEND,
                "default_from_email": settings.DEFAULT_FROM_EMAIL,
                "supabase_storage": "Enabled" if settings.SUPABASE_STORAGE_ENABLED else "Disabled",
                "debug": "On" if settings.DEBUG else "Off",
                "recent_errors": recent_errors,
            },
        },
    )


@user_passes_test(is_app_admin, login_url="login")
def admin_review(request):
    status_filter = (request.GET.get("status") or "pending").strip()
    proof_filter = (request.GET.get("proof") or "all").strip()
    order_filter = (request.GET.get("order") or "newest").strip()
    query = (request.GET.get("q") or "").strip()

    submissions = Submission.objects.select_related("user", "user__profile").prefetch_related("verification_events")
    if status_filter != "all":
        submissions = submissions.filter(status=status_filter)
    if proof_filter == "with-proof":
        submissions = submissions.filter(Q(video_link__gt="") | Q(video_storage_path__gt="") | Q(video_file__gt=""))
    elif proof_filter == "needs-proof":
        submissions = submissions.filter(video_link="", video_storage_path="", video_file="")
    if query:
        submissions = submissions.filter(Q(name__icontains=query) | Q(email__icontains=query) | Q(user__username__icontains=query))

    ordering = {
        "newest": "-created_at",
        "oldest": "created_at",
        "highest": "-reps",
        "lowest": "reps",
    }.get(order_filter, "-created_at")
    review_submissions = submissions.order_by(ordering, "-created_at")[:50]
    return render(
        request,
        "admin_review.html",
        {
            "review_submissions": review_submissions,
            "status_filter": status_filter,
            "proof_filter": proof_filter,
            "order_filter": order_filter,
            "query": query,
            "pending_count": pending_submission_queryset().count(),
            "review_count": submissions.count(),
        },
    )


@require_POST
@user_passes_test(is_app_admin, login_url="login")
def review_submission(request, submission_id):
    submission = get_object_or_404(Submission, pk=submission_id)
    action = request.POST.get("action")
    review_note = (request.POST.get("review_note") or "").strip()

    if action == "approve":
        submission.status = Submission.STATUS_VERIFIED
        submission.verified = True
        submission.save(update_fields=["status", "verified"])
        create_verification_event(
            submission,
            VerificationEvent.ACTION_APPROVED,
            reviewer=request.user,
            note=review_note,
        )
        send_submission_notification(
            submission,
            "Earned Club submission approved",
            f"Your {submission.reps}-rep submission was approved. Your verified result is now live on Earned Club.",
        )
        if submission.user_id:
            rank = get_official_rank_for_submission(submission)
            notify_user_email(
                submission.user,
                "Your EarnedClub result was verified",
                f"Your {submission.reps}-rep result was verified. Your official rank is currently #{rank}.",
            )
        messages.success(request, f"{submission.name} was approved with {submission.reps} reps.")
    elif action == "reject":
        submission.status = Submission.STATUS_REJECTED
        submission.verified = False
        submission.save(update_fields=["status", "verified"])
        create_verification_event(
            submission,
            VerificationEvent.ACTION_REJECTED,
            reviewer=request.user,
            note=review_note,
        )
        send_submission_notification(
            submission,
            "Earned Club submission update",
            (
                f"Your {submission.reps}-rep submission was reviewed but not approved."
                + (f" Reviewer note: {review_note}" if review_note else " You can submit again with clearer proof.")
            ),
        )
        if submission.user_id:
            notify_user_email(
                submission.user,
                "Your EarnedClub result needs another try",
                "Your latest result was not verified. Check the rules and submit a clearer proof video when you are ready.",
            )
        messages.info(request, f"{submission.name} was rejected.")
    elif action == "mark_pending":
        if not submission.has_proof:
            messages.error(request, "This submission cannot move to pending without proof.")
        else:
            submission.status = Submission.STATUS_PENDING
            submission.verified = False
            submission.save(update_fields=["status", "verified"])
            messages.success(request, f"{submission.name} was moved back to pending review.")
    elif action == "mark_unverified":
        submission.status = Submission.STATUS_UNVERIFIED
        submission.verified = False
        submission.save(update_fields=["status", "verified"])
        messages.success(request, f"{submission.name} was marked unverified.")
    elif action == "delete":
        submission.delete()
        messages.info(request, f"{submission.name}'s submission was deleted.")
    else:
        messages.error(request, "Unknown review action.")

    params = build_querystring(
        status=request.POST.get("status_filter") or Submission.STATUS_PENDING,
        proof=request.POST.get("proof_filter") or "all",
        order=request.POST.get("order_filter") or "newest",
        q=request.POST.get("q") or "",
    )
    redirect_url = reverse("admin_review")
    if params:
        redirect_url = f"{redirect_url}?{params}"
    return redirect(redirect_url)


def newsletter_signup(request):
    if request.method != "POST":
        return redirect("home")

    email = (request.POST.get("email") or "").strip().lower()
    if not email:
        messages.error(request, "Enter your email to join the newsletter.")
        return redirect("home")

    try:
        NewsletterSubscriber.objects.create(email=email)
        messages.success(
            request,
            "You are in. Weekly updates will focus on leaderboard movement, new challenges, and future drops.",
        )
    except IntegrityError:
        messages.info(request, "This email is already on the newsletter list.")

    return redirect("home")


@user_passes_test(is_app_admin, login_url="login")
def newsletter_admin(request):
    default_week = NewsletterCampaign.objects.order_by("-week_number").values_list("week_number", flat=True).first() or 0
    week_number = parse_positive_int(request.POST.get("week_number") if request.method == "POST" else request.GET.get("week")) or default_week + 1
    draft = build_newsletter_draft(week_number)

    if request.method == "POST":
        form_type = request.POST.get("form_type") or "campaign"
        if form_type == "segment":
            name = (request.POST.get("segment_name") or "").strip()
            subscriber_ids = request.POST.getlist("subscriber_ids")
            if not name:
                messages.error(request, "Segment name is required.")
                return redirect("newsletter_admin")
            segment, _created = NewsletterSegment.objects.get_or_create(name=name)
            segment.subscribers.set(NewsletterSubscriber.objects.filter(id__in=subscriber_ids))
            messages.success(request, f"{segment.name} saved with {segment.subscribers.count()} subscriber(s).")
            return redirect("newsletter_admin")

        subject = (request.POST.get("subject") or draft["subject"]).strip()
        body = (request.POST.get("body") or draft["body"]).strip()
        if not subject or not body:
            messages.error(request, "Subject and body are required.")
            return redirect("newsletter_admin")

        campaign = NewsletterCampaign.objects.create(week_number=week_number, subject=subject, body=body)
        segment_id = request.POST.get("segment_id")
        auto_segment = request.POST.get("auto_segment")
        segment = NewsletterSegment.objects.filter(pk=segment_id).prefetch_related("subscribers").first() if segment_id else None
        if auto_segment:
            recipient_qs = newsletter_auto_segment_subscribers(auto_segment)
        else:
            recipient_qs = segment.subscribers.all() if segment else NewsletterSubscriber.objects.all()
        recipients = list(recipient_qs.order_by("email"))
        if request.POST.get("action") == "preview":
            messages.info(request, f"Preview: {len([subscriber for subscriber in recipients if subscriber.is_subscribed])} subscribed recipient(s).")
            return render(
                request,
                "newsletter_admin.html",
                {
                    "week_number": week_number,
                    "draft_subject": subject,
                    "draft_body": body,
                    "subscriber_count": NewsletterSubscriber.objects.count(),
                    "subscribers": NewsletterSubscriber.objects.prefetch_related("segments").order_by("email"),
                    "segments": NewsletterSegment.objects.prefetch_related("subscribers"),
                    "campaigns": NewsletterCampaign.objects.all()[:8],
                    "week_choices": range(1, 13),
                    "preview_subject": subject,
                    "preview_body": body,
                    "preview_count": len([subscriber for subscriber in recipients if subscriber.is_subscribed]),
                },
            )
        if request.POST.get("action") == "send" and recipients:
            sent_count = send_newsletter_to_subscribers(subject, body, recipients, campaign=campaign, request=request)
            campaign.sent_at = timezone.now()
            campaign.sent_count = sent_count
            campaign.save(update_fields=["sent_at", "sent_count"])
            destination = f" segment {segment.name}" if segment else (f" auto filter {auto_segment}" if auto_segment else "")
            messages.success(request, f"Newsletter sent to {sent_count} subscriber(s){destination}.")
        elif request.POST.get("action") == "send":
            messages.info(request, "Newsletter draft saved. There are no subscribers yet.")
        else:
            messages.success(request, "Newsletter draft saved.")
        return redirect("newsletter_admin")

    campaigns = NewsletterCampaign.objects.all()[:8]
    subscribers = NewsletterSubscriber.objects.prefetch_related("segments").order_by("email")
    segments = NewsletterSegment.objects.prefetch_related("subscribers")
    auto_segments = {
        "Verified users": NewsletterSubscriber.objects.filter(email__in=Submission.objects.filter(status=Submission.STATUS_VERIFIED).exclude(email="").values("email")).count(),
        "Unverified users": NewsletterSubscriber.objects.filter(email__in=Submission.objects.filter(status=Submission.STATUS_UNVERIFIED).exclude(email="").values("email")).count(),
        "No submission yet": NewsletterSubscriber.objects.exclude(email__in=Submission.objects.exclude(email="").values("email")).count(),
        "High rank users": NewsletterSubscriber.objects.filter(email__in=Submission.objects.filter(status=Submission.STATUS_VERIFIED, reps__gte=60).exclude(email="").values("email")).count(),
    }
    return render(
        request,
        "newsletter_admin.html",
        {
            "week_number": week_number,
            "draft_subject": draft["subject"],
            "draft_body": draft["body"],
            "subscriber_count": NewsletterSubscriber.objects.count(),
            "subscribers": subscribers,
            "segments": segments,
            "auto_segments": auto_segments,
            "campaigns": campaigns,
            "week_choices": range(1, 13),
        },
    )


@user_passes_test(is_app_admin, login_url="login")
def newsletter_subscriber_detail(request, subscriber_id):
    subscriber = get_object_or_404(NewsletterSubscriber.objects.prefetch_related("segments"), pk=subscriber_id)
    default_week = NewsletterCampaign.objects.order_by("-week_number").values_list("week_number", flat=True).first() or 0
    draft = build_newsletter_draft(default_week + 1)

    if request.method == "POST":
        subject = (request.POST.get("subject") or "").strip()
        body = (request.POST.get("body") or "").strip()
        if not subject or not body:
            messages.error(request, "Subject and body are required.")
            return redirect("newsletter_subscriber_detail", subscriber_id=subscriber.id)
        sent_count = send_newsletter_to_subscribers(subject, body, [subscriber], request=request)
        NewsletterCampaign.objects.create(
            week_number=default_week + 1,
            subject=subject,
            body=body,
            sent_at=timezone.now(),
            sent_count=sent_count,
        )
        messages.success(request, f"Email sent to {subscriber.email}.")
        return redirect("newsletter_subscriber_detail", subscriber_id=subscriber.id)

    return render(
        request,
        "newsletter_subscriber_detail.html",
        {
            "subscriber": subscriber,
            "draft_subject": draft["subject"],
            "draft_body": draft["body"],
            "segments": NewsletterSegment.objects.prefetch_related("subscribers"),
            "send_events": subscriber.send_events.select_related("campaign")[:10],
        },
    )


def newsletter_unsubscribe(request, token):
    subscriber = get_object_or_404(NewsletterSubscriber, unsubscribe_token=token)
    subscriber.unsubscribe()
    messages.success(request, "You have been unsubscribed from Earned Club emails.")
    return redirect("home")


def calculators(request):
    prompts = ContentEnginePrompt.objects.filter(is_active=True)
    return render(request, "calculators.html", {"rank_tiers": RANK_TIERS, "content_prompts": prompts})


def workout_detail(request, slug):
    workout = get_object_or_404(Workout.objects.prefetch_related("exercises").select_related("user", "user__profile"), slug=slug)
    if not workout.is_public and (not request.user.is_authenticated or workout.user != request.user):
        messages.error(request, "This workout is private.")
        return redirect("home")
    return render(request, "workout_detail.html", {"workout": workout})


@login_required
def workouts(request):
    ensure_system_workout_templates()
    if request.method == "POST":
        form_type = request.POST.get("form_type", "workout")
        if form_type == "generated_workout":
            workout = create_generated_workout(request)
            session = start_workout_session_for_user(request.user, workout)
            messages.success(request, f"{workout.title} generated and started.")
            return redirect("workout_session_detail", session_id=session.id)

        if form_type == "quick_result":
            exercise_name = (request.POST.get("quick_exercise") or "Quick result").strip()
            default_exercise = get_default_exercise(exercise_name)
            exercise_type = default_exercise.get("type", WorkoutExercise.TYPE_STRENGTH)
            reps = parse_positive_int(request.POST.get("quick_reps"))
            sets = parse_positive_int(request.POST.get("quick_sets")) or 1
            seconds = parse_positive_int(request.POST.get("quick_seconds"))
            if exercise_type == WorkoutExercise.TYPE_CARDIO and not seconds:
                messages.error(request, "Cardio quick logs need a time.")
                return redirect("workouts")
            if exercise_type != WorkoutExercise.TYPE_CARDIO and not reps:
                messages.error(request, "Strength quick logs need reps.")
                return redirect("workouts")
            workout = Workout.objects.create(user=request.user, title=f"Quick log - {exercise_name}")
            WorkoutExercise.objects.create(
                workout=workout,
                name=exercise_name,
                exercise_type=exercise_type,
                body_part=(request.POST.get("quick_body_part") or default_exercise.get("body_part", "")).strip(),
                sets=sets,
                reps=reps,
                seconds=seconds,
            )
            messages.success(request, "Quick log saved.")
            return redirect("workouts")

        workout, error = create_workout_from_request(request)
        if error:
            messages.error(request, error)
        else:
            if request.POST.get("start_now") == "1":
                session = start_workout_session_for_user(request.user, workout)
                messages.success(request, f"{workout.title} started.")
                return redirect("workout_session_detail", session_id=session.id)
            messages.success(request, "Workout saved.")
        return redirect("workouts")

    workout_query = (request.GET.get("q") or "").strip()
    workouts_qs = request.user.workouts.prefetch_related("exercises").order_by("-created_at")
    if workout_query:
        workouts_qs = workouts_qs.filter(
            Q(title__icontains=workout_query)
            | Q(notes__icontains=workout_query)
            | Q(exercises__name__icontains=workout_query)
            | Q(exercises__body_part__icontains=workout_query)
        ).distinct()
    workout_page = paginate_items(request, workouts_qs, per_page=5)
    templates = WorkoutTemplate.objects.filter(Q(user=request.user) | Q(is_system=True)).order_by("-is_system", "difficulty", "name")
    user_reps = request.user.profile.personal_best_reps
    recommended_difficulty = WorkoutTemplate.DIFFICULTY_BEGINNER
    if user_reps >= 60:
        recommended_difficulty = WorkoutTemplate.DIFFICULTY_ADVANCED
    elif user_reps >= 20:
        recommended_difficulty = WorkoutTemplate.DIFFICULTY_INTERMEDIATE
    recommended_cards = build_template_cards(list(templates.filter(is_system=True, difficulty=recommended_difficulty)))
    random.shuffle(recommended_cards)
    recommended_cards = recommended_cards[:3]
    template_cards = build_template_cards(list(templates.filter(is_system=True)))
    random.shuffle(template_cards)
    return render(
        request,
        "workouts.html",
        {
            "workouts": workout_page,
            "workout_query": workout_query,
            "workout_pages": workout_page.paginator.get_elided_page_range(
                number=workout_page.number,
                on_each_side=1,
                on_ends=1,
            ),
            "workout_templates": templates,
            "recommended_templates": recommended_cards,
            "template_cards": template_cards,
            "template_payload": build_template_payload(template_cards),
            "recommended_difficulty": recommended_difficulty,
            "default_exercises": DEFAULT_EXERCISES,
            "body_parts": BODY_PARTS,
            "active_workout_session": request.user.workout_sessions.filter(status=WorkoutSession.STATUS_ACTIVE).select_related("workout").first(),
        },
    )


@require_POST
@login_required
def start_workout(request):
    workout_id = request.POST.get("workout_id")
    template_id = request.POST.get("template_id")
    source_workout = None

    if workout_id:
        source_workout = get_object_or_404(
            Workout.objects.prefetch_related("exercises").select_related("user"),
            pk=workout_id,
        )
        if source_workout.user != request.user and not source_workout.is_public:
            messages.error(request, "You cannot start that private workout.")
            return redirect("workouts")
        workout = source_workout if source_workout.user == request.user else clone_workout(source_workout, user=request.user)
    elif template_id:
        template = get_object_or_404(
            WorkoutTemplate.objects.filter(Q(user=request.user) | Q(is_system=True)),
            pk=template_id,
        )
        workout = create_workout_from_template(template, request.user)
    else:
        messages.error(request, "Choose a workout to start.")
        return redirect("workouts")

    session = start_workout_session_for_user(request.user, workout)
    messages.success(request, f"{workout.title} started.")
    return redirect("workout_session_detail", session_id=session.id)


@login_required
def workout_session_detail(request, session_id):
    session = get_object_or_404(
        WorkoutSession.objects.select_related("workout", "user").prefetch_related("exercise_sessions"),
        pk=session_id,
        user=request.user,
    )
    exercises = list(session.exercise_sessions.all())
    completed_sets = sum(exercise.completed_sets for exercise in exercises)
    target_sets = sum(exercise.target_sets for exercise in exercises)
    target_reps = sum((exercise.target_reps or 0) * exercise.completed_sets for exercise in exercises)
    target_seconds = sum((exercise.target_seconds or 0) * exercise.completed_sets for exercise in exercises)
    body_parts = sorted({exercise.body_part for exercise in exercises if exercise.body_part})
    elapsed_seconds = 0
    if session.started_at:
        end_time = session.completed_at or timezone.now()
        elapsed_seconds = max(0, int((end_time - session.started_at).total_seconds()))
    return render(
        request,
        "workout_session.html",
        {
            "session": session,
            "completed_sets": completed_sets,
            "target_sets": target_sets,
            "session_reps": target_reps,
            "session_seconds": target_seconds,
            "trained_body_parts": body_parts,
            "elapsed_seconds": elapsed_seconds,
        },
    )


@require_POST
@login_required
def finish_workout_session(request, session_id):
    session = get_object_or_404(WorkoutSession.objects.prefetch_related("exercise_sessions"), pk=session_id, user=request.user)
    if session.status == WorkoutSession.STATUS_ACTIVE:
        session.exercise_sessions.update(completed_sets=F("target_sets"))
        session.status = WorkoutSession.STATUS_COMPLETED
        session.completed_at = timezone.now()
        session.save(update_fields=["status", "completed_at"])
        messages.success(request, f"{session.workout.title} completed.")
        messages.info(request, "Retest reminder: try a fresh strict push-up test in 14 days.")
    else:
        messages.info(request, "This workout is already completed.")
    return redirect("workout_session_detail", session_id=session.id)


@require_POST
@login_required
def update_workout_session(request, session_id, exercise_id):
    session = get_object_or_404(WorkoutSession, pk=session_id, user=request.user)
    exercise = get_object_or_404(WorkoutSessionExercise, pk=exercise_id, session=session)
    action = request.POST.get("action")

    if session.status != WorkoutSession.STATUS_ACTIVE:
        messages.info(request, "This workout is already completed.")
        return redirect("workout_session_detail", session_id=session.id)

    if action == "complete_set":
        exercise.completed_sets = min(exercise.target_sets, exercise.completed_sets + 1)
        exercise.save(update_fields=["completed_sets"])
    elif action == "undo_set":
        exercise.completed_sets = max(0, exercise.completed_sets - 1)
        exercise.save(update_fields=["completed_sets"])

    if not session.exercise_sessions.filter(completed_sets__lt=F("target_sets")).exists():
        session.status = WorkoutSession.STATUS_COMPLETED
        session.completed_at = timezone.now()
        session.save(update_fields=["status", "completed_at"])
        messages.success(request, f"{session.workout.title} completed.")

    return redirect("workout_session_detail", session_id=session.id)


@require_POST
@login_required
def duplicate_workout(request, workout_id):
    source = get_object_or_404(Workout.objects.prefetch_related("exercises"), pk=workout_id, user=request.user)
    workout = clone_workout(source, user=request.user, title=f"{source.title} copy", is_public=False)
    messages.success(request, "Workout duplicated.")
    return redirect("workouts")


@require_POST
@login_required
def quick_add_last_workout(request):
    source = request.user.workouts.prefetch_related("exercises").first()
    if not source:
        messages.error(request, "You do not have a previous workout to quick add yet.")
        return redirect("workouts")
    clone_workout(source, user=request.user, is_public=False)
    messages.success(request, "Last workout added again.")
    return redirect("workouts")


@require_POST
@login_required
def delete_workout(request, workout_id):
    workout = get_object_or_404(Workout, pk=workout_id, user=request.user)
    workout.delete()
    messages.success(request, "Workout deleted.")
    return redirect(request.POST.get("next") or "workouts")


@require_POST
@login_required
def toggle_highlight_workout(request, workout_id):
    workout = get_object_or_404(Workout, pk=workout_id, user=request.user)
    if not workout.is_public:
        messages.error(request, "Only public workouts can be highlighted.")
        return redirect("workouts")
    request.user.workouts.update(highlighted_on_profile=False)
    workout.highlighted_on_profile = True
    workout.save(update_fields=["highlighted_on_profile"])
    messages.success(request, "Workout highlighted on your profile.")
    return redirect("workouts")


@user_passes_test(is_app_admin, login_url="login")
def content_engine_admin(request):
    if request.method == "POST":
        title = (request.POST.get("title") or "").strip()
        engine_type = request.POST.get("engine_type") or ContentEnginePrompt.ENGINE_LEVEL
        prompt = (request.POST.get("prompt") or "").strip()
        cta = (request.POST.get("cta") or "").strip()
        if not title or not prompt:
            messages.error(request, "Title and prompt are required.")
            return redirect("content_engine_admin")
        ContentEnginePrompt.objects.create(title=title, engine_type=engine_type, prompt=prompt, cta=cta)
        messages.success(request, "Content engine prompt created.")
        return redirect("content_engine_admin")

    prompts = ContentEnginePrompt.objects.order_by("engine_type", "-created_at")
    return render(request, "content_engine_admin.html", {"prompts": prompts, "engine_choices": ContentEnginePrompt.ENGINE_CHOICES})


def privacy(request):
    return render(request, "privacy.html")


def terms(request):
    return render(request, "terms.html")

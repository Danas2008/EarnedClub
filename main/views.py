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
from django.core.serializers.json import DjangoJSONEncoder
from django.http import HttpResponse
from django.db import IntegrityError, transaction
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
    DISCIPLINE_CONFIG,
    DISCIPLINE_PUSHUPS,
    HYBRID_RANKS,
    Submission,
    VerificationEvent,
    Workout,
    WorkoutExercise,
    WorkoutSession,
    WorkoutSessionExercise,
    WorkoutTemplate,
    get_best_verified_submission_for_user,
    get_hybrid_rank,
    get_discipline_config,
    format_duration,
    get_official_rank_for_submission,
    get_official_verified_submissions,
    get_rank_tier,
    get_submission_identity,
    normalize_discipline,
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
EMAIL_SYSTEM_DISABLED_MESSAGE = (
    "Email delivery is temporarily disabled. Newsletter and notification data is kept for later reactivation."
)
logger = logging.getLogger(__name__)


SITEMAP_NAMESPACE = "http://www.sitemaps.org/schemas/sitemap/0.9"
register_namespace("", SITEMAP_NAMESPACE)

SITEMAP_STATIC_PAGES = [
    {"view_name": "home", "changefreq": "daily", "priority": "1.0"},
    {"view_name": "rank", "changefreq": "daily", "priority": "0.95"},
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
HYBRID_LEADERBOARD_CONFIG = {
    "key": "hybrid",
    "label": "Hybrid Score",
    "title": "Hybrid Leaderboard",
    "short_label": "Hybrid",
    "score_type": "hybrid",
    "unit": "points",
    "higher_is_better": True,
    "input_label": "Hybrid Score",
    "placeholder": "",
}


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


def build_hybrid_breakdown(user):
    rows = []
    verified_points = []
    verified_submissions = user.submission_set.filter(status=Submission.STATUS_VERIFIED).select_related("user")
    all_submissions = user.submission_set.all()
    for config in DISCIPLINE_CONFIG.values():
        best_submission = None
        for submission in verified_submissions:
            if submission.normalized_discipline != config["key"]:
                continue
            if best_submission is None or is_better_submission(submission, best_submission):
                best_submission = submission
        latest_unverified = (
            all_submissions.filter(discipline=config["key"])
            .exclude(status=Submission.STATUS_VERIFIED)
            .order_by("-created_at")
            .first()
        )
        points = best_submission.hybrid_points if best_submission else 0
        if best_submission:
            verified_points.append(points)
        intensity = "empty"
        if points >= 900:
            intensity = "legend"
        elif points >= 750:
            intensity = "elite"
        elif points >= 550:
            intensity = "advanced"
        elif points >= 350:
            intensity = "intermediate"
        elif points > 0:
            intensity = "starter"
        rows.append(
            {
                "discipline": config,
                "submission": best_submission,
                "latest_unverified": latest_unverified,
                "points": points,
                "intensity": intensity,
                "progress_percent": min(100, round((points / 1000) * 100)),
                "display_score": best_submission.display_score if best_submission else "-",
                "status": "Verified" if best_submission else "Missing",
                "rank_name": best_submission.rank_name if best_submission else "No verified result",
                "action_label": "Improve" if best_submission else ("Add proof" if latest_unverified and latest_unverified.status == Submission.STATUS_UNVERIFIED else "Submit result"),
                "action_url": reverse("dashboard") if latest_unverified and latest_unverified.status == Submission.STATUS_UNVERIFIED else f"{reverse('challenge')}?discipline={config['key']}#submit-form-top",
            }
        )
    hybrid_score = round(sum(verified_points) / len(verified_points)) if verified_points else 0
    verified_rows = [row for row in rows if row["submission"]]
    best_row = max(verified_rows, key=lambda row: row["points"], default=None)
    weakest_row = min(verified_rows, key=lambda row: row["points"], default=None)
    missing_row = next((row for row in rows if not row["submission"]), None)
    return {
        "score": hybrid_score,
        "rank": get_hybrid_rank(hybrid_score),
        "breakdown": rows,
        "best_discipline": best_row,
        "weakest_discipline": weakest_row or missing_row,
        "next_target_points": max(0, next((rank["min_score"] for rank in HYBRID_RANKS if rank["min_score"] > hybrid_score), 1000) - hybrid_score),
        "verified_count": len(verified_points),
        "max_disciplines": len(DISCIPLINE_CONFIG),
        "completion_percent": round((len(verified_points) / len(DISCIPLINE_CONFIG)) * 100),
    }


DISCIPLINE_TIER_TARGETS = {
    Submission.DISCIPLINE_PUSHUPS: [
        {"name": "Intermediate", "value": 20},
        {"name": "Advanced", "value": 40},
        {"name": "Elite", "value": 60},
        {"name": "Earned Legend", "value": 80},
    ],
    Submission.DISCIPLINE_PULLUPS: [
        {"name": "Intermediate", "value": 5},
        {"name": "Advanced", "value": 10},
        {"name": "Elite", "value": 20},
        {"name": "Earned Legend", "value": 30},
    ],
    Submission.DISCIPLINE_5K: [
        {"name": "Intermediate", "value": 30 * 60},
        {"name": "Advanced", "value": 25 * 60},
        {"name": "Elite", "value": 18 * 60},
        {"name": "Earned Legend", "value": 16 * 60},
    ],
    Submission.DISCIPLINE_10K: [
        {"name": "Intermediate", "value": 60 * 60},
        {"name": "Advanced", "value": 50 * 60},
        {"name": "Elite", "value": 38 * 60},
        {"name": "Earned Legend", "value": 32 * 60},
    ],
}


def get_next_discipline_target(current_value, discipline):
    config = get_discipline_config(discipline)
    targets = DISCIPLINE_TIER_TARGETS[config["key"]]
    if current_value is None:
        return targets[0]
    if config["higher_is_better"]:
        return next((target for target in targets if target["value"] > current_value), None)
    return next((target for target in targets if target["value"] < current_value), None)


def format_goal_value(value, discipline):
    config = get_discipline_config(discipline)
    return format_duration(value) if config["score_type"] == "time" else str(value)


def build_improvement_recommendation(user, hybrid_summary=None):
    summary = hybrid_summary or build_hybrid_breakdown(user)
    candidates = []
    for row in summary["breakdown"]:
        discipline = row["discipline"]["key"]
        current = row["submission"].reps if row["submission"] else None
        target = get_next_discipline_target(current, discipline)
        if not target:
            continue
        config = row["discipline"]
        if current is None:
            text = f"Submit your first verified {config['short_label']} result to increase Hybrid completion."
            priority = -1
        elif config["higher_is_better"]:
            text = f"Go from {current} to {target['value']} {config['unit']} to reach {target['name']}."
            priority = target["value"] - current
        else:
            text = f"Improve your {config['short_label']} from {format_duration(current)} to {format_duration(target['value'])} to reach {target['name']}."
            priority = current - target["value"]
        candidates.append(
            {
                "discipline": config,
                "current": current,
                "target": target,
                "text": text,
                "priority": priority,
                "url": f"{reverse('challenge')}?discipline={discipline}#submit-form-top",
            }
        )
    if not candidates:
        return {
            "label": "Defend your Hybrid status",
            "text": "You have cleared the current discipline tier targets. Keep improving any verified lane.",
            "url": reverse("challenge"),
        }
    missing = [item for item in candidates if item["current"] is None]
    if missing:
        item = missing[0]
        return {
            "label": f"Complete {item['discipline']['short_label']}",
            "text": item["text"],
            "url": item["url"],
        }
    weakest_key = summary.get("weakest_discipline", {}).get("discipline", {}).get("key")
    item = next((candidate for candidate in candidates if candidate["discipline"]["key"] == weakest_key), min(candidates, key=lambda candidate: candidate["priority"]))
    return {
        "label": f"Fastest path: {item['discipline']['short_label']}",
        "text": item["text"],
        "url": item["url"],
    }


def build_goal_rank_options(user, hybrid_summary):
    options = {}
    for key, config in DISCIPLINE_CONFIG.items():
        current = get_goal_current_value(user, key, hybrid_summary=hybrid_summary)
        rows = []
        for target in DISCIPLINE_TIER_TARGETS[key]:
            if current is None:
                available = True
            elif config["higher_is_better"]:
                available = target["value"] > current
            else:
                available = target["value"] < current
            if available:
                rows.append(
                    {
                        "value": target["value"],
                        "label": target["name"],
                        "display": format_goal_value(target["value"], key),
                    }
                )
        options[key] = rows
    current_score = hybrid_summary["score"]
    options[Goal.GOAL_HYBRID_SCORE] = [
        {"value": rank["min_score"], "label": rank["name"], "display": f"{rank['min_score']} score"}
        for rank in HYBRID_RANKS
        if rank["min_score"] > current_score
    ]
    return options


def build_hybrid_leaderboard_rows(query=""):
    rows = []
    users = User.objects.filter(submission__status=Submission.STATUS_VERIFIED).select_related("profile").distinct()
    if query:
        users = users.filter(
            Q(username__icontains=query)
            | Q(profile__display_name__icontains=query)
            | Q(profile__country__icontains=query)
        )
    for user in users:
        summary = build_hybrid_breakdown(user)
        if summary["score"] <= 0:
            continue
        rows.append(
            {
                "position": 0,
                "medal_place": None,
                "user": user,
                "profile": getattr(user, "profile", None),
                "hybrid_score": summary["score"],
                "hybrid_rank": summary["rank"],
                "breakdown": summary["breakdown"],
                "verified_count": summary["verified_count"],
            }
        )
    rows = sorted(rows, key=lambda row: (-row["hybrid_score"], getattr(row["profile"], "display_name", row["user"].username)))
    for index, row in enumerate(rows, start=1):
        row["position"] = index
        row["medal_place"] = index if index <= 3 else None
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
    safe_send_mail(subject, message, [user.email])


def safe_send_mail(subject, message, recipients, from_email=None):
    safe_send_mail.last_error = EMAIL_SYSTEM_DISABLED_MESSAGE
    logger.info("Email delivery disabled for subject %s to %s.", subject, recipients)
    return 0


def get_email_delivery_issue():
    return EMAIL_SYSTEM_DISABLED_MESSAGE


def get_configured_email_delivery_issue():
    backend = getattr(settings, "EMAIL_BACKEND", "")
    if backend == "django.core.mail.backends.console.EmailBackend":
        return "EMAIL_BACKEND is console-only, so messages are printed to logs instead of delivered."
    if backend == "django.core.mail.backends.smtp.EmailBackend":
        if not getattr(settings, "EMAIL_HOST", "") or settings.EMAIL_HOST == "localhost":
            return "EMAIL_HOST is not configured for SMTP delivery."
        if not getattr(settings, "EMAIL_HOST_USER", ""):
            return "EMAIL_HOST_USER is not configured."
        if not getattr(settings, "EMAIL_HOST_PASSWORD", ""):
            return "EMAIL_HOST_PASSWORD is not configured."
        if settings.EMAIL_USE_TLS and settings.EMAIL_USE_SSL:
            return "EMAIL_USE_TLS and EMAIL_USE_SSL cannot both be enabled."
        if "gmail.com" in settings.EMAIL_HOST.lower() and settings.EMAIL_PORT == 587 and not settings.EMAIL_USE_TLS:
            return "Gmail SMTP on port 587 requires EMAIL_USE_TLS=True."
        if "gmail.com" in settings.EMAIL_HOST.lower() and settings.EMAIL_PORT == 465 and not settings.EMAIL_USE_SSL:
            return "Gmail SMTP on port 465 requires EMAIL_USE_SSL=True."
    return ""


def notify_admin_submission(submission, event_label):
    proof = submission.proof_url or "No proof attached"
    return safe_send_mail(
        f"Earned Club result submitted: {submission.discipline_label} {submission.display_score}",
        (
            f"{event_label}\n\n"
            f"Name: {submission.name}\n"
            f"Email: {submission.email or 'No email'}\n"
            f"Discipline: {submission.discipline_label}\n"
            f"Result: {submission.display_score}\n"
            f"Status: {submission.public_status_label}\n"
            f"Proof: {proof}"
        ),
        [ADMIN_SUBMISSION_EMAIL],
    )


def get_profile_share_message(profile, request):
    url = request.build_absolute_uri(reverse("athlete_profile", args=[profile.slug]))
    return f"Check out {profile.display_name}'s EarnedClub profile: {url}"


def get_pr_share_message(profile, request):
    url = request.build_absolute_uri(reverse("athlete_profile", args=[profile.slug]))
    return f"Hey, I am building my verified Hybrid Score on earnedclub.club. Can you beat it? {url}"


def build_submission_success(submission, request):
    discipline_config = get_discipline_config(submission.discipline)
    leaderboard_url = f"{reverse('leaderboard')}?discipline={submission.discipline}#full-leaderboard"
    register_params = urlencode({"name": submission.name, "email": submission.email}) if submission.email else urlencode({"name": submission.name})
    proof_params = urlencode({
        "discipline": submission.discipline,
        "score": submission.display_score if discipline_config["score_type"] == "time" else submission.reps,
        "name": submission.name,
        "email": submission.email,
    })
    profile_url = reverse("athlete_profile", args=[submission.user.profile.slug]) if submission.user_id else ""
    return {
        "submission": submission,
        "is_official_pending": submission.has_proof,
        "leaderboard_url": leaderboard_url,
        "profile_url": profile_url,
        "register_url": f"{reverse('register')}?{register_params}" if register_params else reverse("register"),
        "proof_url": reverse("dashboard") if submission.user_id else f"{reverse('challenge')}?{proof_params}#submit-form-top",
        "share_text": (
            f"I submitted {submission.discipline_label} {submission.display_score} on Earned Club. "
            f"Proof makes it official. {request.build_absolute_uri(leaderboard_url)}"
        ),
    }


def get_daily_suggestion(profile, verified_count, workout_count):
    quotes = [
        "Small proof beats loud claims.",
        "Make today's result clean enough to count.",
        "Consistency is the quiet part of status.",
        "Train the performance you want verified.",
        "Good training is boring until the numbers move.",
        "Win today's focused session.",
    ]
    if profile.personal_best_reps >= 80:
        tasks = [
            "Keep today submax: push, pull, core, then stop before form breaks.",
            "Do a quality density session with no failed reps.",
            "Train recovery and shoulder stability so your next test is sharp.",
            "Run a balanced full-body workout instead of another max-test day.",
        ]
    elif profile.personal_best_reps >= 60:
        tasks = [
            "Do 4 controlled strength sets at about 65% effort.",
            "Pair pushing with rows and core so your shoulders stay balanced.",
            "Use an advanced workout today, but leave one rep in reserve.",
            "Retest one strong set only if you feel sharp.",
        ]
    elif profile.personal_best_reps >= 40:
        tasks = [
            "Do 4 controlled sets at 60-70% of your current best.",
            "Add one pull exercise today.",
            "Try a clean pace set before you submit again.",
            "Start your highlighted workout and finish every set.",
            "Use a shorter recovery workout and protect form.",
        ]
    elif workout_count:
        tasks = [
            "Repeat your last workout and add one clean rep.",
            "Quick log one exercise now.",
            "Do push, pull, legs, and core.",
            "Start one saved workout and complete every planned set.",
            "Pick a random recommended session and finish it today.",
        ]
    else:
        tasks = [
            "Submit your first performance today.",
            "Start with a balanced training session.",
            "Log one honest result.",
            "Open a beginner workout and finish the first round.",
            "Build one simple 15-minute session and complete it.",
        ]
    task = random.choice(tasks)
    quote = random.choice(quotes)
    return f"{task} {quote}"


def verified_submission_queryset():
    return Submission.objects.filter(status=Submission.STATUS_VERIFIED)


def public_submission_queryset(since=None, discipline=DISCIPLINE_PUSHUPS):
    discipline = normalize_discipline(discipline)
    visible = {}
    if since:
        verified_pool = (
            Submission.objects.filter(status=Submission.STATUS_VERIFIED, discipline=discipline, created_at__gte=since)
            .select_related("user", "user__profile")
            .order_by("-reps" if get_discipline_config(discipline)["higher_is_better"] else "reps", "created_at")
        )
    else:
        verified_pool = get_official_verified_submissions(discipline)
    for submission in verified_pool:
        identity = get_submission_identity(submission)
        current = visible.get(identity)
        if current is None or is_better_submission(submission, current):
            visible[identity] = submission

    pending_submissions = (
        Submission.objects.filter(status=Submission.STATUS_PENDING, discipline=discipline)
        .select_related("user", "user__profile")
        .order_by("-reps" if get_discipline_config(discipline)["higher_is_better"] else "reps", "created_at")
    )
    if since:
        pending_submissions = pending_submissions.filter(created_at__gte=since)
    for submission in pending_submissions:
        identity = get_submission_identity(submission)
        current = visible.get(identity)
        if current is None or is_better_submission(submission, current):
            visible[identity] = submission

    unverified_submissions = (
        Submission.objects.filter(status=Submission.STATUS_UNVERIFIED, discipline=discipline)
        .select_related("user", "user__profile")
        .order_by("-reps" if get_discipline_config(discipline)["higher_is_better"] else "reps", "created_at")
    )
    if since:
        unverified_submissions = unverified_submissions.filter(created_at__gte=since)
    for submission in unverified_submissions:
        identity = get_submission_identity(submission)
        current = visible.get(identity)
        if current is None or is_better_submission(submission, current):
            visible[identity] = submission

    return sort_submissions_for_discipline(visible.values(), discipline)


def pending_submission_queryset(discipline=None):
    submissions = Submission.objects.filter(status=Submission.STATUS_PENDING)
    if discipline:
        submissions = submissions.filter(discipline=normalize_discipline(discipline))
    return submissions


def active_submission_queryset(discipline=None):
    submissions = Submission.objects.filter(status__in=[Submission.STATUS_UNVERIFIED, Submission.STATUS_PENDING])
    if discipline:
        submissions = submissions.filter(discipline=normalize_discipline(discipline))
    return submissions


def blocking_submission_queryset(discipline=None):
    recent_cutoff = timezone.now() - timedelta(minutes=1)
    submissions = Submission.objects.filter(
        Q(status=Submission.STATUS_PENDING) |
        Q(status=Submission.STATUS_UNVERIFIED, created_at__gte=recent_cutoff)
    )
    if discipline:
        submissions = submissions.filter(discipline=normalize_discipline(discipline))
    return submissions


def is_better_submission(candidate, current):
    if candidate.discipline_config["higher_is_better"]:
        return candidate.reps > current.reps
    return candidate.reps < current.reps


def sort_submissions_for_discipline(submissions, discipline):
    reverse = get_discipline_config(discipline)["higher_is_better"]
    return sorted(submissions, key=lambda item: (item.reps if not reverse else -item.reps, item.created_at))


def estimate_verified_position(score, discipline=DISCIPLINE_PUSHUPS):
    if get_discipline_config(discipline)["higher_is_better"]:
        equal_or_better = sum(1 for item in get_official_verified_submissions(discipline) if item.reps >= score)
    else:
        equal_or_better = sum(1 for item in get_official_verified_submissions(discipline) if item.reps <= score)
    return equal_or_better + 1


def get_leaderboard_discipline(request, discipline_key=None):
    requested = (discipline_key or request.GET.get("discipline") or "hybrid").strip().lower()
    if requested == "hybrid":
        return HYBRID_LEADERBOARD_CONFIG
    return get_discipline_config(requested)


def parse_duration_to_seconds(value):
    raw = (value or "").strip()
    if not raw:
        raise ValueError("Enter a time.")
    parts = raw.split(":")
    if len(parts) not in {2, 3}:
        raise ValueError("Use HH:MM:SS or MM:SS, like 00:21:34 or 21:34.")
    if not all(part.isdigit() for part in parts):
        raise ValueError("Use numbers only in HH:MM:SS or MM:SS format.")
    if len(parts) == 2:
        hours = 0
        minutes, seconds = (int(part) for part in parts)
    else:
        hours, minutes, seconds = (int(part) for part in parts)
    if minutes > 59 or seconds > 59 or (hours == 0 and minutes == 0 and seconds == 0):
        raise ValueError("Use a valid time like 00:21:34 or 21:34.")
    return hours * 3600 + minutes * 60 + seconds


def parse_submission_score(raw_value, discipline):
    discipline = normalize_discipline(discipline)
    config = get_discipline_config(discipline)
    if config["score_type"] == "time":
        return parse_duration_to_seconds(raw_value)
    reps_value = int((raw_value or "").strip())
    if reps_value <= 0:
        raise ValueError("Reps must be greater than zero.")
    return reps_value


def validate_submission_score(score, discipline):
    discipline = normalize_discipline(discipline)
    config = get_discipline_config(discipline)
    if not config.get("world_record"):
        return ""
    if config["higher_is_better"]:
        if score > config["world_record"]:
            return f"{config['label']} cannot be above the current listed world-record benchmark of {config['world_record']} reps."
    elif score < config["world_record"]:
        return f"{config['label']} cannot be faster than the current listed world-record benchmark of {format_duration(config['world_record'])}."
    return ""


def is_elite_score(score, discipline):
    discipline = normalize_discipline(discipline)
    config = get_discipline_config(discipline)
    threshold = config["elite_threshold"]
    if config["higher_is_better"]:
        return score >= threshold
    return score < threshold


def requires_proof(score, discipline):
    return is_elite_score(score, discipline)


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


def build_performance_progress_series(user):
    submissions = list(user.submission_set.filter(status=Submission.STATUS_VERIFIED).order_by("created_at", "id"))
    best_by_discipline = {}
    series = {
        "hybrid": {
            "label": "Hybrid Score",
            "unit": "pts",
            "higher_is_better": True,
            "points": [],
        }
    }
    for config in DISCIPLINE_CONFIG.values():
        series[config["key"]] = {
            "label": config["short_label"],
            "unit": "time" if config["score_type"] == "time" else "reps",
            "higher_is_better": config["higher_is_better"],
            "points": [],
        }

    for submission in submissions:
        key = submission.normalized_discipline
        current_best = best_by_discipline.get(key)
        if current_best is None or is_better_submission(submission, current_best):
            best_by_discipline[key] = submission

        verified_points = [item.hybrid_points for item in best_by_discipline.values()]
        hybrid_score = round(sum(verified_points) / len(verified_points)) if verified_points else 0
        label = submission.created_at.strftime("%b %d, %H:%M")
        date = submission.created_at.strftime("%Y-%m-%d")
        series["hybrid"]["points"].append(
            {
                "date": date,
                "label": label,
                "value": hybrid_score,
                "display": f"{hybrid_score} pts",
            }
        )
        best_submission = best_by_discipline[key]
        series[key]["points"].append(
            {
                "date": date,
                "label": label,
                "value": best_submission.reps,
                "display": best_submission.display_score,
            }
        )
    return series


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


def get_leaderboard_submissions(mode_key, discipline=DISCIPLINE_PUSHUPS):
    discipline = normalize_discipline(discipline)
    order = "-reps" if get_discipline_config(discipline)["higher_is_better"] else "reps"
    if mode_key == "verified":
        return get_official_verified_submissions(discipline)
    if mode_key == "week":
        return public_submission_queryset(since=get_weekly_window(), discipline=discipline)
    if mode_key == "month":
        return public_submission_queryset(since=get_monthly_window(), discipline=discipline)
    if mode_key == "pending":
        return pending_submission_queryset(discipline).select_related("user", "user__profile").order_by(order, "created_at")
    if mode_key == "unverified":
        return Submission.objects.filter(status=Submission.STATUS_UNVERIFIED, discipline=discipline).select_related("user", "user__profile").order_by(order, "created_at")
    return public_submission_queryset(discipline=discipline)


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
    safe_send_mail(subject, message, [recipient])


def safe_post_submission_side_effects(submission, event_action, event_label, email_subject, email_body, request=None):
    admin_notified = 0
    try:
        create_verification_event(submission, event_action)
    except Exception:
        logger.exception("Verification event creation failed for submission %s", submission.pk)
        if request:
            messages.warning(request, "Your result was saved, but the audit event could not be written. Staff can still review it.")
    try:
        admin_notified = notify_admin_submission(submission, event_label)
    except Exception:
        logger.exception("Admin notification failed for submission %s", submission.pk)
    try:
        send_submission_notification(submission, email_subject, email_body)
    except Exception:
        logger.exception("Submitter notification failed for submission %s", submission.pk)
    return admin_notified


def find_submission_blocker(request, name, email, reps, discipline=DISCIPLINE_PUSHUPS):
    if request.POST.get("website"):
        return "silent"

    cooldown = timezone.now() - timedelta(minutes=1)
    recent_duplicate = Submission.objects.filter(created_at__gte=cooldown, reps=reps, discipline=discipline)
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
            f"{profile.display_name} has a verified Earned Club athlete profile "
            "with public performance results."
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
            f"Verified {best_submission.discipline_label} result: {best_submission.display_score}",
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
        {"label": "Get first verified performance", "done": user.submission_set.filter(status=Submission.STATUS_VERIFIED).exists(), "url": reverse("challenge")},
        {"label": "Publish one workout", "done": user.workouts.filter(is_public=True).exists(), "url": reverse("workouts")},
    ]
    completed = sum(1 for item in items if item["done"])
    return items, round((completed / len(items)) * 100)


def build_onboarding_checklist(user):
    return [
        {"label": "Run the Hybrid Score check", "done": user.submission_set.exists(), "url": reverse("level_test")},
        {"label": "Submit proof", "done": user.submission_set.filter(status__in=[Submission.STATUS_PENDING, Submission.STATUS_VERIFIED]).exists(), "url": reverse("challenge")},
        {"label": "Create a workout", "done": user.workouts.exists(), "url": reverse("workouts")},
        {"label": "Set a goal", "done": user.goals.exists(), "url": reverse("dashboard")},
        {"label": "Share your profile", "done": bool(user.profile.personal_best_reps), "url": reverse("athlete_profile", args=[user.profile.slug])},
    ]


def build_next_action(user):
    if not user.submission_set.exists():
        return {"label": "Submit a performance", "url": reverse("challenge"), "text": "Choose a discipline and start your Hybrid Score."}
    if user.submission_set.filter(status=Submission.STATUS_UNVERIFIED).exists():
        return {"label": "Add proof", "url": reverse("dashboard"), "text": "Add proof so your performance can be reviewed."}
    if not user.workouts.exists():
        return {"label": "Create workout", "url": reverse("workouts"), "text": "Build a training plan for your next verified result."}
    if not user.goals.exists():
        return {"label": "Set goal", "url": reverse("dashboard"), "text": "Pick the next performance target you want to reach."}
    return {"label": "Share profile", "url": reverse("athlete_profile", args=[user.profile.slug]), "text": "Share your public profile and keep building proof."}


def get_goal_current_value(user, goal_type, hybrid_summary=None):
    if goal_type == Goal.GOAL_HYBRID_SCORE:
        return (hybrid_summary or build_hybrid_breakdown(user))["score"]
    if goal_type == Goal.GOAL_RANK:
        best = get_best_verified_submission_for_user(user, Submission.DISCIPLINE_PUSHUPS)
        return best.reps if best else 0
    if goal_type in {Goal.GOAL_PUSHUPS, Goal.GOAL_PULLUPS, Goal.GOAL_5K, Goal.GOAL_10K}:
        best = get_best_verified_submission_for_user(user, goal_type)
        return best.reps if best else None
    return 0


def is_goal_completed(user, goal, hybrid_summary=None):
    current = get_goal_current_value(user, goal.goal_type, hybrid_summary=hybrid_summary)
    if current is None:
        return False
    if goal.is_time_goal:
        return current <= goal.target_value
    return current >= goal.target_value


def build_goal_rows(user, goals, hybrid_summary):
    rows = []
    for goal in goals:
        current = get_goal_current_value(user, goal.goal_type, hybrid_summary=hybrid_summary)
        if goal.is_time_goal:
            current_display = format_duration(current) if current else "No verified time"
            progress = min(100, round((goal.target_value / current) * 100)) if current else 0
        elif goal.goal_type == Goal.GOAL_HYBRID_SCORE:
            current_display = f"{current} score"
            progress = min(100, round((current / goal.target_value) * 100)) if goal.target_value else 0
        else:
            current_display = f"{current or 0} reps"
            progress = min(100, round(((current or 0) / goal.target_value) * 100)) if goal.target_value else 0
        rows.append(
            {
                "goal": goal,
                "completed": is_goal_completed(user, goal, hybrid_summary=hybrid_summary),
                "current_display": current_display,
                "progress_percent": progress,
            }
        )
    return rows


def build_dashboard_next_action(user, hybrid_summary):
    unverified = user.submission_set.filter(status=Submission.STATUS_UNVERIFIED).order_by("-created_at").first()
    if unverified:
        return {
            "label": f"Add proof to {unverified.discipline_label}",
            "text": f"Proof makes your {unverified.display_score} result count toward official status.",
            "url": reverse("dashboard"),
        }
    missing = next((row for row in hybrid_summary["breakdown"] if not row["submission"]), None)
    if missing:
        return {
            "label": f"Submit your first {missing['discipline']['short_label']} result",
            "text": "Build your Hybrid Score by filling the empty discipline lanes.",
            "url": f"{reverse('challenge')}?discipline={missing['discipline']['key']}#submit-form-top",
        }
    next_points = hybrid_summary["next_target_points"]
    if next_points:
        return {
            "label": f"{next_points} points to the next Hybrid title",
            "text": "Improve your weakest discipline to move the overall score fastest.",
            "url": reverse("rank"),
        }
    weakest = hybrid_summary.get("weakest_discipline")
    if weakest:
        return {
            "label": f"Improve your {weakest['discipline']['short_label']}",
            "text": "Your weakest verified discipline is the fastest path to a higher Hybrid Score.",
            "url": f"{reverse('challenge')}?discipline={weakest['discipline']['key']}#submit-form-top",
        }
    return build_next_action(user)


def send_newsletter_to_subscribers(subject, body, subscribers, campaign=None, request=None):
    sent_count = 0
    failures = []
    for subscriber in subscribers:
        if not subscriber.is_subscribed:
            continue
        message = body
        if request:
            unsubscribe_url = request.build_absolute_uri(reverse("newsletter_unsubscribe", args=[subscriber.unsubscribe_token]))
            message = f"{body}\n\nUnsubscribe: {unsubscribe_url}"
        delivered = safe_send_mail(subject, message, [subscriber.email], from_email=getattr(settings, "NEWSLETTER_FROM_EMAIL", settings.DEFAULT_FROM_EMAIL))
        if delivered:
            sent_count += delivered
            NewsletterSendEvent.objects.create(subscriber=subscriber, campaign=campaign, subject=subject)
        else:
            error = getattr(safe_send_mail, "last_error", "") or "Unknown SMTP error"
            failures.append(f"{subscriber.email} ({error})")
    return sent_count, failures


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


def build_sitemap_xml(entries):
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
        "discipline_cards": DISCIPLINE_CONFIG.values(),
        "hybrid_top_five": build_hybrid_leaderboard_rows()[:5],
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


def rank(request):
    raw_scores = {
        Submission.DISCIPLINE_PUSHUPS: (request.GET.get("pushups") or request.GET.get("reps") or "").strip(),
        Submission.DISCIPLINE_PULLUPS: (request.GET.get("pullups") or "").strip(),
        Submission.DISCIPLINE_5K: (request.GET.get("run_5k") or request.GET.get("5k") or "").strip(),
        Submission.DISCIPLINE_10K: (request.GET.get("run_10k") or request.GET.get("10k") or "").strip(),
    }
    hybrid_breakdown = []
    points = []
    first_submit_params = None
    for config in DISCIPLINE_CONFIG.values():
        raw_value = raw_scores.get(config["key"], "")
        row = {"discipline": config, "raw_value": raw_value, "display_score": "-", "points": 0, "tier": None, "error": ""}
        if raw_value:
            try:
                score_value = parse_submission_score(raw_value, config["key"])
                score_error = validate_submission_score(score_value, config["key"])
                if score_error:
                    row["error"] = score_error
                else:
                    preview = Submission(discipline=config["key"], reps=score_value)
                    row.update(
                        {
                            "display_score": preview.display_score,
                            "points": preview.hybrid_points,
                            "tier": preview.rank_tier,
                        }
                    )
                    points.append(preview.hybrid_points)
                    if first_submit_params is None:
                        first_submit_params = urlencode({"discipline": config["key"], "score": raw_value})
            except ValueError as exc:
                row["error"] = str(exc) if config["score_type"] == "time" else "Enter reps as a whole number."
        hybrid_breakdown.append(row)
    hybrid_score = round(sum(points) / len(points)) if points else 0
    hybrid_estimate = {
        "score": hybrid_score,
        "rank": get_hybrid_rank(hybrid_score),
        "verified_count": len(points),
        "max_disciplines": len(DISCIPLINE_CONFIG),
        "completion_percent": round((len(points) / len(DISCIPLINE_CONFIG)) * 100),
        "breakdown": hybrid_breakdown,
    }
    submit_url = f"{reverse('challenge')}?{first_submit_params}#submit-form-top" if first_submit_params else f"{reverse('challenge')}#submit-form-top"

    return render(
        request,
        "rank.html",
        {
            "hybrid_estimate": hybrid_estimate,
            "submit_url": submit_url,
            "rank_tiers": RANK_TIERS,
            "discipline_cards": DISCIPLINE_CONFIG.values(),
            "has_rank_input": any(raw_scores.values()),
            "raw_scores": raw_scores,
        },
    )


def sitemap_xml(request):
    xml = build_sitemap_xml(build_sitemap_entries(request))
    return HttpResponse(xml, content_type="application/xml; charset=utf-8")


def sitemap_xsl(request):
    response = render(request, "sitemap.xsl", content_type="text/xsl; charset=utf-8")
    response["X-Robots-Tag"] = "noindex"
    return response



def robots_txt(request):
    lines = [
        "User-agent: *",
        "Allow: /",
        "Disallow: /admin/",
        f"Sitemap: {build_public_url(reverse('sitemap_xml'))}",
    ]
    return HttpResponse("\n".join(lines), content_type="text/plain")


def leaderboard(request, discipline_key=None):
    query = (request.GET.get("q") or "").strip()
    active_mode = get_leaderboard_mode(request)
    active_discipline = get_leaderboard_discipline(request, discipline_key)
    weekly_cutoff = get_weekly_window()
    monthly_cutoff = get_monthly_window()

    is_hybrid_leaderboard = active_discipline["key"] == "hybrid"
    if is_hybrid_leaderboard:
        leaderboard_rows = build_hybrid_leaderboard_rows(query)
        verified_count = len(leaderboard_rows)
        submission_count = len(leaderboard_rows)
        pending_count = pending_submission_queryset().count()
        weekly_count = len(leaderboard_rows)
    else:
        verified_submissions = get_official_verified_submissions(active_discipline["key"])
        public_submissions = list(get_leaderboard_submissions(active_mode["key"], active_discipline["key"]))
        public_submissions = search_submissions(public_submissions, query)
        leaderboard_rows = build_leaderboard_rows(public_submissions)
        verified_count = len(verified_submissions)
        submission_count = len(public_submissions)
        pending_count = pending_submission_queryset(active_discipline["key"]).count()
        weekly_count = len(public_submission_queryset(since=weekly_cutoff, discipline=active_discipline["key"]))

    leaderboard_page = paginate_items(request, leaderboard_rows, per_page=10)

    context = {
        "leaderboard_rows": leaderboard_page,
        "leaderboard_pages": leaderboard_page.paginator.get_elided_page_range(
            number=leaderboard_page.number,
            on_each_side=1,
            on_ends=1,
        ),
        "leaderboard_modes": LEADERBOARD_MODES,
        "discipline_cards": DISCIPLINE_CONFIG.values(),
        "hybrid_leaderboard": HYBRID_LEADERBOARD_CONFIG,
        "active_discipline": active_discipline,
        "is_hybrid_leaderboard": is_hybrid_leaderboard,
        "active_mode": active_mode,
        "weekly_cutoff": weekly_cutoff.isoformat(),
        "monthly_cutoff": monthly_cutoff.isoformat(),
        "rank_tiers": RANK_TIERS,
        "verified_count": verified_count,
        "submission_count": submission_count,
        "pending_count": pending_count,
        "weekly_count": weekly_count,
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
            goal_exercise = request.POST.get("goal_exercise")
            goal_kind = request.POST.get("goal_kind")
            goal_type = goal_exercise or request.POST.get("goal_type") or Goal.GOAL_PUSHUPS
            target_raw = request.POST.get("rank_target" if goal_kind == "rank" else "target_value")
            note = (request.POST.get("note") or "").strip()
            is_public = request.POST.get("is_public") == "on"
            try:
                if goal_type in {Goal.GOAL_5K, Goal.GOAL_10K}:
                    target_value = parse_duration_to_seconds(target_raw)
                else:
                    target_value = int(target_raw)
            except (TypeError, ValueError):
                messages.error(request, "Goal target must be a whole number or a valid time.")
                return redirect("dashboard")
            if target_value <= 0:
                messages.error(request, "Goal target must be greater than zero.")
                return redirect("dashboard")
            if goal_type in {Goal.GOAL_5K, Goal.GOAL_10K}:
                score_error = validate_submission_score(target_value, goal_type)
                if score_error:
                    messages.error(request, score_error)
                    return redirect("dashboard")
            hybrid_summary = build_hybrid_breakdown(request.user)
            current_value = get_goal_current_value(request.user, goal_type, hybrid_summary=hybrid_summary)
            if goal_kind == "rank":
                available_values = {
                    option["value"]
                    for option in build_goal_rank_options(request.user, hybrid_summary).get(goal_type, [])
                }
                if target_value not in available_values:
                    messages.error(request, "Choose a rank above your current level.")
                    return redirect("dashboard")
            elif current_value is not None:
                if goal_type in {Goal.GOAL_5K, Goal.GOAL_10K} and target_value >= current_value:
                    messages.error(request, "Running goals must be faster than your current verified best.")
                    return redirect("dashboard")
                if goal_type not in {Goal.GOAL_5K, Goal.GOAL_10K} and target_value <= current_value:
                    messages.error(request, "Goal target must be higher than your current verified best.")
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
    hybrid_summary = build_hybrid_breakdown(request.user)
    hybrid_rank_position = next(
        (row["position"] for row in build_hybrid_leaderboard_rows() if row["user"].id == request.user.id),
        None,
    )
    recommendation = get_daily_suggestion(profile, verified_submissions.count(), workouts.count())
    active_goals = list(request.user.goals.filter(is_active=True)[:5])
    current_pr = best_submission.reps if best_submission else 0
    goal_rows = build_goal_rows(request.user, active_goals, hybrid_summary)
    completed_goals = [row["goal"] for row in goal_rows if row["completed"]]
    history_submissions = paginate_items(request, request.user.submission_set.order_by("-created_at"), per_page=5)
    workout_page = paginate_items(request, workouts, per_page=5, page_param="workout_page")
    profile_completion, profile_completion_percent = profile_completion_items(request.user)
    onboarding_checklist = build_onboarding_checklist(request.user)
    show_onboarding = any(not item["done"] for item in onboarding_checklist)
    improvement_recommendation = build_improvement_recommendation(request.user, hybrid_summary)

    context = {
        "profile": profile,
        "best_submission": best_submission,
        "current_pr": current_pr,
        "all_time_pr": current_pr,
        "current_rank": current_rank,
        "current_tier": current_tier,
        "hybrid_summary": hybrid_summary,
        "hybrid_rank_position": hybrid_rank_position,
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
        "performance_progress": build_performance_progress_series(request.user),
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
        "goal_rows": goal_rows,
        "completed_goals": completed_goals,
        "goal_rank_options": build_goal_rank_options(request.user, hybrid_summary),
        "daily_suggestion": recommendation,
        "profile_completion": profile_completion,
        "profile_completion_percent": profile_completion_percent,
        "onboarding_checklist": onboarding_checklist,
        "show_onboarding": show_onboarding,
        "next_action": build_dashboard_next_action(request.user, hybrid_summary),
        "improvement_recommendation": improvement_recommendation,
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
    profiles_with_scores = Profile.objects.select_related("user").order_by("display_name")
    if query:
        profiles_with_scores = profiles_with_scores.filter(
            Q(display_name__icontains=query)
            | Q(user__username__icontains=query)
            | Q(country__icontains=query)
        )
    hybrid_positions = {row["user"].id: row["position"] for row in build_hybrid_leaderboard_rows()}
    profile_rows = [
        {
            "profile": profile,
            "hybrid_summary": build_hybrid_breakdown(profile.user),
            "hybrid_rank_position": hybrid_positions.get(profile.user_id),
        }
        for profile in profiles_with_scores
    ]
    return render(
        request,
        "profiles.html",
        {
            "profiles": paginate_items(request, profile_rows, per_page=10),
            "query": query,
        },
    )


def athlete_profile(request, slug):
    profile = get_object_or_404(Profile, slug=slug)
    verified_submissions = profile.user.submission_set.filter(status=Submission.STATUS_VERIFIED)
    best_submission = get_best_verified_submission_for_user(profile.user)
    profile.refresh_verified_stats()
    hybrid_summary = build_hybrid_breakdown(profile.user)
    hybrid_rank_position = next(
        (row["position"] for row in build_hybrid_leaderboard_rows() if row["user"].id == profile.user.id),
        None,
    )
    profile_description = (
        f"{profile.display_name} has an Earned Club Hybrid Score of "
        f"{hybrid_summary['score']}"
        + (f" and is ranked #{hybrid_rank_position} on the Hybrid Leaderboard" if hybrid_rank_position else "")
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
                "my_hybrid_score": build_hybrid_breakdown(request.user)["score"],
                "their_hybrid_score": hybrid_summary["score"],
                "score_delta": build_hybrid_breakdown(request.user)["score"] - hybrid_summary["score"],
            }
    verified_history = paginate_items(request, verified_submissions.order_by("-created_at"), per_page=5)
    public_progress_series = build_performance_progress_series(profile.user)
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
        "progress_data": public_progress_series.get("hybrid", {}).get("points", []),
        "profile_description": profile_description,
        "profile_schema_json": json_ld(build_profile_schema(profile, best_submission)),
        "hybrid_summary": hybrid_summary,
        "hybrid_rank_position": hybrid_rank_position,
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
    left_summary = build_hybrid_breakdown(left_profile.user)
    right_summary = build_hybrid_breakdown(right_profile.user)
    left_rank = next((row["position"] for row in build_hybrid_leaderboard_rows() if row["user"].id == left_profile.user_id), None)
    right_rank = next((row["position"] for row in build_hybrid_leaderboard_rows() if row["user"].id == right_profile.user_id), None)
    score_margin = abs(left_summary["score"] - right_summary["score"])
    completion_margin = abs(left_summary["verified_count"] - right_summary["verified_count"])
    if left_summary["score"] > right_summary["score"]:
        winner_profile = left_profile
        result_label = f"{left_profile.display_name} wins by {score_margin} Hybrid points"
    elif right_summary["score"] > left_summary["score"]:
        winner_profile = right_profile
        result_label = f"{right_profile.display_name} wins by {score_margin} Hybrid points"
    else:
        winner_profile = None
        result_label = "Dead even on Hybrid Score"
    return render(
        request,
        "comparison.html",
        {
            "left_profile": left_profile,
            "right_profile": right_profile,
            "left_summary": left_summary,
            "right_summary": right_summary,
            "left_rank": left_rank,
            "right_rank": right_rank,
            "score_delta": left_summary["score"] - right_summary["score"],
            "completion_delta": left_summary["verified_count"] - right_summary["verified_count"],
            "score_margin": score_margin,
            "completion_margin": completion_margin,
            "winner_profile": winner_profile,
            "result_label": result_label,
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
    selected_discipline = get_discipline_config((request.POST.get("discipline") if request.method == "POST" else request.GET.get("discipline")) or DISCIPLINE_PUSHUPS)
    context = {
        "rank_tiers": RANK_TIERS,
        "discipline_cards": DISCIPLINE_CONFIG.values(),
        "selected_discipline": selected_discipline,
        "verified_count": len(verified_submissions),
        "leaderboard_preview": build_leaderboard_rows(list(public_submission_queryset(discipline=selected_discipline["key"]))[:3]),
        "form_data": request.GET,
        "form_score": request.GET.get("score") or request.GET.get("reps") or "",
        "show_submit_help": False,
    }
    if request.user.is_authenticated:
        context["profile"] = request.user.profile
        context["active_submission"] = blocking_submission_queryset(selected_discipline["key"]).filter(user=request.user).order_by("-created_at").first()

    success_submission_id = request.session.pop("last_submission_id", None) if request.method == "GET" else None
    if success_submission_id:
        success_submission = Submission.objects.filter(pk=success_submission_id).select_related("user", "user__profile").first()
        if success_submission:
            context["submission_success"] = build_submission_success(success_submission, request)

    if request.method == "POST":
        name = (request.POST.get("name") or "").strip()
        email = (request.POST.get("email") or "").strip().lower()
        discipline = selected_discipline["key"]
        score_raw = (request.POST.get("score") or request.POST.get("reps") or "").strip()
        proof_link = (request.POST.get("proof_link") or "").strip()
        video_file = request.FILES.get("video_file")
        if selected_discipline["score_type"] != "time":
            proof_link = ""

        if request.user.is_authenticated:
            name = user_display_name(request.user)
            email = request.user.email

        if request.POST.get("website"):
            messages.success(request, "Submission received. If it passes review, it will appear on the leaderboard.")
            return redirect("challenge")

        if not name or not score_raw or (not request.user.is_authenticated and not email):
            messages.error(request, "Please fill in your name, email, and performance before submitting.")
            context["form_data"] = request.POST
            context["form_score"] = score_raw
            context["show_submit_help"] = True
            return render(request, "challenge.html", context)

        try:
            score_value = parse_submission_score(score_raw, discipline)
        except ValueError as exc:
            messages.error(request, str(exc) if selected_discipline["score_type"] == "time" else "Reps must be a whole number greater than zero.")
            context["form_data"] = request.POST
            context["form_score"] = score_raw
            context["show_submit_help"] = True
            return render(request, "challenge.html", context)

        score_error = validate_submission_score(score_value, discipline)
        if score_error:
            messages.error(request, score_error)
            context["form_data"] = request.POST
            context["form_score"] = score_raw
            context["show_submit_help"] = True
            return render(request, "challenge.html", context)

        if discipline == Submission.DISCIPLINE_PUSHUPS and not request.user.is_authenticated and score_value > 40:
            messages.error(request, "Anonymous submissions are capped at 40 push-ups. Log in and add video proof to submit more.")
            context["form_data"] = request.POST
            context["form_score"] = score_raw
            context["show_submit_help"] = True
            return render(request, "challenge.html", context)

        if requires_proof(score_value, discipline) and not (video_file or proof_link):
            messages.error(request, f"{selected_discipline['label']} elite-level results need proof before they can be submitted.")
            context["form_data"] = request.POST
            context["form_score"] = score_raw
            context["show_submit_help"] = True
            return render(request, "challenge.html", context)

        active_filter = blocking_submission_queryset(discipline)
        if request.user.is_authenticated:
            active_submission = active_filter.filter(user=request.user).first()
        else:
            active_submission = active_filter.filter(email=email).first()

        if active_submission:
            if active_submission.status == Submission.STATUS_UNVERIFIED and (video_file or proof_link):
                active_submission.name = name
                active_submission.email = email
                active_submission.discipline = discipline
                active_submission.reps = score_value
                active_submission.video_link = proof_link
                if video_file:
                    stored_video = store_submission_video(active_submission, video_file)
                    active_submission.video_storage_path = stored_video["storage_path"]
                    active_submission.video_file = stored_video["local_file"] or ""
                active_submission.status = Submission.STATUS_PENDING
                active_submission.verified = False
                active_submission.save(
                    update_fields=[
                        "name",
                        "email",
                        "discipline",
                        "reps",
                        "video_link",
                        "video_storage_path",
                        "video_file",
                        "status",
                        "verified",
                    ]
                )
                estimated_position = estimate_verified_position(score_value, discipline)
                safe_post_submission_side_effects(
                    active_submission,
                    VerificationEvent.ACTION_PROOF_ADDED,
                    "Proof was added to an existing result.",
                    "Earned Club proof received",
                    (
                        f"Your proof for {active_submission.discipline_label} {active_submission.display_score} was added and is now waiting for review. "
                        f"If verified, it would currently rank #{estimated_position}."
                    ),
                    request=request,
                )
                messages.success(
                    request,
                    "Your result is pending review. If approved, your official rank will update.",
                )
                messages.info(request, "Next: open your dashboard, watch review status, and build the next discipline.")
                request.session["last_submission_id"] = active_submission.id
                return redirect("challenge")

            messages.error(
                request,
                "You already have an active submission. Add proof to your current entry or wait until it is reviewed before submitting again.",
            )
            context["form_data"] = request.POST
            context["form_score"] = score_raw
            context["active_submission"] = active_submission
            context["show_submit_help"] = True
            return render(request, "challenge.html", context)

        blocker = find_submission_blocker(request, name, email, score_value, discipline)
        if blocker == "silent":
            messages.success(request, "Submission received. If it passes review, it will appear on the leaderboard.")
            return redirect("challenge")
        if blocker:
            messages.error(request, blocker)
            context["form_data"] = request.POST
            context["form_score"] = score_raw
            context["show_submit_help"] = True
            return render(request, "challenge.html", context)

        estimated_position = estimate_verified_position(score_value, discipline)
        submission = Submission.objects.create(
            user=request.user if request.user.is_authenticated else None,
            name=name,
            email=email,
            discipline=discipline,
            reps=score_value,
            video_link="",
            status=Submission.STATUS_PENDING if video_file else Submission.STATUS_UNVERIFIED,
        )
        submission.video_link = proof_link
        if proof_link and not video_file:
            submission.status = Submission.STATUS_PENDING
            submission.save(update_fields=["video_link", "status"])
        if video_file:
            stored_video = store_submission_video(submission, video_file)
            submission.video_storage_path = stored_video["storage_path"]
            submission.video_file = stored_video["local_file"] or ""
            submission.video_link = proof_link
            submission.status = Submission.STATUS_PENDING
            submission.save(update_fields=["video_link", "video_storage_path", "video_file", "status"])

        safe_post_submission_side_effects(
            submission,
            VerificationEvent.ACTION_SUBMITTED,
            "A new result was submitted.",
            "Earned Club submission received",
            (
                f"Your Earned Club submission for {submission.discipline_label} {submission.display_score} was received. "
                + (
                    f"It is waiting for verification and would currently rank #{estimated_position} if approved."
                    if submission.has_proof else
                    "Upload proof from your profile dashboard to move it into review."
                )
            ),
            request=request,
        )

        messages.success(
            request,
            (
                "Your result is pending review. If approved, your official rank will update."
                if submission.has_proof else
                "You are now on the open leaderboard. Add proof to make it official."
            ),
        )
        messages.info(request, "Next: open the leaderboard, share your result, or add proof for official status.")
        request.session["last_submission_id"] = submission.id
        return redirect("challenge")

    return render(request, "challenge.html", context)


@require_POST
@login_required
def add_submission_proof(request, submission_id):
    submission = get_object_or_404(Submission, pk=submission_id, user=request.user)
    video_file = request.FILES.get("video_file")
    proof_link = (request.POST.get("proof_link") or "").strip()

    if submission.status != Submission.STATUS_UNVERIFIED:
        messages.error(request, "Proof can only be added to unverified submissions.")
        return redirect("dashboard")

    if pending_submission_queryset().filter(user=request.user).exclude(pk=submission.pk).exists():
        messages.error(request, "You already have a submission waiting for verification.")
        return redirect("dashboard")

    if not video_file and not proof_link:
        messages.error(request, "Add a proof link or upload a proof video file.")
        return redirect("dashboard")

    submission.video_link = proof_link
    if video_file:
        stored_video = store_submission_video(submission, video_file)
        submission.video_storage_path = stored_video["storage_path"]
        submission.video_file = stored_video["local_file"] or ""
    submission.status = Submission.STATUS_PENDING
    submission.verified = False
    submission.save(update_fields=["video_link", "video_storage_path", "video_file", "status", "verified"])
    safe_post_submission_side_effects(
        submission,
        VerificationEvent.ACTION_PROOF_ADDED,
        "Proof was added from the dashboard.",
        "Earned Club proof received",
        f"Your proof for {submission.discipline_label} {submission.display_score} was added. The submission is now waiting for review.",
        request=request,
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
                "email_host": settings.EMAIL_HOST,
                "email_user": settings.EMAIL_HOST_USER or "Not configured",
                "email_port": settings.EMAIL_PORT,
                "email_tls": "On" if settings.EMAIL_USE_TLS else "Off",
                "email_ssl": "On" if settings.EMAIL_USE_SSL else "Off",
                "email_delivery_issue": get_email_delivery_issue() or "Ready",
                "supabase_storage": "Enabled" if settings.SUPABASE_STORAGE_ENABLED else "Disabled",
                "debug": "On" if settings.DEBUG else "Off",
                "recent_errors": recent_errors,
            },
        },
    )


@user_passes_test(is_app_admin, login_url="login")
def admin_pages(request):
    page_rows = [
        {"name": "home", "route": "/", "url": reverse("home"), "access": "Public"},
        {"name": "rank", "route": "/rank/", "url": reverse("rank"), "access": "Public"},
        {"name": "level_test", "route": "/test/", "url": reverse("level_test"), "access": "Public"},
        {"name": "challenge", "route": "/challenge/", "url": reverse("challenge"), "access": "Public"},
        {"name": "leaderboard", "route": "/leaderboard/", "url": reverse("leaderboard"), "access": "Public"},
        {"name": "profiles", "route": "/profiles/", "url": reverse("profiles"), "access": "Public"},
        {"name": "athlete_profile", "route": "/athlete/<slug>/", "url": "", "access": "Public"},
        {"name": "comparison", "route": "/comparison/<left>vs<right>/", "url": "", "access": "Public"},
        {"name": "workout_detail", "route": "/workout/<slug>/", "url": "", "access": "Public"},
        {"name": "calculators", "route": "/calculators/", "url": reverse("calculators"), "access": "Public"},
        {"name": "privacy", "route": "/privacy/", "url": reverse("privacy"), "access": "Public"},
        {"name": "terms", "route": "/terms/", "url": reverse("terms"), "access": "Public"},
        {"name": "register", "route": "/register/", "url": reverse("register"), "access": "Account"},
        {"name": "login", "route": "/login/", "url": reverse("login"), "access": "Account"},
        {"name": "dashboard", "route": "/dashboard/", "url": reverse("dashboard"), "access": "Account"},
        {"name": "workouts", "route": "/workouts/", "url": reverse("workouts"), "access": "Account"},
        {"name": "admin_menu", "route": "/admin-menu/", "url": reverse("admin_menu"), "access": "Staff"},
        {"name": "admin_pages", "route": "/admin-menu/pages/", "url": reverse("admin_pages"), "access": "Staff"},
        {"name": "admin_review", "route": "/admin-review/", "url": reverse("admin_review"), "access": "Staff"},
        {"name": "content_engine_admin", "route": "/content/", "url": reverse("content_engine_admin"), "access": "Staff"},
        {"name": "newsletter_admin", "route": "/newsletter/", "url": reverse("newsletter_admin"), "access": "Staff"},
        {"name": "newsletter_subscriber_detail", "route": "/newsletter/subscribers/<id>/", "url": "", "access": "Staff"},
        {"name": "sitemap_xml", "route": "/sitemap.xml", "url": reverse("sitemap_xml"), "access": "System"},
        {"name": "robots_txt", "route": "/robots.txt", "url": reverse("robots_txt"), "access": "System"},
    ]
    return render(
        request,
        "admin_pages.html",
        {
            "page_rows": page_rows,
            "page_count": len(page_rows),
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

    params = build_querystring(
        status=request.POST.get("status_filter") or Submission.STATUS_PENDING,
        proof=request.POST.get("proof_filter") or "all",
        order=request.POST.get("order_filter") or "newest",
        q=request.POST.get("q") or "",
    )
    redirect_url = reverse("admin_review")
    if params:
        redirect_url = f"{redirect_url}?{params}"

    try:
        with transaction.atomic():
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
                messages.success(request, f"{submission.name} was approved with {submission.discipline_label} {submission.display_score}.")
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
                messages.info(request, f"{submission.name} was rejected.")
            elif action == "mark_pending":
                if not submission.has_proof:
                    messages.error(request, "This submission cannot move to pending without proof.")
                    return redirect(redirect_url)
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
                submission_name = submission.name
                submission.delete()
                messages.info(request, f"{submission_name}'s submission was deleted.")
            else:
                messages.error(request, "Unknown review action.")
    except Exception as exc:
        logger.exception("Admin review action %s failed for submission %s", action, submission_id)
        messages.error(request, f"Review action failed: {exc.__class__.__name__}. Check server logs for details.")
    else:
        try:
            if action == "approve":
                send_submission_notification(
                    submission,
                    "Earned Club submission approved",
                    f"Your {submission.discipline_label} {submission.display_score} submission was approved. Your verified result is now live on Earned Club.",
                )
                if submission.user_id:
                    rank = get_official_rank_for_submission(submission)
                    notify_user_email(
                        submission.user,
                        "Your EarnedClub result was verified",
                        f"Your {submission.discipline_label} {submission.display_score} result was verified. Your official rank is currently #{rank}.",
                    )
            elif action == "reject":
                send_submission_notification(
                    submission,
                    "Earned Club submission update",
                    (
                        f"Your {submission.discipline_label} {submission.display_score} submission was reviewed but not approved."
                        + (f" Reviewer note: {review_note}" if review_note else " You can submit again with clearer proof.")
                    ),
                )
                if submission.user_id:
                    notify_user_email(
                        submission.user,
                        "Your EarnedClub result needs another try",
                        "Your latest result was not verified. Check the rules and submit a clearer proof video when you are ready.",
                    )
        except Exception:
            logger.exception("Admin review notification failed for submission %s", submission_id)
            messages.warning(request, "Review was saved, but a notification failed. Check server logs for details.")

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
    default_week = NewsletterCampaign.objects.order_by("-week_number").values_list("week_number", flat=True).first() or 1
    week_number = parse_positive_int(request.POST.get("week_number") if request.method == "POST" else request.GET.get("week")) or default_week
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
                    "email_delivery_issue": get_email_delivery_issue(),
                    "newsletter_from_email": getattr(settings, "NEWSLETTER_FROM_EMAIL", settings.DEFAULT_FROM_EMAIL),
                },
            )
        if request.POST.get("action") == "send" and recipients:
            delivery_issue = get_email_delivery_issue()
            if delivery_issue:
                messages.error(request, f"Email is not configured for real delivery: {delivery_issue}")
                return redirect("newsletter_admin")
            campaign = NewsletterCampaign.objects.create(week_number=week_number, subject=subject, body=body)
            sent_count, failures = send_newsletter_to_subscribers(subject, body, recipients, campaign=campaign, request=request)
            campaign.sent_at = timezone.now() if sent_count else None
            campaign.sent_count = sent_count
            campaign.save(update_fields=["sent_at", "sent_count"])
            destination = f" segment {segment.name}" if segment else (f" auto filter {auto_segment}" if auto_segment else "")
            if sent_count:
                messages.success(request, f"Newsletter sent to {sent_count} subscriber(s){destination}.")
            if failures:
                messages.error(request, f"Email failed for {len(failures)} recipient(s): {', '.join(failures[:3])}.")
        elif request.POST.get("action") == "send":
            messages.info(request, "Newsletter draft saved. There are no subscribers yet.")
        else:
            NewsletterCampaign.objects.create(week_number=week_number, subject=subject, body=body)
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
            "email_delivery_issue": get_email_delivery_issue(),
            "newsletter_from_email": getattr(settings, "NEWSLETTER_FROM_EMAIL", settings.DEFAULT_FROM_EMAIL),
        },
    )


@user_passes_test(is_app_admin, login_url="login")
def newsletter_subscriber_detail(request, subscriber_id):
    subscriber = get_object_or_404(NewsletterSubscriber.objects.prefetch_related("segments"), pk=subscriber_id)
    default_week = NewsletterCampaign.objects.order_by("-week_number").values_list("week_number", flat=True).first() or 1
    draft = build_newsletter_draft(default_week)

    if request.method == "POST":
        subject = (request.POST.get("subject") or "").strip()
        body = (request.POST.get("body") or "").strip()
        if not subject or not body:
            messages.error(request, "Subject and body are required.")
            return redirect("newsletter_subscriber_detail", subscriber_id=subscriber.id)
        delivery_issue = get_email_delivery_issue()
        if delivery_issue:
            messages.error(request, f"Email is not configured for real delivery: {delivery_issue}")
            return redirect("newsletter_subscriber_detail", subscriber_id=subscriber.id)
        sent_count, failures = send_newsletter_to_subscribers(subject, body, [subscriber], request=request)
        if sent_count:
            messages.success(request, f"Email sent to {subscriber.email}.")
        else:
            detail = failures[0] if failures else f"{subscriber.email} ({getattr(safe_send_mail, 'last_error', 'Unknown SMTP error')})"
            messages.error(request, f"Email was not sent: {detail}.")
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
            "email_delivery_issue": get_email_delivery_issue(),
            "newsletter_from_email": getattr(settings, "NEWSLETTER_FROM_EMAIL", settings.DEFAULT_FROM_EMAIL),
        },
    )


def newsletter_unsubscribe(request, token):
    subscriber = get_object_or_404(NewsletterSubscriber, unsubscribe_token=token)
    subscriber.unsubscribe()
    messages.success(request, "You have been unsubscribed from Earned Club emails.")
    return redirect("home")


def calculators(request):
    prompts = ContentEnginePrompt.objects.filter(is_active=True)
    return render(
        request,
        "calculators.html",
        {
            "rank_tiers": RANK_TIERS,
            "content_prompts": prompts,
            "discipline_cards": DISCIPLINE_CONFIG.values(),
            "hybrid_ranks": HYBRID_RANKS,
        },
    )


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

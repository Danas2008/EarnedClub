import json
from datetime import timedelta
from xml.etree.ElementTree import Element, SubElement, indent, register_namespace, tostring
from xml.sax.saxutils import quoteattr
from urllib.parse import urlencode, urljoin

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.decorators import user_passes_test
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.contrib.auth.models import User
from django.core.mail import send_mail
from django.core.serializers.json import DjangoJSONEncoder
from django.http import HttpResponse
from django.db import IntegrityError
from django.core.paginator import Paginator
from django.db.models import Q
from django.views.decorators.http import require_POST
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.safestring import mark_safe

from .countries import COUNTRY_CHOICES
from .models import (
    ContentEnginePrompt,
    Follow,
    Goal,
    NewsletterSubscriber,
    Profile,
    RANK_TIERS,
    Submission,
    VerificationEvent,
    Workout,
    WorkoutExercise,
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
    {"name": "Pull-ups", "type": "strength", "body_part": "Back"},
    {"name": "Dips", "type": "strength", "body_part": "Triceps"},
    {"name": "Squats", "type": "strength", "body_part": "Legs"},
    {"name": "Lunges", "type": "strength", "body_part": "Legs"},
    {"name": "Plank", "type": "strength", "body_part": "Core"},
    {"name": "Burpees", "type": "cardio", "body_part": "Full body"},
    {"name": "Running", "type": "cardio", "body_part": "Cardio"},
    {"name": "Cycling", "type": "cardio", "body_part": "Cardio"},
    {"name": "Jump rope", "type": "cardio", "body_part": "Cardio"},
    {"name": "Shoulder press", "type": "strength", "body_part": "Shoulders"},
    {"name": "Rows", "type": "strength", "body_part": "Back"},
    {"name": "Dead bug", "type": "mobility", "body_part": "Core"},
]

BODY_PARTS = sorted({exercise["body_part"] for exercise in DEFAULT_EXERCISES})

SYSTEM_WORKOUT_TEMPLATES = [
    {
        "name": "Push Day",
        "difficulty": WorkoutTemplate.DIFFICULTY_BEGINNER,
        "notes": "Push-ups, dips, plank. Good for building strict rep capacity.",
        "exercises": [("Push-ups", 4, 12, None), ("Dips", 3, 8, None), ("Plank", 3, None, 45)],
    },
    {
        "name": "Leg Day",
        "difficulty": WorkoutTemplate.DIFFICULTY_BEGINNER,
        "notes": "Simple lower-body session for consistency and conditioning.",
        "exercises": [("Squats", 4, 15, None), ("Lunges", 3, 12, None), ("Plank", 3, None, 40)],
    },
    {
        "name": "Elite Push Builder",
        "difficulty": WorkoutTemplate.DIFFICULTY_ADVANCED,
        "notes": "Higher volume for athletes chasing 60+ strict push-ups.",
        "exercises": [("Push-ups", 6, 18, None), ("Dips", 4, 10, None), ("Burpees", 4, 12, None)],
    },
]


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


def notify_user_email(user, subject, message):
    if not user or not user.email:
        return
    send_mail(subject, message, getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@earnedclub.club"), [user.email], fail_silently=True)


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
    ]
    quote = quotes[(profile.user_id + workout_count + verified_count) % len(quotes)]
    if profile.personal_best_reps >= 60:
        task = "Film a controlled submax set or recover with core work."
    elif profile.personal_best_reps >= 40:
        task = "Do 4 push-up sets at 60-70% of your PR."
    elif workout_count:
        task = "Repeat your last workout and add one clean rep."
    else:
        task = "Test push-ups today, then log a short workout."
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


def paginate_items(request, items, per_page=10):
    paginator = Paginator(items, per_page)
    return paginator.get_page(request.GET.get("page"))


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
        return "This proof link is already attached to a submission. Use a different public proof link or update your existing entry."
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


def create_workout_from_request(request):
    title = (request.POST.get("title") or "").strip()
    duration_value = parse_positive_int(request.POST.get("duration_minutes"))
    notes = (request.POST.get("notes") or "").strip()
    is_public = request.POST.get("is_public") == "on"
    highlighted = request.POST.get("highlighted_on_profile") == "on"
    save_as_template = request.POST.get("save_as_template") == "on"
    template_id = request.POST.get("template_id")
    if not title:
        return None, "Workout title is required."

    template = None
    if template_id:
        template = WorkoutTemplate.objects.filter(Q(user=request.user) | Q(is_system=True), pk=template_id).first()
    workout = Workout.objects.create(
        user=request.user,
        template=template,
        title=title,
        duration_minutes=duration_value,
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
        exercise_type = types[index] if index < len(types) and types[index] else WorkoutExercise.TYPE_STRENGTH
        WorkoutExercise.objects.create(
            workout=workout,
            name=exercise_name,
            exercise_type=exercise_type,
            body_part=(body_parts[index] if index < len(body_parts) else "").strip(),
            sets=parse_positive_int(sets_values[index] if index < len(sets_values) else "") or 1,
            reps=parse_positive_int(reps_values[index] if index < len(reps_values) else ""),
            seconds=parse_positive_int(seconds_values[index] if index < len(seconds_values) else ""),
            order=index,
        )
        exercise_created = True
    if not exercise_created and template:
        for index, (name, sets, reps, seconds) in enumerate(get_template_exercises(template)):
            WorkoutExercise.objects.create(workout=workout, name=name, sets=sets, reps=reps, seconds=seconds, order=index)
    if save_as_template:
        template_difficulty = WorkoutTemplate.DIFFICULTY_BEGINNER
        if request.user.profile.personal_best_reps >= 60:
            template_difficulty = WorkoutTemplate.DIFFICULTY_ADVANCED
        elif request.user.profile.personal_best_reps >= 20:
            template_difficulty = WorkoutTemplate.DIFFICULTY_INTERMEDIATE
        WorkoutTemplate.objects.create(user=request.user, name=title, difficulty=template_difficulty, notes=notes)
    return workout, ""


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
        build_public_url(reverse("sitemap_xsl")),
    )
    return HttpResponse(xml, content_type="application/xml")


def sitemap_xsl(request):
    return render(request, "sitemap.xsl", content_type="text/xsl")



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

    context = {
        "leaderboard_rows": paginate_items(request, leaderboard_rows, per_page=100),
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
        form = UserCreationForm(request.POST)
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
        form = UserCreationForm()

    return render(request, "register.html", {"form": form})


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
            try:
                target_value = int(target_value)
            except (TypeError, ValueError):
                messages.error(request, "Goal target must be a whole number.")
                return redirect("dashboard")
            if target_value <= 0:
                messages.error(request, "Goal target must be greater than zero.")
                return redirect("dashboard")
            Goal.objects.create(user=request.user, goal_type=goal_type, target_value=target_value, note=note)
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
        profile_photo = (request.POST.get("profile_photo") or "").strip()
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
    progress_summary = get_progress_summary(verified_submissions)
    recommendation = get_daily_suggestion(profile, verified_submissions.count(), workouts.count())

    context = {
        "profile": profile,
        "best_submission": best_submission,
        "current_pr": best_submission.reps if best_submission else 0,
        "all_time_pr": best_submission.reps if best_submission else 0,
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
        "history_submissions": request.user.submission_set.order_by("-created_at"),
        "rejected_count": rejected_submissions.count(),
        "progress_data": get_progress_data(verified_submissions),
        "progress_summary": progress_summary,
        "country_choices": COUNTRY_CHOICES,
        "badges": profile.earned_badges,
        "followers_count": request.user.follower_links.count(),
        "following_count": request.user.following_links.count(),
        "workouts": workouts[:5],
        "active_goals": request.user.goals.filter(is_active=True)[:5],
        "daily_suggestion": recommendation,
        "profile_share_message": get_profile_share_message(profile, request),
        "pr_share_message": get_pr_share_message(profile, request),
    }
    return render(request, "dashboard.html", context)


def profiles(request):
    query = (request.GET.get("q") or "").strip()
    profiles_with_scores = Profile.objects.filter(personal_best_reps__gt=0).order_by(
        "current_rank", "-personal_best_reps", "display_name"
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
    context = {
        "profile": profile,
        "best_submission": best_submission,
        "current_tier": best_submission.rank_tier if best_submission else get_rank_tier(0),
        "verified_submissions": verified_submissions.order_by("-created_at"),
        "progress_data": get_progress_data(verified_submissions),
        "profile_description": profile_description,
        "profile_schema_json": json_ld(build_profile_schema(profile, best_submission)),
        "profile_og_image": build_public_url(profile.profile_image_url) if profile.profile_image_url and profile.profile_image_url.startswith("/") else (profile.profile_image_url or ""),
        "badges": profile.earned_badges,
        "followers_count": profile.user.follower_links.count(),
        "following_count": profile.user.following_links.count(),
        "public_workouts": profile.user.workouts.filter(is_public=True).prefetch_related("exercises")[:4],
        "highlighted_workout": profile.user.workouts.filter(is_public=True, highlighted_on_profile=True).prefetch_related("exercises").first(),
        "is_following": is_following,
        "compare_profile": compare_profile,
        "comparison": comparison,
        "profile_share_message": get_profile_share_message(profile, request),
        "pr_share_message": get_pr_share_message(profile, request),
    }
    return render(request, "athlete_profile.html", context)


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
            return render(request, "challenge.html", context)

        try:
            reps_value = int(reps)
        except ValueError:
            messages.error(request, "Reps must be a whole number.")
            context["form_data"] = request.POST
            return render(request, "challenge.html", context)

        if reps_value <= 0:
            messages.error(request, "Reps must be greater than zero.")
            context["form_data"] = request.POST
            return render(request, "challenge.html", context)

        if not request.user.is_authenticated and reps_value > 40:
            messages.error(request, "Anonymous submissions are capped at 40 push-ups. Log in and add video proof to submit more.")
            context["form_data"] = request.POST
            return render(request, "challenge.html", context)

        if request.user.is_authenticated and reps_value > 60 and not (video_link or video_file):
            messages.error(request, "Scores above 60 need video proof. Add a public link or upload a video file.")
            context["form_data"] = request.POST
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
                return redirect("challenge")

            messages.error(
                request,
                "You already have an active submission. Add proof to your current entry or wait until it is reviewed before submitting again.",
            )
            context["form_data"] = request.POST
            context["active_submission"] = active_submission
            return render(request, "challenge.html", context)

        blocker = find_submission_blocker(request, name, email, reps_value, video_link)
        if blocker == "silent":
            messages.success(request, "Submission received. If it passes review, it will appear on the leaderboard.")
            return redirect("challenge")
        if blocker:
            messages.error(request, blocker)
            context["form_data"] = request.POST
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
        send_submission_notification(
            submission,
            "Earned Club submission received",
            (
                f"Your Earned Club submission for {submission.reps} reps was received. "
                + (
                    f"It is waiting for verification and would currently rank #{estimated_position} if approved."
                    if submission.has_proof else
                    "Add a public proof link from your profile dashboard to move it into review."
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
                "Submission saved as unverified. Add a video or link from your profile to move it into pending review."
            ),
        )
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
        messages.error(request, "Add a public proof link or upload a video file.")
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
    send_submission_notification(
        submission,
        "Earned Club proof received",
        f"Your proof link for {submission.reps} reps was added. The submission is now waiting for review.",
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
def admin_review(request):
    status_filter = (request.GET.get("status") or Submission.STATUS_PENDING).strip()
    proof_filter = (request.GET.get("proof") or "all").strip()
    order_filter = (request.GET.get("order") or "newest").strip()
    query = (request.GET.get("q") or "").strip()

    submissions = Submission.objects.select_related("user", "user__profile").prefetch_related("verification_events")
    if status_filter != "all":
        allowed_statuses = {key for key, _ in Submission.STATUS_CHOICES}
        submissions = submissions.filter(status=status_filter if status_filter in allowed_statuses else Submission.STATUS_PENDING)
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
    reviewed_submissions = Submission.objects.exclude(status=Submission.STATUS_PENDING).select_related(
        "user", "user__profile"
    ).order_by("-created_at")[:20]
    return render(
        request,
        "admin_review.html",
        {
            "review_submissions": review_submissions,
            "reviewed_submissions": reviewed_submissions,
            "status_filter": status_filter,
            "proof_filter": proof_filter,
            "order_filter": order_filter,
            "query": query,
            "pending_count": pending_submission_queryset().count(),
            "review_count": submissions.count(),
            "status_options": [("all", "All statuses"), *Submission.STATUS_CHOICES],
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
        if form_type == "quick_result":
            exercise_name = (request.POST.get("quick_exercise") or "Quick result").strip()
            exercise_type = request.POST.get("quick_type") or WorkoutExercise.TYPE_STRENGTH
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
                body_part=(request.POST.get("quick_body_part") or "").strip(),
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
            messages.success(request, "Workout saved.")
        return redirect("workouts")

    workouts_qs = request.user.workouts.prefetch_related("exercises").order_by("-created_at")
    templates = WorkoutTemplate.objects.filter(Q(user=request.user) | Q(is_system=True)).order_by("-is_system", "difficulty", "name")
    return render(
        request,
        "workouts.html",
        {
            "workouts": workouts_qs,
            "workout_templates": templates,
            "default_exercises": DEFAULT_EXERCISES,
            "body_parts": BODY_PARTS,
            "exercise_types": WorkoutExercise.TYPE_CHOICES,
        },
    )


@require_POST
@login_required
def duplicate_workout(request, workout_id):
    source = get_object_or_404(Workout.objects.prefetch_related("exercises"), pk=workout_id, user=request.user)
    workout = Workout.objects.create(
        user=request.user,
        template=source.template,
        title=f"{source.title} copy",
        notes=source.notes,
        duration_minutes=source.duration_minutes,
        is_public=False,
    )
    for exercise in source.exercises.all():
        WorkoutExercise.objects.create(
            workout=workout,
            name=exercise.name,
            sets=exercise.sets,
            reps=exercise.reps,
            seconds=exercise.seconds,
            notes=exercise.notes,
            order=exercise.order,
        )
    messages.success(request, "Workout duplicated.")
    return redirect("workouts")


@require_POST
@login_required
def quick_add_last_workout(request):
    source = request.user.workouts.prefetch_related("exercises").first()
    if not source:
        messages.error(request, "You do not have a previous workout to quick add yet.")
        return redirect("dashboard")
    workout = Workout.objects.create(
        user=request.user,
        template=source.template,
        title=source.title,
        notes=source.notes,
        duration_minutes=source.duration_minutes,
        is_public=False,
    )
    for exercise in source.exercises.all():
        WorkoutExercise.objects.create(
            workout=workout,
            name=exercise.name,
            sets=exercise.sets,
            reps=exercise.reps,
            seconds=exercise.seconds,
            notes=exercise.notes,
            order=exercise.order,
        )
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

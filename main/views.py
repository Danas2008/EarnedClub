from datetime import timedelta

from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.db import IntegrityError
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from .models import NewsletterSubscriber, Profile, RANK_TIERS, Submission, get_rank_tier


def build_leaderboard_rows(submissions):
    rows = []
    for index, submission in enumerate(submissions, start=1):
        profile = None
        if submission.user_id:
            profile = getattr(submission.user, "profile", None)
        rows.append(
            {
                "position": index,
                "medal_place": index if index <= 3 else None,
                "submission": submission,
                "profile": profile,
            }
        )
    return rows


def verified_submission_queryset():
    return Submission.objects.filter(status=Submission.STATUS_VERIFIED)


def pending_submission_queryset():
    return Submission.objects.filter(status=Submission.STATUS_PENDING)


def estimate_verified_position(reps):
    equal_or_better = verified_submission_queryset().filter(reps__gte=reps).count()
    return equal_or_better + 1


def user_display_name(user):
    profile = getattr(user, "profile", None)
    if profile:
        return profile.display_name
    return user.get_full_name() or user.username


def get_progress_data(submissions):
    return [
        {
            "date": submission.created_at.strftime("%Y-%m-%d"),
            "reps": submission.reps,
        }
        for submission in submissions.order_by("created_at")
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


def home(request):
    verified_submissions = list(verified_submission_queryset())
    leaderboard_rows = build_leaderboard_rows(verified_submissions)
    weekly_cutoff = get_weekly_window()
    weekly_rows = build_leaderboard_rows(
        [submission for submission in verified_submissions if submission.created_at >= weekly_cutoff]
    )

    context = {
        "rank_tiers": RANK_TIERS,
        "total_verified": len(leaderboard_rows),
        "top_three": leaderboard_rows[:3],
        "weekly_top_five": weekly_rows[:5],
        "overall_top_five": leaderboard_rows[:10],
    }
    return render(request, "home.html", context)


def leaderboard(request):
    verified_submissions = list(verified_submission_queryset())
    weekly_cutoff = get_weekly_window()
    weekly_submissions = [
        submission for submission in verified_submissions if submission.created_at >= weekly_cutoff
    ]

    context = {
        "leaderboard_rows": build_leaderboard_rows(verified_submissions),
        "weekly_rows": build_leaderboard_rows(weekly_submissions)[:5],
        "rank_tiers": RANK_TIERS,
        "verified_count": len(verified_submissions),
    }
    return render(request, "leaderboard.html", context)


def register(request):
    if request.user.is_authenticated:
        return redirect("dashboard")

    if request.method == "POST":
        form = UserCreationForm(request.POST)
        display_name = (request.POST.get("display_name") or "").strip()
        email = (request.POST.get("email") or "").strip().lower()
        if form.is_valid():
            user = form.save(commit=False)
            user.email = email
            user.save()
            profile = user.profile
            profile.display_name = display_name or user.username
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
    verified_submissions = request.user.submission_set.filter(status=Submission.STATUS_VERIFIED)
    pending_submissions = request.user.submission_set.filter(status=Submission.STATUS_PENDING)
    best_submission = verified_submissions.order_by("-reps", "created_at").first()
    first_submission = request.user.submission_set.order_by("created_at").first()
    current_rank = None
    current_tier = get_rank_tier(0)

    if best_submission:
        current_rank = verified_submission_queryset().filter(reps__gt=best_submission.reps).count() + 1
        current_tier = best_submission.rank_tier

    weeks_active = 0
    if first_submission:
        weeks_active = max(1, ((timezone.now() - first_submission.created_at).days // 7) + 1)

    context = {
        "profile": request.user.profile,
        "best_submission": best_submission,
        "current_pr": best_submission.reps if best_submission else 0,
        "all_time_pr": best_submission.reps if best_submission else 0,
        "current_rank": current_rank,
        "current_tier": current_tier,
        "rank_movement": "New season baseline",
        "total_verified": verified_submissions.count(),
        "total_pending": pending_submissions.count(),
        "weeks_active": weeks_active,
        "verified_streak": get_current_streak(verified_submissions),
        "pending_submissions": pending_submissions.order_by("-created_at"),
        "verified_submissions": verified_submissions.order_by("-created_at"),
        "progress_data": get_progress_data(verified_submissions),
    }
    return render(request, "dashboard.html", context)


def profiles(request):
    profiles_with_scores = Profile.objects.filter(personal_best_reps__gt=0).order_by(
        "current_rank", "-personal_best_reps", "display_name"
    )
    return render(request, "profiles.html", {"profiles": profiles_with_scores})


def athlete_profile(request, slug):
    profile = get_object_or_404(Profile, slug=slug)
    verified_submissions = profile.user.submission_set.filter(status=Submission.STATUS_VERIFIED)
    best_submission = verified_submissions.order_by("-reps", "created_at").first()
    profile.refresh_verified_stats()
    context = {
        "profile": profile,
        "best_submission": best_submission,
        "current_tier": best_submission.rank_tier if best_submission else get_rank_tier(0),
        "verified_submissions": verified_submissions.order_by("-created_at"),
        "progress_data": get_progress_data(verified_submissions),
    }
    return render(request, "athlete_profile.html", context)


def challenge(request):
    context = {}
    if request.user.is_authenticated:
        context["profile"] = request.user.profile
        context["has_pending_submission"] = pending_submission_queryset().filter(user=request.user).exists()

    if request.method == "POST":
        name = (request.POST.get("name") or "").strip()
        email = (request.POST.get("email") or "").strip().lower()
        reps = (request.POST.get("reps") or "").strip()
        video_link = (request.POST.get("video_link") or "").strip()

        if request.user.is_authenticated:
            name = user_display_name(request.user)
            email = request.user.email

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

        pending_filter = pending_submission_queryset()
        if request.user.is_authenticated:
            has_pending_submission = pending_filter.filter(user=request.user).exists()
        else:
            has_pending_submission = pending_filter.filter(email=email).exists()

        if has_pending_submission:
            messages.error(
                request,
                "You already have a submission waiting for verification. Please wait until it is reviewed before submitting again.",
            )
            context["form_data"] = request.POST
            context["has_pending_submission"] = has_pending_submission
            return render(request, "challenge.html", context)

        estimated_position = estimate_verified_position(reps_value)
        Submission.objects.create(
            user=request.user if request.user.is_authenticated else None,
            name=name,
            email=email,
            reps=reps_value,
            video_link=video_link,
        )

        messages.success(
            request,
            f"Submission received. If verified, this result would currently rank #{estimated_position} on the verified leaderboard.",
        )
        return redirect("challenge")

    return render(request, "challenge.html", context)


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
    return render(request, "calculators.html", {"rank_tiers": RANK_TIERS})

from datetime import timedelta

from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.decorators import user_passes_test
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.contrib.auth.models import User
from django.http import HttpResponse
from django.db import IntegrityError
from django.core.paginator import Paginator
from django.db.models import Q
from django.views.decorators.http import require_POST
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from .countries import COUNTRY_CHOICES
from .models import (
    NewsletterSubscriber,
    Profile,
    RANK_TIERS,
    Submission,
    get_best_verified_submission_for_user,
    get_official_rank_for_submission,
    get_official_verified_submissions,
    get_rank_tier,
    get_submission_identity,
)


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


def estimate_verified_position(reps):
    equal_or_better = sum(1 for item in get_official_verified_submissions() if item.reps >= reps)
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
            "time": submission.created_at.strftime("%H:%M"),
            "label": submission.created_at.strftime("%b %d, %H:%M"),
            "reps": submission.reps,
        }
        for submission in submissions.order_by("created_at", "id")
    ]


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


def build_absolute_url(request, view_name, *args):
    return request.build_absolute_uri(reverse(view_name, args=args))


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


def sitemap_xml(request):
    urls = [
        ("home", None),
        ("challenge", None),
        ("leaderboard", None),
        ("profiles", None),
        ("calculators", None),
        ("register", None),
        ("login", None),
        ("privacy", None),
        ("terms", None),
    ]
    entries = [build_absolute_url(request, name) for name, _ in urls]
    entries.extend(
        build_absolute_url(request, "athlete_profile", profile.slug)
        for profile in Profile.objects.filter(personal_best_reps__gt=0).order_by("slug")
    )

    xml = ['<?xml version="1.0" encoding="UTF-8"?>', '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for entry in entries:
        xml.append(f"  <url><loc>{entry}</loc></url>")
    xml.append("</urlset>")
    return HttpResponse("\n".join(xml), content_type="application/xml")


def robots_txt(request):
    lines = [
        "User-agent: *",
        "Allow: /",
        f"Sitemap: {request.build_absolute_uri(reverse('sitemap_xml'))}",
    ]
    return HttpResponse("\n".join(lines), content_type="text/plain")


def leaderboard(request):
    query = (request.GET.get("q") or "").strip()
    verified_submissions = get_official_verified_submissions()
    public_submissions = list(public_submission_queryset())
    public_submissions = search_submissions(public_submissions, query)
    weekly_cutoff = get_weekly_window()
    weekly_submissions = search_submissions(public_submission_queryset(since=weekly_cutoff), query)

    leaderboard_rows = build_leaderboard_rows(public_submissions)

    context = {
        "leaderboard_rows": paginate_items(request, leaderboard_rows),
        "weekly_rows": build_leaderboard_rows(weekly_submissions)[:5],
        "rank_tiers": RANK_TIERS,
        "verified_count": len(verified_submissions),
        "submission_count": len(public_submissions),
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
        username = (request.POST.get("username") or "").strip()
        email = (request.POST.get("email") or "").strip().lower()
        profile_photo = (request.POST.get("profile_photo") or "").strip()
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
        profile.profile_image = ""
        profile.profile_storage_path = ""
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
        "country_choices": COUNTRY_CHOICES,
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
        context["active_submission"] = active_submission_queryset().filter(user=request.user).order_by("-created_at").first()

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

        active_filter = active_submission_queryset()
        if request.user.is_authenticated:
            active_submission = active_filter.filter(user=request.user).first()
        else:
            active_submission = active_filter.filter(email=email).first()

        if active_submission:
            if active_submission.status == Submission.STATUS_UNVERIFIED and video_link:
                active_submission.name = name
                active_submission.email = email
                active_submission.reps = reps_value
                active_submission.video_link = video_link
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
                estimated_position = estimate_verified_position(reps_value)
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

        estimated_position = estimate_verified_position(reps_value)
        submission = Submission.objects.create(
            user=request.user if request.user.is_authenticated else None,
            name=name,
            email=email,
            reps=reps_value,
            video_link=video_link,
            status=Submission.STATUS_PENDING if video_link else Submission.STATUS_UNVERIFIED,
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

    if submission.status != Submission.STATUS_UNVERIFIED:
        messages.error(request, "Proof can only be added to unverified submissions.")
        return redirect("dashboard")

    if pending_submission_queryset().filter(user=request.user).exclude(pk=submission.pk).exists():
        messages.error(request, "You already have a submission waiting for verification.")
        return redirect("dashboard")

    if not video_link:
        messages.error(request, "Add a public proof link.")
        return redirect("dashboard")

    submission.video_link = video_link
    submission.video_storage_path = ""
    submission.video_file = ""
    submission.status = Submission.STATUS_PENDING
    submission.verified = False
    submission.save(update_fields=["video_link", "video_storage_path", "video_file", "status", "verified"])
    messages.success(request, "Proof added. Your submission is back in pending review.")
    return redirect("dashboard")


def is_app_admin(user):
    return user.is_authenticated and user.is_staff


@user_passes_test(is_app_admin, login_url="login")
def admin_review(request):
    pending_submissions = Submission.objects.filter(status=Submission.STATUS_PENDING).select_related(
        "user", "user__profile"
    ).order_by("-created_at")
    reviewed_submissions = Submission.objects.exclude(status=Submission.STATUS_PENDING).select_related(
        "user", "user__profile"
    ).order_by("-created_at")[:20]
    return render(
        request,
        "admin_review.html",
        {
            "pending_submissions": pending_submissions,
            "reviewed_submissions": reviewed_submissions,
        },
    )


@require_POST
@user_passes_test(is_app_admin, login_url="login")
def review_submission(request, submission_id):
    submission = get_object_or_404(Submission, pk=submission_id)
    action = request.POST.get("action")

    if action == "approve":
        submission.status = Submission.STATUS_VERIFIED
        submission.verified = True
        submission.save(update_fields=["status", "verified"])
        messages.success(request, f"{submission.name} was approved with {submission.reps} reps.")
    elif action == "reject":
        submission.status = Submission.STATUS_REJECTED
        submission.verified = False
        submission.save(update_fields=["status", "verified"])
        messages.info(request, f"{submission.name} was rejected.")
    else:
        messages.error(request, "Unknown review action.")

    return redirect("admin_review")


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


def privacy(request):
    return render(request, "privacy.html")


def terms(request):
    return render(request, "terms.html")

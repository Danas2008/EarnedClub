from datetime import timedelta

from django.contrib import messages
from django.db import IntegrityError
from django.shortcuts import redirect, render
from django.utils import timezone

from .models import NewsletterSubscriber, RANK_TIERS, Submission


def build_leaderboard_rows(submissions):
    rows = []
    for index, submission in enumerate(submissions, start=1):
        rows.append(
            {
                "position": index,
                "medal_place": index if index <= 3 else None,
                "submission": submission,
            }
        )
    return rows


def get_weekly_window():
    return timezone.now() - timedelta(days=7)


def home(request):
    verified_submissions = list(Submission.objects.filter(verified=True))
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
    verified_submissions = list(Submission.objects.filter(verified=True))
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


def challenge(request):
    if request.method == "POST":
        name = (request.POST.get("name") or "").strip()
        reps = (request.POST.get("reps") or "").strip()
        video_link = (request.POST.get("video_link") or "").strip()

        if not name or not reps or not video_link:
            messages.error(request, "Please fill in all fields before submitting.")
            return render(request, "challenge.html", {"form_data": request.POST})

        try:
            reps_value = int(reps)
        except ValueError:
            messages.error(request, "Reps must be a whole number.")
            return render(request, "challenge.html", {"form_data": request.POST})

        if reps_value <= 0:
            messages.error(request, "Reps must be greater than zero.")
            return render(request, "challenge.html", {"form_data": request.POST})

        Submission.objects.create(
            name=name,
            reps=reps_value,
            video_link=video_link,
        )

        messages.success(
            request,
            "Submission received. It will appear on the leaderboard after manual verification.",
        )
        return redirect("challenge")

    return render(request, "challenge.html")


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

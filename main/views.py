from django.contrib import messages
from django.shortcuts import redirect, render

from .models import Submission


def home(request):
    return render(request, "home.html")


def leaderboard(request):
    submissions = Submission.objects.filter(verified=True).order_by("-reps", "created_at")
    return render(request, "leaderboard.html", {"submissions": submissions})


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

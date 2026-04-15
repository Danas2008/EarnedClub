from django.shortcuts import render, redirect
from .models import Submission

def home(request):
    return render(request, "home.html")


def leaderboard(request):
    return render(request, "leaderboard.html")


def challenge(request):
    if request.method == 'POST':
        name = request.POST.get('name')
        reps = request.POST.get('reps')
        video_link = request.POST.get('video_link')

        Submission.objects.create(
            name=name,
            reps=reps,
            video_link=video_link
        )

        return redirect('leaderboard')

    return render(request, 'challenge.html')
from django.shortcuts import render

def home(request):
    return render(request, "home.html")

def challenge(request):
    return render(request, "challenge.html")

def leaderboard(request):
    return render(request, "leaderboard.html")
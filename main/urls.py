from django.urls import path

from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("challenge/", views.challenge, name="challenge"),
    path("leaderboard/", views.leaderboard, name="leaderboard"),
    path("calculators/", views.calculators, name="calculators"),
    path("newsletter-signup/", views.newsletter_signup, name="newsletter_signup"),
]

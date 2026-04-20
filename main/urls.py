from django.urls import path

from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("register/", views.register, name="register"),
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("dashboard/", views.dashboard, name="dashboard"),
    path("profiles/", views.profiles, name="profiles"),
    path("athlete/<slug:slug>/", views.athlete_profile, name="athlete_profile"),
    path("challenge/", views.challenge, name="challenge"),
    path("leaderboard/", views.leaderboard, name="leaderboard"),
    path("calculators/", views.calculators, name="calculators"),
    path("newsletter-signup/", views.newsletter_signup, name="newsletter_signup"),
]

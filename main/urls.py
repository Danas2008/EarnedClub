from django.urls import path

from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("register/", views.register, name="register"),
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("dashboard/", views.dashboard, name="dashboard"),
    path("dashboard/submissions/<int:submission_id>/proof/", views.add_submission_proof, name="add_submission_proof"),
    path("admin-review/", views.admin_review, name="admin_review"),
    path("admin-review/<int:submission_id>/", views.review_submission, name="review_submission"),
    path("profiles/", views.profiles, name="profiles"),
    path("athlete/<slug:slug>/", views.athlete_profile, name="athlete_profile"),
    path("challenge/", views.challenge, name="challenge"),
    path("leaderboard/", views.leaderboard, name="leaderboard"),
    path("calculators/", views.calculators, name="calculators"),
    path("newsletter-signup/", views.newsletter_signup, name="newsletter_signup"),
    path("privacy/", views.privacy, name="privacy"),
    path("terms/", views.terms, name="terms"),
]

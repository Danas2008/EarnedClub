from django.urls import path
from . import views

urlpatterns = [
    path('', views.home),
    path('challenge/', views.challenge),
    path('leaderboard/', views.leaderboard),
]
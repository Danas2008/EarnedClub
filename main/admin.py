from django.contrib import admin

from .models import Submission


@admin.register(Submission)
class SubmissionAdmin(admin.ModelAdmin):
    list_display = ("name", "reps", "verified", "created_at")
    list_filter = ("verified", "created_at")
    search_fields = ("name", "video_link")
    ordering = ("-created_at",)

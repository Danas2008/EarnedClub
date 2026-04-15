from django.contrib import admin

from .models import NewsletterSubscriber, Submission


@admin.register(Submission)
class SubmissionAdmin(admin.ModelAdmin):
    list_display = ("name", "reps", "rank_name", "verified", "created_at")
    list_filter = ("verified", "created_at")
    search_fields = ("name", "video_link")
    ordering = ("-created_at",)


@admin.register(NewsletterSubscriber)
class NewsletterSubscriberAdmin(admin.ModelAdmin):
    list_display = ("email", "created_at")
    search_fields = ("email",)
    ordering = ("-created_at",)

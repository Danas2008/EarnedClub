from django.contrib import admin
from django.utils.html import format_html

from .models import NewsletterSubscriber, Profile, Submission


@admin.register(Submission)
class SubmissionAdmin(admin.ModelAdmin):
    list_display = ("name", "email", "reps", "rank_name", "status", "verified", "proof_access", "created_at")
    list_filter = ("status", "verified", "created_at")
    search_fields = ("name", "email", "video_link")
    ordering = ("-created_at",)
    readonly_fields = ("proof_access",)

    @admin.display(description="Proof")
    def proof_access(self, obj):
        if not obj.proof_url:
            return "No proof"
        return format_html('<a href="{}" target="_blank" rel="noopener noreferrer">View video</a>', obj.proof_url)


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ("display_name", "user", "country", "age", "current_rank", "personal_best_reps", "created_at")
    prepopulated_fields = {"slug": ("display_name",)}
    search_fields = ("display_name", "user__username", "user__email")
    ordering = ("display_name",)


@admin.register(NewsletterSubscriber)
class NewsletterSubscriberAdmin(admin.ModelAdmin):
    list_display = ("email", "created_at")
    search_fields = ("email",)
    ordering = ("-created_at",)

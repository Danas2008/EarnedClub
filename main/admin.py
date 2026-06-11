from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html

from .models import (
    ContentEnginePrompt,
    ChallengeRoom,
    ChallengeRoomEntry,
    Follow,
    Goal,
    GymLead,
    NewsletterSubscriber,
    Profile,
    Submission,
    VerificationEvent,
    Workout,
    WorkoutExercise,
    NewsletterCampaign,
    NewsletterSendEvent,
    NewsletterSegment,
    WorkoutTemplate,
)


class ChallengeRoomEntryInline(admin.TabularInline):
    model = ChallengeRoomEntry
    extra = 0
    readonly_fields = ("joined_at",)


@admin.register(ChallengeRoom)
class ChallengeRoomAdmin(admin.ModelAdmin):
    list_display = ("display_title", "focus", "token", "created_by", "created_at")
    list_filter = ("focus", "created_at")
    search_fields = ("title", "description", "token")
    readonly_fields = ("token", "created_at")
    inlines = [ChallengeRoomEntryInline]


@admin.register(Submission)
class SubmissionAdmin(admin.ModelAdmin):
    list_display = ("name", "email", "discipline", "score_display", "rank_name", "status", "verified", "proof_access", "created_at")
    list_filter = ("discipline", "status", "verified", "created_at")
    search_fields = ("name", "email", "video_link", "claim_token")
    ordering = ("-created_at",)
    readonly_fields = ("proof_access", "claim_link")

    @admin.display(description="Proof")
    def proof_access(self, obj):
        if not obj.proof_url:
            return "No proof"
        return format_html('<a href="{}" target="_blank" rel="noopener noreferrer">View video</a>', obj.proof_url)

    @admin.display(description="Result")
    def score_display(self, obj):
        return obj.display_score

    @admin.display(description="Recovery / Claim Link")
    def claim_link(self, obj):
        if not obj.claim_token:
            return "No token — submission is linked to a registered account"
        path = reverse("claim_token", args=[obj.claim_token])
        return format_html(
            '<a href="{path}" target="_blank" rel="noopener noreferrer" style="margin-right:14px;">Open link ↗</a>'
            '<code onclick="this.parentElement.querySelector(\'input\').select()" '
            'style="font-size:12px;cursor:pointer;" title="Click the field to select all">'
            '{path}</code>'
            '<br><input readonly value="{path}" '
            'style="margin-top:6px;width:100%;max-width:480px;padding:4px 8px;'
            'font-family:monospace;font-size:12px;border:1px solid #ccc;border-radius:4px;'
            'background:#f9f9f9;cursor:text;" onclick="this.select()" '
            'title="Click to select all — then Ctrl+C / Cmd+C to copy for email">',
            path=path,
        )


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ("display_name", "user", "country", "age", "current_rank", "personal_best_reps", "created_at")
    prepopulated_fields = {"slug": ("display_name",)}
    search_fields = ("display_name", "user__username", "user__email")
    ordering = ("display_name",)


@admin.register(NewsletterSubscriber)
class NewsletterSubscriberAdmin(admin.ModelAdmin):
    list_display = ("email", "is_subscribed", "created_at", "unsubscribed_at")
    search_fields = ("email",)
    ordering = ("-created_at",)


@admin.register(VerificationEvent)
class VerificationEventAdmin(admin.ModelAdmin):
    list_display = ("submission", "action", "reviewer", "created_at")
    list_filter = ("action", "created_at")
    search_fields = ("submission__name", "submission__email", "note")
    readonly_fields = ("submission", "reviewer", "action", "note", "created_at")
    ordering = ("-created_at",)


class WorkoutExerciseInline(admin.TabularInline):
    model = WorkoutExercise
    extra = 0


@admin.register(Workout)
class WorkoutAdmin(admin.ModelAdmin):
    list_display = ("title", "user", "is_public", "duration_minutes", "created_at")
    search_fields = ("title", "user__username")
    prepopulated_fields = {"slug": ("title",)}
    inlines = [WorkoutExerciseInline]


@admin.register(WorkoutTemplate)
class WorkoutTemplateAdmin(admin.ModelAdmin):
    list_display = ("name", "difficulty", "is_system", "user", "created_at")
    list_filter = ("difficulty", "is_system")
    search_fields = ("name", "notes")


@admin.register(NewsletterCampaign)
class NewsletterCampaignAdmin(admin.ModelAdmin):
    list_display = ("week_number", "subject", "sent_count", "sent_at", "created_at")
    search_fields = ("subject", "body")


@admin.register(NewsletterSegment)
class NewsletterSegmentAdmin(admin.ModelAdmin):
    list_display = ("name", "created_at")
    search_fields = ("name", "subscribers__email")
    filter_horizontal = ("subscribers",)


@admin.register(NewsletterSendEvent)
class NewsletterSendEventAdmin(admin.ModelAdmin):
    list_display = ("subscriber", "subject", "campaign", "sent_at")
    search_fields = ("subscriber__email", "subject")


@admin.register(Follow)
class FollowAdmin(admin.ModelAdmin):
    list_display = ("follower", "following", "created_at")
    search_fields = ("follower__username", "following__username")


@admin.register(Goal)
class GoalAdmin(admin.ModelAdmin):
    list_display = ("user", "goal_type", "target_value", "is_active", "created_at")
    list_filter = ("goal_type", "is_active")


@admin.register(GymLead)
class GymLeadAdmin(admin.ModelAdmin):
    list_display = ("gym_name", "contact_name", "email", "phone", "created_at")
    search_fields = ("gym_name", "contact_name", "email")
    ordering = ("-created_at",)
    readonly_fields = ("created_at",)


@admin.register(ContentEnginePrompt)
class ContentEnginePromptAdmin(admin.ModelAdmin):
    list_display = ("title", "engine_type", "is_active", "created_at")
    list_filter = ("engine_type", "is_active")
    search_fields = ("title", "prompt")

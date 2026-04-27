from django.contrib import admin
from django.utils.html import format_html

from .models import (
    ContentEnginePrompt,
    Follow,
    Goal,
    NewsletterSubscriber,
    Profile,
    Submission,
    VerificationEvent,
    Workout,
    WorkoutExercise,
    WorkoutTemplate,
)


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


@admin.register(Follow)
class FollowAdmin(admin.ModelAdmin):
    list_display = ("follower", "following", "created_at")
    search_fields = ("follower__username", "following__username")


@admin.register(Goal)
class GoalAdmin(admin.ModelAdmin):
    list_display = ("user", "goal_type", "target_value", "is_active", "created_at")
    list_filter = ("goal_type", "is_active")


@admin.register(ContentEnginePrompt)
class ContentEnginePromptAdmin(admin.ModelAdmin):
    list_display = ("title", "engine_type", "is_active", "created_at")
    list_filter = ("engine_type", "is_active")
    search_fields = ("title", "prompt")

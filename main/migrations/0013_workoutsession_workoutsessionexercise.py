from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("main", "0012_goal_is_public"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="WorkoutSession",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("status", models.CharField(choices=[("active", "Active"), ("completed", "Completed")], default="active", max_length=16)),
                ("started_at", models.DateTimeField(auto_now_add=True)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="workout_sessions", to=settings.AUTH_USER_MODEL)),
                ("workout", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="sessions", to="main.workout")),
            ],
            options={
                "ordering": ("-started_at",),
            },
        ),
        migrations.CreateModel(
            name="WorkoutSessionExercise",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=120)),
                ("exercise_type", models.CharField(choices=[("strength", "Strength"), ("cardio", "Cardio"), ("mobility", "Mobility")], default="strength", max_length=24)),
                ("body_part", models.CharField(blank=True, max_length=80)),
                ("target_sets", models.PositiveIntegerField(default=1)),
                ("target_reps", models.PositiveIntegerField(blank=True, null=True)),
                ("target_seconds", models.PositiveIntegerField(blank=True, null=True)),
                ("completed_sets", models.PositiveIntegerField(default=0)),
                ("order", models.PositiveIntegerField(default=0)),
                ("session", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="exercise_sessions", to="main.workoutsession")),
                ("workout_exercise", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="session_entries", to="main.workoutexercise")),
            ],
            options={
                "ordering": ("order", "id"),
            },
        ),
    ]

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("main", "0020_alter_goal_goal_type"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="ChallengeRoom",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("title", models.CharField(blank=True, max_length=140)),
                ("description", models.TextField(blank=True)),
                ("focus", models.CharField(choices=[("hybrid", "Hybrid Score"), ("pushups", "Push-ups"), ("pullups", "Pull-ups"), ("run_5k", "5K")], default="hybrid", max_length=16)),
                ("token", models.SlugField(blank=True, max_length=32, unique=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("created_by", models.ForeignKey(null=True, blank=True, on_delete=django.db.models.deletion.SET_NULL, related_name="challenge_rooms", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "ordering": ("-created_at",),
            },
        ),
        migrations.CreateModel(
            name="ChallengeRoomEntry",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("joined_at", models.DateTimeField(auto_now_add=True)),
                ("room", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="entries", to="main.challengeroom")),
                ("submission", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="challenge_room_entries", to="main.submission")),
            ],
            options={
                "ordering": ("joined_at",),
            },
        ),
        migrations.AddConstraint(
            model_name="challengeroomentry",
            constraint=models.UniqueConstraint(fields=("room", "submission"), name="unique_submission_per_challenge_room"),
        ),
    ]

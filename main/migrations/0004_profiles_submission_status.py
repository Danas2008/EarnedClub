from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
from django.utils.text import slugify


def backfill_status_and_profiles(apps, schema_editor):
    Submission = apps.get_model("main", "Submission")
    Profile = apps.get_model("main", "Profile")
    User = apps.get_model("auth", "User")

    for submission in Submission.objects.all():
        submission.status = "verified" if submission.verified else "pending"
        submission.save(update_fields=["status"])

    used_slugs = set(Profile.objects.values_list("slug", flat=True))
    for user in User.objects.all():
        if Profile.objects.filter(user=user).exists():
            continue
        display_name = user.get_full_name() or user.username
        base_slug = slugify(display_name) or slugify(user.username) or "athlete"
        slug = base_slug
        suffix = 2
        while slug in used_slugs:
            slug = f"{base_slug}-{suffix}"
            suffix += 1
        used_slugs.add(slug)
        Profile.objects.create(user=user, display_name=display_name, slug=slug)


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("main", "0003_newslettersubscriber"),
    ]

    operations = [
        migrations.AddField(
            model_name="submission",
            name="email",
            field=models.EmailField(blank=True, max_length=254),
        ),
        migrations.AddField(
            model_name="submission",
            name="status",
            field=models.CharField(
                choices=[
                    ("pending", "Pending"),
                    ("verified", "Verified"),
                    ("rejected", "Rejected"),
                ],
                default="pending",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="submission",
            name="user",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AlterField(
            model_name="submission",
            name="video_link",
            field=models.URLField(blank=True),
        ),
        migrations.CreateModel(
            name="Profile",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("display_name", models.CharField(max_length=100)),
                ("slug", models.SlugField(blank=True, max_length=120, unique=True)),
                ("profile_photo", models.URLField(blank=True)),
                ("bio", models.TextField(blank=True)),
                ("current_rank", models.PositiveIntegerField(blank=True, null=True)),
                ("personal_best_reps", models.PositiveIntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "user",
                    models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL),
                ),
            ],
            options={
                "ordering": ("display_name",),
            },
        ),
        migrations.RunPython(backfill_status_and_profiles, migrations.RunPython.noop),
    ]

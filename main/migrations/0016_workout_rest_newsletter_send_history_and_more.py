import django.utils.crypto
from django.db import migrations, models
import django.db.models.deletion


def seed_unsubscribe_tokens(apps, schema_editor):
    NewsletterSubscriber = apps.get_model("main", "NewsletterSubscriber")
    for subscriber in NewsletterSubscriber.objects.filter(unsubscribe_token=""):
        token = django.utils.crypto.get_random_string(32)
        while NewsletterSubscriber.objects.filter(unsubscribe_token=token).exclude(pk=subscriber.pk).exists():
            token = django.utils.crypto.get_random_string(32)
        subscriber.unsubscribe_token = token
        subscriber.save(update_fields=["unsubscribe_token"])


class Migration(migrations.Migration):

    dependencies = [
        ("main", "0015_newslettersegment"),
    ]

    operations = [
        migrations.AddField(
            model_name="workout",
            name="rest_interval_seconds",
            field=models.PositiveIntegerField(default=60),
        ),
        migrations.AddField(
            model_name="newslettersubscriber",
            name="unsubscribe_token",
            field=models.CharField(blank=True, max_length=48),
        ),
        migrations.AddField(
            model_name="newslettersubscriber",
            name="unsubscribed_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.RunPython(seed_unsubscribe_tokens, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="newslettersubscriber",
            name="unsubscribe_token",
            field=models.CharField(blank=True, max_length=48, unique=True),
        ),
        migrations.CreateModel(
            name="NewsletterSendEvent",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("subject", models.CharField(max_length=180)),
                ("sent_at", models.DateTimeField(auto_now_add=True)),
                (
                    "campaign",
                    models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="send_events", to="main.newslettercampaign"),
                ),
                (
                    "subscriber",
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="send_events", to="main.newslettersubscriber"),
                ),
            ],
            options={
                "ordering": ("-sent_at",),
            },
        ),
        migrations.AddConstraint(
            model_name="workout",
            constraint=models.UniqueConstraint(condition=models.Q(("highlighted_on_profile", True)), fields=("user",), name="unique_highlighted_workout_per_user"),
        ),
    ]

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("main", "0014_newslettercampaign"),
    ]

    operations = [
        migrations.CreateModel(
            name="NewsletterSegment",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=120, unique=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "subscribers",
                    models.ManyToManyField(blank=True, related_name="segments", to="main.newslettersubscriber"),
                ),
            ],
            options={
                "ordering": ("name",),
            },
        ),
    ]

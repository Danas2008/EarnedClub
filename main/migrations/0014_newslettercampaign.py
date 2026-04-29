from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("main", "0013_workoutsession_workoutsessionexercise"),
    ]

    operations = [
        migrations.CreateModel(
            name="NewsletterCampaign",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("week_number", models.PositiveIntegerField()),
                ("subject", models.CharField(max_length=180)),
                ("body", models.TextField()),
                ("sent_at", models.DateTimeField(blank=True, null=True)),
                ("sent_count", models.PositiveIntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "ordering": ("-week_number", "-created_at"),
            },
        ),
    ]

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("main", "0016_workout_rest_newsletter_send_history_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="submission",
            name="discipline",
            field=models.CharField(
                choices=[
                    ("pushups", "Push-ups"),
                    ("pullups", "Pull-ups"),
                    ("5k", "5K run"),
                    ("10k", "10K run"),
                ],
                default="pushups",
                max_length=16,
            ),
        ),
    ]

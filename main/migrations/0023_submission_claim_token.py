from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("main", "0022_challengeroomentry_participant_key"),
    ]

    operations = [
        migrations.AddField(
            model_name="submission",
            name="claim_token",
            field=models.CharField(blank=True, default="", db_index=True, max_length=64),
        ),
    ]

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("main", "0021_challengeroom_challengeroomentry"),
    ]

    operations = [
        migrations.AddField(
            model_name="challengeroomentry",
            name="participant_key",
            field=models.CharField(blank=True, db_index=True, max_length=80),
        ),
    ]

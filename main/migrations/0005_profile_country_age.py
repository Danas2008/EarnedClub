from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("main", "0004_alter_submission_options"),
        ("main", "0004_profiles_submission_status"),
    ]

    operations = [
        migrations.AddField(
            model_name="profile",
            name="age",
            field=models.PositiveSmallIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="profile",
            name="country",
            field=models.CharField(blank=True, max_length=80),
        ),
    ]

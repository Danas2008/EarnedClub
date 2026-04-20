from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("main", "0004_profiles_submission_status"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="submission",
            options={"ordering": ("-reps", "created_at")},
        ),
    ]

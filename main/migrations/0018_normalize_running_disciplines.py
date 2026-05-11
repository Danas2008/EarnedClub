from django.db import migrations, models


def forwards(apps, schema_editor):
    Submission = apps.get_model("main", "Submission")
    Submission.objects.filter(discipline="5k").update(discipline="run_5k")
    Submission.objects.filter(discipline="10k").update(discipline="run_10k")


def backwards(apps, schema_editor):
    Submission = apps.get_model("main", "Submission")
    Submission.objects.filter(discipline="run_5k").update(discipline="5k")
    Submission.objects.filter(discipline="run_10k").update(discipline="10k")


class Migration(migrations.Migration):

    dependencies = [
        ("main", "0017_submission_discipline"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
        migrations.AlterField(
            model_name="submission",
            name="discipline",
            field=models.CharField(
                choices=[
                    ("pushups", "Push-ups"),
                    ("pullups", "Pull-ups"),
                    ("run_5k", "5K run"),
                    ("run_10k", "10K run"),
                ],
                default="pushups",
                max_length=16,
            ),
        ),
    ]

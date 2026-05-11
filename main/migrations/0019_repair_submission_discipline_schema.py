from django.db import migrations, models


def repair_submission_discipline(apps, schema_editor):
    Submission = apps.get_model("main", "Submission")
    table_name = Submission._meta.db_table
    existing_columns = {
        column.name
        for column in schema_editor.connection.introspection.get_table_description(
            schema_editor.connection.cursor(),
            table_name,
        )
    }

    if "discipline" not in existing_columns:
        field = models.CharField(
            choices=[
                ("pushups", "Push-ups"),
                ("pullups", "Pull-ups"),
                ("run_5k", "5K run"),
                ("run_10k", "10K run"),
            ],
            default="pushups",
            max_length=16,
        )
        field.set_attributes_from_name("discipline")
        schema_editor.add_field(Submission, field)

    Submission.objects.filter(discipline__isnull=True).update(discipline="pushups")
    Submission.objects.filter(discipline="").update(discipline="pushups")
    Submission.objects.filter(discipline="5k").update(discipline="run_5k")
    Submission.objects.filter(discipline="10k").update(discipline="run_10k")


class Migration(migrations.Migration):

    dependencies = [
        ("main", "0018_normalize_running_disciplines"),
    ]

    operations = [
        migrations.RunPython(repair_submission_discipline, migrations.RunPython.noop),
    ]

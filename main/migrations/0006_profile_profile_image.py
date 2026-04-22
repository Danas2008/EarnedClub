from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("main", "0005_profile_country_age"),
    ]

    operations = [
        migrations.AddField(
            model_name="profile",
            name="profile_image",
            field=models.FileField(blank=True, upload_to="profile_photos/"),
        ),
    ]

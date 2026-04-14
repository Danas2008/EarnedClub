from django.db import models

# Create your models here.

class Submission(models.Model):
    name = models.CharField(max_length=100)
    pushups = models.IntegerField()
    video_link = models.URLField()
    verified = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name} - {self.pushups}"
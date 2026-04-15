from django.db import models

class Submission(models.Model):
    name = models.CharField(max_length=100)
    reps = models.IntegerField()
    video_link = models.URLField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name} - {self.reps}"
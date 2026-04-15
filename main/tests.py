from django.test import TestCase
from django.urls import reverse

from .models import Submission


class SubmissionFlowTests(TestCase):
    def test_challenge_submission_creates_unverified_record(self):
        response = self.client.post(
            reverse("challenge"),
            {
                "name": "Alex",
                "reps": 42,
                "video_link": "https://example.com/video",
            },
        )

        self.assertRedirects(response, reverse("challenge"))
        submission = Submission.objects.get(name="Alex")
        self.assertEqual(submission.reps, 42)
        self.assertFalse(submission.verified)

    def test_challenge_submission_shows_success_message(self):
        response = self.client.post(
            reverse("challenge"),
            {
                "name": "Jordan",
                "reps": 33,
                "video_link": "https://example.com/proof",
            },
            follow=True,
        )

        self.assertContains(response, "Submission received.")

    def test_leaderboard_shows_only_verified_submissions(self):
        Submission.objects.create(
            name="Visible Athlete",
            reps=55,
            video_link="https://example.com/visible",
            verified=True,
        )
        Submission.objects.create(
            name="Hidden Athlete",
            reps=99,
            video_link="https://example.com/hidden",
            verified=False,
        )

        response = self.client.get(reverse("leaderboard"))

        self.assertContains(response, "Visible Athlete")
        self.assertNotContains(response, "Hidden Athlete")

import shutil
import tempfile
from datetime import timedelta
from unittest.mock import patch
from xml.etree import ElementTree

from django.core.files.uploadedfile import SimpleUploadedFile
from django.contrib.auth.models import User
from django.db import IntegrityError
from django.test import TestCase
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from .models import (
    ContentEnginePrompt,
    ChallengeRoom,
    ChallengeRoomEntry,
    Follow,
    NewsletterSubscriber,
    NewsletterSendEvent,
    NewsletterSegment,
    Profile,
    Submission,
    VerificationEvent,
    Workout,
    WorkoutSession,
    calculate_submission_points,
    get_rank_tier,
)


class SubmissionFlowTests(TestCase):
    def setUp(self):
        super().setUp()
        self._media_root = tempfile.mkdtemp()
        self.settings_override = override_settings(MEDIA_ROOT=self._media_root)
        self.settings_override.enable()
        self.addCleanup(self.settings_override.disable)
        self.addCleanup(lambda: shutil.rmtree(self._media_root, ignore_errors=True))

    def proof_video(self, name="proof.mp4"):
        return SimpleUploadedFile(name, b"fake video content", content_type="video/mp4")

    def test_challenge_submission_creates_unverified_record(self):
        response = self.client.post(
            reverse("challenge"),
            {
                "name": "Alex",
                "email": "alex@example.com",
                "reps": 40,
                "video_file": self.proof_video(),
            },
        )

        self.assertRedirects(response, reverse("challenge"))
        submission = Submission.objects.get(name="Alex")
        self.assertEqual(submission.reps, 40)
        self.assertFalse(submission.verified)
        self.assertEqual(submission.status, Submission.STATUS_PENDING)
        self.assertEqual(submission.video_link, "")
        self.assertEqual(submission.email, "alex@example.com")

    def test_anonymous_submission_above_40_is_blocked(self):
        response = self.client.post(
            reverse("challenge"),
            {
                "name": "Too High",
                "email": "high@example.com",
                "reps": 41,
            },
            follow=True,
        )

        self.assertEqual(Submission.objects.filter(email="high@example.com").count(), 0)
        self.assertContains(response, "Anonymous push-up submissions above 40 need login and video proof.")

    def test_logged_in_submission_above_60_requires_proof(self):
        user = User.objects.create_user(username="elite-no-proof", password="StrongPass12345")
        self.client.force_login(user)

        response = self.client.post(reverse("challenge"), {"reps": 60}, follow=True)

        self.assertEqual(Submission.objects.filter(user=user).count(), 0)
        self.assertContains(response, "elite-level results need proof")

    def test_challenge_submission_without_proof_becomes_unverified(self):
        response = self.client.post(
            reverse("challenge"),
            {
                "name": "No Proof",
                "email": "noproof@example.com",
                "reps": 21,
            },
            follow=True,
        )

        self.assertRedirects(response, reverse("challenge"))
        submission = Submission.objects.get(name="No Proof")
        self.assertEqual(submission.status, Submission.STATUS_UNVERIFIED)
        self.assertContains(response, "You are now on the open leaderboard. Add proof to make it official.")
        self.assertContains(response, "Open Leaderboard")
        self.assertContains(response, "Claim Your Athlete Profile")

    def test_anonymous_unverified_submission_can_be_completed_with_proof(self):
        self.client.post(
            reverse("challenge"),
            {
                "name": "No Proof",
                "email": "noproof@example.com",
                "reps": 21,
            },
        )

        response = self.client.post(
            reverse("challenge"),
            {
                "name": "No Proof",
                "email": "noproof@example.com",
                "reps": 24,
                "video_file": self.proof_video(),
            },
            follow=True,
        )

        self.assertEqual(Submission.objects.filter(email="noproof@example.com").count(), 1)
        submission = Submission.objects.get(email="noproof@example.com")
        self.assertEqual(submission.status, Submission.STATUS_PENDING)
        self.assertEqual(submission.reps, 24)
        self.assertEqual(submission.video_link, "")
        self.assertTrue(submission.has_proof)
        self.assertContains(response, "Your result is pending review. If approved, your official rank will update.")

    def test_challenge_submission_shows_success_message(self):
        Submission.objects.create(
            name="Top Athlete",
            reps=50,
            video_link="https://example.com/top",
            verified=True,
        )
        response = self.client.post(
            reverse("challenge"),
            {
                "name": "Jordan",
                "email": "jordan@example.com",
                "reps": 33,
                "video_file": self.proof_video(),
            },
            follow=True,
        )

        self.assertContains(response, "Your result is pending review. If approved, your official rank will update.")

    def test_leaderboard_shows_all_submissions_with_verification_status(self):
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
            status=Submission.STATUS_PENDING,
        )
        Submission.objects.create(
            name="Open Board Athlete",
            reps=25,
            status=Submission.STATUS_UNVERIFIED,
        )

        response = self.client.get(f"{reverse('leaderboard')}?discipline={Submission.DISCIPLINE_PUSHUPS}")

        self.assertContains(response, "Visible Athlete")
        self.assertContains(response, "Hidden Athlete")
        self.assertContains(response, "Open Board Athlete")
        self.assertContains(response, "Verified")
        self.assertContains(response, "Pending")
        self.assertContains(response, "Unverified")
        self.assertContains(response, "Waiting for verification")

    def test_leaderboard_verified_mode_uses_official_results_only(self):
        verified = Submission.objects.create(
            name="Verified Mode",
            reps=55,
            video_link="https://example.com/verified-mode",
            status=Submission.STATUS_VERIFIED,
        )
        Submission.objects.create(
            name="Pending Mode",
            reps=99,
            video_link="https://example.com/pending-mode",
            status=Submission.STATUS_PENDING,
        )

        response = self.client.get(f"{reverse('leaderboard')}?discipline={Submission.DISCIPLINE_PUSHUPS}&mode=verified")
        rows = list(response.context["leaderboard_rows"].object_list)

        self.assertEqual([row["submission"] for row in rows], [verified])
        self.assertEqual(response.context["active_mode"]["key"], "verified")

    def test_default_leaderboard_is_hybrid_score(self):
        user = User.objects.create_user(username="hybrid-default", password="StrongPass12345")
        user.profile.display_name = "Hybrid Default"
        user.profile.save()
        Submission.objects.create(user=user, name="Hybrid Default", reps=40, status=Submission.STATUS_VERIFIED)

        response = self.client.get(reverse("leaderboard"))

        self.assertTrue(response.context["is_hybrid_leaderboard"])
        self.assertContains(response, "Hybrid Default")
        self.assertContains(response, "Hybrid Score")

    def test_hybrid_score_averages_verified_discipline_points_only(self):
        user = User.objects.create_user(username="hybrid-score", password="StrongPass12345")
        Submission.objects.create(user=user, name="Hybrid Score", reps=40, discipline=Submission.DISCIPLINE_PUSHUPS, status=Submission.STATUS_VERIFIED)
        Submission.objects.create(user=user, name="Hybrid Score", reps=15, discipline=Submission.DISCIPLINE_PULLUPS, status=Submission.STATUS_VERIFIED)
        Submission.objects.create(user=user, name="Hybrid Score", reps=80, discipline=Submission.DISCIPLINE_PUSHUPS, status=Submission.STATUS_UNVERIFIED)
        self.client.force_login(user)

        response = self.client.get(reverse("dashboard"))

        self.assertEqual(response.context["hybrid_summary"]["score"], 562)
        pushups = next(item for item in response.context["hybrid_summary"]["breakdown"] if item["discipline"]["key"] == Submission.DISCIPLINE_PUSHUPS)
        pullups = next(item for item in response.context["hybrid_summary"]["breakdown"] if item["discipline"]["key"] == Submission.DISCIPLINE_PULLUPS)
        self.assertEqual(pushups["points"], 450)
        self.assertEqual(pullups["points"], 675)

    def test_discipline_points_are_balanced_by_rank_tier(self):
        advanced_scores = [
            calculate_submission_points(Submission(reps=42, discipline=Submission.DISCIPLINE_PUSHUPS)),
            calculate_submission_points(Submission(reps=11, discipline=Submission.DISCIPLINE_PULLUPS)),
            calculate_submission_points(Submission(reps=21 * 60 + 34, discipline=Submission.DISCIPLINE_5K)),
            calculate_submission_points(Submission(reps=45 * 60, discipline=Submission.DISCIPLINE_10K)),
        ]

        for score in advanced_scores:
            self.assertGreaterEqual(score, 450)
            self.assertLessEqual(score, 750)

        elite_scores = [
            calculate_submission_points(Submission(reps=70, discipline=Submission.DISCIPLINE_PUSHUPS)),
            calculate_submission_points(Submission(reps=20, discipline=Submission.DISCIPLINE_PULLUPS)),
            calculate_submission_points(Submission(reps=18 * 60, discipline=Submission.DISCIPLINE_5K)),
            calculate_submission_points(Submission(reps=38 * 60, discipline=Submission.DISCIPLINE_10K)),
        ]
        self.assertTrue(all(score >= 750 for score in elite_scores))

    def test_discipline_points_match_current_public_thresholds(self):
        thresholds = [
            (Submission.DISCIPLINE_PUSHUPS, 20, 250),
            (Submission.DISCIPLINE_PUSHUPS, 40, 450),
            (Submission.DISCIPLINE_PUSHUPS, 50, 600),
            (Submission.DISCIPLINE_PUSHUPS, 70, 850),
            (Submission.DISCIPLINE_PUSHUPS, 85, 950),
            (Submission.DISCIPLINE_PUSHUPS, 100, 1000),
            (Submission.DISCIPLINE_PULLUPS, 5, 250),
            (Submission.DISCIPLINE_PULLUPS, 10, 500),
            (Submission.DISCIPLINE_PULLUPS, 15, 675),
            (Submission.DISCIPLINE_PULLUPS, 20, 800),
            (Submission.DISCIPLINE_PULLUPS, 30, 950),
            (Submission.DISCIPLINE_PULLUPS, 35, 1000),
            (Submission.DISCIPLINE_5K, 30 * 60, 250),
            (Submission.DISCIPLINE_5K, 25 * 60, 450),
            (Submission.DISCIPLINE_5K, 22 * 60, 600),
            (Submission.DISCIPLINE_5K, 18 * 60, 850),
            (Submission.DISCIPLINE_5K, 16 * 60, 950),
            (Submission.DISCIPLINE_5K, 15 * 60, 1000),
            (Submission.DISCIPLINE_10K, 60 * 60, 250),
            (Submission.DISCIPLINE_10K, 50 * 60, 450),
            (Submission.DISCIPLINE_10K, 44 * 60, 600),
            (Submission.DISCIPLINE_10K, 38 * 60, 800),
            (Submission.DISCIPLINE_10K, 34 * 60, 900),
            (Submission.DISCIPLINE_10K, 32 * 60, 950),
            (Submission.DISCIPLINE_10K, 30 * 60, 1000),
        ]

        for discipline, value, expected in thresholds:
            with self.subTest(discipline=discipline, value=value):
                self.assertEqual(calculate_submission_points(Submission(reps=value, discipline=discipline)), expected)

    def test_hybrid_leaderboard_sorts_by_hybrid_score(self):
        lower = User.objects.create_user(username="lower-hybrid", password="StrongPass12345")
        higher = User.objects.create_user(username="higher-hybrid", password="StrongPass12345")
        lower.profile.display_name = "Lower Hybrid"
        lower.profile.save()
        higher.profile.display_name = "Higher Hybrid"
        higher.profile.save()
        Submission.objects.create(user=lower, name="Lower Hybrid", reps=24, discipline=Submission.DISCIPLINE_PUSHUPS, status=Submission.STATUS_VERIFIED)
        Submission.objects.create(user=higher, name="Higher Hybrid", reps=72, discipline=Submission.DISCIPLINE_PUSHUPS, status=Submission.STATUS_VERIFIED)

        response = self.client.get(reverse("leaderboard"))
        rows = list(response.context["leaderboard_rows"].object_list)

        self.assertEqual([row["profile"].display_name for row in rows], ["Higher Hybrid", "Lower Hybrid"])

    def test_hybrid_leaderboard_includes_verified_anonymous_athletes(self):
        Submission.objects.create(
            name="Anonymous Hybrid",
            email="anonymous-hybrid@example.com",
            reps=70,
            discipline=Submission.DISCIPLINE_PUSHUPS,
            status=Submission.STATUS_VERIFIED,
        )
        Submission.objects.create(
            name="Anonymous Hybrid",
            email="anonymous-hybrid@example.com",
            reps=20,
            discipline=Submission.DISCIPLINE_PULLUPS,
            status=Submission.STATUS_VERIFIED,
        )

        response = self.client.get(reverse("leaderboard"))

        self.assertContains(response, "Anonymous Hybrid")
        rows = list(response.context["leaderboard_rows"].object_list)
        anonymous = next(row for row in rows if row["display_name"] == "Anonymous Hybrid")
        self.assertTrue(anonymous["is_anonymous"])
        self.assertEqual(anonymous["verified_count"], 2)

    def test_hybrid_leaderboard_includes_eligible_unverified_results(self):
        Submission.objects.create(
            name="Open Hybrid",
            email="",
            reps=50,
            discipline=Submission.DISCIPLINE_PUSHUPS,
            status=Submission.STATUS_UNVERIFIED,
        )

        response = self.client.get(reverse("leaderboard"))

        self.assertContains(response, "Open Hybrid")
        rows = list(response.context["leaderboard_rows"].object_list)
        open_row = next(row for row in rows if row["display_name"] == "Open Hybrid")
        self.assertEqual(open_row["hybrid_score"], 600)
        self.assertEqual(open_row["status_label"], "Unofficial")

    def test_hybrid_leaderboard_uses_discipline_table_labels(self):
        Submission.objects.create(
            name="Header Hybrid",
            reps=32,
            discipline=Submission.DISCIPLINE_PUSHUPS,
            status=Submission.STATUS_UNVERIFIED,
        )

        response = self.client.get(reverse("leaderboard"))

        self.assertContains(response, "<th>Rank</th>", html=False)
        self.assertContains(response, "<th>Position</th>", html=False)
        self.assertNotContains(response, "<th>Label</th>", html=False)
        self.assertContains(response, "Unofficial")
        self.assertContains(response, "Open Board")
        self.assertContains(response, "Verified Only")
        self.assertContains(response, "leaderboard-tier-card rank-advanced")
        self.assertContains(response, "tag-pill rank-pill rank-")

    def test_hybrid_leaderboard_mode_filters_work(self):
        Submission.objects.create(
            name="Pending Hybrid",
            reps=32,
            discipline=Submission.DISCIPLINE_PUSHUPS,
            status=Submission.STATUS_PENDING,
            video_link="https://example.com/proof",
        )
        Submission.objects.create(
            name="Unverified Hybrid",
            reps=30,
            discipline=Submission.DISCIPLINE_PUSHUPS,
            status=Submission.STATUS_UNVERIFIED,
        )

        pending_response = self.client.get(f"{reverse('leaderboard')}?discipline=hybrid&mode=pending")
        unverified_response = self.client.get(f"{reverse('leaderboard')}?discipline=hybrid&mode=unverified")
        pending_names = [row["display_name"] for row in pending_response.context["leaderboard_rows"].object_list]
        unverified_names = [row["display_name"] for row in unverified_response.context["leaderboard_rows"].object_list]

        self.assertIn("Pending Hybrid", pending_names)
        self.assertNotIn("Unverified Hybrid", pending_names)
        self.assertIn("Unverified Hybrid", unverified_names)
        self.assertNotIn("Pending Hybrid", unverified_names)

    def test_hybrid_leaderboard_hides_strong_unverified_without_proof(self):
        Submission.objects.create(
            name="Needs Proof Hybrid",
            email="",
            reps=100,
            discipline=Submission.DISCIPLINE_PUSHUPS,
            status=Submission.STATUS_UNVERIFIED,
        )

        response = self.client.get(reverse("leaderboard"))

        self.assertNotContains(response, "Needs Proof Hybrid")
        rows = list(response.context["leaderboard_rows"].object_list)
        self.assertFalse(any(row["display_name"] == "Needs Proof Hybrid" for row in rows))

    def test_hybrid_leaderboard_averages_verified_and_unverified_open_results(self):
        user = User.objects.create_user(username="open-hybrid-user", password="StrongPass12345")
        user.profile.display_name = "Open Hybrid User"
        user.profile.save()
        Submission.objects.create(user=user, name="Open Hybrid User", reps=20, discipline=Submission.DISCIPLINE_PUSHUPS, status=Submission.STATUS_VERIFIED)
        Submission.objects.create(user=user, name="Open Hybrid User", reps=10, discipline=Submission.DISCIPLINE_PULLUPS, status=Submission.STATUS_UNVERIFIED)

        response = self.client.get(reverse("leaderboard"))
        rows = list(response.context["leaderboard_rows"].object_list)
        open_row = next(row for row in rows if row["display_name"] == "Open Hybrid User")

        self.assertEqual(open_row["hybrid_score"], 375)
        self.assertEqual(open_row["verified_count"], 1)
        self.assertEqual(open_row["open_count"], 2)

    def test_home_and_leaderboard_show_real_recent_activity(self):
        submission = Submission.objects.create(
            name="Activity Alex",
            reps=32,
            discipline=Submission.DISCIPLINE_PUSHUPS,
            status=Submission.STATUS_UNVERIFIED,
        )
        VerificationEvent.objects.create(
            submission=submission,
            action=VerificationEvent.ACTION_PROOF_ADDED,
        )

        home_response = self.client.get(reverse("home"))
        leaderboard_response = self.client.get(reverse("leaderboard"))

        self.assertContains(home_response, "Recent activity")
        self.assertContains(home_response, "Activity Alex submitted 32 push-ups")
        self.assertContains(home_response, "Activity Alex added proof for Push-ups")
        self.assertContains(leaderboard_response, "Recent activity")
        self.assertContains(leaderboard_response, "Activity Alex submitted 32 push-ups")

    def test_leaderboard_empty_state_invites_first_entry(self):
        response = self.client.get(reverse("leaderboard_discipline", args=[Submission.DISCIPLINE_PULLUPS]))

        self.assertContains(response, "No one owns this board yet. Be first.")
        self.assertContains(response, reverse("level_test"))

    def test_founding_athlete_status_appears_on_profile_and_leaderboard(self):
        user = User.objects.create_user(username="founding-user", password="StrongPass12345")
        user.profile.display_name = "Founding User"
        user.profile.save()
        Submission.objects.create(
            user=user,
            name="Founding User",
            reps=32,
            discipline=Submission.DISCIPLINE_PUSHUPS,
            status=Submission.STATUS_UNVERIFIED,
        )

        profile_response = self.client.get(reverse("athlete_profile", args=[user.profile.slug]))
        leaderboard_response = self.client.get(reverse("leaderboard"))

        self.assertContains(profile_response, "Founding athlete")
        self.assertContains(profile_response, "one of the first 100")
        self.assertContains(leaderboard_response, "Founding athlete")

    def test_profile_prioritizes_hybrid_score_and_breakdown(self):
        user = User.objects.create_user(username="hybrid-profile", password="StrongPass12345")
        Submission.objects.create(user=user, name="Hybrid Profile", reps=40, discipline=Submission.DISCIPLINE_PUSHUPS, status=Submission.STATUS_VERIFIED)
        Submission.objects.create(user=user, name="Hybrid Profile", reps=15, discipline=Submission.DISCIPLINE_PULLUPS, status=Submission.STATUS_VERIFIED)

        response = self.client.get(reverse("athlete_profile", args=[user.profile.slug]))

        self.assertContains(response, "Hybrid Score")
        self.assertContains(response, "500")
        self.assertContains(response, "Push-ups")
        self.assertContains(response, "Pull-ups")

    def test_legacy_submission_defaults_to_pushups(self):
        submission = Submission.objects.create(name="Legacy", reps=42, status=Submission.STATUS_VERIFIED)

        self.assertEqual(submission.discipline, Submission.DISCIPLINE_PUSHUPS)
        self.assertEqual(submission.display_score, "42 reps")

    def test_pullup_submission_works(self):
        response = self.client.post(
            reverse("challenge"),
            {
                "name": "Pull Athlete",
                "email": "pull@example.com",
                "discipline": Submission.DISCIPLINE_PULLUPS,
                "score": "12",
            },
            follow=True,
        )

        submission = Submission.objects.get(email="pull@example.com")
        self.assertRedirects(response, reverse("challenge"))
        self.assertEqual(submission.discipline, Submission.DISCIPLINE_PULLUPS)
        self.assertEqual(submission.reps, 12)
        self.assertEqual(submission.display_score, "12 reps")

    def test_run_time_submissions_work(self):
        self.client.post(
            reverse("challenge"),
            {
                "name": "Five Runner",
                "email": "five@example.com",
                "discipline": Submission.DISCIPLINE_5K,
                "score": "22:00",
            },
        )

        five = Submission.objects.get(email="five@example.com")
        self.assertEqual(five.reps, 1320)
        self.assertEqual(five.display_score, "22:00")

    def test_run_time_accepts_dot_separator_as_time(self):
        self.client.post(
            reverse("challenge"),
            {
                "name": "Dot Runner",
                "email": "dot-run@example.com",
                "discipline": Submission.DISCIPLINE_5K,
                "score": "22.00",
            },
        )

        submission = Submission.objects.get(email="dot-run@example.com")
        self.assertEqual(submission.reps, 22 * 60)
        self.assertEqual(submission.display_score, "22:00")

    def test_run_time_rejects_seconds_only_format(self):
        response = self.client.post(
            reverse("challenge"),
            {
                "name": "Bad Runner",
                "email": "bad-run@example.com",
                "discipline": Submission.DISCIPLINE_5K,
                "score": "930",
            },
            follow=True,
        )

        self.assertFalse(Submission.objects.filter(email="bad-run@example.com").exists())
        self.assertContains(response, "Use HH:MM:SS or MM:SS")

    def test_running_elite_requires_result_link_or_video(self):
        response = self.client.post(
            reverse("challenge"),
            {
                "name": "Elite Runner",
                "email": "elite-run@example.com",
                "discipline": Submission.DISCIPLINE_5K,
                "score": "17:59",
            },
            follow=True,
        )

        self.assertFalse(Submission.objects.filter(email="elite-run@example.com").exists())
        self.assertContains(response, "elite-level results need proof")

    def test_running_elite_accepts_proof_link(self):
        response = self.client.post(
            reverse("challenge"),
            {
                "name": "Linked Runner",
                "email": "linked-run@example.com",
                "discipline": Submission.DISCIPLINE_5K,
                "score": "17:59",
                "proof_link": "https://www.strava.com/activities/123",
            },
        )

        self.assertRedirects(response, reverse("challenge"))
        submission = Submission.objects.get(email="linked-run@example.com")
        self.assertEqual(submission.status, Submission.STATUS_PENDING)
        self.assertEqual(submission.video_link, "https://www.strava.com/activities/123")

    def test_running_score_cannot_be_faster_than_world_record(self):
        response = self.client.post(
            reverse("challenge"),
            {
                "name": "Impossible Runner",
                "email": "impossible@example.com",
                "discipline": Submission.DISCIPLINE_5K,
                "score": "12:30",
                "proof_link": "https://www.strava.com/activities/999",
            },
            follow=True,
        )

        self.assertFalse(Submission.objects.filter(email="impossible@example.com").exists())
        self.assertContains(response, "cannot be faster than")

    def test_pullup_elite_requires_proof(self):
        response = self.client.post(
            reverse("challenge"),
            {
                "name": "Pull Elite",
                "email": "pull-elite@example.com",
                "discipline": Submission.DISCIPLINE_PULLUPS,
                "score": "20",
            },
            follow=True,
        )

        self.assertFalse(Submission.objects.filter(email="pull-elite@example.com").exists())
        self.assertContains(response, "elite-level results need proof")

    def test_pullup_score_cannot_exceed_world_record_benchmark(self):
        response = self.client.post(
            reverse("challenge"),
            {
                "name": "Impossible Pull",
                "email": "impossible-pull@example.com",
                "discipline": Submission.DISCIPLINE_PULLUPS,
                "score": "83",
                "proof_link": "https://example.com/proof",
            },
            follow=True,
        )

        self.assertFalse(Submission.objects.filter(email="impossible-pull@example.com").exists())
        self.assertContains(response, "cannot be above")

    def test_leaderboard_sorts_reps_descending_and_time_ascending(self):
        low = Submission.objects.create(name="Lower Pull", reps=8, discipline=Submission.DISCIPLINE_PULLUPS, status=Submission.STATUS_VERIFIED)
        high = Submission.objects.create(name="Higher Pull", reps=18, discipline=Submission.DISCIPLINE_PULLUPS, status=Submission.STATUS_VERIFIED)
        fast = Submission.objects.create(name="Fast 5K", reps=1200, discipline=Submission.DISCIPLINE_5K, status=Submission.STATUS_VERIFIED)
        slow = Submission.objects.create(name="Slow 5K", reps=1500, discipline=Submission.DISCIPLINE_5K, status=Submission.STATUS_VERIFIED)

        pull_response = self.client.get(reverse("leaderboard_discipline", args=[Submission.DISCIPLINE_PULLUPS]))
        run_response = self.client.get(reverse("leaderboard_discipline", args=[Submission.DISCIPLINE_5K]))

        pull_rows = [row["submission"] for row in pull_response.context["leaderboard_rows"].object_list]
        run_rows = [row["submission"] for row in run_response.context["leaderboard_rows"].object_list]
        self.assertEqual(pull_rows, [high, low])
        self.assertEqual(run_rows, [fast, slow])

    def test_verified_only_official_logic_is_discipline_specific(self):
        Submission.objects.create(name="Pending Fast", reps=1100, discipline=Submission.DISCIPLINE_5K, status=Submission.STATUS_PENDING, video_link="https://example.com/proof")
        verified = Submission.objects.create(name="Verified Run", reps=1300, discipline=Submission.DISCIPLINE_5K, status=Submission.STATUS_VERIFIED)
        Submission.objects.create(name="Push Leader", reps=90, discipline=Submission.DISCIPLINE_PUSHUPS, status=Submission.STATUS_VERIFIED)

        response = self.client.get(f"{reverse('leaderboard_discipline', args=[Submission.DISCIPLINE_5K])}?mode=verified")
        rows = list(response.context["leaderboard_rows"].object_list)

        self.assertEqual([row["submission"] for row in rows], [verified])
        self.assertContains(response, "Official rank #1")

    def test_admin_review_shows_discipline_and_formatted_result(self):
        staff = User.objects.create_user(username="staff", password="StrongPass12345", is_staff=True)
        self.client.force_login(staff)
        Submission.objects.create(name="Review Run", reps=1294, discipline=Submission.DISCIPLINE_5K, status=Submission.STATUS_PENDING, video_link="https://example.com/proof")

        response = self.client.get(reverse("admin_review"))

        self.assertContains(response, "5K run")
        self.assertContains(response, "21:34")

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_challenge_submission_creates_audit_event_with_email_disabled(self):
        response = self.client.post(
            reverse("challenge"),
            {
                "name": "Notify",
                "email": "notify@example.com",
                "reps": 38,
                "video_file": self.proof_video(),
            },
            follow=True,
        )
        submission = Submission.objects.get(email="notify@example.com")

        self.assertContains(response, "Your result is pending review. If approved, your official rank will update.")
        self.assertTrue(
            VerificationEvent.objects.filter(
                submission=submission,
                action=VerificationEvent.ACTION_SUBMITTED,
            ).exists()
        )
        self.assertNotContains(response, "admin email could not be delivered")

    def test_proof_link_post_is_ignored_for_new_submissions(self):
        Submission.objects.create(
            name="Original",
            email="original@example.com",
            reps=40,
            status=Submission.STATUS_PENDING,
            video_link="https://example.com/shared-proof",
        )

        response = self.client.post(
            reverse("challenge"),
            {
                "name": "Copy",
                "email": "copy@example.com",
                "reps": 40,
                "video_link": "https://example.com/shared-proof",
            },
            follow=True,
        )

        self.assertEqual(Submission.objects.count(), 2)
        submission = Submission.objects.get(email="copy@example.com")
        self.assertEqual(submission.video_link, "")
        self.assertEqual(submission.status, Submission.STATUS_UNVERIFIED)
        self.assertContains(response, "You are now on the open leaderboard. Add proof to make it official.")

    def test_honeypot_submission_is_silently_ignored(self):
        response = self.client.post(
            reverse("challenge"),
            {
                "name": "Bot",
                "email": "bot@example.com",
                "reps": 44,
                "video_link": "https://example.com/bot",
                "website": "https://spam.example",
            },
            follow=True,
        )

        self.assertEqual(Submission.objects.count(), 0)
        self.assertContains(response, "Submission received.")

    def test_newsletter_signup_creates_subscriber(self):
        response = self.client.post(
            reverse("newsletter_signup"),
            {"email": "test@example.com"},
            follow=True,
        )

        self.assertRedirects(response, reverse("home"))
        self.assertTrue(NewsletterSubscriber.objects.filter(email="test@example.com").exists())
        self.assertContains(response, "You are in.")

    def test_submission_exposes_rank_name(self):
        submission = Submission.objects.create(
            name="Legend",
            reps=82,
            video_link="https://example.com/legend",
            verified=True,
        )

        self.assertEqual(submission.rank_name, "Earned Legend")

    def test_rank_tier_boundaries_match_plan(self):
        expectations = {
            0: "Beginner",
            19: "Beginner",
            20: "Intermediate",
            39: "Intermediate",
            40: "Advanced",
            59: "Advanced",
            60: "Elite",
            79: "Elite",
            80: "Earned Legend",
        }

        for reps, expected_name in expectations.items():
            with self.subTest(reps=reps):
                self.assertEqual(get_rank_tier(reps)["name"], expected_name)

    def test_rank_page_shows_tier_and_official_submit_cta(self):
        response = self.client.get(f"{reverse('rank')}?reps=42")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Find your Hybrid Score")
        self.assertContains(response, "480 pts")
        self.assertContains(response, "Submit Official Result")
        self.assertNotContains(response, "Prove Your Score")
        self.assertContains(response, f"{reverse('challenge')}?discipline=pushups&amp;score=42#submit-form-top", html=False)
        self.assertContains(response, "Hybrid Score Calculator")

    def test_calculators_page_includes_hybrid_score_and_discipline_tiers(self):
        response = self.client.get(reverse("calculators"))

        self.assertContains(response, "Hybrid Score")
        self.assertContains(response, "Discipline Tier")
        self.assertContains(response, "run_5k")
        self.assertContains(response, '<span class="tag-pill rank-pill rank-beginner" id="score-result-rank">Beginner Hybrid</span>', html=False)
        self.assertContains(response, '<input id="calc-5k" class="range-input" type="range" min="900" max="2400" step="5" value="1800">', html=False)
        self.assertNotContains(response, "run_10k")
        self.assertNotContains(response, "10K")
        self.assertContains(response, "Slower")
        self.assertContains(response, "Faster")

    def test_registration_creates_user_and_profile(self):
        response = self.client.post(
            reverse("register"),
            {
                "username": "athlete",
                "email": "athlete@example.com",
                "password1": "StrongPass12345",
                "password2": "StrongPass12345",
            },
        )

        self.assertRedirects(response, reverse("dashboard"))
        user = User.objects.get(username="athlete")
        self.assertEqual(user.email, "athlete@example.com")
        self.assertEqual(user.profile.display_name, "athlete")
        self.assertEqual(user.profile.slug, "athlete")

    def test_registration_accepts_six_character_password(self):
        response = self.client.post(
            reverse("register"),
            {
                "username": "sixpass",
                "email": "six@example.com",
                "password1": "z9Qv7p",
                "password2": "z9Qv7p",
            },
        )

        self.assertRedirects(response, reverse("dashboard"))
        self.assertTrue(User.objects.filter(username="sixpass").exists())

    def test_registration_accepts_unicode_username_with_spaces(self):
        response = self.client.post(
            reverse("register"),
            {
                "username": "Daniel Č Š",
                "email": "unicode@example.com",
                "password1": "StrongPass12345",
                "password2": "StrongPass12345",
            },
        )

        self.assertRedirects(response, reverse("dashboard"))
        user = User.objects.get(username="Daniel Č Š")
        self.assertEqual(user.profile.display_name, "Daniel Č Š")

    def test_register_prefills_name_and_email_from_quiz(self):
        response = self.client.get(f"{reverse('register')}?name=Daniel%20Test&email=daniel@example.com&reps=33")

        self.assertContains(response, 'value="daniel@example.com"')
        self.assertContains(response, "Daniel Test")

    def test_profile_slug_is_unique(self):
        first = User.objects.create_user(username="first")
        second = User.objects.create_user(username="second")
        first.profile.display_name = "Same Name"
        first.profile.slug = ""
        first.profile.save()
        second.profile.display_name = "Same Name"
        second.profile.slug = ""
        second.profile.save()

        self.assertEqual(first.profile.slug, "same-name")
        self.assertEqual(second.profile.slug, "same-name-2")

    def test_logged_in_submission_links_to_user(self):
        user = User.objects.create_user(
            username="linked",
            email="linked@example.com",
            password="StrongPass12345",
        )
        user.profile.display_name = "Linked Athlete"
        user.profile.save()
        self.client.force_login(user)

        self.client.post(
            reverse("challenge"),
            {
                "reps": 45,
                "video_link": "https://example.com/linked",
            },
        )

        submission = Submission.objects.get(user=user)
        self.assertEqual(submission.name, "Linked Athlete")
        self.assertEqual(submission.email, "linked@example.com")

    def test_duplicate_pending_submission_is_blocked_for_user(self):
        user = User.objects.create_user(username="pending", password="StrongPass12345")
        self.client.force_login(user)
        Submission.objects.create(user=user, name="Pending", reps=20, status=Submission.STATUS_PENDING, video_link="https://example.com/proof")

        response = self.client.post(reverse("challenge"), {"reps": 30}, follow=True)

        self.assertEqual(Submission.objects.filter(user=user).count(), 1)
        self.assertContains(response, "already have an active submission")

    def test_duplicate_pending_submission_is_blocked_for_email(self):
        Submission.objects.create(
            name="Anon",
            email="anon@example.com",
            reps=20,
            status=Submission.STATUS_PENDING,
            video_link="https://example.com/proof",
        )

        response = self.client.post(
            reverse("challenge"),
            {"name": "Anon", "email": "anon@example.com", "reps": 30},
            follow=True,
        )

        self.assertEqual(Submission.objects.filter(email="anon@example.com").count(), 1)
        self.assertContains(response, "already have an active submission")

    def test_dashboard_requires_login(self):
        response = self.client.get(reverse("dashboard"))

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response["Location"])

    def test_dashboard_counts_only_verified_submissions(self):
        user = User.objects.create_user(username="dash", password="StrongPass12345")
        self.client.force_login(user)
        Submission.objects.create(user=user, name="Dash", reps=30, status=Submission.STATUS_PENDING, video_link="https://example.com/proof")
        Submission.objects.create(user=user, name="Dash", reps=55, status=Submission.STATUS_VERIFIED)

        response = self.client.get(reverse("dashboard"))

        self.assertEqual(response.context["current_pr"], 55)
        self.assertEqual(response.context["total_submissions"], 2)
        self.assertEqual(response.context["total_verified"], 1)
        self.assertEqual(response.context["total_pending"], 1)
        self.assertEqual([point["reps"] for point in response.context["progress_data"]], [55])
        self.assertIn("hybrid", response.context["performance_progress"])
        self.assertIn("pushups", response.context["performance_progress"])

    def test_dashboard_exposes_selectable_hybrid_progress_series(self):
        user = User.objects.create_user(username="series", password="StrongPass12345")
        self.client.force_login(user)
        Submission.objects.create(user=user, name="Series", reps=40, discipline=Submission.DISCIPLINE_PUSHUPS, status=Submission.STATUS_VERIFIED)
        Submission.objects.create(user=user, name="Series", reps=12, discipline=Submission.DISCIPLINE_PULLUPS, status=Submission.STATUS_VERIFIED)
        Submission.objects.create(user=user, name="Series", reps=1294, discipline=Submission.DISCIPLINE_5K, status=Submission.STATUS_VERIFIED)

        response = self.client.get(reverse("dashboard"))
        progress = response.context["performance_progress"]

        self.assertContains(response, "Performance Progress")
        self.assertContains(response, "Hybrid Score")
        self.assertTrue(progress["hybrid"]["points"])
        self.assertEqual(progress["pullups"]["points"][-1]["display"], "12 reps")
        self.assertEqual(progress["run_5k"]["points"][-1]["display"], "21:34")

    def test_dashboard_supports_discipline_and_running_goals(self):
        user = User.objects.create_user(username="goal-disciplines", password="StrongPass12345")
        self.client.force_login(user)

        response = self.client.post(
            reverse("dashboard"),
            {
                "form_type": "goal",
                "goal_type": Submission.DISCIPLINE_5K,
                "target_value": "21:34",
                "note": "Race target",
                "is_public": "on",
            },
        )

        self.assertRedirects(response, reverse("dashboard"))
        goal = user.goals.get(goal_type=Submission.DISCIPLINE_5K)
        self.assertEqual(goal.target_value, 1294)
        self.assertEqual(goal.display_target, "21:34")

    def test_dashboard_goal_completion_opens_richer_goal_modal(self):
        user = User.objects.create_user(username="goal-modal", password="StrongPass12345")
        Submission.objects.create(
            user=user,
            name="Goal Modal",
            reps=40,
            discipline=Submission.DISCIPLINE_PUSHUPS,
            status=Submission.STATUS_VERIFIED,
        )
        goal = user.goals.create(goal_type=Submission.DISCIPLINE_PUSHUPS, target_value=50)
        Submission.objects.create(
            user=user,
            name="Goal Modal",
            reps=50,
            discipline=Submission.DISCIPLINE_PUSHUPS,
            status=Submission.STATUS_VERIFIED,
        )
        self.client.force_login(user)

        response = self.client.get(reverse("dashboard"))

        self.assertContains(response, "Goal completed")
        self.assertContains(response, "50 Push-ups Achieved")
        self.assertContains(response, "Advanced -> Elite Push-ups")
        self.assertContains(response, "Next Suggested Goal")
        self.assertContains(response, "60 Push-ups")
        self.assertContains(response, "data-goal-modal")
        self.assertContains(response, f'data-goal-delete-url="{reverse("delete_goal", args=[goal.id])}"', html=False)

    def test_goal_target_must_improve_current_best(self):
        user = User.objects.create_user(username="goal-validation", password="StrongPass12345")
        Submission.objects.create(user=user, name="Goal Validation", reps=42, discipline=Submission.DISCIPLINE_PUSHUPS, status=Submission.STATUS_VERIFIED)
        Submission.objects.create(user=user, name="Goal Validation", reps=1294, discipline=Submission.DISCIPLINE_5K, status=Submission.STATUS_VERIFIED)
        self.client.force_login(user)

        response = self.client.post(
            reverse("dashboard"),
            {"form_type": "goal", "goal_exercise": "pushups", "goal_kind": "target", "target_value": "40"},
            follow=True,
        )
        self.assertContains(response, "Goal target must be higher")
        self.assertEqual(user.goals.count(), 0)

        response = self.client.post(
            reverse("dashboard"),
            {"form_type": "goal", "goal_exercise": "run_5k", "goal_kind": "target", "target_value": "22:00"},
            follow=True,
        )
        self.assertContains(response, "Running goals must be faster")
        self.assertEqual(user.goals.count(), 0)

    def test_rank_goal_only_allows_higher_tiers(self):
        user = User.objects.create_user(username="rank-goal-validation", password="StrongPass12345")
        Submission.objects.create(user=user, name="Rank Goal", reps=42, discipline=Submission.DISCIPLINE_PUSHUPS, status=Submission.STATUS_VERIFIED)
        self.client.force_login(user)

        response = self.client.post(
            reverse("dashboard"),
            {"form_type": "goal", "goal_exercise": "pushups", "goal_kind": "rank", "rank_target": "40"},
            follow=True,
        )

        self.assertContains(response, "Choose a rank above your current level.")
        self.assertFalse(user.goals.exists())

    def test_rank_page_estimates_hybrid_score_breakdown(self):
        response = self.client.get(f"{reverse('rank')}?pushups=42&pullups=10&run_5k=21:34")

        self.assertContains(response, "Estimated Hybrid Score")
        self.assertContains(response, "Push-ups")
        self.assertContains(response, "Pull-ups")
        self.assertContains(response, "5K")
        self.assertContains(response, "21:34")
        self.assertEqual(response.context["hybrid_estimate"]["verified_count"], 3)

    def test_rank_page_hides_estimate_before_calculation(self):
        response = self.client.get(reverse("rank"))

        self.assertContains(response, "Enter Performances")
        self.assertNotContains(response, "Estimated Hybrid Score")
        self.assertNotContains(response, "Discipline breakdown")

    def test_level_test_is_fast_single_discipline_funnel(self):
        response = self.client.get(reverse("level_test"))

        self.assertContains(response, "What is your strongest discipline?")
        self.assertContains(response, 'value="pushups"', html=False)
        self.assertContains(response, 'value="pullups"', html=False)
        self.assertContains(response, 'value="run_5k"', html=False)
        self.assertNotContains(response, 'value="run_10k"', html=False)
        self.assertNotContains(response, "10K")
        self.assertContains(response, "Where should we send your result?")
        self.assertContains(response, "Skip Email")
        self.assertContains(response, "Result required")
        self.assertContains(response, "Post My Result")
        self.assertContains(response, 'method="POST" action="{}"'.format(reverse("level_test")), html=False)

    def test_level_test_posts_result_and_shows_success_step(self):
        response = self.client.post(
            reverse("level_test"),
            {
                "name": "Fast Test",
                "discipline": Submission.DISCIPLINE_PUSHUPS,
                "score": "48",
            },
            follow=True,
        )

        self.assertContains(response, "You're in!")
        self.assertContains(response, "You're on the open leaderboard")
        self.assertContains(response, "Hybrid Score incomplete")
        self.assertContains(response, "1/3 disciplines completed")
        self.assertContains(response, "Continue with Pull-ups")
        self.assertContains(response, "Add 5K time")
        self.assertContains(response, "Make Your Score Official")
        self.assertContains(response, "Claim Your Athlete Profile")
        self.assertContains(response, "Challenge a Friend")
        self.assertContains(response, "See Yourself On The Leaderboard")
        submission = Submission.objects.get(name="Fast Test")
        self.assertEqual(submission.status, Submission.STATUS_UNVERIFIED)
        self.assertEqual(submission.email, "")
        self.assertContains(response, reverse("test_submission_proof", args=[submission.id]), html=False)

    def test_level_test_make_official_adds_proof_to_existing_result(self):
        self.client.post(
            reverse("level_test"),
            {
                "name": "Proof Session",
                "discipline": Submission.DISCIPLINE_PUSHUPS,
                "score": "36",
            },
        )
        submission = Submission.objects.get(name="Proof Session")

        get_response = self.client.get(reverse("test_submission_proof", args=[submission.id]))
        post_response = self.client.post(
            reverse("test_submission_proof", args=[submission.id]),
            {"proof_link": "https://example.com/proof"},
            follow=True,
        )

        submission.refresh_from_db()
        self.assertContains(get_response, "This adds proof to your existing Push-ups result")
        self.assertEqual(Submission.objects.filter(name="Proof Session").count(), 1)
        self.assertEqual(submission.status, Submission.STATUS_PENDING)
        self.assertEqual(submission.video_link, "https://example.com/proof")
        self.assertContains(post_response, "Proof added. This result is now waiting for review.")
        self.assertContains(post_response, "Pending")

    def test_session_proof_route_rejects_unrelated_submission(self):
        submission = Submission.objects.create(name="Other Session", reps=22, status=Submission.STATUS_UNVERIFIED)

        response = self.client.get(reverse("test_submission_proof", args=[submission.id]), follow=True)

        self.assertRedirects(response, reverse("level_test"))
        self.assertContains(response, "Open your own test result before adding proof.")

    def test_level_test_preserves_identity_and_continues_next_discipline(self):
        self.client.post(
            reverse("level_test"),
            {
                "name": "Journey Athlete",
                "age": "24",
                "email": "journey@example.com",
                "discipline": Submission.DISCIPLINE_PUSHUPS,
                "score": "32",
            },
        )

        next_response = self.client.get(f"{reverse('level_test')}?discipline={Submission.DISCIPLINE_PULLUPS}")
        self.assertContains(next_response, 'value="Journey Athlete"', html=False)
        self.assertContains(next_response, 'value="24"', html=False)
        self.assertContains(next_response, 'value="journey@example.com"', html=False)
        self.assertContains(next_response, "Continuing as Journey Athlete")

        response = self.client.post(
            reverse("level_test"),
            {
                "discipline": Submission.DISCIPLINE_PULLUPS,
                "score": "8",
            },
            follow=True,
        )

        self.assertEqual(Submission.objects.filter(email="journey@example.com").count(), 2)
        self.assertContains(response, "2/3 disciplines completed")
        self.assertContains(response, "Add 5K time")

    def test_level_test_session_results_attach_when_profile_is_claimed(self):
        self.client.post(
            reverse("level_test"),
            {
                "name": "Claim Journey",
                "email": "claimjourney@example.com",
                "discipline": Submission.DISCIPLINE_PUSHUPS,
                "score": "30",
            },
        )

        response = self.client.post(
            reverse("register"),
            {
                "username": "claimjourney",
                "email": "claimjourney@example.com",
                "password1": "StrongPass12345",
                "password2": "StrongPass12345",
            },
            follow=True,
        )

        user = User.objects.get(username="claimjourney")
        submission = Submission.objects.get(name="Claim Journey")
        self.assertEqual(submission.user, user)
        self.assertEqual(submission.status, Submission.STATUS_UNVERIFIED)
        self.assertEqual(response.context["hybrid_summary"]["score"], 0)
        self.assertContains(response, "test result(s) are now saved to your profile")

    def test_level_test_requires_name_for_anonymous_submission(self):
        response = self.client.post(
            reverse("level_test"),
            {
                "discipline": Submission.DISCIPLINE_PUSHUPS,
                "score": "32",
            },
        )

        self.assertContains(response, "Enter your name before posting your result.")
        self.assertFalse(Submission.objects.exists())

    def test_level_test_uses_profile_name_for_logged_in_submission_without_name(self):
        user = User.objects.create_user(username="named-test-user", password="StrongPass12345")
        user.profile.display_name = "Named Test User"
        user.profile.save()
        self.client.force_login(user)

        response = self.client.post(
            reverse("level_test"),
            {
                "discipline": Submission.DISCIPLINE_PUSHUPS,
                "score": "32",
            },
            follow=True,
        )

        self.assertContains(response, "You're in!")
        submission = Submission.objects.get(user=user)
        self.assertEqual(submission.name, "Named Test User")

    def test_level_test_requires_proof_for_strong_open_result(self):
        response = self.client.post(
            reverse("level_test"),
            {
                "name": "Proof Needed",
                "discipline": Submission.DISCIPLINE_PULLUPS,
                "score": "15",
            },
        )

        self.assertContains(response, "need proof before it can appear on the leaderboard")
        self.assertFalse(Submission.objects.filter(name="Proof Needed").exists())

    def test_challenge_allows_anonymous_submission_without_email(self):
        response = self.client.post(
            reverse("challenge"),
            {
                "name": "No Email Athlete",
                "discipline": Submission.DISCIPLINE_PUSHUPS,
                "score": "28",
            },
            follow=True,
        )

        self.assertContains(response, "Your result is now on the open leaderboard")
        self.assertContains(response, "Make Your Score Official")
        self.assertContains(response, "Claim Your Athlete Profile")
        self.assertContains(response, "Challenge a Friend")
        submission = Submission.objects.get(name="No Email Athlete")
        self.assertEqual(submission.email, "")
        self.assertEqual(submission.status, Submission.STATUS_UNVERIFIED)

    def test_challenge_requires_proof_for_strong_open_result(self):
        response = self.client.post(
            reverse("challenge"),
            {
                "name": "Strong Open",
                "discipline": Submission.DISCIPLINE_PULLUPS,
                "score": "15",
            },
        )

        self.assertContains(response, "need proof before it can appear on the leaderboard")
        self.assertFalse(Submission.objects.filter(name="Strong Open").exists())

    def test_level_test_running_inputs_are_mobile_time_text(self):
        response = self.client.get(reverse("level_test"))

        self.assertContains(response, 'placeholder: "21:34"', html=False)
        self.assertContains(response, 'input.inputMode = config.unit === "time" ? "text" : "numeric"', html=False)
        self.assertContains(response, "Use MM:SS, e.g. 21:34.")

    def test_challenge_hides_result_link_for_rep_disciplines(self):
        response = self.client.get(reverse("challenge"))

        self.assertContains(response, "data-proof-link hidden", html=False)
        self.assertContains(response, "Proof video")

    def test_challenge_shows_result_link_for_running(self):
        response = self.client.get(f"{reverse('challenge')}?discipline={Submission.DISCIPLINE_5K}")

        self.assertContains(response, "Race or Strava result link")
        self.assertNotContains(response, "data-proof-link hidden", html=False)

    def test_rep_submission_ignores_manual_proof_link(self):
        response = self.client.post(
            reverse("challenge"),
            {
                "name": "Manual Link",
                "email": "manual-link@example.com",
                "discipline": Submission.DISCIPLINE_PULLUPS,
                "score": "12",
                "proof_link": "https://example.com/not-for-reps",
            },
            follow=True,
        )

        self.assertContains(response, "You are now on the open leaderboard")
        submission = Submission.objects.get(email="manual-link@example.com")
        self.assertEqual(submission.video_link, "")
        self.assertEqual(submission.status, Submission.STATUS_UNVERIFIED)

    def test_onboarding_hides_after_completion(self):
        user = User.objects.create_user(username="onboarding-done", password="StrongPass12345")
        Submission.objects.create(user=user, name="Done", reps=42, status=Submission.STATUS_VERIFIED)
        Workout.objects.create(user=user, title="Public plan")
        user.goals.create(goal_type=Submission.DISCIPLINE_PUSHUPS, target_value=50)
        user.profile.personal_best_reps = 42
        user.profile.save()
        self.client.force_login(user)

        response = self.client.get(reverse("dashboard"))

        self.assertFalse(response.context["show_onboarding"])
        self.assertNotContains(response, "Onboarding")

    def test_improvement_recommendation_supports_running_and_reps(self):
        user = User.objects.create_user(username="improve-next", password="StrongPass12345")
        Submission.objects.create(user=user, name="Improve", reps=45, discipline=Submission.DISCIPLINE_PUSHUPS, status=Submission.STATUS_VERIFIED)
        Submission.objects.create(user=user, name="Improve", reps=5, discipline=Submission.DISCIPLINE_PULLUPS, status=Submission.STATUS_VERIFIED)
        Submission.objects.create(user=user, name="Improve", reps=1294, discipline=Submission.DISCIPLINE_5K, status=Submission.STATUS_VERIFIED)
        Submission.objects.create(user=user, name="Improve", reps=2660, discipline=Submission.DISCIPLINE_10K, status=Submission.STATUS_VERIFIED)
        self.client.force_login(user)

        response = self.client.get(reverse("dashboard"))

        self.assertContains(response, "What to improve next")
        self.assertIn("pull-ups", response.context["improvement_recommendation"]["label"].lower())

    def test_legacy_pushup_goal_still_works(self):
        user = User.objects.create_user(username="legacy-goal", password="StrongPass12345")
        self.client.force_login(user)

        response = self.client.post(
            reverse("dashboard"),
            {"form_type": "goal", "goal_type": "pushups", "target_value": "50"},
        )

        self.assertRedirects(response, reverse("dashboard"))
        self.assertTrue(user.goals.filter(goal_type="pushups", target_value=50).exists())

    def test_dashboard_badges_use_verified_hybrid_achievements(self):
        user = User.objects.create_user(username="badge-user", password="StrongPass12345")
        Submission.objects.create(user=user, name="Badge", reps=45, discipline=Submission.DISCIPLINE_PUSHUPS, status=Submission.STATUS_VERIFIED)
        Submission.objects.create(user=user, name="Badge", reps=1300, discipline=Submission.DISCIPLINE_5K, status=Submission.STATUS_VERIFIED)
        self.client.force_login(user)

        response = self.client.get(reverse("dashboard"))
        badge_names = [badge["name"] for badge in response.context["badges"]]

        self.assertIn("Verified Athlete", badge_names)
        self.assertIn("Hybrid Starter", badge_names)
        self.assertIn("Balanced Athlete", badge_names)
        self.assertContains(response, "badge-modal")

    def test_verified_checkbox_updates_status_for_admin_workflow(self):
        submission = Submission.objects.create(name="Manual", reps=44, status=Submission.STATUS_PENDING, video_link="https://example.com/proof")

        submission.verified = True
        submission.save()
        submission.refresh_from_db()
        self.assertEqual(submission.status, Submission.STATUS_VERIFIED)

        submission.verified = False
        submission.save()
        submission.refresh_from_db()
        self.assertEqual(submission.status, Submission.STATUS_PENDING)

    def test_status_updates_verified_flag(self):
        submission = Submission.objects.create(name="Status", reps=41, verified=True)

        submission.status = Submission.STATUS_REJECTED
        submission.save()
        submission.refresh_from_db()

        self.assertFalse(submission.verified)

    def test_verified_status_sync_survives_update_fields(self):
        submission = Submission.objects.create(name="Partial", reps=47, status=Submission.STATUS_PENDING, video_link="https://example.com/proof")

        submission.verified = True
        submission.save(update_fields=["verified"])
        submission.refresh_from_db()

        self.assertTrue(submission.verified)
        self.assertEqual(submission.status, Submission.STATUS_VERIFIED)

    def test_profile_rank_cache_refreshes_for_existing_profiles(self):
        first = User.objects.create_user(username="first-rank", password="StrongPass12345")
        second = User.objects.create_user(username="second-rank", password="StrongPass12345")
        Submission.objects.create(user=first, name="First", reps=50, status=Submission.STATUS_VERIFIED)
        first.profile.refresh_from_db()
        self.assertEqual(first.profile.current_rank, 1)

        Submission.objects.create(user=second, name="Second", reps=70, status=Submission.STATUS_VERIFIED)
        first.profile.refresh_from_db()
        second.profile.refresh_from_db()

        self.assertEqual(second.profile.current_rank, 1)
        self.assertEqual(first.profile.current_rank, 2)

    def test_athlete_profile_keeps_official_score_verified_but_shows_claimed_preview_results(self):
        user = User.objects.create_user(username="public", password="StrongPass12345")
        Submission.objects.create(user=user, name="Public", reps=25, status=Submission.STATUS_PENDING, video_link="https://example.com/proof")
        Submission.objects.create(user=user, name="Public", reps=65, status=Submission.STATUS_VERIFIED)

        response = self.client.get(reverse("athlete_profile", args=[user.profile.slug]))

        self.assertContains(response, "65 reps")
        self.assertContains(response, "Preview: 25 reps")
        self.assertContains(response, "Pending")
        self.assertContains(response, "Preview 312")
        self.assertNotContains(response, "What to improve next")
        self.assertContains(response, 'type="application/ld+json"', html=False)
        self.assertContains(response, "https://earnedclub.club/athlete/public/", html=False)

    def test_athlete_profile_shows_unverified_claimed_result_without_official_points(self):
        user = User.objects.create_user(username="preview-only", password="StrongPass12345")
        Submission.objects.create(user=user, name="Preview Only", reps=44, discipline=Submission.DISCIPLINE_PUSHUPS, status=Submission.STATUS_UNVERIFIED)

        response = self.client.get(reverse("athlete_profile", args=[user.profile.slug]))

        self.assertContains(response, "44 reps")
        self.assertContains(response, "Unverified preview")
        self.assertContains(response, "Not official yet. Add proof to make this count toward Hybrid Score.")
        self.assertContains(response, "Preview 510")
        self.assertContains(response, "Hybrid Score")
        self.assertContains(response, '<div class="profile-pr-number">0</div>', html=False)

    def test_comparison_uses_hybrid_score_not_pushup_delta(self):
        left = User.objects.create_user(username="compare-left", password="StrongPass12345")
        right = User.objects.create_user(username="compare-right", password="StrongPass12345")
        Submission.objects.create(user=left, name="Left", reps=40, discipline=Submission.DISCIPLINE_PUSHUPS, status=Submission.STATUS_VERIFIED)
        Submission.objects.create(user=left, name="Left", reps=10, discipline=Submission.DISCIPLINE_PULLUPS, status=Submission.STATUS_VERIFIED)
        Submission.objects.create(user=right, name="Right", reps=42, discipline=Submission.DISCIPLINE_PUSHUPS, status=Submission.STATUS_VERIFIED)

        response = self.client.get(reverse("comparison", args=[left.profile.slug, right.profile.slug]))

        self.assertContains(response, "compare-left vs compare-right")
        self.assertContains(response, "wins by")
        self.assertContains(response, "Hybrid Score Result")
        self.assertContains(response, "Verified Discipline Difference")
        self.assertContains(response, "&#9819;", html=False)
        self.assertNotContains(response, "Push-up Delta")
        self.assertNotContains(response, "Beat their current PR")
        self.assertNotContains(response, "Positive means the left athlete leads overall.")

    def test_comparison_page_loads_with_profile_picker(self):
        left = User.objects.create_user(username="picker-left", password="StrongPass12345")
        right = User.objects.create_user(username="picker-right", password="StrongPass12345")

        response = self.client.get(reverse("comparison_index"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Build an athlete battle")
        self.assertContains(response, "Want to compare with friends")
        self.assertContains(response, reverse("challenge_room_create"), html=False)
        self.assertContains(response, left.profile.display_name)
        self.assertContains(response, right.profile.display_name)

    def test_two_profiles_compare_winner_and_shareable_link(self):
        left = User.objects.create_user(username="battle-left", password="StrongPass12345")
        right = User.objects.create_user(username="battle-right", password="StrongPass12345")
        left.profile.display_name = "Battle Left"
        left.profile.save()
        right.profile.display_name = "Battle Right"
        right.profile.save()
        Submission.objects.create(user=left, name="Battle Left", reps=70, discipline=Submission.DISCIPLINE_PUSHUPS, status=Submission.STATUS_VERIFIED)
        Submission.objects.create(user=right, name="Battle Right", reps=20, discipline=Submission.DISCIPLINE_PUSHUPS, status=Submission.STATUS_VERIFIED)

        response = self.client.get(reverse("comparison", args=[left.profile.slug, right.profile.slug]))

        self.assertContains(response, "Battle Left vs Battle Right")
        self.assertContains(response, "Battle Left wins by")
        self.assertContains(response, "Point difference: 600 Hybrid points")
        self.assertContains(response, "Copy Link / Share")
        self.assertContains(response, reverse("comparison", args=[left.profile.slug, right.profile.slug]), html=False)
        self.assertContains(response, "Discipline breakdown")
        self.assertContains(response, "strengths / weaknesses")
        self.assertContains(response, "Want to compare with friends in a group challenge")
        self.assertContains(response, reverse("challenge_room_create"), html=False)

    def test_comparison_picker_redirects_to_shareable_comparison(self):
        left = User.objects.create_user(username="redirect-left", password="StrongPass12345")
        right = User.objects.create_user(username="redirect-right", password="StrongPass12345")

        response = self.client.post(
            reverse("comparison_index"),
            {"left": left.profile.slug, "right": right.profile.slug},
        )

        self.assertRedirects(response, reverse("comparison", args=[left.profile.slug, right.profile.slug]))

    def test_challenge_link_guest_can_view_but_needs_account_to_join_officially(self):
        left = User.objects.create_user(username="guest-left", password="StrongPass12345")
        right = User.objects.create_user(username="guest-right", password="StrongPass12345")
        url = reverse("comparison", args=[left.profile.slug, right.profile.slug])

        view_response = self.client.get(url)
        join_response = self.client.post(reverse("comparison_join", args=[left.profile.slug, right.profile.slug]), follow=True)

        self.assertEqual(view_response.status_code, 200)
        self.assertContains(view_response, "Join Challenge Officially")
        self.assertRedirects(join_response, f"{reverse('register')}?next={url}")
        self.assertContains(join_response, "Claim Your Athlete Profile")

    def test_claim_profile_ctas_render_in_key_flows(self):
        user = User.objects.create_user(username="claim-flow", password="StrongPass12345")

        leaderboard_response = self.client.get(reverse("leaderboard"))
        profiles_response = self.client.get(reverse("profiles"))
        comparison_response = self.client.get(reverse("comparison", args=[user.profile.slug, user.profile.slug]))

        self.assertContains(leaderboard_response, "Claim Your Athlete Profile")
        self.assertContains(profiles_response, "Claim Your Athlete Profile")
        self.assertContains(comparison_response, "Claim Your Athlete Profile")

    def test_challenge_room_can_be_created_and_loaded_without_10k(self):
        response = self.client.post(
            reverse("challenge_room_create"),
            {"title": "Group Battle", "description": "Friday test", "focus": ChallengeRoom.FOCUS_HYBRID},
            follow=True,
        )

        room = ChallengeRoom.objects.get(title="Group Battle")
        self.assertRedirects(response, reverse("challenge_room", args=[room.token]))
        self.assertContains(response, "Group Battle")
        self.assertContains(response, "Copy Link")
        self.assertContains(response, "Join my EarnedClub challenge and compare your score")
        self.assertNotContains(response, "10K")

    def test_challenge_room_numeric_id_redirects_to_token_url(self):
        room = ChallengeRoom.objects.create(title="Numeric Room", focus=ChallengeRoom.FOCUS_PUSHUPS)

        response = self.client.get(reverse("challenge_room", args=[room.id]))

        self.assertRedirects(response, reverse("challenge_room", args=[room.token]), fetch_redirect_response=False)

    def test_discipline_specific_room_only_allows_that_discipline_in_test(self):
        room = ChallengeRoom.objects.create(title="Pull Room", focus=ChallengeRoom.FOCUS_PULLUPS)

        response = self.client.get(f"{reverse('level_test')}?room={room.token}")

        self.assertContains(response, "Pull Room")
        self.assertContains(response, 'value="pullups"', html=False)
        self.assertNotContains(response, 'value="pushups"', html=False)
        self.assertNotContains(response, 'value="run_5k"', html=False)
        self.assertNotContains(response, "10K")

    def test_room_token_is_preserved_through_test_and_result_returns_to_room(self):
        room = ChallengeRoom.objects.create(title="Push Room", focus=ChallengeRoom.FOCUS_PUSHUPS)

        response = self.client.post(
            f"{reverse('level_test')}?room={room.token}",
            {"name": "Room Guest", "discipline": Submission.DISCIPLINE_PULLUPS, "score": "31"},
            follow=True,
        )

        submission = Submission.objects.get(name="Room Guest")
        self.assertRedirects(response, reverse("challenge_room", args=[room.token]))
        self.assertEqual(submission.discipline, Submission.DISCIPLINE_PUSHUPS)
        self.assertTrue(ChallengeRoomEntry.objects.filter(room=room, submission=submission).exists())
        self.assertContains(response, "Room Guest")
        self.assertContains(response, "Unclaimed guest")
        self.assertContains(response, "Unverified")

    def test_hybrid_room_groups_multiple_guest_test_results_as_one_participant(self):
        room = ChallengeRoom.objects.create(title="Hybrid Session Room", focus=ChallengeRoom.FOCUS_HYBRID)
        self.client.post(
            f"{reverse('level_test')}?room={room.token}",
            {"name": "Session Guest", "discipline": Submission.DISCIPLINE_PUSHUPS, "score": "30"},
            follow=True,
        )

        response = self.client.post(
            f"{reverse('level_test')}?room={room.token}",
            {"discipline": Submission.DISCIPLINE_PULLUPS, "score": "8"},
            follow=True,
        )

        self.assertEqual(Submission.objects.filter(name="Session Guest").count(), 2)
        self.assertEqual(ChallengeRoomEntry.objects.filter(room=room).count(), 2)
        self.assertEqual(len(response.context["leaderboard_rows"]), 1)
        self.assertEqual(response.context["leaderboard_rows"][0]["result_count"], 2)
        self.assertContains(response, "Session Guest")
        self.assertContains(response, "2 results")
        self.assertContains(response, "Push-ups 30 reps")
        self.assertContains(response, "Pull-ups 8 reps")

    def test_claimed_room_session_entries_merge_with_later_logged_in_results(self):
        room = ChallengeRoom.objects.create(title="Claim Merge Room", focus=ChallengeRoom.FOCUS_HYBRID)
        self.client.post(
            f"{reverse('level_test')}?room={room.token}",
            {"name": "Merge Guest", "email": "merge@example.com", "discipline": Submission.DISCIPLINE_PUSHUPS, "score": "30"},
        )
        self.client.post(
            f"{reverse('register')}?room={room.token}",
            {
                "username": "mergeguest",
                "email": "merge@example.com",
                "password1": "StrongPass12345",
                "password2": "StrongPass12345",
            },
            follow=True,
        )

        response = self.client.post(
            f"{reverse('challenge')}?room={room.token}",
            {"discipline": Submission.DISCIPLINE_PULLUPS, "score": "8"},
            follow=True,
        )

        user = User.objects.get(username="mergeguest")
        self.assertEqual(ChallengeRoomEntry.objects.filter(room=room).count(), 2)
        self.assertEqual(set(ChallengeRoomEntry.objects.filter(room=room).values_list("participant_key", flat=True)), {f"user:{user.id}"})
        self.assertEqual(len(response.context["leaderboard_rows"]), 1)
        self.assertContains(response, "mergeguest")

    def test_room_test_make_official_returns_to_room_without_duplicate(self):
        room = ChallengeRoom.objects.create(title="Proof Room", focus=ChallengeRoom.FOCUS_PUSHUPS)
        self.client.post(
            f"{reverse('level_test')}?room={room.token}",
            {"name": "Room Proof Guest", "score": "30"},
        )
        submission = Submission.objects.get(name="Room Proof Guest")

        response = self.client.post(
            f"{reverse('test_submission_proof', args=[submission.id])}?room={room.token}",
            {"proof_link": "https://example.com/room-proof"},
            follow=True,
        )

        submission.refresh_from_db()
        self.assertRedirects(response, reverse("challenge_room", args=[room.token]))
        self.assertEqual(Submission.objects.filter(name="Room Proof Guest").count(), 1)
        self.assertEqual(submission.status, Submission.STATUS_PENDING)
        self.assertTrue(ChallengeRoomEntry.objects.filter(room=room, submission=submission).exists())

    def test_room_token_is_preserved_through_logged_in_challenge_submission(self):
        user = User.objects.create_user(username="room-user", password="StrongPass12345")
        room = ChallengeRoom.objects.create(title="Five Room", focus=ChallengeRoom.FOCUS_5K)
        self.client.force_login(user)

        get_response = self.client.get(f"{reverse('challenge')}?room={room.token}")
        post_response = self.client.post(
            f"{reverse('challenge')}?room={room.token}",
            {"discipline": Submission.DISCIPLINE_PUSHUPS, "score": "24:10"},
            follow=True,
        )

        submission = Submission.objects.get(user=user)
        self.assertContains(get_response, "Five Room")
        self.assertContains(get_response, 'value="run_5k"', html=False)
        self.assertNotContains(get_response, 'value="pushups"', html=False)
        self.assertRedirects(post_response, reverse("challenge_room", args=[room.token]))
        self.assertEqual(submission.discipline, Submission.DISCIPLINE_5K)
        self.assertTrue(ChallengeRoomEntry.objects.filter(room=room, submission=submission).exists())
        self.assertContains(post_response, user.profile.display_name)

    def test_challenge_room_ranking_winners_for_hybrid_reps_and_5k(self):
        hybrid_room = ChallengeRoom.objects.create(title="Hybrid Room", focus=ChallengeRoom.FOCUS_HYBRID)
        push_room = ChallengeRoom.objects.create(title="Push Room", focus=ChallengeRoom.FOCUS_PUSHUPS)
        five_room = ChallengeRoom.objects.create(title="Fast Room", focus=ChallengeRoom.FOCUS_5K)
        low = Submission.objects.create(name="Low Hybrid", reps=20, discipline=Submission.DISCIPLINE_PUSHUPS, status=Submission.STATUS_UNVERIFIED)
        high = Submission.objects.create(name="High Hybrid", reps=70, discipline=Submission.DISCIPLINE_PUSHUPS, status=Submission.STATUS_UNVERIFIED)
        fast = Submission.objects.create(name="Fast Runner", reps=20 * 60, discipline=Submission.DISCIPLINE_5K, status=Submission.STATUS_UNVERIFIED)
        slow = Submission.objects.create(name="Slow Runner", reps=30 * 60, discipline=Submission.DISCIPLINE_5K, status=Submission.STATUS_UNVERIFIED)
        for submission in (low, high):
            ChallengeRoomEntry.objects.create(room=hybrid_room, submission=submission)
            ChallengeRoomEntry.objects.create(room=push_room, submission=submission)
        for submission in (fast, slow):
            ChallengeRoomEntry.objects.create(room=five_room, submission=submission)

        hybrid_response = self.client.get(reverse("challenge_room", args=[hybrid_room.token]))
        push_response = self.client.get(reverse("challenge_room", args=[push_room.token]))
        five_response = self.client.get(reverse("challenge_room", args=[five_room.token]))

        self.assertContains(hybrid_response, "High Hybrid")
        self.assertEqual(hybrid_response.context["winner"]["display_name"], "High Hybrid")
        self.assertEqual(push_response.context["winner"]["display_name"], "High Hybrid")
        self.assertEqual(five_response.context["winner"]["display_name"], "Fast Runner")
        self.assertContains(five_response, "&#9819;", html=False)

    def test_guest_room_result_attaches_to_profile_when_claimed(self):
        room = ChallengeRoom.objects.create(title="Claim Room", focus=ChallengeRoom.FOCUS_PUSHUPS)
        self.client.post(
            f"{reverse('level_test')}?room={room.token}",
            {"name": "Claim Room Guest", "email": "roomclaim@example.com", "score": "28"},
        )

        response = self.client.post(
            f"{reverse('register')}?room={room.token}",
            {
                "username": "roomclaim",
                "email": "roomclaim@example.com",
                "password1": "StrongPass12345",
                "password2": "StrongPass12345",
            },
            follow=True,
        )

        submission = Submission.objects.get(name="Claim Room Guest")
        self.assertEqual(submission.user.username, "roomclaim")
        self.assertRedirects(response, reverse("challenge_room", args=[room.token]))
        self.assertContains(response, "Claimed profile")
        self.assertEqual(response.context["winner"]["display_name"], "roomclaim")

    def test_profiles_directory_shows_real_accounts_not_anonymous_submitters(self):
        user = User.objects.create_user(username="real-account", password="StrongPass12345")
        user.profile.display_name = "Real Account"
        user.profile.save()
        Submission.objects.create(name="Anonymous Submitter", email="anon@example.com", reps=35, status=Submission.STATUS_UNVERIFIED)

        response = self.client.get(reverse("profiles"))

        self.assertContains(response, "Real Account")
        self.assertContains(response, "Hybrid 0")
        self.assertNotContains(response, "Anonymous Submitter")

    def test_leaderboard_shows_best_pending_instead_of_lower_verified_for_user(self):
        user = User.objects.create_user(username="one-row", password="StrongPass12345")
        user.profile.display_name = "One Row"
        user.profile.save()
        Submission.objects.create(user=user, name="One Row", reps=40, status=Submission.STATUS_VERIFIED)
        Submission.objects.create(user=user, name="One Row", reps=55, status=Submission.STATUS_PENDING, video_link="https://example.com/proof")

        response = self.client.get(f"{reverse('leaderboard')}?discipline={Submission.DISCIPLINE_PUSHUPS}")

        self.assertContains(response, "55")
        self.assertContains(response, "Pending")
        self.assertContains(response, "Official rank #1")
        self.assertNotContains(response, "40</span>")

    def test_approving_higher_verified_submission_preserves_history_for_user(self):
        user = User.objects.create_user(username="replace", password="StrongPass12345")
        Submission.objects.create(user=user, name="Replace", reps=42, status=Submission.STATUS_VERIFIED)
        newer = Submission.objects.create(user=user, name="Replace", reps=60, status=Submission.STATUS_PENDING, video_link="https://example.com/proof")

        newer.status = Submission.STATUS_VERIFIED
        newer.save(update_fields=["status"])

        self.assertEqual(
            list(user.submission_set.filter(status=Submission.STATUS_VERIFIED).values_list("reps", flat=True)),
            [60, 42],
        )
        user.profile.refresh_from_db()
        self.assertEqual(user.profile.personal_best_reps, 60)

    def test_dashboard_updates_profile_fields(self):
        user = User.objects.create_user(username="editable", password="StrongPass12345")
        self.client.force_login(user)

        response = self.client.post(
            reverse("dashboard"),
            {
                "username": "edited-name",
                "email": "edited@example.com",
                "country": "Czech Republic",
                "age": "24",
                "profile_photo": "https://example.com/photo.jpg",
                "bio": "Training daily.",
            },
        )

        self.assertRedirects(response, reverse("dashboard"))
        user.refresh_from_db()
        user.profile.refresh_from_db()
        self.assertEqual(user.username, "edited-name")
        self.assertEqual(user.email, "edited@example.com")
        self.assertEqual(user.profile.display_name, "edited-name")
        self.assertEqual(user.profile.country, "Czech Republic")
        self.assertEqual(user.profile.age, 24)

    def test_dashboard_history_includes_rejected_submission(self):
        user = User.objects.create_user(username="history-user", password="StrongPass12345")
        self.client.force_login(user)
        Submission.objects.create(user=user, name="History", reps=33, status=Submission.STATUS_REJECTED)

        response = self.client.get(reverse("dashboard"))

        self.assertContains(response, "Rejected")
        self.assertEqual(response.context["rejected_count"], 1)

    def test_dashboard_updates_profile_photo_url(self):
        user = User.objects.create_user(username="photo-user", password="StrongPass12345")
        self.client.force_login(user)

        response = self.client.post(
            reverse("dashboard"),
            {
                "username": "photo-user",
                "email": "photo@example.com",
                "country": "Czech Republic",
                "profile_photo": "https://example.com/avatar.jpg",
            },
        )

        self.assertRedirects(response, reverse("dashboard"))
        user.profile.refresh_from_db()
        self.assertEqual(user.profile.profile_photo, "https://example.com/avatar.jpg")

    def test_dashboard_can_add_proof_to_unverified_submission(self):
        user = User.objects.create_user(username="proof-user", password="StrongPass12345")
        self.client.force_login(user)
        submission = Submission.objects.create(user=user, name="Proof User", reps=31, status=Submission.STATUS_UNVERIFIED)

        response = self.client.post(
            reverse("add_submission_proof", args=[submission.id]),
            {"video_file": self.proof_video()},
            follow=True,
        )

        self.assertRedirects(response, reverse("dashboard"))
        submission.refresh_from_db()
        self.assertEqual(submission.status, Submission.STATUS_PENDING)
        self.assertEqual(submission.video_link, "")
        self.assertTrue(submission.has_proof)

    def test_dashboard_can_log_workout(self):
        user = User.objects.create_user(username="workout-user", password="StrongPass12345")
        self.client.force_login(user)

        response = self.client.post(
            reverse("dashboard"),
            {
                "form_type": "workout",
                "title": "Push Day",
                "duration_minutes": "30",
                "exercise_name": ["Push-ups"],
                "exercise_sets": ["3"],
                "exercise_reps": ["15"],
                "exercise_seconds": [""],
            },
        )

        self.assertRedirects(response, reverse("dashboard"))
        workout = Workout.objects.get(user=user)
        self.assertEqual(workout.title, "Push Day")
        self.assertEqual(workout.exercises.first().reps, 15)

    def test_workout_can_be_started_from_history(self):
        user = User.objects.create_user(username="starter", password="StrongPass12345")
        workout = Workout.objects.create(user=user, title="Push Builder", duration_minutes=20)
        workout.exercises.create(name="Push-ups", sets=3, reps=12)
        self.client.force_login(user)

        response = self.client.post(reverse("start_workout"), {"workout_id": workout.id})

        session = WorkoutSession.objects.get(user=user, workout=workout)
        self.assertRedirects(response, reverse("workout_session_detail", args=[session.id]))
        self.assertEqual(session.exercise_sessions.count(), 1)

    def test_generated_workout_uses_selected_body_part_and_title(self):
        user = User.objects.create_user(username="generator", password="StrongPass12345")
        self.client.force_login(user)

        response = self.client.post(
            reverse("workouts"),
            {
                "form_type": "generated_workout",
                "builder_minutes": "20",
                "builder_body_parts": ["Chest"],
            },
        )

        workout = Workout.objects.get(user=user)
        self.assertEqual(workout.title, "Chest 20-minute custom workout")
        self.assertRedirects(response, reverse("workout_session_detail", args=[workout.sessions.first().id]))
        self.assertTrue(workout.exercises.exists())
        self.assertTrue(all(exercise.body_part == "Chest" for exercise in workout.exercises.all()))

    def test_workout_session_marks_complete_after_finishing_sets(self):
        user = User.objects.create_user(username="session-user", password="StrongPass12345")
        workout = Workout.objects.create(user=user, title="Session Flow")
        exercise = workout.exercises.create(name="Push-ups", sets=2, reps=10)
        session = WorkoutSession.objects.create(user=user, workout=workout)
        session_exercise = session.exercise_sessions.create(
            workout_exercise=exercise,
            name=exercise.name,
            target_sets=2,
            target_reps=10,
        )
        self.client.force_login(user)

        self.client.post(reverse("update_workout_session", args=[session.id, session_exercise.id]), {"action": "complete_set"})
        response = self.client.post(reverse("update_workout_session", args=[session.id, session_exercise.id]), {"action": "complete_set"}, follow=True)

        session.refresh_from_db()
        session_exercise.refresh_from_db()
        self.assertEqual(session_exercise.completed_sets, 2)
        self.assertEqual(session.status, WorkoutSession.STATUS_COMPLETED)
        self.assertContains(response, "completed")
        self.assertNotContains(response, "Complete Set")
        self.assertNotContains(response, "data-rest-start", html=False)

    def test_only_one_highlighted_workout_per_user_constraint(self):
        user = User.objects.create_user(username="highlight-constraint", password="StrongPass12345")
        Workout.objects.create(user=user, title="First", is_public=True, highlighted_on_profile=True)

        with self.assertRaises(IntegrityError):
            Workout.objects.create(user=user, title="Second", is_public=True, highlighted_on_profile=True)

    def test_follow_toggle_creates_follow(self):
        follower = User.objects.create_user(username="follower", password="StrongPass12345")
        target = User.objects.create_user(username="target", password="StrongPass12345")
        self.client.force_login(follower)

        response = self.client.post(reverse("toggle_follow", args=[target.profile.slug]))

        self.assertRedirects(response, reverse("athlete_profile", args=[target.profile.slug]))
        self.assertTrue(Follow.objects.filter(follower=follower, following=target).exists())

    def test_staff_can_create_content_engine_prompt(self):
        staff = User.objects.create_user(username="content-staff", password="StrongPass12345", is_staff=True)
        self.client.force_login(staff)

        response = self.client.post(
            reverse("content_engine_admin"),
            {
                "title": "Can you beat this?",
                "engine_type": "challenge",
                "prompt": "Film a 40 push-up challenge.",
                "cta": "Prove it.",
            },
        )

        self.assertRedirects(response, reverse("content_engine_admin"))
        self.assertTrue(ContentEnginePrompt.objects.filter(title="Can you beat this?").exists())

    def test_staff_can_create_newsletter_segment(self):
        staff = User.objects.create_user(username="newsletter-staff", password="StrongPass12345", is_staff=True)
        first = NewsletterSubscriber.objects.create(email="first@example.com")
        second = NewsletterSubscriber.objects.create(email="second@example.com")
        self.client.force_login(staff)

        response = self.client.post(
            reverse("newsletter_admin"),
            {
                "form_type": "segment",
                "segment_name": "Week 1",
                "subscriber_ids": [str(first.id), str(second.id)],
            },
        )

        self.assertRedirects(response, reverse("newsletter_admin"))
        segment = NewsletterSegment.objects.get(name="Week 1")
        self.assertEqual(segment.subscribers.count(), 2)

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_newsletter_segment_send_is_disabled_for_now(self):
        staff = User.objects.create_user(username="segment-send-staff", password="StrongPass12345", is_staff=True)
        included = NewsletterSubscriber.objects.create(email="included@example.com")
        NewsletterSubscriber.objects.create(email="excluded@example.com")
        segment = NewsletterSegment.objects.create(name="Included")
        segment.subscribers.add(included)
        self.client.force_login(staff)

        response = self.client.post(
            reverse("newsletter_admin"),
            {
                "week_number": "1",
                "subject": "Segment hello",
                "body": "Only one set.",
                "segment_id": str(segment.id),
                "action": "send",
            },
        )

        self.assertRedirects(response, reverse("newsletter_admin"))
        self.assertEqual(NewsletterSendEvent.objects.count(), 0)

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_newsletter_auto_segment_send_is_disabled_for_now(self):
        staff = User.objects.create_user(username="auto-segment-staff", password="StrongPass12345", is_staff=True)
        verified_user = User.objects.create_user(username="verified-email", email="verified@example.com", password="StrongPass12345")
        NewsletterSubscriber.objects.create(email="verified@example.com")
        NewsletterSubscriber.objects.create(email="other@example.com")
        Submission.objects.create(user=verified_user, name="Verified", email="verified@example.com", reps=70, status=Submission.STATUS_VERIFIED)
        self.client.force_login(staff)

        response = self.client.post(
            reverse("newsletter_admin"),
            {
                "week_number": "1",
                "subject": "Verified hello",
                "body": "For verified users.",
                "auto_segment": "verified",
                "action": "send",
            },
        )

        self.assertRedirects(response, reverse("newsletter_admin"))
        self.assertEqual(NewsletterSendEvent.objects.count(), 0)

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_direct_newsletter_email_is_disabled_for_now(self):
        staff = User.objects.create_user(username="direct-staff", password="StrongPass12345", is_staff=True)
        subscriber = NewsletterSubscriber.objects.create(email="direct@example.com")
        self.client.force_login(staff)

        response = self.client.post(
            reverse("newsletter_subscriber_detail", args=[subscriber.id]),
            {"subject": "Direct hello", "body": "Only for this subscriber."},
        )

        self.assertRedirects(response, reverse("newsletter_subscriber_detail", args=[subscriber.id]))
        self.assertEqual(NewsletterSendEvent.objects.count(), 0)

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.smtp.EmailBackend",
        EMAIL_HOST="smtp.gmail.com",
        EMAIL_PORT=587,
        EMAIL_USE_TLS=True,
        EMAIL_USE_SSL=False,
        EMAIL_HOST_USER="earnedclub1@gmail.com",
        EMAIL_HOST_PASSWORD="app-password",
    )
    def test_direct_newsletter_email_reports_disabled_delivery_without_send_event(self):
        staff = User.objects.create_user(username="network-staff", password="StrongPass12345", is_staff=True)
        subscriber = NewsletterSubscriber.objects.create(email="network@example.com")
        self.client.force_login(staff)

        response = self.client.post(
            reverse("newsletter_subscriber_detail", args=[subscriber.id]),
            {"subject": "Network hello", "body": "Only for this subscriber."},
            follow=True,
        )

        self.assertContains(response, "Email delivery is temporarily disabled")
        self.assertEqual(NewsletterSendEvent.objects.count(), 0)

    def test_sitemap_xml_lists_core_pages(self):
        response = self.client.get(reverse("sitemap_xml"))
        namespace = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
        root = ElementTree.fromstring(response.content)
        locs = [node.text for node in root.findall("s:url/s:loc", namespace)]

        self.assertEqual(response.status_code, 200)
        self.assertIn("application/xml", response["Content-Type"])
        self.assertNotContains(response, "<?xml-stylesheet", html=False)
        self.assertContains(response, "<urlset", html=False)
        self.assertIn("https://earnedclub.club/rank/", locs)
        self.assertIn("https://earnedclub.club/leaderboard/", locs)
        self.assertIn("https://earnedclub.club/challenge/", locs)
        self.assertIn("https://earnedclub.club/comparison/", locs)
        self.assertIn("https://earnedclub.club/test/", locs)

    def test_sitemap_xml_lists_public_athlete_profiles(self):
        user = User.objects.create_user(username="sitemap-athlete", password="StrongPass12345")
        profile = user.profile
        profile.personal_best_reps = 54
        profile.save()

        response = self.client.get(reverse("sitemap_xml"))
        namespace = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
        root = ElementTree.fromstring(response.content)
        profile_url = f"https://earnedclub.club{reverse('athlete_profile', args=[profile.slug])}"
        profile_nodes = [
            node
            for node in root.findall("s:url", namespace)
            if node.find("s:loc", namespace).text == profile_url
        ]

        self.assertEqual(len(profile_nodes), 1)
        self.assertRegex(profile_nodes[0].find("s:lastmod", namespace).text, r"^\d{4}-\d{2}-\d{2}$")
        self.assertEqual(profile_nodes[0].find("s:changefreq", namespace).text, "weekly")

    def test_sitemap_xml_lists_public_workouts(self):
        user = User.objects.create_user(username="sitemap-workout", password="StrongPass12345")
        public_workout = Workout.objects.create(user=user, title="Public Push", is_public=True)
        private_workout = Workout.objects.create(user=user, title="Private Push", is_public=False)

        response = self.client.get(reverse("sitemap_xml"))
        namespace = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
        root = ElementTree.fromstring(response.content)
        locs = [node.text for node in root.findall("s:url/s:loc", namespace)]

        self.assertIn(f"https://earnedclub.club{reverse('workout_detail', args=[public_workout.slug])}", locs)
        self.assertNotIn(f"https://earnedclub.club{reverse('workout_detail', args=[private_workout.slug])}", locs)

    def test_sitemap_xsl_renders_browser_stylesheet(self):
        response = self.client.get(reverse("sitemap_xsl"))

        self.assertEqual(response.status_code, 200)
        self.assertIn("text/xsl", response["Content-Type"])
        self.assertEqual(response["X-Robots-Tag"], "noindex")
        self.assertContains(response, "Earned Club Sitemap", html=False)
        self.assertContains(response, "s:urlset/s:url", html=False)

    def test_robots_txt_references_sitemap(self):
        response = self.client.get(reverse("robots_txt"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "User-agent: *")
        self.assertContains(response, "Disallow: /admin/")
        self.assertContains(response, "Sitemap: https://earnedclub.club/sitemap.xml")

    def test_staff_can_approve_submission_in_app(self):
        admin = User.objects.create_user(username="staff", password="StrongPass12345", is_staff=True)
        self.client.force_login(admin)
        submission = Submission.objects.create(name="Review Me", reps=48, status=Submission.STATUS_PENDING, video_link="https://example.com/proof")

        response = self.client.post(
            reverse("review_submission", args=[submission.id]),
            {"action": "approve"},
        )

        self.assertRedirects(response, f"{reverse('admin_review')}?status=pending&proof=all&order=newest")
        submission.refresh_from_db()
        self.assertEqual(submission.status, Submission.STATUS_VERIFIED)
        self.assertTrue(
            VerificationEvent.objects.filter(
                submission=submission,
                action=VerificationEvent.ACTION_APPROVED,
                reviewer=admin,
            ).exists()
        )

    def test_review_action_failure_redirects_instead_of_500(self):
        admin = User.objects.create_user(username="review-failure-staff", password="StrongPass12345", is_staff=True)
        self.client.force_login(admin)
        submission = Submission.objects.create(name="Review Fails", reps=48, status=Submission.STATUS_PENDING, video_link="https://example.com/proof")

        with patch("main.views.create_verification_event", side_effect=RuntimeError("review write failed")):
            response = self.client.post(
                reverse("review_submission", args=[submission.id]),
                {"action": "approve"},
                follow=True,
            )

        submission.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(submission.status, Submission.STATUS_PENDING)
        self.assertContains(response, "Review action failed")

    def test_review_notification_failure_does_not_rollback_approval(self):
        admin = User.objects.create_user(username="notify-failure-staff", password="StrongPass12345", is_staff=True)
        self.client.force_login(admin)
        submission = Submission.objects.create(name="Notify Fails", reps=48, status=Submission.STATUS_PENDING, video_link="https://example.com/proof")

        with patch("main.views.send_submission_notification", side_effect=RuntimeError("email failed")):
            response = self.client.post(
                reverse("review_submission", args=[submission.id]),
                {"action": "approve"},
                follow=True,
            )

        submission.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(submission.status, Submission.STATUS_VERIFIED)
        self.assertContains(response, "Review was saved")

    def test_staff_can_view_admin_pages_index(self):
        staff = User.objects.create_user(username="pages-staff", password="StrongPass12345", is_staff=True)
        self.client.force_login(staff)

        response = self.client.get(reverse("admin_pages"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Existing pages")
        self.assertContains(response, "/rank/")
        self.assertContains(response, "/challenge/")

    def test_staff_can_view_challenge_room_overview(self):
        staff = User.objects.create_user(username="rooms-staff", password="StrongPass12345", is_staff=True)
        self.client.force_login(staff)
        room = ChallengeRoom.objects.create(title="Friday Room", focus=ChallengeRoom.FOCUS_HYBRID, created_by=staff)

        response = self.client.get(reverse("admin_challenge_rooms"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Challenge rooms")
        self.assertContains(response, "Friday Room")
        self.assertContains(response, room.token)
        self.assertContains(response, reverse("admin:main_challengeroom_change", args=[room.id]), html=False)

    def test_staff_can_view_registered_user_overview(self):
        staff = User.objects.create_user(username="users-staff", password="StrongPass12345", is_staff=True)
        athlete = User.objects.create_user(username="overview-athlete", email="athlete@example.com", password="StrongPass12345")
        self.client.force_login(staff)

        response = self.client.get(reverse("admin_users"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Registered users")
        self.assertContains(response, "overview-athlete")
        self.assertContains(response, "athlete@example.com")
        self.assertContains(response, reverse("admin:auth_user_change", args=[athlete.id]), html=False)

    def test_review_page_requires_staff_or_superuser(self):
        user = User.objects.create_user(username="regular", password="StrongPass12345")
        self.client.force_login(user)

        response = self.client.get(reverse("admin_review"))

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response["Location"])

    def test_review_page_filters_queue(self):
        admin = User.objects.create_user(username="filter-staff", password="StrongPass12345", is_staff=True)
        self.client.force_login(admin)
        Submission.objects.create(name="Needs Proof", reps=20, status=Submission.STATUS_UNVERIFIED)
        Submission.objects.create(name="Proof Ready", reps=70, status=Submission.STATUS_PENDING, video_link="https://example.com/ready")

        response = self.client.get(f"{reverse('admin_review')}?status=all&proof=with-proof&q=Ready&order=highest")
        review_names = [submission.name for submission in response.context["review_submissions"]]

        self.assertContains(response, "Proof Ready")
        self.assertEqual(review_names, ["Proof Ready"])
        self.assertEqual(response.context["review_count"], 1)

    def test_review_page_defaults_to_all_status_and_tracks_new_since_last_check(self):
        admin = User.objects.create_user(username="review-default-staff", password="StrongPass12345", is_staff=True)
        self.client.force_login(admin)
        old_submission = Submission.objects.create(name="Old Seen", reps=22, status=Submission.STATUS_UNVERIFIED)
        seen_at = timezone.now()
        session = self.client.session
        session["admin_review_last_checked"] = seen_at.isoformat()
        session.save()
        old_submission.created_at = seen_at - timedelta(minutes=5)
        old_submission.save(update_fields=["created_at"])
        new_submission = Submission.objects.create(name="New Away", reps=24, status=Submission.STATUS_UNVERIFIED)
        new_submission.created_at = seen_at + timedelta(minutes=5)
        new_submission.save(update_fields=["created_at"])

        response = self.client.get(reverse("admin_review"))

        self.assertEqual(response.context["status_filter"], "all")
        self.assertContains(response, '<option value="all" selected>All</option>', html=False)
        self.assertContains(response, "New since last check")
        self.assertEqual(response.context["new_since_last_count"], 1)
        self.assertContains(response, "Old Seen")
        self.assertContains(response, "New Away")

    def test_admin_can_change_reviewed_submission_back_to_pending(self):
        admin = User.objects.create_user(username="review-staff", password="StrongPass12345", is_staff=True)
        self.client.force_login(admin)
        submission = Submission.objects.create(
            name="Reviewed",
            reps=44,
            status=Submission.STATUS_REJECTED,
            video_link="https://example.com/reviewed-proof",
        )

        response = self.client.post(
            reverse("review_submission", args=[submission.id]),
            {"action": "mark_pending", "status_filter": "rejected", "proof_filter": "all", "order_filter": "newest"},
        )

        self.assertRedirects(response, f"{reverse('admin_review')}?status=rejected&proof=all&order=newest")
        submission.refresh_from_db()
        self.assertEqual(submission.status, Submission.STATUS_PENDING)

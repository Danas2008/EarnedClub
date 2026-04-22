from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from .models import NewsletterSubscriber, Profile, Submission, get_rank_tier


class SubmissionFlowTests(TestCase):
    def test_challenge_submission_creates_unverified_record(self):
        response = self.client.post(
            reverse("challenge"),
            {
                "name": "Alex",
                "email": "alex@example.com",
                "reps": 42,
                "video_link": "https://example.com/video",
            },
        )

        self.assertRedirects(response, reverse("challenge"))
        submission = Submission.objects.get(name="Alex")
        self.assertEqual(submission.reps, 42)
        self.assertFalse(submission.verified)
        self.assertEqual(submission.status, Submission.STATUS_PENDING)
        self.assertEqual(submission.email, "alex@example.com")

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
                "video_link": "https://example.com/proof",
            },
            follow=True,
        )

        self.assertContains(response, "Submission received.")
        self.assertContains(response, "would currently rank #2")

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
            verified=False,
        )

        response = self.client.get(reverse("leaderboard"))

        self.assertContains(response, "Visible Athlete")
        self.assertContains(response, "Hidden Athlete")
        self.assertContains(response, "Verified")
        self.assertContains(response, "Unverified")
        self.assertContains(response, "Waiting for verification")

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

    def test_registration_creates_user_and_profile(self):
        response = self.client.post(
            reverse("register"),
            {
                "username": "athlete",
                "display_name": "Earned Athlete",
                "email": "athlete@example.com",
                "password1": "StrongPass12345",
                "password2": "StrongPass12345",
            },
        )

        self.assertRedirects(response, reverse("dashboard"))
        user = User.objects.get(username="athlete")
        self.assertEqual(user.email, "athlete@example.com")
        self.assertEqual(user.profile.display_name, "Earned Athlete")
        self.assertEqual(user.profile.slug, "earned-athlete")

    def test_registration_accepts_six_character_password(self):
        response = self.client.post(
            reverse("register"),
            {
                "username": "sixpass",
                "display_name": "Six Pass",
                "email": "six@example.com",
                "password1": "z9Qv7p",
                "password2": "z9Qv7p",
            },
        )

        self.assertRedirects(response, reverse("dashboard"))
        self.assertTrue(User.objects.filter(username="sixpass").exists())

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
        Submission.objects.create(user=user, name="Pending", reps=20, status=Submission.STATUS_PENDING)

        response = self.client.post(reverse("challenge"), {"reps": 30}, follow=True)

        self.assertEqual(Submission.objects.filter(user=user).count(), 1)
        self.assertContains(response, "already have a submission waiting for verification")

    def test_duplicate_pending_submission_is_blocked_for_email(self):
        Submission.objects.create(
            name="Anon",
            email="anon@example.com",
            reps=20,
            status=Submission.STATUS_PENDING,
        )

        response = self.client.post(
            reverse("challenge"),
            {"name": "Anon", "email": "anon@example.com", "reps": 30},
            follow=True,
        )

        self.assertEqual(Submission.objects.filter(email="anon@example.com").count(), 1)
        self.assertContains(response, "already have a submission waiting for verification")

    def test_dashboard_requires_login(self):
        response = self.client.get(reverse("dashboard"))

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response["Location"])

    def test_dashboard_counts_only_verified_submissions(self):
        user = User.objects.create_user(username="dash", password="StrongPass12345")
        self.client.force_login(user)
        Submission.objects.create(user=user, name="Dash", reps=30, status=Submission.STATUS_PENDING)
        Submission.objects.create(user=user, name="Dash", reps=55, status=Submission.STATUS_VERIFIED)

        response = self.client.get(reverse("dashboard"))

        self.assertEqual(response.context["current_pr"], 55)
        self.assertEqual(response.context["total_submissions"], 2)
        self.assertEqual(response.context["total_verified"], 1)
        self.assertEqual(response.context["total_pending"], 1)
        self.assertEqual([point["reps"] for point in response.context["progress_data"]], [55])

    def test_verified_checkbox_updates_status_for_admin_workflow(self):
        submission = Submission.objects.create(name="Manual", reps=44, status=Submission.STATUS_PENDING)

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
        submission = Submission.objects.create(name="Partial", reps=47, status=Submission.STATUS_PENDING)

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

    def test_athlete_profile_shows_only_verified_submissions(self):
        user = User.objects.create_user(username="public", password="StrongPass12345")
        Submission.objects.create(user=user, name="Public", reps=25, status=Submission.STATUS_PENDING)
        Submission.objects.create(user=user, name="Public", reps=65, status=Submission.STATUS_VERIFIED)

        response = self.client.get(reverse("athlete_profile", args=[user.profile.slug]))

        self.assertContains(response, "65 reps")
        self.assertNotContains(response, "25 reps")

    def test_leaderboard_shows_best_pending_instead_of_lower_verified_for_user(self):
        user = User.objects.create_user(username="one-row", password="StrongPass12345")
        user.profile.display_name = "One Row"
        user.profile.save()
        Submission.objects.create(user=user, name="One Row", reps=40, status=Submission.STATUS_VERIFIED)
        Submission.objects.create(user=user, name="One Row", reps=55, status=Submission.STATUS_PENDING)

        response = self.client.get(reverse("leaderboard"))

        self.assertContains(response, "55")
        self.assertContains(response, "Unverified")
        self.assertContains(response, "Official rank #1")
        self.assertNotContains(response, "40</span>")

    def test_approving_higher_verified_submission_removes_previous_verified_for_user(self):
        user = User.objects.create_user(username="replace", password="StrongPass12345")
        Submission.objects.create(user=user, name="Replace", reps=42, status=Submission.STATUS_VERIFIED)
        newer = Submission.objects.create(user=user, name="Replace", reps=60, status=Submission.STATUS_PENDING)

        newer.status = Submission.STATUS_VERIFIED
        newer.save(update_fields=["status"])

        self.assertEqual(
            list(user.submission_set.filter(status=Submission.STATUS_VERIFIED).values_list("reps", flat=True)),
            [60],
        )

    def test_dashboard_updates_profile_fields(self):
        user = User.objects.create_user(username="editable", password="StrongPass12345")
        self.client.force_login(user)

        response = self.client.post(
            reverse("dashboard"),
            {
                "username": "edited-name",
                "display_name": "Edited Athlete",
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
        self.assertEqual(user.profile.display_name, "Edited Athlete")
        self.assertEqual(user.profile.country, "Czech Republic")
        self.assertEqual(user.profile.age, 24)

    def test_staff_can_approve_submission_in_app(self):
        admin = User.objects.create_user(username="staff", password="StrongPass12345", is_staff=True)
        self.client.force_login(admin)
        submission = Submission.objects.create(name="Review Me", reps=48, status=Submission.STATUS_PENDING)

        response = self.client.post(
            reverse("review_submission", args=[submission.id]),
            {"action": "approve"},
        )

        self.assertRedirects(response, reverse("admin_review"))
        submission.refresh_from_db()
        self.assertEqual(submission.status, Submission.STATUS_VERIFIED)

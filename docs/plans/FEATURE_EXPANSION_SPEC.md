# Earned Club Feature Expansion Specification

## Purpose

Transform Earned Club from a simple public push-up leaderboard into a persistent performance identity platform with user accounts, verified progress tracking, challenges, social sharing, and retention mechanics.

This document is based on the current Django project state as of 2026-04-20.

## Current Project Map

### Stack

- Django 5.2.13
- Django templates
- Bootstrap loaded from CDN
- Local SQLite fallback
- Supabase PostgreSQL through `DATABASE_URL`
- WhiteNoise static file serving
- Render deployment config

### Existing Django Structure

- `core/settings.py`
  - Django auth, sessions, messages, staticfiles, admin, and `main` are installed.
  - Database uses Supabase/Postgres when `DATABASE_URL` exists, otherwise local SQLite.
  - No custom user model is currently configured.

- `core/urls.py`
  - Admin at `/admin/`
  - Main app mounted at `/`

- `main/models.py`
  - `Submission`
    - `name`
    - `reps`
    - `video_link`
    - `verified`
    - `created_at`
  - `NewsletterSubscriber`
    - `email`
    - `created_at`
  - `RANK_TIERS` and helper properties for tier display.

- `main/views.py`
  - `home`
  - `leaderboard`
  - `challenge`
  - `newsletter_signup`
  - `calculators`

- `main/templates/`
  - `base.html`
  - `home.html`
  - `challenge.html`
  - `leaderboard.html`
  - `calculators.html`

- `main/tests.py`
  - Verifies unverified submission creation.
  - Verifies leaderboard hides unverified results.
  - Verifies newsletter signup.
  - Verifies rank tier helper.

### Existing Behavior

- Users submit push-up results through `/challenge/`.
- Submissions are created as unverified.
- Admin manually toggles `verified`.
- Public leaderboard shows only verified submissions.
- Homepage shows top verified athletes and recent weekly top performers.
- Newsletter signup exists.
- Calculators page exists, but the JavaScript thresholds do not exactly match `RANK_TIERS` in Python.

### Important Current Constraints

- There are no user accounts yet.
- `Submission` is not linked to `auth.User`.
- Submissions currently require `video_link`.
- There is no rejected status; verification is a boolean only.
- There is no profile, dashboard, badge, challenge, or rank history model.
- Navigation has only Home, Challenge, and Leaderboard.

## Product Requirements

## 1. User Authentication

Implement full user accounts using Django's built-in `User` model plus a separate `Profile` model.

### Required Routes

- `/register/`
- `/login/`
- `/logout/`
- `/dashboard/`
- `/athlete/<slug>/`

### Profile Model

Use a `Profile` model with a one-to-one relationship to `auth.User`.

Fields:

- `user`
- `display_name`
- `slug`
- `profile_photo`
- `bio`
- `current_rank`
- `personal_best_reps`
- `created_at`
- `updated_at`

Notes:

- `username`, `email`, `password`, and `date_joined` should stay on Django's built-in `User`.
- `current_rank` and `personal_best_reps` can be denormalized for display, but must be recalculated from verified submissions.
- Generate `Profile` automatically when a user registers.

### Submission Link

Extend `Submission`:

- Add nullable `user = ForeignKey(User, null=True, blank=True, on_delete=SET_NULL)`.
- Keep `name` for backwards compatibility and public display of legacy submissions.
- New logged-in submissions should set both `user` and `name` from the user's profile/display name.

### Auth Behavior

- Logged-out users may still submit through the low-friction honor-system flow.
- Logged-in users get submission history and progress tracking.
- Authenticated dashboard and profile pages must only count verified submissions.

## 2. Progress Dashboard

Create an authenticated dashboard at `/dashboard/`.

### Metrics

Show:

- Current verified PR
- All-time PR
- Current rank
- Rank movement
- Total verified submissions
- Total pending submissions
- Weeks active
- Current verified-submission streak

### Progress Graph

Plot verified reps over time.

Minimum MVP implementation:

- Render data from Django as JSON.
- Use lightweight inline JavaScript or a CDN chart library.
- If avoiding chart dependencies, render a simple accessible SVG/HTML line chart.

Only verified submissions count in the graph.

## 3. Rep-to-Elite Calculator

Upgrade the existing calculators page.

### Inputs

- Current reps
- Optional weekly improvement

### Outputs

- Current tier
- Reps needed to reach Elite, target `60`
- Reps needed to reach Earned Legend, target `80`
- Estimated weeks to Elite
- Estimated weeks to Earned Legend

### Technical Note

The current JavaScript thresholds in `calculators.html` are off by one compared with `main/models.py`.

Canonical tier thresholds should be:

- Beginner: `0-19`
- Intermediate: `20-39`
- Advanced: `40-59`
- Elite: `60-79`
- Earned Legend: `80+`

Use one source of truth where possible by passing `RANK_TIERS` from Django to the template.

## 4. Weekly Challenges System

Add first-class challenges instead of treating `/challenge/` as only a generic submission form.

### Challenge Model

Fields:

- `name`
- `slug`
- `description`
- `challenge_type`
- `start_date`
- `end_date`
- `active`
- `created_at`
- `updated_at`

Suggested `challenge_type` choices:

- `max_strict_pushups`
- `two_minute_pushup_test`
- `one_hundred_for_time`

### Submission Changes

Extend `Submission`:

- Add nullable `challenge = ForeignKey(Challenge, null=True, blank=True, on_delete=SET_NULL)`.
- Add `submission_type` if needed later, but keep MVP simple unless requirements expand.

### Views

- `/challenge/` should show the current active challenge.
- `/challenges/archive/` should list past challenges.
- `/challenge/<slug>/` should show challenge detail and leaderboard.

### Challenge Leaderboard

- Only verified submissions count.
- Winner is the highest verified result for reps-based challenges.
- For time-based challenges, a future field will be needed. Do not add time scoring until the challenge type needs it.

## 5. Public Athlete Profiles

Each registered user gets a public athlete profile.

Route:

- `/athlete/<slug>/`

Profile should show:

- Display name
- Current overall rank
- Current tier
- Verified PR
- Progress graph
- Verified submission history
- Badges
- Rank history

MVP rule:

- Only registered users have athlete profiles.
- Legacy anonymous submissions remain visible on leaderboards but do not get full athlete pages unless later claimed.

## 6. Shareable Rank Cards

Authenticated users can generate a social-share rank card.

### Route

- `/rank-card/`

### MVP Implementation

Use an HTML/CSS card optimized for screenshots first.

Card dimensions:

- Instagram Story/TikTok friendly: `1080x1920` aspect ratio.
- Responsive preview in browser.

Include:

- Display name
- Verified rank
- Tier
- Verified PR reps
- Earned Club branding

### Later Implementation

Add downloadable image generation after the HTML card is stable.

Options:

- Browser-side screenshot using `html2canvas`
- Server-side image generation with Pillow
- Headless browser rendering if deployment supports it

Only verified results may appear on rank cards.

## 7. Badges / Achievement System

Add achievements to reward retention.

### Badge Model

Fields:

- `name`
- `slug`
- `description`
- `badge_type`
- `icon`
- `created_at`

### UserBadge Model

Fields:

- `user`
- `badge`
- `awarded_at`
- `source_submission`

### MVP Badges

- First Submission
- Top 10
- Elite Athlete
- Weekly Winner
- 5 Submission Streak

### Awarding Rules

- Only verified submissions trigger badges.
- Badge awarding can run after admin verification.
- MVP can use a management command or model/admin action before moving to signals.

## 8. Navigation Update

Update navigation in `base.html`.

### Public Navigation

- Home
- Challenge
- Leaderboard
- Profiles
- Calculators NOT LISTED - only link through button on homepage

### Logged-Out Controls

- Login
- Register

### Logged-In Controls

- Dashboard
- My Profile
- Logout

## 9. Preserve Manual Verification

Do not remove the manual verification workflow.

Every feature must respect:

- Unverified submissions can exist.
- Verified submissions are manually approved by admin.
- Only verified submissions count for rankings, dashboard progress, badges, rank cards, challenge winners, and public athlete statistics.

### Recommended Verification Upgrade

Replace boolean-only verification with status choices:

- `pending`
- `verified`
- `rejected`

For backward compatibility:

- Keep `verified` during the migration or replace it carefully.
- If replacing, migrate `verified=True` to `status=verified`, `verified=False` to `status=pending`.
- Add helper property `is_verified`.

MVP can keep `verified` and add `rejected` only when needed for the one-active-submission rule.

## 10. MVP Implementation Priority

### Phase 1

- Registration
- Login
- Logout
- Profile model
- User-linked submissions
- Public athlete profiles
- Navigation update
- One active pending submission rule

### Phase 2

- Authenticated dashboard
- Progress metrics
- Progress graph
- Rep-to-Elite calculator cleanup

### Phase 3

- Challenge model
- Active weekly challenge display
- Challenge-specific submissions
- Challenge leaderboard
- Archived challenges
- Shareable rank card HTML version
- Badge models and first badge awarding flow

## 11. Low-Friction Honor-System Submission

Keep the first submission as low-friction as possible.

Allow logged-out submission with:

- Name
- Email
- Reps
- Optional video link

### Submission Visibility

Create two public board concepts:

- Verified board: manually approved results.
- Open board: unverified/pending honor-system entries.

### MVP Recommendation

Keep the existing verified leaderboard as the main public leaderboard.

Add open board only after the submission status model supports:

- Pending
- Verified
- Rejected

This avoids weakening the current credibility of the leaderboard.

## 12. One Active Submission at a Time

Users should only be able to have one active pending submission at a time.
Unverified users can send only 1 submit a day. Verified can send 3 a day.

### Rule

If a user already has a pending/unverified submission, they cannot submit another result until the existing one is:

- verified
- rejected
- deleted by admin

This applies to:

- Normal leaderboard submissions
- Challenge submissions

### Behavior

If the user tries to submit again while a pending submission exists, show:

`You already have a submission waiting for verification. Please wait until it is reviewed before submitting again.`

### Scope

- Registered users: enforce by `Submission.user`.
- Logged-out users: enforce by submitted email once `email` exists on `Submission`.

### Required Model Support

Add `email` to `Submission` for logged-out honor-system entries.

Recommended fields:

- `email = EmailField(blank=True)`
- `status = CharField(choices=[pending, verified, rejected], default=pending)`

If keeping `verified` temporarily:

- Treat `verified=False` as active pending.
- Rejected state will require either `status` or `rejected` boolean.

## Data Model Plan

### Phase 1 Models

Add:

- `Profile`

Modify:

- `Submission.user`
- `Submission.email`

Recommended but can be deferred:

- `Submission.status`

### Phase 2 Models

No required new models if dashboard metrics are calculated from `Submission`.

Optional:

- `RankSnapshot` for rank history if exact historical rank movement is required.

### Phase 3 Models

Add:

- `Challenge`
- `Badge`
- `UserBadge`

Modify:

- `Submission.challenge`

Optional later:

- `RankSnapshot`
- `Follow`
- `Notification`

## Implementation Plan

## Phase 0: Stabilize Current Foundations

1. Run current tests.
2. Add tests around rank tiers and calculator expectations.
3. Fix calculator tier thresholds to match `RANK_TIERS`.
4. Decide whether to add `status` immediately or keep `verified` for Phase 1.

Recommended decision:

Add `status` now because one-active-submission and rejected submissions need it. Keep `verified` as a compatibility property or migrate templates/views to `status`.

## Phase 1: Accounts, Profiles, and Linked Submissions

1. Add `Profile` model.
2. Add migration for `Profile`, `Submission.user`, `Submission.email`, and optional `Submission.status`.
3. Register `Profile` in admin.
4. Add registration/login/logout views or use Django auth views with custom templates.
5. Add templates:
   - `register.html`
   - `login.html`
   - `dashboard.html` placeholder
   - `athlete_profile.html`
6. Update `base.html` navigation for auth-aware links.
7. Update submission flow:
   - Logged-in: attach `request.user`.
   - Logged-out: collect `email`.
   - Enforce one active pending submission.
8. Add public athlete profile route.
9. Update tests:
   - User registration creates profile.
   - Logged-in submission links to user.
   - Pending duplicate submission is blocked.
   - Verified-only leaderboard still works.
   - Public athlete profile shows verified submissions only.

## Phase 2: Dashboard and Calculator

1. Implement dashboard view with `login_required`.
2. Calculate:
   - PR
   - rank
   - rank movement placeholder
   - total verified submissions
   - pending submissions
   - weeks active
   - streak
3. Add progress data serialization.
4. Render progress graph.
5. Update calculators page:
   - Current tier
   - reps to Elite
   - reps to Legend
   - estimated weeks
6. Add tests for dashboard access and verified-only calculations.

## Phase 3: Challenges, Cards, and Badges

1. Add `Challenge` model and migration.
2. Add `Submission.challenge`.
3. Update `/challenge/` to display active challenge.
4. Add challenge detail and archive routes.
5. Add challenge leaderboard.
6. Add rank-card route and HTML card template.
7. Add `Badge` and `UserBadge` models.
8. Implement badge awarding function.
9. Add admin actions or save hook for awarding badges after verification.
10. Add tests for challenge leaderboard, rank card verified data, and badge awarding.

## Future Retention Layer

After Phase 3, consider:

- Follow athletes
- Notifications when followed athletes improve
- Rivalries
- Claim legacy anonymous submission
- Supabase Storage video uploads
- Email notifications for verification result
- Public open board for pending honor submissions

## Acceptance Criteria

### Global

- Existing manual verification remains intact.
- Existing verified leaderboard behavior does not regress.
- All ranking and achievement features use only verified submissions.
- Anonymous legacy submissions remain supported.
- New authenticated submissions are linked to users.
- A user cannot submit a second pending result while one is waiting.

### Technical

- Migrations run on SQLite and Supabase Postgres.
- Tests cover changed submission and ranking behavior.
- Templates remain responsive.
- Admin can still review and manage submissions.
- No feature depends on Supabase Storage until video uploads are explicitly implemented.

### Adition
- To motivate users while submitting if its unverified somehow tell them if they would verify they would be no. x in vefified leaderboard

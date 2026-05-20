# Earned Club Project Plan

This document is the shared project map for Earned Club. Use it at the start of future conversations, feature work, debugging, deployment checks, and design decisions so everyone can quickly understand what the app is, how it is built, and what rules should stay consistent.

Keep this file current. Any meaningful product, route, model, scoring, verification, dashboard/profile, homepage, onboarding, deployment, or email-system change should update this plan in the same working session before the change is considered finished.

## Product Summary

Earned Club is a Django fitness web app built around one core promise: athletes earn public status by proving real performance.

The product is now a hybrid fitness leaderboard platform. Athletes currently submit performances across push-ups, pull-ups, and 5K. Each active discipline converts into points, and verified discipline points combine into the athlete's public Hybrid Score. Push-ups remain the flagship challenge and level test, but the main identity/status metric across the platform is now Hybrid Score.

The product also includes athlete profiles, public leaderboards, discipline leaderboards, workout planning, active workout sessions, goals, following/social pages, newsletter tools, SEO pages, and staff review/admin workflows.

Core positioning:

- The fitness leaderboard for real performance.
- Submit your best performance. Get ranked. Prove it.
- Hybrid Score is the public athlete status metric.
- Proof makes official rank credible.
- Public trust matters more than vanity metrics.

Current primary CTA language:

- Homepage primary CTA: "Submit Your Score", pointing to `/test/`.
- Calculator CTA: "Estimate Hybrid Score".
- Official submission CTA: "Submit Official Performance" or "Submit Your Score".
- QR, TikTok, Instagram, sticker, and short-link traffic should point to `/test/` unless there is a specific campaign reason not to.

## Tech Stack

- Framework: Django 5.2.13
- Language/runtime: Python 3.10 project environment
- Database:
  - Local: SQLite when `DATABASE_URL` is not set
  - Production: Supabase Postgres through `DATABASE_URL`
- Static files: WhiteNoise compressed manifest storage
- Media:
  - Local media under `MEDIA_ROOT`
  - Optional Supabase Storage for profile images and submission videos
- Deployment target: Render
- Email:
  - Temporarily disabled in the web app
  - Newsletter/submission notification models and admin screens are kept for later reactivation
  - SMTP/backend configuration notes are preserved below, but no web action should attempt real delivery right now

Important dependencies:

- `Django`
- `dj-database-url`
- `psycopg[binary]`
- `gunicorn`
- `Pillow`
- `whitenoise`

## Repository Map

- `core/`: Django project configuration.
  - `settings.py`: environment config, database selection, storage settings, security flags, static/media settings.
  - `urls.py`: includes the `main` app routes and serves local media in development.
  - `wsgi.py` / `asgi.py`: server entry points.

- `main/`: primary Django application.
  - `models.py`: core domain models: submissions, profiles, follows, challenge rooms, goals, workouts, content prompts, newsletters.
  - `views.py`: most product behavior and page controllers.
  - `urls.py`: route table for public, account, workout, admin, newsletter, SEO, and legal pages.
  - `forms.py`: custom registration form.
  - `admin.py`: Django admin model registrations.
  - `media_utils.py`: profile image and submission video processing.
  - `supabase_storage.py`: Supabase Storage upload/delete/public/signed URL helpers.
  - `context_processors.py`: shared site metadata for templates.
  - `countries.py`: country data for profiles/forms.
  - `tests.py`: regression coverage for submissions, verification, profiles, workouts, newsletter, SEO, and admin review.
  - `templates/`: all page templates.
  - `static/`: images and favicon.
  - `migrations/`: database schema history.

- `docs/`: planning and project documentation.
- `README.md`: local setup, production env, sitemap notes.
- `DEPLOYMENT_PLAN.md`: deployment-oriented plan.
- `render.yaml`: Render service config.
- `requirements.txt`: Python dependencies.
- `manage.py`: Django command entry point.

## Main Domain Models

### Submission

Represents a performance submission for one leaderboard discipline.

Supported disciplines:

- `pushups`
- `pullups`
- `run_5k`

Temporarily parked/legacy discipline:

- `run_10k`

Legacy aliases such as `5k` and `10k` are normalized to the current running discipline keys. Existing submissions default safely to `pushups`.

Key fields:

- `user`: optional linked Django user.
- `name`, `email`: public/contact identity fields.
- `discipline`: leaderboard discipline key.
- `reps`: stored performance value. For rep-based disciplines this is the rep count; for running disciplines this stores total seconds.
- `video_file`, `video_storage_path`: uploaded proof sources, mainly for strength submissions.
- `video_link`: proof link source, used for race results, Strava activities, and legacy proof links.
- `status`: `unverified`, `pending`, `verified`, or `rejected`.
- `verified`: legacy/synced boolean derived from status.
- `created_at`: submission time.

Important behavior:

- New submissions with no proof become `unverified`.
- New submissions with proof become `pending` unless explicitly verified.
- Verified submissions set `verified=True`.
- Pending submissions without proof are forced back to `unverified`.
- Saving a submission refreshes affected profile stats, Hybrid Score context, and official ranks.
- `proof_url` returns a Supabase signed URL, local file URL, or plain proof link depending on storage/source.
- Rep-based disciplines rank higher values above lower values.
- Time-based disciplines rank lower values above higher values.
- Running input accepts `MM:SS` or `HH:MM:SS` and displays times such as `21:34`.
- Running submissions cannot go below the configured world-record floor.
- Elite-level running and pull-up submissions require proof before they can be reviewed as official.

### VerificationEvent

Audit trail for review activity.

Actions:

- `submitted`
- `proof_added`
- `approved`
- `rejected`

Used to keep reviewer history and status changes explainable.

### Profile

One-to-one extension of Django `User`.

Key fields:

- `display_name`
- `slug`
- `profile_photo`
- `profile_image`
- `profile_storage_path`
- `country`
- `age`
- `bio`
- `current_rank`
- `personal_best_reps`

Important behavior:

- Created automatically when a new user is created.
- Slugs are generated from display name or username and made unique.
- Verified legacy push-up stats are refreshed from the best verified push-up submission.
- Public profile pages now prioritize Hybrid Score, Hybrid rank/title, discipline breakdown, and verified status.
- Claimed pending/unverified submissions are shown on the public profile discipline card as previews, but their points do not count toward official Hybrid Score, badges, rank, or verified history until approved.
- Earned badges are based on verified performance and rank.

### Follow

Represents one user following another user.

Rules:

- `follower` and `following` are unique together.
- Used by athlete profile and social list pages.

### ChallengeRoom and ChallengeRoomEntry

Challenge rooms are shareable friend-group competitions. A room has a unique token, title/description, scoring focus, and entries that link normal `Submission` records into the room.

Active room focuses:

- Hybrid Score
- Push-ups
- Pull-ups
- 5K

10K is intentionally not available in challenge rooms while 10K is parked from active user-facing flows.

Important behavior:

- Room links preserve context through `/test/`, `/challenge/`, `/login/`, and `/register/` with `room=<token>`.
- Guest `/test/` submissions can appear in a room as unclaimed/unverified.
- Multiple `/test/` submissions from the same guest session are grouped as one room participant so adding another discipline builds that athlete's room result instead of adding a duplicate participant.
- Logged-in `/challenge/` submissions can attach directly to a room.
- Registering after a room-based `/test/` journey attaches unowned session submissions to the new account where possible.
- Claiming a profile converts session-based room entries to the user participant key so later logged-in submissions continue the same room participant.
- Room ranking uses highest score for Hybrid Score, push-ups, and pull-ups; 5K uses fastest/lower time.

### Goal

User-defined performance or rank target.

Supported goal directions:

- Push-ups
- Pull-ups
- 5K
- Hybrid Score / rank where supported

10K goals are kept only for legacy data while 10K is parked from new user-facing flows. Goals may be active/inactive and public/private. Rep goals should target a higher value than the current verified best. Running goals should target a faster time than the current verified best and use mobile-friendly text time input such as `21:34`. Rank goals should point above the athlete's current rank/tier rather than allowing already-earned or lower tiers.

### WorkoutTemplate

Reusable workout template, either system-provided or user-owned.

Difficulties:

- `beginner`
- `intermediate`
- `advanced`

### Workout

User workout plan.

Key fields:

- `template`
- `title`
- `slug`
- `notes`
- `duration_minutes`
- `rest_interval_seconds`
- `is_public`
- `highlighted_on_profile`

Important behavior:

- Slugs are generated from owner and title.
- Only one workout per user can be highlighted on profile.
- Public workouts can appear in sitemap and public detail pages.

### WorkoutExercise

Exercise rows inside a workout.

Types:

- `strength`
- `cardio`
- `mobility`

Supports sets, reps, seconds, body part, notes, and ordering.

### WorkoutSession and WorkoutSessionExercise

Tracks an active or completed workout session.

Behavior:

- Starting a workout creates a session snapshot.
- Each exercise session tracks target sets and completed sets.
- Finishing a session marks it complete and stores completion time.

### ContentEnginePrompt

Staff-managed content prompt library for conversion/content pages.

Types:

- `level`: "What's your level?"
- `challenge`: "Can you beat this?"
- `compare`: rank comparison
- `progress`: fake vs real progress

### NewsletterSubscriber, NewsletterCampaign, NewsletterSegment, NewsletterSendEvent

Newsletter system for subscribers, campaign drafts/sends, manual segments, automatic segments, unsubscribe tokens, and send history.

## Ranking And Scoring Rules

Push-up rank tiers live in `main/models.py` as `RANK_TIERS`.

- Beginner: 0-19 reps
- Intermediate: 20-39 reps
- Advanced: 40-59 reps
- Elite: 60-79 reps
- Earned Legend: 80+ reps

Discipline-specific rank helpers also exist for pull-ups, 5K, and parked legacy 10K. Do not blindly apply push-up tiers to every discipline.

Current discipline standards:

- Push-ups: existing `RANK_TIERS`.
- Pull-ups: Beginner 0-4, Intermediate 5-9, Advanced 10-19, Elite 20-29, Earned Legend 30+.
- 5K: Beginner 30:00+, Intermediate sub-30, Advanced sub-25, Elite sub-18, Earned Legend sub-16.
- Parked legacy 10K: Beginner 60:00+, Intermediate sub-60, Advanced sub-50, Elite sub-38, Earned Legend sub-32.

Hybrid Score:

- Each verified discipline performance converts into roughly 0-1000 points.
- Rep-based scores use higher-is-better logic.
- Running scores use lower-is-better inverse logic.
- Current public point curves:
  - Push-ups: 20=250, 40=450, 50=600, 70=850, 85=950, 100=1000.
  - Pull-ups: 5=250, 10=500, 15=675, 20=800, 30=950, 35=1000.
  - 5K: 30:00=250, 25:00=450, 22:00=600, 18:00=850, 16:00=950, 15:00=1000.
  - Parked legacy 10K: 60:00=250, 50:00=450, 44:00=600, 38:00=800, 34:00=900, 32:00=950, 30:00=1000.
- Official Hybrid Score is the average of verified discipline points.
- No-proof results above 600 points require proof before they can appear on open leaderboards.
- Athletes with incomplete discipline sets can still have a Hybrid Score.
- Unverified and pending submissions can be visible but must not inflate official Hybrid Score.

Hybrid titles:

- Beginner Hybrid
- Intermediate Hybrid
- Advanced Hybrid
- Elite Hybrid Athlete
- Earned Legend

Official ranks are based only on verified submissions. A person is ranked by their best verified submission per discipline, and by verified discipline points for Hybrid Score.

Important distinction:

- Public/open leaderboards can show pending or unverified context depending on selected mode.
- Official status, rank, badges, and profile stats should come from verified submissions.
- The default `/leaderboard/` view is the Hybrid Leaderboard.
- The public Hybrid Leaderboard is an open leaderboard, not only a verified ranking: verified, pending, and eligible unverified athletes can appear. No-proof results above 600 points require proof before they can appear.
- Open Hybrid Leaderboard scores can include verified, pending, and eligible unverified discipline results. Official profile/dashboard Hybrid Score remains verified-only.
- Active discipline leaderboards are push-ups, pull-ups, and 5K; 10K remains parked/legacy.
- Verified anonymous athletes also appear on the Hybrid Leaderboard, grouped by their submission identity, so an account is not required to be visible in overall rankings.

## Core User Workflows

### Visitor

1. Lands on home page.
2. Uses the primary "Submit Your Score" CTA into the fast `/test/` funnel.
3. Chooses strongest discipline, enters result, name/age, optionally skips email, and cannot continue past the result step without a valid score/time.
4. Finishes `/test/`, which posts the result to the open leaderboard immediately as unverified.
5. Lands on the final "You're in!" result screen, with make-it-official proof, profile creation, native share/challenge, and leaderboard CTAs.
6. Can register/login and connect activity to a profile.
7. Can browse Hybrid Leaderboard, discipline leaderboards, profiles, public workouts, calculators, privacy, and terms.

### Athlete

1. Registers or logs in.
2. Uses dashboard to manage profile, Hybrid Score status, goals, submissions, proof, and workouts.
3. Submits challenge results across push-ups, pull-ups, and 5K.
4. Adds proof for unverified submissions.
5. Tracks Hybrid Score, discipline breakdown, personal bests, and rank after verification.
6. Creates workouts, starts sessions, logs completed sets, and highlights one public workout.
7. Follows other athletes and shares profile/comparison pages.

### Staff/Admin

1. Uses Django admin or in-app admin pages.
2. Reviews pending submissions.
3. Approves, rejects, or changes status.
4. Review actions create verification events.
5. Can manage content engine prompts.
6. Can manage newsletter subscribers, campaigns, segments, and sends.

## Key Routes

Public:

- `/`: home
- `/test/`: fast onboarding-style performance funnel
- `/test/official/`: session-level proof flow for completed `/test/` results; updates existing submissions instead of creating duplicates
- `/test/result/<token>/`: public share page for a test-session Hybrid Score preview challenge
- `/challenge/`: challenge submission
- `/rank/`: discipline rank check and Hybrid Score calculator
- `/leaderboard/`: default Hybrid Leaderboard
- `/leaderboard/<discipline_key>/`: discipline leaderboard for active public disciplines such as pushups, pullups, and run_5k; run_10k remains legacy/parked only
- `/profiles/`: athlete directory
- `/athlete/<slug>/`: public athlete profile
- `/athlete/<slug>/follow/`: follow toggle
- `/athlete/<slug>/<kind>/`: followers/following social list
- `/comparison/`: athlete comparison picker/search page for creating shareable Hybrid 1v1 battles
- `/comparison/<left>vs<right>/`: athlete comparison using Hybrid Score, displayed as `Name vs Name`
- `/comparison/<left>vs<right>/join/`: official comparison challenge join action; guests can view the battle but are sent to claim an athlete profile before joining officially
- `/challenge-room/create/`: creates a shareable challenge room
- `/challenge-room/<token>/`: room leaderboard with room-preserved join/submission links
- `/test/submissions/<id>/proof/`: session-protected proof upload/link flow that makes an existing `/test/` result official-reviewable without creating a duplicate result
- `/calculators/`: calculators
- `/workout/<slug>/`: public workout detail
- `/privacy/`: privacy page
- `/terms/`: terms page

Account:

- `/register/`
- `/login/`
- `/logout/`
- `/dashboard/`
- `/dashboard/submissions/<id>/proof/`
- `/dashboard/submissions/<id>/delete/`
- `/dashboard/goals/<id>/delete/`

Workouts:

- `/workouts/`
- `/workouts/start/`
- `/workouts/sessions/<id>/`
- `/workouts/sessions/<id>/finish/`
- `/workouts/sessions/<id>/exercise/<exercise_id>/`
- `/workouts/<id>/delete/`
- `/workouts/<id>/highlight/`
- `/dashboard/workouts/<id>/duplicate/`
- `/dashboard/workouts/quick-add-last/`

Admin/staff:

- `/admin/`: Django admin
- `/admin-menu/`: in-app admin menu
- `/admin-menu/challenge-rooms/`: staff overview of existing challenge rooms with public and Django-admin edit links
- `/admin-menu/users/`: staff overview of registered users with Django-admin edit links
- `/admin-review/`: review queue
- `/admin-review/<submission_id>/`: review detail/action
- `/content/`: content engine admin
- `/content-engine-admin/`: legacy content admin route
- `/newsletter/`: newsletter admin
- `/newsletter/subscribers/<id>/`: subscriber detail

SEO/system:

- `/sitemap.xml`
- `/sitemap.xsl`
- `/robots.txt`
- `/newsletter-signup/`
- `/newsletter/unsubscribe/<token>/`

## Templates

Main templates:

- `base.html`: shared layout.
- `home.html`: first public page centered on Hybrid Score, proof, rank tiers, and the primary "Submit Your Score" CTA.
- `test_landing.html`: fast onboarding funnel: choose strongest discipline, enter result, enter name/age, optionally skip email, then show an unverified preview card.
- `test_proof.html`: proof upload/link page for a session-known `/test/` submission; updates the existing result and sends it to review.
- `test_session_official.html`: lists completed `/test/` session disciplines and allows adding proof to each existing result.
- `test_result_share.html`: social-friendly public result summary for challenging friends to beat a test-session Hybrid Score preview.
- `challenge.html`: multi-discipline submission workflow.
- `leaderboard.html`: Hybrid Leaderboard, discipline cards, discipline leaderboard modes, and ranking display.
- `rank.html`: discipline rank check and Hybrid Score calculator.
- `dashboard.html`: logged-in athlete dashboard with Hybrid Score hero, discipline breakdown, and selectable progress graph.
- `athlete_profile.html`: public profile centered on Hybrid Score and verified discipline breakdown.
- `profiles.html`: profile directory.
- `comparison.html`: Hybrid Score 1v1 picker and battle page with `Name vs Name`, winner crown, point margin, discipline breakdown, strengths/weaknesses, invited/joined athletes, Join Challenge, Test Your Score, and Copy Link / Share actions.
- `challenge_room_create.html`: room creation form for Hybrid Score, push-ups, pull-ups, and 5K.
- `challenge_room.html`: mobile-first room leaderboard with share link, current winner, participant rows, claimed/unclaimed status, and room-preserved CTAs.
- `social_list.html`: followers/following lists.
- `workouts.html`: workout creation/listing/generation.
- `workout_detail.html`: public workout page.
- `workout_session.html`: active session tracker.
- `admin_menu.html`: staff entry point.
- `admin_challenge_rooms.html`: staff challenge room overview with search, participant counts, public links, and Django-admin edit actions.
- `admin_users.html`: staff registered-user overview with search, account/profile/submission context, and Django-admin edit actions.
- `admin_review.html`: in-app verification queue.
- `content_engine_admin.html`: content prompt management.
- `newsletter_admin.html`: newsletter campaign/admin page.
- `newsletter_subscriber_detail.html`: subscriber detail/admin page.
- `calculators.html`, `privacy.html`, `terms.html`, `login.html`, `register.html`, `sitemap.xsl`.

When editing UI, keep the experience utilitarian and athlete/status focused. Avoid turning operational pages into marketing-style pages. Dashboard, review, newsletter, and workout tools should be dense, readable, and efficient.

Header/logo note: the current navbar uses `main/static/Earned_Club_wthBG.png` as the visible Earned Club logo. The text brand label beside it is hidden because the image itself contains the wordmark.

## Environment Variables

Required for production:

- `SECRET_KEY`
- `DEBUG=False`
- `SITE_URL=https://earnedclub.club`
- `ALLOWED_HOSTS=earnedclub.club,www.earnedclub.club,earnedclub.onrender.com`
- `CSRF_TRUSTED_ORIGINS=https://earnedclub.club,https://www.earnedclub.club,https://earnedclub.onrender.com`
- `DATABASE_URL=<Supabase Postgres connection string>`

Optional email:

- `EMAIL_BACKEND`
- `DEFAULT_FROM_EMAIL`
- `EMAIL_HOST`
- `EMAIL_PORT`
- `EMAIL_HOST_USER`
- `EMAIL_HOST_PASSWORD`
- `EMAIL_USE_TLS`
- `EMAIL_USE_SSL`
- `EMAIL_TIMEOUT`
- `NEWSLETTER_FROM_EMAIL`
- Supported aliases: `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_FROM_EMAIL`, `EMAIL_PASSWORD`

Recommended Gmail SMTP on Render:

```text
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_USE_TLS=True
EMAIL_HOST_USER=earnedclub1@gmail.com
EMAIL_HOST_PASSWORD=<Gmail app password>
DEFAULT_FROM_EMAIL=Earned Club <earnedclub1@gmail.com>
NEWSLETTER_FROM_EMAIL=Earned Club <earnedclub1@gmail.com>
```

For Gmail, use an App Password, not the normal Gmail account password.

Optional Supabase Storage:

- `SUPABASE_URL`
- `NEXT_PUBLIC_SUPABASE_URL`
- `PUBLIC_SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`
- `SUPABASE_SERVICE_KEY`
- `SUPABASE_SECRET_KEY`
- `SUPABASE_SUBMISSION_BUCKET`, default `Submit_video`
- `SUPABASE_PROFILE_BUCKET`, default `Profile_picture`
- `SUPABASE_SIGNED_URL_TTL`, default `3600`

Other:

- `TIME_ZONE`, default `Europe/Prague`

Security behavior:

- SSL redirect, secure cookies, and HSTS are enabled when `DEBUG=False`.
- `SECURE_PROXY_SSL_HEADER` is set for Render/proxy HTTPS.

## Local Development Commands

Create/activate virtual environment, then:

```powershell
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver
```

Health checks:

```powershell
python manage.py check
python manage.py test
python manage.py migrate --noinput
```

Static collection check:

```powershell
python manage.py collectstatic --noinput
```

Create admin:

```powershell
python manage.py createsuperuser
```

## Testing Expectations

The main regression suite is in `main/tests.py`.

Coverage currently includes:

- challenge submission creation and validation
- discipline support for push-ups, pull-ups, 5K, and 10K
- running time parsing and display
- Hybrid Score calculation
- verified-only official Hybrid Score logic
- anonymous and logged-in submission rules
- proof upload/link behavior
- duplicate proof/submission blockers
- honeypot handling
- verification status synchronization
- audit events and email notifications
- registration/profile creation
- profile slug uniqueness
- dashboard stats, profile updates, Hybrid Score context, and selectable performance progress series
- public profile visibility rules
- Hybrid Leaderboard, discipline leaderboard modes, verified ranking behavior, reps-desc sorting, and time-asc sorting
- calculators and rank page Hybrid Score UI
- goals and workouts
- workout generation and active sessions
- highlighted workout constraint
- follow toggle
- content engine prompt creation
- newsletter subscribers, segments, campaigns, and sends
- sitemap, XSL, and robots output
- in-app admin review permissions and actions

Before merging meaningful behavior changes, run:

```powershell
python manage.py test
```

For config-only changes, also run:

```powershell
python manage.py check
```

## Deployment Notes

Production is intended to run on Render with Supabase Postgres.

Important deployment checks:

- `DATABASE_URL` points to the Supabase Postgres connection string.
- `SITE_URL` is the canonical public domain, usually `https://earnedclub.club`.
- `ALLOWED_HOSTS` contains public and Render domains.
- `CSRF_TRUSTED_ORIGINS` contains the full HTTPS origins.
- Static files are collected and served through WhiteNoise.
- A superuser exists for admin access.
- If Supabase Storage is enabled, service role credentials and bucket names are correct.

SEO checks:

- `https://earnedclub.club/sitemap.xml` should return HTTP 200 and XML.
- `https://earnedclub.club/robots.txt` should reference the sitemap.
- `SITE_URL` should not be set to the Render subdomain in production unless intentionally changing canonical URLs.

## Product Rules To Preserve

- Do not treat unverified submissions as official rank.
- Do not award official profile status from pending or rejected submissions.
- Do not count unverified or pending submissions toward official Hybrid Score.
- Do not apply push-up rank tiers blindly to pull-ups or running disciplines.
- Do not allow time-based running submissions below configured world-record benchmarks.
- Do require proof for elite-level running and pull-up submissions.
- Do not lose the audit trail when review actions happen.
- A submission with proof should move toward review; a submission without proof should stay unverified.
- A user's personal best should come from verified submissions only.
- Legacy push-up profile stats should keep working while Hybrid Score becomes the main public status metric.
- Only one workout per user can be highlighted on profile.
- Public workout/profile pages should remain crawlable and sitemap-friendly.
- Unsubscribe tokens must remain unique.
- Staff-only pages must remain protected by staff/superuser checks.

## Communication Conventions For Future Work

When asking for or discussing new work, include as much of this as possible:

- Feature area: submissions, verification, profiles, dashboard, workouts, newsletter, SEO, deployment, design, or admin.
- User role: visitor, athlete, staff, admin, or search crawler.
- Expected behavior: what should happen.
- Current behavior: what happens now.
- Important page/template/route if known.
- Whether the change affects official ranks, proof, privacy, or public SEO.
- Whether existing data needs a migration or backfill.
- Whether tests should be added or updated.

Good task example:

```text
Feature area: verification/admin review.
Role: staff.
Route: /admin-review/<id>/.
Expected: staff can add a rejection note and the athlete gets an email.
Current: status changes to rejected but no note appears in the athlete history.
Please update behavior and tests.
```

## Common Change Areas

### Add or change a page

Usually touches:

- `main/urls.py`
- `main/views.py`
- `main/templates/<page>.html`
- tests in `main/tests.py`

If public/SEO-relevant, also inspect sitemap behavior in `build_sitemap_entries`.

### Change submission rules

Usually touches:

- `main/models.py`
- `main/views.py`
- `main/tests.py`
- `admin_review.html` or `challenge.html`

Be careful with discipline normalization, rank, Hybrid Score, profile stats, status synchronization, proof requirements, world-record floors for running, and verified-only official logic.

### Change profile behavior

Usually touches:

- `Profile` in `main/models.py`
- dashboard/profile sections in `main/views.py`
- `dashboard.html`
- `athlete_profile.html`
- `profiles.html`
- profile-related tests

Hybrid Score is now the main public profile metric. Legacy push-up PR fields still exist and should not be removed casually because existing tests, rankings, badges, and comparisons may depend on them.

### Change workouts

Usually touches:

- `Workout`, `WorkoutExercise`, `WorkoutSession`, `WorkoutSessionExercise`
- workout helper functions in `main/views.py`
- `workouts.html`, `workout_detail.html`, `workout_session.html`
- workout tests

### Change newsletters

Usually touches:

- newsletter models in `main/models.py`
- newsletter helpers/views in `main/views.py`
- `newsletter_admin.html`
- `newsletter_subscriber_detail.html`
- newsletter tests

### Change deployment or storage

Usually touches:

- `core/settings.py`
- `render.yaml`
- `main/media_utils.py`
- `main/supabase_storage.py`
- `README.md`
- deployment docs

## Current Risk Notes

- `main/views.py` is large and contains many helper functions plus page controllers. Be extra careful with unrelated behavior when editing it.
- Submission `status` and `verified` are intentionally synchronized. Changes here can affect leaderboard, dashboard, profiles, and tests.
- Submission `reps` is a legacy field name but now stores either reps or running seconds depending on `discipline`.
- `discipline` defaults to pushups for backwards compatibility. Do not remove this default without a migration/backfill plan.
- Hybrid Score is official only when built from verified submissions.
- Open discipline leaderboards can show unverified/pending context, but official rank/status must remain verified-only.
- Supabase Storage is optional. Code should keep working locally with normal Django media files.
- Public URLs and sitemap behavior depend on `SITE_URL`; deployment mistakes can hurt SEO.
- Some docs folders have naming typos from earlier history (`implementation-pan`, `implemetation-plans`). Avoid moving them casually unless cleaning docs is the explicit task.

## Change Log

Note: the newest entry is authoritative for current product direction. Older entries are preserved as historical implementation notes and may describe behavior that was later superseded.

### 2026-05-20 mobile test continuation and admin overview update

- `/test/` post-result Hybrid Score continuation rows now use a mobile-first two-row layout so discipline labels, status, and next-discipline CTAs do not squeeze into vertical text on small screens.
- The continuation checklist still shows completed disciplines, unverified status, and next active disciplines for building a fuller Hybrid Score.
- `/admin/` is explicitly mounted in project URLs so registered Django admin model screens are reachable.
- `/admin-menu/` now links to challenge room and registered user overviews.
- `/admin-menu/challenge-rooms/` lists existing challenge rooms with search, focus, entry count, participant count, public room links, and Django-admin edit/delete access.
- `/admin-menu/users/` lists registered users with search, email/profile context, submission count, created-room count, and Django-admin edit/delete access.

### 2026-05-20 full /test/ Hybrid journey update

- `/test/` now behaves as a multi-discipline Hybrid Score journey across active disciplines: push-ups, pull-ups, and 5K.
- 10K remains parked from active `/test/` UI.
- The test journey keeps using `test_session_id` and remembered submission ids to group anonymous or logged-in test results.
- After each completed discipline, `/test/` shows discipline points, Hybrid Score Preview average, completion checklist, open/unverified status, and next-discipline CTAs.
- Hybrid Score Preview averages only completed test-session disciplines.
- Completing all three active disciplines shows "Full Hybrid Score completed", "3/3 disciplines completed", current preview score, title, and final CTAs.
- Strong `/test/` results above the no-proof open threshold are now saved first, then guided to proof, instead of being blocked before submission.
- `/test/official/` lists all completed session disciplines and lets athletes add proof to existing submissions without creating duplicates.
- Added public share pages at `/test/result/<token>/` so Challenge a Friend summarizes the athlete name, Hybrid Score Preview, completed count, and discipline breakdown instead of sharing a generic `/test/` link.
- Challenge room context remains preserved through `/test/`; discipline-specific rooms lock `/test/` to the room discipline, while Hybrid rooms allow push-ups, pull-ups, and 5K.
- Logged-in profile claiming now attaches remembered test-session submissions on login as well as registration where safely possible.
- Official profile/dashboard Hybrid Score remains verified-only; `/test/` preview and Open Score remain non-official until proof and staff verification.

### 2026-05-17 early-submission conversion update

- `/test/` now frames Step 1 as "What is your strongest discipline?" while preserving all four entry disciplines.
- `/test/` blocks continuing from the performance entry step until the athlete enters a valid result.
- `/test/` final result step is required and posts directly from `/test/` instead of feeling like an optional preview.
- The final `/test/` screen appears after the result has already been saved and starts with "You're in!".
- Anonymous athletes can submit without email; name and performance are still required.
- Post-submit success copy now states that the result is already on the open leaderboard.
- Post-submit actions now prioritize making the result official with proof, creating or viewing a profile, opening the native challenge/share menu, and seeing yourself on the leaderboard.
- Share copy now challenges another person to beat the submitted result and points them to `/test/`.
- Homepage and leaderboard now show a real recent activity strip sourced from actual submissions and proof-added events only.
- Early entries can show Founding Athlete / early leaderboard status when they are among the first 100 Earned Club submissions.
- Empty leaderboard states now use "No one owns this board yet. Be first." with a direct `/test/` CTA.
- Proofless results above 600 points require proof before appearing on open leaderboards.
- Hybrid Leaderboard now behaves as an open leaderboard by including verified, pending, and unverified athletes instead of only verified official rankings.
- Leaderboard rows now keep neutral black/grey bodies; score intensity appears only through a small left-side fill meter.
- Hybrid Leaderboard rows now use the same table structure as discipline leaderboards: discipline, athlete, score, rank, status, and position.
- Hybrid Leaderboard status labels use Official or Unofficial; Founding athlete appears under the status label.
- Leaderboard row bodies should stay neutral black/grey; rank intensity is shown as a small left-side vertical fill meter that grows upward by score tier.
- Hybrid Leaderboard uses the same mode controls as discipline leaderboards: Open Board, Verified Only, This Week, This Month, Pending, and Unverified.
- Admin review now defaults the status filter to All.
- Admin review shows how many submissions arrived since the staff member last checked the review page.
- `/test/` no longer allows anonymous results to post with a blank fallback name; logged-in users can still post through their profile identity.
- Rank colors are standardized across the web: Beginner grey, Intermediate blue, Advanced gold, Elite orange, and Legend green.
- Hybrid rank tier cards on leaderboard use the same colorful tier-card treatment as the homepage.
- Hybrid Points Calculator running sliders are directionally normalized: dragging right always improves the score, so lower 5K/10K times sit on the right side.

### 2026-05-12 current hybrid UX and planning update

- Project plan must be updated in the same session as meaningful product, scoring, route, verification, deployment, email, homepage, dashboard, profile, onboarding, or admin changes.
- Homepage hero now uses "Submit Your Score" as the primary CTA and sends that traffic to `/test/`; "Estimate Hybrid Score" remains the secondary calculator CTA.
- Homepage first section is centered on the hybrid athlete leaderboard, proof, and official Hybrid Score rather than a generic score check.
- Homepage first section desktop layout keeps the Hybrid Score preview attached to the main hero copy instead of drifting into a detached right-side block.
- The homepage score card now presents an example official athlete rating and links down to rank tiers instead of duplicating the submission CTA.
- Header logo was replaced with the new Earned Club wordmark image at `main/static/Earned_Club_wthBG.png`; duplicate navbar brand copy is hidden.
- `/test/` is now a fast onboarding-style funnel: choose strongest discipline, enter reps/time, enter name and age, optionally skip email, then see an unverified athlete preview.
- `/test/` preview now makes "Submit Your Score" the primary conversion action into `/challenge/`, with profile creation secondary.
- `/test/` final result is mandatory rather than an optional preview; submitting it posts the score to the open leaderboard directly from `/test/`.
- `/test/` Step 1 headline is "What is your strongest discipline?" while keeping push-ups, pull-ups, 5K, and 10K as choices.
- Anonymous challenge submissions can omit email; name and performance remain required.
- Post-submission success now emphasizes that the score is visible on the open leaderboard and pushes the athlete toward making it official, creating a profile, or challenging a friend.
- `/test/` discipline cards hide the native radio dot, use corner discipline badges such as PU/PL/5K/10K, and keep title/helper text separated for mobile readability.
- Running inputs in `/test/` use text entry for `MM:SS` or `HH:MM:SS` so mobile users can type `:`.
- `/challenge/` now shows a post-submit success card with result, status, Hybrid preview points, leaderboard/profile/proof CTAs, and a share action.
- Unverified submissions now use the reward copy: "You are now on the open leaderboard. Add proof to make it official."
- 1v1 comparison now focuses on Hybrid Score rather than push-up deltas.
- 1v1 comparison displays `Name vs Name`, highlights the winner with a crown, and uses copy such as "Name wins by X Hybrid points" instead of delta language.
- Public profile improvement recommendations should remain personal/dashboard context, not public-facing clutter.
- Email delivery remains parked; database actions should not fail because an email side effect fails.

### 2026-05-11 hybrid leaderboard platform update

- Earned Club repositioned from a push-up-focused ranking app into a hybrid fitness leaderboard platform.
- Added multi-discipline submission support for push-ups, pull-ups, 5K, and 10K.
- Existing submissions default/backfill safely to pushups.
- Running disciplines use time-based scoring with lower-is-better sorting and `MM:SS` / `HH:MM:SS` display.
- Proof links are supported for race results, Strava activities, and legacy proof records.
- Strength proof can still use uploaded video.
- Elite-level running and pull-up submissions require proof for official review.
- Running submissions are guarded against impossible below-world-record times.
- Added discipline-specific rank logic instead of using push-up tiers everywhere.
- Added normalized 0-1000 discipline point scoring.
- Added Hybrid Score as the main overall athlete rating, based only on verified discipline performances.
- Added Hybrid titles: Beginner Hybrid, Intermediate Hybrid, Advanced Hybrid, Elite Hybrid Athlete, and Earned Legend.
- `/leaderboard/` now defaults to the Hybrid Leaderboard.
- Discipline leaderboard routes are available under `/leaderboard/<discipline_key>/`.
- Open discipline leaderboards can show unverified/pending results while official ranks remain verified-only.
- Homepage sample rank card now promotes Hybrid Score rather than only push-up reps.
- `/rank/` now supports discipline rank checking and includes a Hybrid Score calculator.
- `/calculators/` now includes a Hybrid Score calculator and discipline tier calculator.
- Public athlete profiles prioritize Hybrid Score, Hybrid title/rank, verified status, and discipline breakdown.
- Dashboard now uses a Hybrid Score hero/status layout and includes a selectable progress graph for Hybrid Score, push-ups, pull-ups, 5K, and 10K.
- Admin review and dashboard submission areas display discipline and formatted score/time clearly.
- Tests were expanded for Hybrid Score, discipline submissions, running time parsing, leaderboard sorting, verified-only official logic, calculators, rank page, dashboard progress series, profile rendering, and admin review compatibility.

### 2026-05-06 conversion and rank flow update

- Added `/rank/` as a minimal mobile-first conversion page for social traffic.
- `/rank/` uses the existing `get_rank_tier` / `RANK_TIERS` logic and does not change verified ranking rules.
- Superseded by the hybrid positioning update: home page now focuses on Hybrid Score and the Hybrid Leaderboard.
- Home secondary CTA is "View Leaderboard".
- Superseded by the hybrid positioning update: conversion copy now centers on verified multi-discipline performance and Hybrid Score.
- Challenge page copy now makes proof optional but clearly recommended.
- Challenge page explains that unverified results are visible but not official, and proof is required for official rank.
- Challenge form now uses uploaded video proof only; proof links are not user-facing.
- Post-submit messages now distinguish between unverified no-proof submissions and proof-backed pending review submissions.
- Leaderboard copy now states that official ranks require proof, unverified results are shown but not official, and verified athletes earn public status.
- Test page placeholder name was changed from the personal/encoding-broken example to "Jack".
- Staff admin menu now links to a new pages index at `/admin-menu/pages/`.
- The pages index lists existing app routes and direct links for static routes.
- Submission admin notifications still go to `daniel.havlicek1@seznam.cz`.
- Email sending now uses a helper that logs delivery exceptions instead of silently swallowing them.
- Newsletter sends now report failed recipients in the admin UI instead of always showing a successful send.
- Django email settings now read standard SMTP environment variables, so production delivery can be configured on Render.
- Admin menu site health now shows SMTP host/user configuration status.
- `/rank/` was added to the sitemap static pages list.

### 2026-05-06 upload-only proof correction

- Removed the proof link field from the challenge submission form.
- Challenge submissions now treat only uploaded video files as proof.
- Dashboard add-proof flow now requires an uploaded video file and clears any posted proof link.
- New challenge submissions ignore posted `video_link` values so hidden/manual link posts cannot create proof-backed results.
- Kept `video_link` in the database/model for legacy submissions and admin review visibility only.
- Video processing now falls back to the original upload if `ffmpeg` is unavailable.
- Superseded by the 2026-05-11 hybrid update for running submissions: proof links are again user-facing where appropriate for race results and Strava activities.

### 2026-05-06 admin pages and email delivery correction

- Reworked `/admin-menu/pages/` to use an explicit page list instead of importing URL patterns from inside the view.
- Newsletter admin and single-subscriber direct email pages now show the configured sender address.
- Newsletter send buttons are disabled when Django is using console-only email or missing required SMTP settings.
- Direct single-recipient sends now fail visibly when real delivery is not configured instead of looking successful.
- `EMAIL_BACKEND` now automatically switches to SMTP when SMTP host/user/password environment variables are present and no explicit backend is set.
- `NEWSLETTER_FROM_EMAIL` defaults to the SMTP user address when available.
- Admin menu site health now shows the email delivery readiness message.

### 2026-05-06 SMTP diagnostics correction

- SMTP settings now support common Render/env aliases like `SMTP_HOST`, `SMTP_USER`, and `SMTP_PASSWORD`.
- SMTP defaults now enable TLS automatically for port 587 and SSL automatically for port 465.
- Direct newsletter send failures now display the actual SMTP exception instead of only saying to check settings.
- Admin menu site health now shows SMTP port and TLS/SSL status.

### 2026-05-11 email system parked

- Email delivery is intentionally disabled in the web app for now.
- Reason: submission/review database actions were succeeding, but follow-up mail side effects could still produce production 500s.
- Current behavior: `safe_send_mail()` is a no-op, newsletter send buttons remain disabled, submission/admin/review flows keep saving data without trying SMTP.
- Kept for later: newsletter subscribers, segments, campaigns, send history, admin newsletter screens, submission notification helper names, and SMTP settings notes.
- Previous design: submission flows called admin/user notifications after saving; admin review sent accepted/rejected emails; newsletter admin used `send_newsletter_to_subscribers()`.
- Reintroduction plan:
  - Add an explicit feature flag such as `EMAIL_SYSTEM_ENABLED=True`.
  - Keep email sending outside critical database transactions and never let delivery failure roll back a saved result or review.
  - Configure production SMTP through Render environment variables.
  - Re-enable `safe_send_mail()` to call Django `send_mail()` only when the flag and SMTP health checks pass.
  - Restore/update newsletter delivery tests and keep failure-path tests proving saves do not 500 when mail fails.

### 2026-05-06 homepage second-pass polish

- Superseded by the hybrid positioning update: homepage hero now uses Hybrid Score as the primary CTA concept.
- The large `42` visual was redesigned into an intentional score-to-rank preview card.
- Removed the small live-count/status emphasis from the homepage so the early-stage community does not feel artificially inflated.
- Added a "How ranks are earned" proof/status section focused on unverified, review, and official status.
- Video/content area now uses polished thumbnail-style preview cards with play overlays and a future YouTube slot.
- Tools section now presents rank check, performance calculators, and leaderboard comparison as separate utilities.
- Added lightweight scroll reveal effects with reduced-motion support and graceful no-JS fallback.
- Homepage copy was tightened around "Don't just claim it. Prove it.", "One clean set. One public rank.", and "Built for performance, not vanity."

### 2026-05-06 full-site UX polish pass

- `/rank/` now hides the input form after a result is shown, removes result-state autofocus from the input, scrolls/focuses to the result, and includes "Check Again".
- Completed workout sessions now render as clean overviews without active set controls or rest timer controls.
- Profiles directory copy and tests now make clear that only registered user accounts appear; anonymous submitters remain leaderboard entries only.
- Newsletter direct-send failures now map `Network is unreachable` to an admin-friendly SMTP/network message and do not create send events.
- Newsletter week defaults no longer jump to the next number after every send/direct-send by default.
- Workout pagination on workout lists/dashboard now uses clear Previous / Page N / Next controls instead of ellipses.
- Generate workout desktop layout now uses a more intentional control grid and grouped body-part picker.
- EnduroBuddy.cz promo was restyled as a green ad block and placed on homepage/tools and workouts.
- Shared UI now has stronger focus-visible states and better long-text wrapping for admin health/email rows.
- Homepage score preview now uses layout containment to reduce desktop paint/layout cost.

### 2026-05-06 profile and hero refinement

- Public athlete profile hero was redesigned into a stronger identity/status layout with a PR-focused card.
- Homepage hero score preview now uses labels and status pills instead of repeated numbered steps.
- Homepage value/how-it-works areas now use named phase labels to reduce the overused 1/2/3/4 pattern.
- SMTP network failure copy was softened into an admin-friendly message about email server reachability and Render SMTP configuration.

### 2026-05-06 sitemap, mobile admin pages, and homepage polish

- `/sitemap.xml` now returns plain sitemap XML without an XSL stylesheet processing instruction.
- `/sitemap.xsl` remains available as a human-readable stylesheet page, but it should not be submitted to Google Search Console as a sitemap.
- `/sitemap.xsl` now sends `X-Robots-Tag: noindex`.
- Google Search Console should be given only `https://earnedclub.club/sitemap.xml`.
- Admin pages now include mobile cards so `/admin-menu/pages/` remains visible on small screens where tables are hidden.
- Superseded by the hybrid positioning update: homepage is now centered on Hybrid Score and the Hybrid Leaderboard.
- Homepage now includes hero, value strip, how-it-works, rank system, why-it-exists, feature preview, video/content placeholders, tools, and final CTA sections.
- Homepage keeps YouTube/content placeholders and links to calculators/tools and `/rank/`.
- Homepage copy now emphasizes "Don't just claim your strength. Prove it.", "Earn your rank.", "Verified status.", "Public leaderboard.", and "Real reps. Real proof."

### 2026-05-06 rank and first-screen conversion polish

- `/rank/` was redesigned from nested hero/panel cards into a single focused rank-check stage.
- `/rank/` now gives the input more space, hides it after result, animates the result ticket subtly, and keeps "Check Again" as the reset action.
- Homepage hero no longer uses a logo badge inside the first section.
- Header brand text now shows "EarnedClub" so the brand is readable without relying only on the logo.
- Homepage sample result was redesigned into a compact "Sample rank check" card with the large `42`, Advanced status, a rank meter, and proof-status copy.
- Homepage first mobile screen now has stronger headline sizing, tighter spacing, and a cleaner score-to-status visual for social traffic.

### 2026-05-06 header readability and mobile hero trimming

- Header brand text was restyled into a clearer high-contrast `EarnedClub` wordmark.
- Homepage hero copy was shortened so mobile visitors are not hit with too much text at the start.
- Removed the low-value hero chips for "Verified scores", "Public leaderboard", and "Real reps. Real proof."
- Added a compact scroll cue under the hero sample card to pull phone visitors toward rank tiers and proof rules.

### 2026-05-06 homepage first-view premium polish

- Homepage hero received stronger athletic lighting with layered gradients, a sharper border, and subtle angled highlights.
- Primary and secondary hero CTAs were given more intentional contrast and depth.
- The sample result card kept the same structure but gained richer lighting, edge depth, and a subtle highlight sweep.
- Mobile hero spacing was tightened so the first screen feels more visual and less text-heavy.
- Scroll cue copy was shortened and styled to make the next section feel more inviting.

### 2026-05-06 mobile hero fit and tier color pass

- Mobile homepage hero was compressed so more of the sample rank result appears in the first view.
- Mobile hero CTAs now sit side by side with smaller tap-friendly sizing.
- Mobile sample result hides secondary descriptive copy so the `42`, Advanced status, and rank meter appear sooner.
- Rank tier cards are now color-coded by level: Beginner, Intermediate, Advanced, Elite, and Earned Legend.

### 2026-05-06 focused hero simplification

- Homepage first hero was simplified after the premium pass to reduce visual chaos.
- Removed the extra angled highlight sweep from the sample result card and softened hero lighting.
- Mobile hero spacing and typography were adjusted for cleaner hierarchy.
- Mobile hero CTAs returned to a stacked layout for clearer primary action focus.
- Sample rank result remains a separate card in the first hero section.

### 2026-05-13 public scoring and calculator refresh

- Hybrid discipline point curves were updated to the current public thresholds for push-ups, pull-ups, 5K, and 10K.
- The fast `/test/` funnel now treats age as optional with an explicit skip action.
- Time entry accepts dot shorthand such as `21.34` and normalizes it to `21:34`; invalid time hints now suggest a valid format immediately.
- Leaderboard pages now show appealing point/rank tier context under the leaderboard chooser for Hybrid and each discipline.
- Calculators now include discipline selection and live sliders for single-discipline points or four-slider Hybrid Score estimation, replacing old push-up-only benchmark behavior.
- Homepage rank-tier anchor now lands at the beginning of the rank tier section so the tier hero/header is visible.

### 2026-05-13 anonymous Hybrid leaderboard and goal detail UX

- Hybrid Leaderboard now includes verified athletes without accounts, grouped by anonymous submission identity.
- Dashboard goals now open like badges, with a larger modal for share/delete, set date, completion time, improvement since the goal was set, point gain, and next suggested goal.
- Completed goals now use a stronger card structure: goal achieved, tier movement, Hybrid point gain, and the next suggested target.

### 2026-05-18 comparison and claim-profile growth update

- `/comparison/` now loads as a profile picker/search page for creating shareable athlete battles.
- `/comparison/<left>vs<right>/` now works as a richer Hybrid 1v1 challenge link with winner logic, point margin, discipline breakdown, strengths/weaknesses, joined athletes, Join Challenge, Test Your Score, and Copy Link / Share.
- Comparison pages now also promote group challenge rooms with a "Create Group Challenge" CTA for friend-group competitions.
- `/challenge-room/<id>/` style numeric room URLs are tolerated and redirected to the canonical token URL.
- Guests can still view comparison challenge links, but joining officially now pushes them to claim an athlete profile first.
- Registration language across public flows now emphasizes "Claim Your Athlete Profile", "Save Your Hybrid Score", "Make Your Score Official", athlete identity, badges, official challenge joining, and progress history.
- Post-test results, challenge submission success, leaderboard, profiles, rank tools, and comparison pages now present account creation as claiming status after the user has seen their result.
- Verified-only official Hybrid Score logic remains unchanged: official profile/dashboard status still comes only from verified submissions.

### 2026-05-18 test journey and temporary discipline availability update

- 10K is temporarily parked from active user-facing flows. The model/scoring constants remain for legacy data, but new public UI should present only push-ups, pull-ups, and 5K until 10K is re-enabled intentionally.
- `/test/` now keeps a lightweight session journey with a generated `test_session_id`, preserved name/age/email, and remembered anonymous test submission ids.
- `/test/` result success now makes the next step explicit: the athlete is on the open leaderboard, the Hybrid Score is incomplete, completed disciplines are checked off, and remaining active disciplines get direct next-step CTAs.
- Claiming an athlete profile after a `/test/` journey attaches unowned session submissions to the new account where possible.
- Unverified `/test/` results remain open-leaderboard results only and do not count toward official profile/dashboard Hybrid Score.
- The `/test/` "Make Your Score Official" CTA now opens a proof form for the existing session-known result instead of sending the athlete back through a duplicate submission form.
- Claimed account/profile cards now show pending or unverified owned results as previews, clearly marked as not official, while keeping official Hybrid Score verified-only.
- Added shareable challenge rooms at `/challenge-room/create/` and `/challenge-room/<token>/`.
- Challenge room links preserve room context through `/test/`, `/challenge/`, `/login/`, and `/register/` using `room=<token>`.
- Discipline-specific challenge rooms lock `/test/` and `/challenge/` to the room focus; Hybrid Score rooms allow the active supported disciplines.
- Room leaderboards show current winner, participant result, points, verification status, and claimed/unclaimed profile state.
- Room entries now store a participant key, so second and third `/test/` disciplines from the same guest session update one participant row instead of creating fake extra participants.
- 10K is excluded from challenge rooms and from the visible active web while parked.

## Short Glossary

- Hybrid Score: overall athlete rating from verified discipline points.
- Discipline: one leaderboard category such as pushups, pullups, run_5k, or run_10k.
- Official rank: rank/status based only on verified best submissions.
- Open leaderboard: broader leaderboard display that may include non-official statuses.
- Proof: race result link, Strava link, video link, uploaded file, or Supabase-stored video.
- Athlete: a registered user with a profile.
- Staff review: in-app or Django-admin verification workflow.
- Highlighted workout: the single workout shown prominently on an athlete profile.
- Content engine: staff-managed prompt/content ideas used by product pages.

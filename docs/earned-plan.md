# Earned Club Project Plan

This document is the shared project map for Earned Club. Use it at the start of future conversations, feature work, debugging, deployment checks, and design decisions so everyone can quickly understand what the app is, how it is built, and what rules should stay consistent.

## Product Summary

Earned Club is a Django fitness web app built around one core promise: athletes earn public status by proving real performance.

The main challenge is strict push-up performance. Users submit a rep count, optionally attach proof, and can earn an official verified rank after review. The product also includes athlete profiles, public leaderboards, workout planning, active workout sessions, goals, following/social pages, newsletter tools, SEO pages, and staff review/admin workflows.

Core positioning:

- Earn your rank.
- Prove your performance.
- Unlock status-based fitness rewards.
- Public trust matters more than vanity metrics.

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
  - Console backend by default
  - Configurable SMTP/backend through environment variables

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
  - `models.py`: core domain models: submissions, profiles, follows, goals, workouts, content prompts, newsletters.
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

Represents a push-up challenge submission.

Key fields:

- `user`: optional linked Django user.
- `name`, `email`: public/contact identity fields.
- `reps`: push-up count.
- `video_file`, `video_storage_path`: active proof sources. `video_link` remains in the model for legacy records/admin display, but new user-facing proof submission should use uploaded video only.
- `status`: `unverified`, `pending`, `verified`, or `rejected`.
- `verified`: legacy/synced boolean derived from status.
- `created_at`: submission time.

Important behavior:

- New submissions with no proof become `unverified`.
- New submissions with proof become `pending` unless explicitly verified.
- Verified submissions set `verified=True`.
- Pending submissions without proof are forced back to `unverified`.
- Saving a submission refreshes affected profile stats and official ranks.
- `proof_url` returns a Supabase signed URL, local file URL, or legacy plain video link depending on storage.

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
- Verified stats are refreshed from the best verified submission.
- Earned badges are based on verified performance and rank.

### Follow

Represents one user following another user.

Rules:

- `follower` and `following` are unique together.
- Used by athlete profile and social list pages.

### Goal

User-defined performance or rank target.

Types:

- `pushups`
- `rank`

Goals may be active/inactive and public/private.

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

## Ranking Rules

Rank tiers live in `main/models.py` as `RANK_TIERS`.

- Beginner: 0-19 reps
- Intermediate: 20-39 reps
- Advanced: 40-59 reps
- Elite: 60-79 reps
- Earned Legend: 80+ reps

Official ranks are based only on verified submissions. A person is ranked by their best verified submission, not every submission they have ever made.

Important distinction:

- Public/open leaderboards can show pending or unverified context depending on selected mode.
- Official status, rank, badges, and profile stats should come from verified submissions.

## Core User Workflows

### Visitor

1. Lands on home page.
2. Takes level test or goes to challenge.
3. Enters name, email, reps, and optional proof.
4. Can register/login and connect activity to a profile.
5. Can browse leaderboard, profiles, public workouts, calculators, privacy, and terms.

### Athlete

1. Registers or logs in.
2. Uses dashboard to manage profile, goals, submissions, proof, and workouts.
3. Submits challenge results.
4. Adds proof for unverified submissions.
5. Tracks personal best and rank after verification.
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
- `/test/`: level test
- `/challenge/`: challenge submission
- `/leaderboard/`: leaderboard
- `/profiles/`: athlete directory
- `/athlete/<slug>/`: public athlete profile
- `/athlete/<slug>/follow/`: follow toggle
- `/athlete/<slug>/<kind>/`: followers/following social list
- `/comparison/<left>vs<right>/`: athlete comparison
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
- `home.html`: first public page.
- `test_landing.html`: level test page.
- `challenge.html`: submission workflow.
- `leaderboard.html`: leaderboard modes and ranking display.
- `dashboard.html`: logged-in athlete dashboard.
- `athlete_profile.html`: public profile.
- `profiles.html`: profile directory.
- `comparison.html`: athlete comparison page.
- `social_list.html`: followers/following lists.
- `workouts.html`: workout creation/listing/generation.
- `workout_detail.html`: public workout page.
- `workout_session.html`: active session tracker.
- `admin_menu.html`: staff entry point.
- `admin_review.html`: in-app verification queue.
- `content_engine_admin.html`: content prompt management.
- `newsletter_admin.html`: newsletter campaign/admin page.
- `newsletter_subscriber_detail.html`: subscriber detail/admin page.
- `calculators.html`, `privacy.html`, `terms.html`, `login.html`, `register.html`, `sitemap.xsl`.

When editing UI, keep the experience utilitarian and athlete/status focused. Avoid turning operational pages into marketing-style pages. Dashboard, review, newsletter, and workout tools should be dense, readable, and efficient.

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
- anonymous and logged-in submission rules
- proof upload behavior
- duplicate proof/submission blockers
- honeypot handling
- verification status synchronization
- audit events and email notifications
- registration/profile creation
- profile slug uniqueness
- dashboard stats and profile updates
- public profile visibility rules
- leaderboard modes and verified ranking behavior
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
- Do not lose the audit trail when review actions happen.
- A submission with proof should move toward review; a submission without proof should stay unverified.
- A user's personal best should come from verified submissions only.
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

Be careful with rank, profile stats, status synchronization, and proof requirements.

### Change profile behavior

Usually touches:

- `Profile` in `main/models.py`
- dashboard/profile sections in `main/views.py`
- `dashboard.html`
- `athlete_profile.html`
- `profiles.html`
- profile-related tests

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
- Supabase Storage is optional. Code should keep working locally with normal Django media files.
- Public URLs and sitemap behavior depend on `SITE_URL`; deployment mistakes can hurt SEO.
- Some docs folders have naming typos from earlier history (`implementation-pan`, `implemetation-plans`). Avoid moving them casually unless cleaning docs is the explicit task.

## Change Log

### 2026-05-06 conversion and rank flow update

- Added `/rank/` as a minimal mobile-first conversion page for social traffic.
- `/rank/` uses the existing `get_rank_tier` / `RANK_TIERS` logic and does not change verified ranking rules.
- Home page now focuses on the primary CTA: "Take the Official Push-Up Test".
- Home secondary CTA is "View Leaderboard".
- Main conversion copy is now centered on: "Don't just claim your strength. Prove it." and "Submit your max clean push-ups and earn your rank."
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

### 2026-05-06 homepage second-pass polish

- Homepage hero now uses one primary "Get Your Rank" CTA and varies later CTAs by context.
- The large `42` visual was redesigned into an intentional score-to-rank preview card.
- Removed the small live-count/status emphasis from the homepage so the early-stage community does not feel artificially inflated.
- Added a "How ranks are earned" proof/status section focused on unverified, review, and official status.
- Video/content area now uses polished thumbnail-style preview cards with play overlays and a future YouTube slot.
- Tools section now presents rank check, performance calculators, and leaderboard comparison as separate utilities.
- Added lightweight scroll reveal effects with reduced-motion support and graceful no-JS fallback.
- Homepage copy was tightened around "Don't just claim it. Prove it.", "One clean set. One public rank.", and "Built for performance, not vanity."

### 2026-05-06 sitemap, mobile admin pages, and homepage polish

- `/sitemap.xml` now returns plain sitemap XML without an XSL stylesheet processing instruction.
- `/sitemap.xsl` remains available as a human-readable stylesheet page, but it should not be submitted to Google Search Console as a sitemap.
- `/sitemap.xsl` now sends `X-Robots-Tag: noindex`.
- Google Search Console should be given only `https://earnedclub.club/sitemap.xml`.
- Admin pages now include mobile cards so `/admin-menu/pages/` remains visible on small screens where tables are hidden.
- Homepage was redesigned mobile-first around the primary CTA "Get Your Rank".
- Homepage now includes hero, value strip, how-it-works, rank system, why-it-exists, feature preview, video/content placeholders, tools, and final CTA sections.
- Homepage keeps YouTube/content placeholders and links to calculators/tools and `/rank/`.
- Homepage copy now emphasizes "Don't just claim your strength. Prove it.", "Earn your rank.", "Verified status.", "Public leaderboard.", and "Real reps. Real proof."

## Short Glossary

- Official rank: rank based only on verified best submissions.
- Open leaderboard: broader leaderboard display that may include non-official statuses.
- Proof: video link, uploaded file, or Supabase-stored video.
- Athlete: a registered user with a profile.
- Staff review: in-app or Django-admin verification workflow.
- Highlighted workout: the single workout shown prominently on an athlete profile.
- Content engine: staff-managed prompt/content ideas used by product pages.

# EarnedClub: Supabase + Render plan

## Current state

- The project currently uses SQLite in `core/settings.py`.
- `DEBUG = True`, `ALLOWED_HOSTS = ['*']`, and the secret key is hardcoded, which is not suitable for production.
- WhiteNoise and `gunicorn` are present, so the app is already close to a simple Render deployment.
- There is no checked-in `render.yaml`, `Procfile`, or deployment guide in the repo.
- The app writes submissions to the database, but the leaderboard still shows static placeholder data.
- `main/models.py` and `main/migrations/0001_initial.py` are out of sync:
  - model: `reps`
  - migration/db history: `pushups`, `verified`

## Recommendation

Use Supabase only as the PostgreSQL database layer for Django in phase 1.

That is the cleanest path because:

- Django already expects a relational database.
- Supabase is PostgreSQL under the hood, so Django works well with it.
- You do not need the Supabase Python client for normal Django ORM usage.
- Render can connect to Supabase through `DATABASE_URL`.

Do **not** rebuild auth or data access around Supabase APIs right now. For this project, that would add complexity without much benefit.

## What to change first

### 1. Fix the data model before deployment

Pick one schema and make it consistent:

- Option A: keep `reps` and remove `verified`
- Option B: keep `pushups` and `verified`
- Option C: keep `reps` and also keep `verified`

Recommended:

- keep `reps`
- keep `verified`

Why:

- `reps` matches the current form field naming
- `verified` is useful for moderation and leaderboard filtering

Then create a proper migration so the database history is clean before production.

## Production architecture

Recommended setup:

- App hosting: Render Web Service
- Database: Supabase Postgres
- Static files: WhiteNoise on Render
- Media/videos: keep external links for now
- Admin moderation: Django admin

Later, if users should upload videos directly inside the app:

- use Supabase Storage or Cloudinary
- store only the uploaded file URL in Django

## Environment variables

At minimum, configure these on Render:

- `SECRET_KEY`
- `DEBUG=False`
- `ALLOWED_HOSTS=earnedclub.onrender.com,<your-domain>`
- `DATABASE_URL=<Supabase pooled or direct Postgres URL>`
- `CSRF_TRUSTED_ORIGINS=https://earnedclub.onrender.com,https://<your-domain>`

Optional:

- `RENDER_EXTERNAL_HOSTNAME`

## Django settings changes

Update `core/settings.py` so production is environment-based:

- move `SECRET_KEY` to env var
- set `DEBUG` from env var
- set `ALLOWED_HOSTS` from env var
- use `DATABASE_URL` instead of hardcoded SQLite in production
- keep SQLite only for local fallback if you want simple local development
- add secure proxy / HTTPS settings for Render

Recommended production flags:

- `SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')`
- `SECURE_SSL_REDIRECT = not DEBUG`
- `SESSION_COOKIE_SECURE = not DEBUG`
- `CSRF_COOKIE_SECURE = not DEBUG`

## Dependencies

Add:

- `psycopg[binary]`
- `dj-database-url`

Possible minimal `requirements.txt` additions:

- `dj-database-url`
- `psycopg[binary]`

## Render deployment

Recommended Render service settings:

- Build command:
  - `pip install -r requirements.txt && python manage.py collectstatic --noinput && python manage.py migrate`
- Start command:
  - `gunicorn core.wsgi:application`

Better long-term:

- keep build command for install + collectstatic
- run `python manage.py migrate` as a pre-deploy command or release step if you separate concerns later

## Supabase setup

1. Create a Supabase project.
2. Open Project Settings -> Database.
3. Copy the PostgreSQL connection string.
4. Prefer the pooled connection string if Render opens many connections.
5. Put that value into Render as `DATABASE_URL`.
6. Restrict database access and store credentials only in Render/Supabase env settings.

Important:

- Supabase often exposes both direct and pooler URLs.
- For Render web apps, the pooler is usually the safer first choice.
- If you later run heavy migrations or scripts, direct connection can also be useful.

## App-level improvements before go-live

### High priority

- Make the leaderboard read real submissions from the database.
- Filter leaderboard to `verified=True` if moderation is required.
- Add validation for `reps` and `video_link`.
- Add basic tests for submission creation and leaderboard rendering.
- Lock down production settings.

### Medium priority

- Improve admin for reviewing submissions.
- Add unique ordering logic for ranking.
- Handle empty leaderboard state.
- Add success/error messages after form submit.

### Lower priority

- Add file upload flow instead of external video links.
- Add user accounts.
- Add async verification workflows.

## Suggested rollout plan

### Phase 1: stabilize the codebase

- Fix model/migration mismatch.
- Add environment-based settings.
- Add PostgreSQL dependencies.
- Make leaderboard dynamic.
- Add basic tests.

### Phase 2: wire Supabase

- Create Supabase Postgres project.
- Add `DATABASE_URL` to Render.
- Run migrations against Supabase.
- Create Django superuser.
- Verify admin and submission flow in production.

### Phase 3: harden deployment

- Add `render.yaml` to the repo.
- Add custom domain if needed.
- Add error logging/monitoring.
- Add backup and restore notes.

## Strong recommendation for this project

The best near-term version is:

- Django app on Render
- Supabase Postgres as external DB
- Django admin for verification
- WhiteNoise for static files
- video links stored as URLs only

That gives you a clean production setup quickly without prematurely adding extra services or complexity.

## Biggest current risks

1. Production settings are not safe yet.
2. SQLite is not suitable for Render production persistence.
3. Model and migration history are inconsistent.
4. The leaderboard is still static, so the database is not yet visible in the user experience.
5. There are no tests protecting the submit/deploy flow.

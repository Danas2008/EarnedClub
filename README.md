# Earned Club

Earn your rank. Prove your performance. Unlock exclusive status-based fitness rewards.

## Local development

1. Create and activate a virtual environment.
2. Install dependencies with `pip install -r requirements.txt`.
3. Run migrations with `python manage.py migrate`.
4. Optional but useful: create local static output with `python manage.py collectstatic --noinput`.
5. Start the server with `python manage.py runserver`.

If `DATABASE_URL` is not set, the project falls back to local SQLite.

Quick health check:

```powershell
python manage.py check
python manage.py test
python manage.py migrate --noinput
```

## Production stack

- Web app: Render
- Database: Supabase Postgres
- Static files: WhiteNoise

## Required Render environment variables

- `SECRET_KEY`
- `DEBUG=False`
- `SITE_URL=https://earnedclub.club`
- `ALLOWED_HOSTS=earnedclub.club,www.earnedclub.club,earnedclub.onrender.com`
- `CSRF_TRUSTED_ORIGINS=https://earnedclub.club,https://www.earnedclub.club,https://earnedclub.onrender.com`
- `DATABASE_URL=<Supabase Postgres connection string>`
- Optional email delivery:
  - `EMAIL_BACKEND=<your SMTP/email backend>`
  - `DEFAULT_FROM_EMAIL=Earned Club <noreply@earnedclub.club>`

`SITE_URL` is used for canonical links, robots.txt, sitemap URLs, and structured data. Keep it set to the public production domain, not the Render subdomain.

## Supabase setup

1. Create a Supabase project.
2. Open `Project Settings -> Database`.
3. Copy the Postgres connection string.
4. Add it to Render as `DATABASE_URL`.
5. Deploy the Render web service.
6. Create an admin user with `python manage.py createsuperuser`.

## Verification flow

- Submissions without proof are saved as unverified.
- Submissions with proof enter pending review.
- Review actions create an audit event and can notify the athlete by email.
- The leaderboard can show open, verified, weekly, monthly, and pending views.
- Only verified submissions receive official rank.

## Sitemap and Google Search Console

- Public sitemap: `https://earnedclub.club/sitemap.xml`
- Robots file: `https://earnedclub.club/robots.txt`
- Human-readable sitemap styling: `https://earnedclub.club/sitemap.xsl`

If Search Console reports `nelze nacist` / Could not fetch, check:

1. Render has deployed the latest `working-version` commit.
2. `ALLOWED_HOSTS` includes `earnedclub.club` and `www.earnedclub.club`.
3. `SITE_URL` is exactly `https://earnedclub.club`.
4. `https://earnedclub.club/sitemap.xml` returns HTTP 200 with `application/xml`.

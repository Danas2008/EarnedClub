# Earned Club

Earn your rank. Prove your performance. Unlock exclusive status-based fitness rewards.

## Local development

1. Create and activate a virtual environment.
2. Install dependencies with `pip install -r requirements.txt`.
3. Run migrations with `python manage.py migrate`.
4. Start the server with `python manage.py runserver`.

If `DATABASE_URL` is not set, the project falls back to local SQLite.

## Production stack

- Web app: Render
- Database: Supabase Postgres
- Static files: WhiteNoise

## Required Render environment variables

- `SECRET_KEY`
- `DEBUG=False`
- `ALLOWED_HOSTS=earnedclub.onrender.com,<your-domain>`
- `CSRF_TRUSTED_ORIGINS=https://earnedclub.onrender.com,https://<your-domain>`
- `DATABASE_URL=<Supabase Postgres connection string>`

## Supabase setup

1. Create a Supabase project.
2. Open `Project Settings -> Database`.
3. Copy the Postgres connection string.
4. Add it to Render as `DATABASE_URL`.
5. Deploy the Render web service.
6. Create an admin user with `python manage.py createsuperuser`.

## Verification flow

- User submissions are created as unverified.
- Verified results are managed in Django admin.
- The leaderboard displays only verified submissions.

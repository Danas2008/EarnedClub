# Account, Profile, and Dashboard Expansion Plan

## Goal

Implement the first account-based expansion of Earned Club on the `extension-web` branch.

The goal is to keep the existing manual verification workflow intact while adding user accounts, public athlete profiles, linked submissions, dashboard metrics, calculator cleanup, and an open public board that shows every submission with verification status.

## Scope

This plan covers the MVP account and progression layer:

- User registration, login, and logout.
- Automatic athlete profiles for registered users.
- Public athlete profile pages.
- Authenticated dashboard with verified-only performance metrics and total submission counts.
- User-linked submissions while preserving anonymous submissions.
- Email and status fields on submissions.
- One-active-pending-submission guard.
- Calculator thresholds aligned with backend rank tiers.
- Motivation message after submit with estimated verified leaderboard position.
- Tests for the main ranking, auth, profile, and submission flows.

This plan does not include:

- Challenge model and challenge archive.
- Rank card route.
- Badge model and badge awarding.
- Social sharing image generation.
- Claiming legacy anonymous submissions.
- Email notification workflow.

Those should be implemented in later, separate plans.

## Existing Baseline

Current project state before this change:

- Django app `main` has a `Submission` model with `name`, `reps`, `video_link`, `verified`, and `created_at`.
- Manual verification is represented by `verified=True`.
- Public leaderboard shows all submissions with verification status.
- Official ranks, profile stats, dashboard PRs, and progress graphs only count verified submissions.
- Anonymous submissions through `/challenge/` are supported.
- There are no user accounts, profiles, dashboards, or public athlete profile pages.
- Calculator frontend thresholds are not fully aligned with Python `RANK_TIERS`.

## Design Rules

Preserve:

- Dark visual system from `base.html`.
- Existing verified leaderboard credibility.
- Manual admin verification.
- Legacy anonymous submissions.
- Existing rank tier definitions from `main/models.py`.

Add only small visual extensions:

- `.auth-card` for login and register pages.
- `.profile-header` for dashboard and athlete profile hero areas.
- `.metric-card` for dashboard metrics.
- `.progress-chart` for verified progress graph.
- `.status-pill` for unverified, verified, and rejected labels.

Avoid:

- Light admin-style forms.
- A redesigned landing page.
- Counting pending or rejected submissions in official rankings.
- Requiring accounts for anonymous submissions.

## Data Model Changes

### Profile

Add `Profile` linked to Django's built-in `User`:

- `user = OneToOneField(User)`
- `display_name`
- `slug`
- `profile_photo`
- `bio`
- `current_rank`
- `personal_best_reps`
- `created_at`
- `updated_at`

Behavior:

- Create a profile automatically when a user is created.
- Generate unique slugs from display name.
- Store denormalized `current_rank` and `personal_best_reps`.
- Recalculate profile stats from verified submissions only.

### Submission

Extend `Submission`:

- `user = ForeignKey(User, null=True, blank=True, on_delete=SET_NULL)`
- `email = EmailField(blank=True)`
- `status = CharField(choices=pending/verified/rejected, default=pending)`
- `video_link` becomes optional with `blank=True`.

Compatibility rule:

- Keep `verified` for current admin workflow.
- Add helper `is_verified`.
- Keep `verified` and `status` synchronized in `save()`.
- Existing `verified=True` submissions migrate to `status=verified`.
- Existing `verified=False` submissions migrate to `status=pending`.

## Routes

Add:

- `/register/`
- `/login/`
- `/logout/`
- `/dashboard/`
- `/profiles/`
- `/athlete/<slug>/`

Keep:

- `/`
- `/challenge/`
- `/leaderboard/`
- `/calculators/`
- `/newsletter-signup/`

## View Changes

### Auth

Use Django built-in auth:

- `UserCreationForm` for registration.
- `AuthenticationForm` for login.
- Django session login/logout.

Registration behavior:

- Create `User`.
- Store email on `User.email`.
- Update generated `Profile.display_name`.
- Redirect new users to dashboard.

### Challenge Submission

Logged-in users:

- Use `request.user.profile.display_name` as public submission name.
- Use `request.user.email` as submission email.
- Attach `Submission.user`.

Logged-out users:

- Require `name`, `email`, and `reps`.
- Keep `video_link` optional.
- Create anonymous submission with no linked user.

Pending guard:

- Registered users cannot submit if they already have a `pending` submission.
- Logged-out users cannot submit if the same email already has a `pending` submission.

Success message:

- After submit, estimate where the score would rank among currently verified submissions.
- Show: `Submission received. If verified, this result would currently rank #X on the verified leaderboard.`

### Leaderboard

Show an open board of all submissions sorted by reps.

Behavior:

- Legacy anonymous submissions still display as plain names.
- Linked user submissions link to their athlete profile.
- Pending submissions appear with an `Unverified` status.
- Rejected submissions appear with a `Rejected` status.
- Only verified submissions receive official rank numbers and count toward profile/dashboard performance stats.

### Dashboard

Require login.

Show verified-only metrics:

- Current verified PR.
- All-time verified PR.
- Current verified rank.
- Rank movement placeholder.
- Total submissions.
- Total verified submissions.
- Total pending submissions.
- Weeks active.
- Current verified-submission streak.

Show pending submissions separately.

Render progress graph from verified submissions only.

### Athlete Profile

Public route for registered users.

Show:

- Display name.
- Current verified rank.
- Verified PR.
- Current tier.
- Verified submission history.
- Progress graph.

Do not show pending or rejected submissions.

### Profiles Index

Add a simple public profile directory:

- Show registered profiles that have verified results.
- Sort by current rank and personal best.

## Template Changes

Add:

- `register.html`
- `login.html`
- `dashboard.html`
- `athlete_profile.html`
- `profiles.html`

Update:

- `base.html` auth-aware navigation:
  - Public: Home, Challenge, Leaderboard, Profiles.
  - Logged-out: Login, Register.
  - Logged-in: Dashboard, My Profile, Logout.
- `challenge.html`:
  - Hide name/email fields for logged-in users.
  - Show pending guard state.
  - Mark video link as optional.
- `leaderboard.html`:
  - Link athlete names to profiles when submission is linked to a user.
  - Show every submission with a visible `Verified`, `Unverified`, or `Rejected` status pill.
  - Show official rank only for verified submissions.
- `calculators.html`:
  - Use backend `RANK_TIERS` data through `json_script`.
  - Fix thresholds:
    - Beginner: `0-19`
    - Intermediate: `20-39`
    - Advanced: `40-59`
    - Elite: `60-79`
    - Earned Legend: `80+`
  - Show reps needed to Elite and Earned Legend.
  - Show estimated weeks based on optional weekly improvement.

## Admin Changes

Update `SubmissionAdmin`:

- Show `email`.
- Show `status`.
- Filter by `status`, `verified`, and `created_at`.
- Search by `name`, `email`, and `video_link`.

Add `ProfileAdmin`:

- Display `display_name`, `user`, `current_rank`, `personal_best_reps`, and `created_at`.
- Search by profile/user identity fields.

## Migration Plan

Add migration for:

- `Submission.user`
- `Submission.email`
- `Submission.status`
- `Submission.video_link` optional
- `Profile`

Backfill:

- Convert existing `verified=True` to `status=verified`.
- Convert existing `verified=False` to `status=pending`.
- Create profiles for existing users, if any.

Add a second migration if needed to align `Submission.Meta.ordering` with current model state.

## Test Plan

Add or update tests for:

- Anonymous challenge submission still creates pending submission.
- Success message includes estimated verified leaderboard position.
- Leaderboard shows all submissions with verification status.
- Leaderboard official rank only applies to verified submissions.
- Rank tier boundaries match the plan.
- Registration creates `User` and `Profile`.
- Profile slugs are unique.
- Logged-in submission links to user.
- Duplicate pending submission is blocked for registered users.
- Duplicate pending submission is blocked for anonymous email submissions.
- Dashboard requires login.
- Dashboard metrics and graph data ignore pending submissions.
- Athlete profile shows verified submissions only.

Run:

```powershell
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py test
```

Optional production sanity check:

```powershell
.\.venv\Scripts\python.exe manage.py collectstatic --noinput
```

## Acceptance Criteria

This change is complete when:

- The work is on the `extension-web` branch.
- Registration, login, and logout work.
- New users automatically receive profiles.
- Profile slugs are unique.
- Logged-in submissions are linked to users.
- Anonymous submissions still work.
- Logged-out submissions store email.
- Users cannot submit a second pending submission.
- Emails cannot create repeated anonymous pending submissions.
- Leaderboard displays all submissions with verification status.
- Leaderboard official ranks count only verified submissions.
- Dashboard counts only verified submissions for performance stats.
- Athlete profile shows only verified history.
- Calculator uses the same tier thresholds as the backend.
- New pages match the existing Earned Club dark visual system.
- Tests pass.

## Future Plans

Recommended next implementation plans:

- Challenge System Plan.
- Rank Card Sharing Plan.
- Badges and Achievement Plan.
- Verification Notification Plan.
- Legacy Submission Claim Plan.

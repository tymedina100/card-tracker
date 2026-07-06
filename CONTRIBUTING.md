# Contributing

Thanks for helping improve Card Tracker. Keep changes focused, tested, and easy
for Tyler, Blake, Claude, and Codex to review.

## Workflow

1. Start from `main` and create a short-lived branch.
2. Use a branch name that describes the work, for example
   `feature/watchlist-alerts`, `fix/import-blanks`, or `docs/pr-template`.
3. Keep each branch focused on one Linear issue or one small repo task.
4. Open a pull request into `main`; do not push directly to `main`.
5. Fill out the PR template with the Linear issue, summary, testing, and notes.

## Local Setup

Use Python 3.11 or newer.

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
copy .env.example .env
```

Edit `.env` only for local secrets or optional eBay credentials. Never commit
`.env`, `.streamlit/secrets.toml`, database files, or private config values.

## Running The App

```powershell
cardtracker dashboard
```

The app runs locally in single-owner mode unless Google auth secrets are
configured. Hosted deployments use Railway, Postgres, and Google sign-in.

## Testing And Validation

Before opening a PR, run the checks that match the change.

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check src tests
```

For UI changes, also manually check the affected Streamlit screen or flow. For
data import, auth, fees, prediction, or owner-scoping changes, add or update
tests that cover the risky path.

## Code Guidelines

- Prefer existing modules and helpers before adding new abstractions.
- Keep Streamlit UI code separate from domain logic when practical.
- Preserve owner scoping on every hosted read/write path.
- Keep ask and sold comp data clearly labeled; do not mix them silently.
- Make half-filled cards and missing market data safe instead of crash-prone.
- Avoid unrelated refactors, formatting churn, or broad cleanup in feature PRs.

## Product And Planning Notes

- Use Linear issue IDs such as `VAN-___` in PRs when available.
- Use `docs/product-roadmap.md` for long-term direction and feature priorities.
- Keep Streamlit productive for the current website, but design major new
  workflows so they can eventually move behind an API for web, mobile, and
  desktop clients.

## Review Checklist

Before requesting review, confirm:

- The PR is focused on one issue or task.
- Tests and manual checks are listed in the PR.
- No private config values or local database files are included.
- Docs are updated when behavior, setup, or workflow changes.
- Screenshots or notes are included for visible UI changes.

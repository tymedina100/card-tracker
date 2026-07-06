"""Entry point for Streamlit, kept at the repo root so the app's modules are
imported once through the installed package instead of being re-executed as
watched script files (which would re-register SQLModel tables).

main() is called on every rerun; the import is cached after the first.
Use this as the main file path on Streamlit Community Cloud.
"""

from cardtracker.webui.auth import write_auth_secrets

# Materialize the Google sign-in secrets from environment variables before the
# dashboard reads them. No-op in local dev where the auth vars are unset.
write_auth_secrets()

from cardtracker.dashboard import main  # noqa: E402  after secrets are written

main()

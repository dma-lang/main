"""Single source of truth for the application's SemVer.

Surfaced at `/healthz` and in the UI alongside the active catalogue version.
Bumped per release (Conventional Commits + annotated tags); keep in sync with CHANGELOG.md.
"""

APP_VERSION: str = "0.0.0"

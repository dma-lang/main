"""Single source of truth for the application's SemVer.

Surfaced at `/healthz` and in the UI alongside the active catalogue version.
Bumped per release (Conventional Commits + annotated tags); keep in sync with CHANGELOG.md.
"""

# Release candidate on the integration branch; tagged 0.1.0 at merge (annotated tag + CHANGELOG).
APP_VERSION: str = "0.1.0-rc.1"

"""F7 job layer — async ingest/cycle jobs.

Cadence lives in ``config/schedules.yaml`` (never code); in the cloud each entry maps to a Cloud
Scheduler trigger -> Cloud Run Job (+ Cloud Tasks DLQ). Hermetic dev runs the same job functions
inline behind admin endpoints, so the pipeline code is identical in both modes.
"""

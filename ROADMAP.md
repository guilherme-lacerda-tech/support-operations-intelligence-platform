# Roadmap

## v0.1.0

- FastAPI service for synthetic operational events.
- SQLAlchemy persistence with SQLite demo mode and PostgreSQL-ready configuration.
- Rule engine, incident lifecycle, action queue and audit trail.
- Health sweep job and retryable action executor.
- PyTest, Ruff, coverage gate and GitHub Actions CI.

## Next

- Add Alembic migrations.
- Add a small web dashboard.
- Export monthly operational metrics.
- Add OpenTelemetry-compatible structured logs.
- Add an optional worker process for queued actions.


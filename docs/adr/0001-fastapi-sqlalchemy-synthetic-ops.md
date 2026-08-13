# ADR 0001: FastAPI, SQLAlchemy and Synthetic Operations Domain

## Status

Accepted

## Context

The project needs to show backend automation, persistence, rule evaluation and operational auditability without using any real support system or corporate process.

## Decision

Use FastAPI for inspectable HTTP endpoints, SQLAlchemy for relational persistence and a fictional operations domain with synthetic assets, incidents, actions and audit records.

SQLite remains the default because it makes the demo reproducible without services. PostgreSQL is available through Docker Compose to show how the same model can run against a production-like relational database.

## Consequences

- The app can be evaluated through local tests, demo script or OpenAPI docs.
- Database-backed rules make behavior explicit instead of hidden in conditionals.
- The public implementation remains independent from any employer or client system.
- Docker validation is useful but optional; the non-Docker path must stay healthy.


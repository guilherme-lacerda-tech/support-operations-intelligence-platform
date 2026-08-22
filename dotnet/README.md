# Ops Intelligence Clean-Room .NET POC

Independent clean-room implementation using synthetic data.

This folder contains a C#/.NET implementation of the same public portfolio problem modeled by the Python project: receive operational events, evaluate deterministic rules, open incidents, queue actions, process retryable work, apply cooldown and keep an audit trail. It is not a port of corporate code and does not contain private data, endpoints, logs, identifiers, firmware or proprietary rules.

## Objective

Validate whether a .NET worker-oriented architecture is technically interesting for long-running operational automation scenarios: batch ingestion, persisted state, retry, concurrency readiness, Windows-friendly deployment and observability.

## Architecture

```text
POST /events
  -> EventIngestionService
    -> RuleEvaluator
    -> SQLite events/incidents/actions/audit_logs
    -> ChannelActionSignalQueue
      -> ActionWorker BackgroundService
        -> ActionProcessor
          -> SyntheticActionExecutor
          -> SQLite action status + audit trail
```

## Synthetic Domain

Rules are intentionally generic:

- severity >= 80 or category `offline`/`critical`: create incident and queue diagnostic action.
- severity >= 50 or category `degraded`/`warning`: create incident without action.
- lower severity: record event and audit only.
- repeated open incident for the same synthetic asset/category inside cooldown is suppressed.

## Persistence Choice

The POC uses `Microsoft.Data.Sqlite` with parameterized SQL. EF Core and Dapper would both be reasonable later; direct SQLite was chosen here to keep the clean-room implementation small, explicit and dependency-light while still proving durable state.

## Run

```powershell
dotnet run --project .\src\OpsIntelligence.Api\OpsIntelligence.Api.csproj --urls http://127.0.0.1:5087
```

Example event:

```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:5087/events -ContentType 'application/json' -Body '{
  "source": "synthetic-monitor",
  "assetId": "SYN-ASSET-001",
  "category": "offline",
  "severity": 90,
  "message": "Synthetic offline event",
  "executorMode": "transient_then_success"
}'
```

Useful endpoints:

- `GET /health`
- `POST /events`
- `GET /metrics`
- `GET /incidents`
- `GET /actions`
- `GET /audit`
- `POST /maintenance/process-actions`
- `POST /benchmarks/run/{count}`
- `DELETE /admin/reset`

## Test

```powershell
dotnet test .\OpsIntelligenceCleanRoom.sln
```

The xUnit suite covers incident creation, action queuing, cooldown suppression, warning-only incidents, normal-event audit, success, transient retry with the same action ID, permanent failure, audit trail, persistence after reopening SQLite, background worker processing and benchmark reporting.

## Cooldown

Cooldown prevents duplicated incident/action creation for the same synthetic asset and category while an open incident was recently created. Suppression is stored as an audit event; it is not converted into a fake manual-hour metric.

## Queue And Worker

The API persists actions first, then signals an in-memory `Channel`. The `BackgroundService` polls persisted due actions, so SQLite remains the recovery source if the process restarts.

## Retry

Retries update the same action row and increment `attempts`. A retry is not counted as a new human operation or new action intent.

## Observability

`GET /metrics` exposes event, incident, action, retry, failure, suppression and audit counts. `GET /audit` returns recent audit entries for traceability.

## Benchmark Python x .NET Plan

Use the same synthetic workload in both implementations:

- batches of 100, 1,000 and 10,000 events.
- measure total duration, events/second, process CPU time, working set memory, errors, incident count, action count and cooldown suppressions.
- compare SQLite persistence costs separately from language/runtime costs before claiming .NET or Python superiority.

Possible conclusions remain open: .NET may help, Python may remain adequate, persistence/API may be the bottleneck, or architecture may matter more than language.

Initial .NET results are recorded in [benchmarks/benchmark-results.md](benchmarks/benchmark-results.md).

## Limitations

- No external integrations.
- No real customer data.
- No proprietary rules.
- No distributed queue yet.
- Benchmark is local and synthetic; production claims require a shared Python/.NET harness.

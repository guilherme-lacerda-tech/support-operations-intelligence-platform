# Ops Intelligence Clean-Room .NET Implementation

This directory contains a clean-room .NET 10 implementation of the same synthetic operations workflow implemented in Python at the repository root.

It does not port employer code, private endpoints, production data, proprietary rules or previous closed-source prototypes. The implementation follows the public behavior contract in `../specification/behavior-contract.md`.

## Structure

```text
dotnet/
  OpsIntelligenceCleanRoom.sln
  src/OpsIntelligence.Api/
    Program.cs
    Domain/
      ActionProcessor.cs
      Contracts.cs
      OpsDatabase.cs
      OpsEngine.cs
      OpsOptions.cs
      QueuedActionBackgroundService.cs
  tests/OpsIntelligence.Tests/
  benchmarks/OpsIntelligence.Benchmarks/
```

## Stack

- .NET 10 SDK
- ASP.NET Core minimal API
- SQLite through `Microsoft.Data.Sqlite`
- Parameterized SQL
- xUnit tests
- Optional `BackgroundService` for queued action processing

## Endpoints

- `GET /health`
- `POST /events`
- `GET /metrics`
- `GET /incidents`
- `GET /actions`
- `GET /audit`
- `POST /maintenance/process-actions`
- `DELETE /admin/reset`

## Run

```bash
dotnet build dotnet/OpsIntelligenceCleanRoom.sln
dotnet test dotnet/OpsIntelligenceCleanRoom.sln --no-build
dotnet run --project dotnet/src/OpsIntelligence.Api/OpsIntelligence.Api.csproj -- --urls http://127.0.0.1:18011
```

## Configuration

Environment variables:

- `OPS_DB_PATH`: SQLite database path.
- `OPS_SQLITE_WAL`: enable SQLite WAL + synchronous NORMAL when set to `true` or `1`.
- `OPS_ENABLE_BACKGROUND`: enable queued action `BackgroundService`.

## Benchmark Runner

```bash
dotnet run --project dotnet/benchmarks/OpsIntelligence.Benchmarks/OpsIntelligence.Benchmarks.csproj -- --workload specification/workloads/workload_1000.jsonl
```

The runner emits JSON with canonical summary, elapsed time, events/s, CPU time and working set.

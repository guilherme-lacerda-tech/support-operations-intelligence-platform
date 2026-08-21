# Python vs .NET Clean-Room Results

Date: 2026-08-21  
Branch: `cleanroom-dotnet-poc`  
Machine: local Windows workstation  
Data: deterministic synthetic JSONL workloads generated from fixed seeds

## Scope

This benchmark compares two clean-room implementations of the same operational workflow:

- Python: FastAPI, SQLAlchemy and SQLite.
- .NET: .NET 10, ASP.NET Core, `Microsoft.Data.Sqlite` and SQLite.

The goal is not to claim that one language is universally faster. The goal is to show a reproducible engineering method: shared contract, identical workloads, behavior equivalence, engine benchmarks, HTTP load tests and documented bottlenecks.

## Correctness

Both stacks produced equivalent canonical summaries for the measured engine workloads:

- `workload_100.jsonl`: equivalent = `true`
- `workload_1000.jsonl`: equivalent = `true`
- `workload_100.jsonl` with SQLite WAL + synchronous NORMAL: equivalent = `true`

Canonical fields compared:

- events
- incidents
- actions
- audit logs
- normal events
- warning incidents
- suppressions
- succeeded actions
- failed actions
- retries
- errors

## Engine Benchmark

Each engine workload used 1 warmup run and 5 measured runs per stack.

| Workload | SQLite mode | Stack | Mean elapsed | Mean events/s | Mean memory |
|---|---:|---|---:|---:|---:|
| 100 events | default | Python | 1,495.589 ms | 67.226 | 58.092 MB |
| 100 events | default | .NET | 1,027.565 ms | 97.780 | 38.980 MB |
| 1,000 events | default | Python | 15,307.384 ms | 65.532 | 61.240 MB |
| 1,000 events | default | .NET | 9,660.941 ms | 104.084 | 46.598 MB |
| 100 events | WAL + NORMAL | Python | 1,661.844 ms | 60.258 | 58.262 MB |
| 100 events | WAL + NORMAL | .NET | 216.734 ms | 473.468 | 36.612 MB |

Observations:

- The .NET clean-room engine processed the 1,000-event default SQLite workload at about 1.59x the Python throughput in this local run.
- The WAL + NORMAL SQLite configuration greatly benefited the .NET SQL-direct implementation in the 100-event workload.
- The comparison is intentionally conservative in interpretation because Python uses SQLAlchemy ORM while .NET uses direct parameterized SQLite commands.

Raw files:

- `benchmarks/results/engine_raw_20260820-230729.jsonl`
- `benchmarks/results/engine_summary_20260820-230729.json`
- `benchmarks/results/engine_raw_20260820-231143.jsonl`
- `benchmarks/results/engine_summary_20260820-231143.json`

## HTTP Benchmark

The HTTP benchmark used a single external load generator (`httpx`) against local FastAPI and ASP.NET Core servers. Each concurrency level sent 50 POST `/events` requests using synthetic events from `workload_1000.jsonl`.

| Concurrency | Stack | RPS | p50 | p95 | p99 | Errors | RSS |
|---:|---|---:|---:|---:|---:|---:|---:|
| 1 | Python | 26.78 | 24.874 ms | 47.939 ms | 96.195 ms | 0 | 74.57 MB |
| 1 | .NET | 45.19 | 12.063 ms | 42.577 ms | 75.654 ms | 0 | 112.77 MB |
| 10 | Python | 7.49 | 120.804 ms | 3,510.611 ms | 5,092.970 ms | 0 | 77.85 MB |
| 10 | .NET | 9.74 | 17.720 ms | 3,124.221 ms | 3,530.049 ms | 0 | 112.93 MB |
| 25 | Python | 2.54 | 1,008.386 ms | 17,190.994 ms | 19,041.093 ms | 0 | 80.74 MB |
| 25 | .NET | 3.48 | 702.734 ms | 12,751.947 ms | 12,934.671 ms | 0 | 112.97 MB |
| 50 | Python | 1.28 | 22,570.298 ms | 36,206.776 ms | 37,647.762 ms | 14 | 90.00 MB |
| 50 | .NET | 1.80 | 12,906.049 ms | 25,133.000 ms | 25,501.941 ms | 0 | 113.23 MB |
| 100 | Python | 0.90 | 43,043.280 ms | 53,470.033 ms | 54,247.543 ms | 14 | 88.62 MB |
| 100 | .NET | 1.00 | 38,368.846 ms | 47,939.686 ms | 48,305.256 ms | 0 | 113.71 MB |

Observations:

- Both HTTP stacks show SQLite write contention under high concurrency in the local single-process setup.
- Python began returning errors at concurrency 50 in this run; .NET completed the same request count without HTTP errors but with high tail latency.
- The most useful engineering conclusion is backpressure: the workflow needs bounded queues, write batching or a different persistence strategy before high-concurrency production-style use.

Raw file:

- `benchmarks/results/http_summary_20260821-071805.json`

## SQLite Comparison

SQLite was tested in:

- default mode
- WAL + synchronous NORMAL

WAL + NORMAL is documented separately because it changes durability/performance tradeoffs. It should not be mixed into default benchmark claims without saying so.

## Long-Running Soak

A 30-minute local HTTP soak was executed with both API servers running at the same time.

Configuration:

- Duration: 1,800 seconds.
- Interval target: 1 event per stack per loop.
- Sampling: every 60 seconds.
- Action processing: periodic `POST /maintenance/process-actions`.
- Servers: local FastAPI and local ASP.NET Core.

Final sampled state at 1,740.438 seconds:

| Stack | Events | Incidents | Actions | Succeeded actions | Failed actions | Retries | Suppressions | Errors |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Python | 1,667 | 400 | 266 | 266 | 0 | 24 | 1,267 | 0 |
| .NET | 1,667 | 400 | 266 | 266 | 0 | 24 | 1,267 | 0 |

The run completed the configured 1,800 seconds and wrote 29 interval samples. Python and .NET remained equivalent in every sampled metrics snapshot.

Raw file:

- `benchmarks/results/http_soak_20260821-074956.json`

## LinkedIn-Ready Metrics

Safe metrics for public profile/project posts:

- Built a clean-room Python vs .NET operational workflow with deterministic JSONL workloads and cross-stack correctness validation.
- Added 14 xUnit tests for the .NET implementation and expanded the Python suite to 19 passing tests.
- Validated canonical equivalence across Python and .NET for 100 and 1,000 synthetic events.
- Executed 5 measured engine runs per stack after warmup, recording elapsed time, throughput, CPU, memory and correctness fields.
- Measured HTTP behavior at concurrency levels 1, 10, 25, 50 and 100 using a single external load generator.
- Identified SQLite write contention and tail-latency growth as the main high-concurrency bottleneck.
- Ran a 30-minute local HTTP soak with 0 errors and equivalent sampled metrics in Python and .NET.

Avoid phrasing this as production experience. Present it as a portfolio engineering case, benchmark lab or clean-room comparative implementation.

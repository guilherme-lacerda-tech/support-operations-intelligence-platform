# Interview Cases

These notes are for interview preparation. They use sanitized metrics and clean-room portfolio evidence only.

## Case 1: Report Automation

Situation:

Manual reporting across many accounts created repetitive work, slow feedback and higher risk of inconsistency.

Task:

Build an automated workflow to collect, process and consolidate account-level data with traceable outputs.

Action:

- Structured the workflow around repeatable inputs and outputs.
- Used Python automation to process operational records.
- Produced consolidated reports and evidence for review.
- Preserved auditability without exposing sensitive data.

Result:

- 41 accounts/reports processed.
- 1,135,045 records handled.
- Runtime: 30min16s.
- Manual baseline: over 41h.
- Estimated gain: >80x.

Interview angle:

This shows practical automation, data handling, repeatability and business impact.

## Case 2: Equipment Analysis

Situation:

Equipment-level analysis required review of large volumes of operational records and status classification.

Task:

Accelerate analysis while preserving traceability and status conclusions.

Action:

- Processed a synthetic/sanitized representation of the workflow with Python and structured outputs.
- Organized statuses into maintenance, attention, OK and inconclusive.
- Compared measured runtime against manual baseline.

Result:

- 41 equipment units analyzed.
- 1,230,862 records processed.
- Runtime: 1h14m15s.
- Statuses: 35 maintenance, 2 attention, 3 OK, 1 inconclusive.
- Manual baseline: 30-40 min/equipment, or 20.5-27.3h.
- Estimated capacity gain: 16.6x-22.1x.

Interview angle:

This shows diagnostic thinking, automation, operational analysis and ability to translate data into action.

## Case 3: Resumable Extractor

Situation:

Large API extraction jobs need resilience, auditability and the ability to resume without losing progress.

Task:

Design a workflow that records manifests and can be audited after execution.

Action:

- Organized request batches.
- Used manifest records to track execution.
- Preserved evidence of requests, outputs and errors.
- Kept public portfolio version sanitized.

Result:

- 4,312 requests.
- >5.4M records.
- 0 errors registered in audited manifests.

Interview angle:

This shows API integration, data engineering discipline and reliability thinking.

## STAR: Clean-Room Python vs .NET Case

Situation:

I wanted my portfolio to show more than domain experience in telemetry/support. I needed a technical case that demonstrated backend design, clean-room implementation, testing and benchmark discipline across stacks.

Task:

Implement the same synthetic operations workflow in Python and .NET without copying private code or proprietary rules, then prove equivalence and measure performance.

Action:

- Defined a public behavior contract with normal, warning, critical, cooldown, transient failure and permanent failure scenarios.
- Created deterministic JSONL workloads with fixed seeds.
- Preserved the Python implementation and added a .NET 10 clean-room implementation with ASP.NET Core and SQLite.
- Added 19 Python tests and 14 xUnit tests.
- Ran cross-stack correctness validation.
- Executed engine benchmarks and HTTP load tests with concurrency 1, 10, 25, 50 and 100.

Result:

- Canonical equivalence validated for 100-event and 1,000-event workloads.
- Engine benchmark collected 5 measured runs per stack after warmup.
- HTTP benchmark recorded RPS, p50, p95, p99, errors and memory.
- Main bottleneck identified: SQLite write contention and tail latency under high concurrency.

Interview angle:

The strongest point is not "which stack won". The strongest point is the engineering method: correctness first, measurement second, interpretation third.

## Tough Questions

Q: Is this production experience with .NET?

A: No. I present this as a clean-room portfolio implementation. It demonstrates learning, architecture, tests and benchmarking, but I do not describe it as professional production .NET experience.

Q: Did you copy logic from a company project?

A: No. The repository uses synthetic data, fictional events and a public behavior contract. It avoids private endpoints, credentials, customer data, proprietary rules and production logs.

Q: Why compare Python and .NET if the database access styles are different?

A: The difference is documented. Python uses SQLAlchemy ORM in the existing public implementation, while .NET uses direct parameterized SQLite commands. The benchmark is useful as an engineering case, but I do not overgeneralize the result as a universal language claim.

Q: What would you improve next?

A: Add batching, queue backpressure, async action workers, connection tuning, a PostgreSQL run, better server CPU measurement and a longer repeated load profile.

Q: What did the HTTP benchmark reveal?

A: Both stacks showed SQLite write contention under high concurrency. Python started returning errors at concurrency 50 in the measured local run, while .NET completed the same request count without HTTP errors but with high tail latency.

Q: How does this connect to your professional background?

A: It connects operational diagnosis, automation, data, auditability and systems integration. Those are real parts of my background, but the public code is a sanitized, independent portfolio case.

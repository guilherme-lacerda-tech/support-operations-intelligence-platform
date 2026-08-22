# Shared Functional Specification

Independent clean-room benchmark using synthetic data only.

The Python and .NET implementations are compared with the same deterministic JSONL workload. Performance is only compared when the normalized functional counters match.

## Event Schema

Each fixture row contains:

- `asset_id`
- `source`
- `category`
- `severity`
- `occurred_at`
- `message`
- `executor_mode`

The Python API maps `asset_id` to `asset_external_id`. The .NET API maps `asset_id` to `assetId`.

## Cases

The deterministic workload repeats a 20-event cycle:

| Position | Case | Expected behavior |
| ---: | --- | --- |
| 0 | CRITICAL | create incident and action; action succeeds |
| 1 | COOLDOWN | repeated critical event for position 0 asset; suppress duplicate action |
| 2 | WARNING | create incident without immediate action |
| 3 | TRANSIENT_FAILURE | create incident and action; first attempt fails transiently, retry succeeds |
| 4 | PERMANENT_FAILURE | create incident and action; action fails permanently |
| 5-19 | NORMAL | record event without incident/action |

## Expected Normalized Counters Per 20 Events

| Counter | Expected |
| --- | ---: |
| events | 20 |
| incidents | 4 |
| actions | 3 |
| cooldown suppressions | 1 |
| succeeded actions | 2 |
| failed actions | 1 |
| retry attempts | 1 |
| permanent failures | 1 |
| processing errors | 0 |

Audit logs are expected to exist for decisions and action processing, but raw audit-entry counts are not used as strict equality because Python and .NET intentionally keep different audit granularity.

## Cooldown Semantics

Cooldown suppresses duplicate operational intent only inside the configured time window for the same synthetic asset/category. It is not a permanent uniqueness rule.

Expected behavior:

- event A creates an incident/action when the rule matches;
- event B inside the cooldown window is suppressed and references the recent incident;
- event C after the cooldown window is allowed to create a new incident/action.

The .NET implementation protects this decision with one SQLite transaction so concurrent duplicates cannot pass the check-then-create boundary independently.

## SQLite Modes

The benchmark separates:

- `standard`: default SQLite behavior.
- `wal`: `PRAGMA journal_mode=WAL`, `PRAGMA synchronous=NORMAL`, `PRAGMA temp_store=MEMORY`.

Batch transaction mode is only valid if both runtimes execute an equivalent write pattern.

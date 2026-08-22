# Benchmark Results

Independent clean-room implementation using synthetic data.

Environment:

- Windows 10.0.26200
- .NET SDK 10.0.400 portable workspace runtime
- ASP.NET Core local API on `127.0.0.1`
- SQLite local file with WAL and `synchronous=NORMAL`
- Synthetic benchmark endpoint: `POST /benchmarks/run/{count}`

## 2026-08-20 Initial Functional Benchmark

Each run reset the local SQLite database before execution.

| Events | Accepted | Errors | Incidents | Actions | Cooldown suppressions | Total ms | Events/s | CPU ms | Working set MB |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 100 | 100 | 0 | 35 | 15 | 5 | 331.82 | 301.37 | 265.62 | 70.30 -> 69.69 |
| 1,000 | 1,000 | 0 | 350 | 150 | 50 | 2,108.22 | 474.33 | 1,328.12 | 70.23 -> 72.62 |
| 10,000 | 10,000 | 0 | 3,500 | 1,500 | 500 | 15,496.08 | 645.32 | 11,031.25 | 73.69 -> 71.79 |

## Interpretation

The first unoptimized run showed SQLite transaction overhead as the dominant bottleneck. Enabling local SQLite WAL/synchronous tuning improved 100-event runtime from about 5.7 seconds to about 0.33 seconds.

This does not prove .NET is inherently faster than Python. It shows that persistence configuration and write pattern are material engineering factors that must be normalized before a fair Python x .NET comparison.

from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "benchmarks" / "results"
CANONICAL_KEYS = (
    "events",
    "incidents",
    "actions",
    "audit_logs",
    "normal_events",
    "warning_incidents",
    "suppressions",
    "action_succeeded",
    "action_failed",
    "retries",
    "errors",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sizes", default="100,1000")
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--warmup", type=int, default=1)
    parser.add_argument("--wal-modes", default="default")
    return parser.parse_args()


def run_command(command: list[str]) -> dict[str, object]:
    completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=True)
    stdout = completed.stdout.strip()
    start = stdout.find("{")
    if start < 0:
        raise RuntimeError(f"Command did not emit JSON: {' '.join(command)}\n{stdout}")
    return json.loads(stdout[start:])


def command_for(stack: str, workload: Path, wal: bool) -> list[str]:
    if stack == "python":
        command = [sys.executable, "benchmarks/python_engine_runner.py", "--workload", str(workload)]
        if wal:
            command.append("--wal")
        return command

    return [
        "dotnet",
        "run",
        "--no-build",
        "--project",
        "dotnet/benchmarks/OpsIntelligence.Benchmarks/OpsIntelligence.Benchmarks.csproj",
        "-c",
        "Debug",
        "--",
        "--workload",
        str(workload),
        "--wal",
        "true" if wal else "false",
    ]


def summarize(values: list[float]) -> dict[str, float]:
    if not values:
        return {"mean": 0.0, "median": 0.0, "min": 0.0, "max": 0.0, "p95": 0.0}
    ordered = sorted(values)
    p95_index = max(0, math.ceil(len(ordered) * 0.95) - 1)
    return {
        "mean": round(statistics.fmean(values), 3),
        "median": round(statistics.median(values), 3),
        "min": round(min(values), 3),
        "max": round(max(values), 3),
        "p95": round(ordered[p95_index], 3),
    }


def main() -> None:
    args = parse_args()
    RESULTS.mkdir(parents=True, exist_ok=True)
    sizes = [int(item) for item in args.sizes.split(",") if item.strip()]
    wal_modes = [item.strip().lower() for item in args.wal_modes.split(",") if item.strip()]
    timestamp = time.strftime("%Y%m%d-%H%M%S")
    raw_path = RESULTS / f"engine_raw_{timestamp}.jsonl"
    summary_path = RESULTS / f"engine_summary_{timestamp}.json"
    csv_path = RESULTS / f"engine_summary_{timestamp}.csv"
    raw_rows: list[dict[str, object]] = []

    for size in sizes:
        workload = ROOT / "specification" / "workloads" / f"workload_{size}.jsonl"
        for wal_label in wal_modes:
            wal = wal_label == "wal"
            for stack in ("python", "dotnet"):
                for warmup_index in range(args.warmup):
                    row = run_command(command_for(stack, workload, wal))
                    row["phase"] = "warmup"
                    row["run"] = warmup_index + 1
                    raw_rows.append(row)
                for run_index in range(args.runs):
                    row = run_command(command_for(stack, workload, wal))
                    row["phase"] = "measured"
                    row["run"] = run_index + 1
                    raw_rows.append(row)
                    print(
                        f"{stack} size={size} wal={wal} run={run_index + 1}/{args.runs} "
                        f"{row['elapsed_ms']}ms {row['events_per_second']} eps",
                        flush=True,
                    )

    raw_path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in raw_rows),
        encoding="utf-8",
    )
    measured = [row for row in raw_rows if row["phase"] == "measured"]
    grouped: dict[tuple[str, str, bool], list[dict[str, object]]] = {}
    for row in measured:
        grouped.setdefault((str(row["workload"]), str(row["stack"]), bool(row["wal"])), []).append(row)

    summaries = []
    for (workload, stack, wal), rows in grouped.items():
        summaries.append(
            {
                "workload": workload,
                "stack": stack,
                "wal": wal,
                "runs": len(rows),
                "elapsed_ms": summarize([float(row["elapsed_ms"]) for row in rows]),
                "events_per_second": summarize([float(row["events_per_second"]) for row in rows]),
                "cpu_ms": summarize([float(row["cpu_ms"]) for row in rows]),
                "working_set_mb": summarize([float(row["working_set_mb"]) for row in rows if row["working_set_mb"] is not None]),
                "canonical": {key: rows[-1][key] for key in CANONICAL_KEYS},
            }
        )

    correctness = []
    for workload in sorted({str(row["workload"]) for row in measured}):
        for wal in sorted({bool(row["wal"]) for row in measured}):
            comparable = [row for row in measured if row["workload"] == workload and bool(row["wal"]) == wal]
            by_stack = {}
            for row in comparable:
                by_stack[row["stack"]] = {key: row[key] for key in CANONICAL_KEYS}
            if "python" in by_stack and "dotnet" in by_stack:
                correctness.append(
                    {
                        "workload": workload,
                        "wal": wal,
                        "equivalent": by_stack["python"] == by_stack["dotnet"],
                        "python": by_stack["python"],
                        "dotnet": by_stack["dotnet"],
                    }
                )

    payload = {"summaries": summaries, "correctness": correctness, "raw": str(raw_path.relative_to(ROOT))}
    summary_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["workload", "stack", "wal", "runs", "elapsed_mean_ms", "events_per_second_mean", "cpu_mean_ms"],
        )
        writer.writeheader()
        for row in summaries:
            writer.writerow(
                {
                    "workload": row["workload"],
                    "stack": row["stack"],
                    "wal": row["wal"],
                    "runs": row["runs"],
                    "elapsed_mean_ms": row["elapsed_ms"]["mean"],
                    "events_per_second_mean": row["events_per_second"]["mean"],
                    "cpu_mean_ms": row["cpu_ms"]["mean"],
                }
            )

    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

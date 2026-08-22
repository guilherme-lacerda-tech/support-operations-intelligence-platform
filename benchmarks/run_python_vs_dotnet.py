from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from pathlib import Path
from statistics import mean, median
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from workload import SharedEvent, expected_counters, generate_events, read_jsonl, write_jsonl  # noqa: E402


def main() -> None:
    args = parse_args()
    work_dir = args.work_dir.resolve()
    work_dir.mkdir(parents=True, exist_ok=True)
    fixture_path = work_dir / f"shared-workload-{args.fixture_count}.jsonl"
    write_jsonl(fixture_path, generate_events(args.fixture_count, args.seed))

    results: dict[str, Any] = {
        "fixture": str(fixture_path),
        "seed": args.seed,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "equivalence": {},
        "engine": [],
        "http": [],
        "long_running": [],
        "notes": [],
    }

    events = read_jsonl(fixture_path, args.fixture_count)
    dotnet_project = ROOT / "dotnet" / "benchmarks" / "OpsIntelligence.Benchmark" / "OpsIntelligence.Benchmark.csproj"

    print("Running functional equivalence check...", flush=True)
    equivalence_count = min(args.equivalence_count, args.fixture_count)
    expected = expected_counters(equivalence_count)
    py_equiv = run_python_engine(
        events[:equivalence_count],
        equivalence_count,
        "wal",
        repetitions=1,
        warmups=0,
        db_root=work_dir,
    )["runs"][0]
    dn_equiv = run_dotnet_engine(
        args.dotnet,
        dotnet_project,
        fixture_path,
        equivalence_count,
        "wal",
        repetitions=1,
        warmups=0,
        db_root=work_dir,
    )["runs"][0]
    results["equivalence"] = {
        "count": equivalence_count,
        "expected": asdict(expected),
        "python": normalized_counter_subset(py_equiv),
        "dotnet": normalized_counter_subset(dn_equiv),
        "match": normalized_counter_subset(py_equiv) == normalized_counter_subset(dn_equiv) == asdict(expected),
    }
    if not results["equivalence"]["match"]:
        results["notes"].append("Functional equivalence failed; performance comparison should not be interpreted as valid.")

    if not args.skip_engine:
        print("Running engine benchmarks...", flush=True)
        for sqlite_mode in args.sqlite_modes:
            for count in engine_counts_for_mode(args, sqlite_mode):
                if count > args.fixture_count:
                    continue
                print(f"ENGINE python sqlite={sqlite_mode} count={count}", flush=True)
                py_result = run_python_engine(
                    events[:count],
                    count,
                    sqlite_mode,
                    args.repetitions,
                    args.warmups,
                    work_dir,
                )
                results["engine"].append(py_result)
                print(f"ENGINE dotnet sqlite={sqlite_mode} count={count}", flush=True)
                dn_result = run_dotnet_engine(
                    args.dotnet,
                    dotnet_project,
                    fixture_path,
                    count,
                    sqlite_mode,
                    args.repetitions,
                    args.warmups,
                    work_dir,
                )
                results["engine"].append(dn_result)
    else:
        results["notes"].append("Engine benchmark was skipped in this run.")

    if args.run_http:
        print("Running HTTP benchmarks...", flush=True)
        for sqlite_mode in args.sqlite_modes:
            for concurrency in http_concurrency_for_mode(args, sqlite_mode):
                count = min(args.http_events, args.fixture_count)
                print(f"HTTP python sqlite={sqlite_mode} concurrency={concurrency} count={count}", flush=True)
                results["http"].append(
                    run_http_runtime("python", events[:count], count, concurrency, sqlite_mode, work_dir, args)
                )
                print(f"HTTP dotnet sqlite={sqlite_mode} concurrency={concurrency} count={count}", flush=True)
                results["http"].append(
                    run_http_runtime("dotnet", events[:count], count, concurrency, sqlite_mode, work_dir, args)
                )

    if args.long_running_seconds > 0:
        print(f"Running long-running benchmark for {args.long_running_seconds} seconds...", flush=True)
        results["long_running"] = run_long_running(events, work_dir, args)
    else:
        results["notes"].append("Long-running benchmark was not executed in this run.")

    json_path = ROOT / "benchmarks" / "python-vs-dotnet-results.json"
    md_path = ROOT / "benchmarks" / "python-vs-dotnet-results.md"
    json_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    md_path.write_text(render_markdown(results), encoding="utf-8")
    print(f"Wrote {md_path}", flush=True)
    print(f"Wrote {json_path}", flush=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dotnet", default=os.environ.get("DOTNET_EXE", "dotnet"))
    parser.add_argument("--work-dir", type=Path, default=ROOT / "work" / "python-vs-dotnet")
    parser.add_argument("--seed", type=int, default=424242)
    parser.add_argument("--fixture-count", type=int, default=50_000)
    parser.add_argument("--equivalence-count", type=int, default=1_000)
    parser.add_argument("--engine-counts", type=int, nargs="+", default=[100, 1_000, 10_000])
    parser.add_argument("--standard-engine-counts", type=int, nargs="+")
    parser.add_argument("--wal-engine-counts", type=int, nargs="+")
    parser.add_argument("--sqlite-modes", nargs="+", default=["standard", "wal"], choices=["standard", "wal"])
    parser.add_argument("--repetitions", type=int, default=5)
    parser.add_argument("--warmups", type=int, default=1)
    parser.add_argument("--skip-engine", action="store_true")
    parser.add_argument("--run-http", action="store_true")
    parser.add_argument("--http-events", type=int, default=1_000)
    parser.add_argument("--http-concurrency", type=int, nargs="+", default=[1, 10, 50, 100])
    parser.add_argument("--standard-http-concurrency", type=int, nargs="+")
    parser.add_argument("--wal-http-concurrency", type=int, nargs="+")
    parser.add_argument("--python-port", type=int, default=8011)
    parser.add_argument("--dotnet-port", type=int, default=5087)
    parser.add_argument("--long-running-seconds", type=int, default=0)
    parser.add_argument("--long-running-concurrency", type=int, default=10)
    parser.add_argument("--long-running-batch", type=int, default=200)
    return parser.parse_args()


def engine_counts_for_mode(args: argparse.Namespace, sqlite_mode: str) -> list[int]:
    if sqlite_mode == "standard" and args.standard_engine_counts:
        return args.standard_engine_counts
    if sqlite_mode == "wal" and args.wal_engine_counts:
        return args.wal_engine_counts
    return args.engine_counts


def http_concurrency_for_mode(args: argparse.Namespace, sqlite_mode: str) -> list[int]:
    if sqlite_mode == "standard" and args.standard_http_concurrency:
        return args.standard_http_concurrency
    if sqlite_mode == "wal" and args.wal_http_concurrency:
        return args.wal_http_concurrency
    return args.http_concurrency


def run_python_engine(
    events: list[SharedEvent],
    count: int,
    sqlite_mode: str,
    repetitions: int,
    warmups: int,
    db_root: Path,
) -> dict[str, Any]:
    runs = []
    for index in range(repetitions + warmups):
        measured = index >= warmups
        run = run_python_engine_once(events, count, sqlite_mode, db_root, index - warmups + 1 if measured else 0)
        if measured:
            runs.append(run)
    return {"runtime": "python", "count": count, "sqliteMode": sqlite_mode, "runs": runs}


def run_python_engine_once(events: list[SharedEvent], count: int, sqlite_mode: str, db_root: Path, run: int) -> dict[str, Any]:
    from sqlalchemy import select

    from support_operations_intelligence_platform.core.database import create_session_factory
    from support_operations_intelligence_platform.core.settings import get_settings
    from support_operations_intelligence_platform.models import Action, ActionState
    from support_operations_intelligence_platform.services.actions import execute_action_with_retry
    from support_operations_intelligence_platform.services.processor import EventProcessor

    db_path = db_root / f"python-engine-{sqlite_mode}-{count}-{os.getpid()}-{time.time_ns()}.sqlite3"
    os.environ["SUPPORT_OPS_SQLITE_MODE"] = sqlite_mode
    get_settings.cache_clear()
    factory = create_session_factory(sqlite_url(db_path))
    session = factory()
    seed_python_database(session, events)

    cpu_start = time.process_time()
    mem_start = process_sample(os.getpid())["workingSetMb"]
    started = time.perf_counter()
    errors = 0
    processor = EventProcessor(session)
    for event in events:
        try:
            processor.process(to_python_payload(event))
            session.commit()
        except Exception:
            session.rollback()
            errors += 1

    queued_actions = list(session.scalars(select(Action).where(Action.state == ActionState.QUEUED.value)).all())
    for action in queued_actions:
        execute_action_with_retry(session, action, max_attempts=3, timeout_seconds=0.001)
        session.commit()

    elapsed = time.perf_counter() - started
    cpu_ms = (time.process_time() - cpu_start) * 1000
    metrics = python_metrics(session)
    mem_end = process_sample(os.getpid())["workingSetMb"]
    session.close()
    delete_sqlite_files(db_path)

    return {
        "run": run,
        "totalMilliseconds": round(elapsed * 1000, 2),
        "eventsPerSecond": round(count / max(elapsed, 0.001), 2),
        "cpuMilliseconds": round(cpu_ms, 2),
        "workingSetStartMb": mem_start,
        "workingSetEndMb": mem_end,
        "errors": errors,
        **metrics,
    }


def run_dotnet_engine(
    dotnet: str,
    project: Path,
    fixture_path: Path,
    count: int,
    sqlite_mode: str,
    repetitions: int,
    warmups: int,
    db_root: Path,
) -> dict[str, Any]:
    benchmark_dll = project.parent / "bin" / "Debug" / "net10.0" / "OpsIntelligence.Benchmark.dll"
    command = [
        dotnet,
        str(benchmark_dll),
        "--fixture",
        str(fixture_path),
        "--count",
        str(count),
        "--sqlite-mode",
        sqlite_mode,
        "--repetitions",
        str(repetitions),
        "--warmups",
        str(warmups),
        "--db-root",
        str(db_root),
    ]
    completed = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=True)
    return json.loads(completed.stdout.strip().splitlines()[-1])


def run_http_runtime(
    runtime: str,
    events: list[SharedEvent],
    count: int,
    concurrency: int,
    sqlite_mode: str,
    work_dir: Path,
    args: argparse.Namespace,
) -> dict[str, Any]:
    port = args.python_port if runtime == "python" else args.dotnet_port
    base_url = f"http://127.0.0.1:{port}"
    db_path = work_dir / f"{runtime}-http-{sqlite_mode}-{concurrency}-{time.time_ns()}.sqlite3"
    process = start_runtime(runtime, db_path, sqlite_mode, port, events, args)
    try:
        wait_for_health(base_url)
        request_json("DELETE", f"{base_url}/admin/reset")
        sample_start = process_sample(process.pid)
        started = time.perf_counter()
        latencies: list[float] = []
        errors = 0
        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            futures = [
                executor.submit(post_event, base_url, runtime, events[index % len(events)])
                for index in range(count)
            ]
            for future in as_completed(futures):
                latency, ok = future.result()
                latencies.append(latency)
                errors += 0 if ok else 1
        elapsed = time.perf_counter() - started
        drain_actions(base_url)
        metrics = request_json("GET", f"{base_url}/metrics")
        sample_end = process_sample(process.pid)
        expected = asdict(expected_counters(count))
        observed = normalize_metrics(metrics, errors)
        return {
            "runtime": runtime,
            "count": count,
            "concurrency": concurrency,
            "sqliteMode": sqlite_mode,
            "requestsPerSecond": round(count / max(elapsed, 0.001), 2),
            "totalMilliseconds": round(elapsed * 1000, 2),
            "p50Milliseconds": percentile(latencies, 50),
            "p95Milliseconds": percentile(latencies, 95),
            "p99Milliseconds": percentile(latencies, 99),
            "cpuMilliseconds": round((sample_end["cpuSeconds"] - sample_start["cpuSeconds"]) * 1000, 2),
            "workingSetStartMb": sample_start["workingSetMb"],
            "workingSetEndMb": sample_end["workingSetMb"],
            "errors": errors,
            "expected": expected,
            "observed": observed,
            "functionalMatch": observed == expected,
        }
    finally:
        stop_process(process)
        delete_sqlite_files(db_path)


def run_long_running(events: list[SharedEvent], work_dir: Path, args: argparse.Namespace) -> dict[str, Any]:
    duration = args.long_running_seconds
    py_port = args.python_port
    dn_port = args.dotnet_port
    py_db = work_dir / f"python-long-{time.time_ns()}.sqlite3"
    dn_db = work_dir / f"dotnet-long-{time.time_ns()}.sqlite3"
    py_process = start_runtime("python", py_db, "wal", py_port, events, args)
    dn_process = start_runtime("dotnet", dn_db, "wal", dn_port, events, args)
    samples: list[dict[str, Any]] = []
    first_divergence: dict[str, Any] | None = None
    py_errors = 0
    dn_errors = 0
    try:
        wait_for_health(f"http://127.0.0.1:{py_port}")
        wait_for_health(f"http://127.0.0.1:{dn_port}")
        request_json("DELETE", f"http://127.0.0.1:{py_port}/admin/reset")
        request_json("DELETE", f"http://127.0.0.1:{dn_port}/admin/reset")
        started = time.perf_counter()
        batch = 0
        while time.perf_counter() - started < duration:
            offset = (batch * args.long_running_batch) % max(len(events), 1)
            current_events = [events[(offset + index) % len(events)] for index in range(args.long_running_batch)]
            py_errors += run_http_batch("python", f"http://127.0.0.1:{py_port}", current_events, args.long_running_concurrency)
            dn_errors += run_http_batch("dotnet", f"http://127.0.0.1:{dn_port}", current_events, args.long_running_concurrency)
            drain_actions(f"http://127.0.0.1:{py_port}")
            drain_actions(f"http://127.0.0.1:{dn_port}")
            py_metrics = request_json("GET", f"http://127.0.0.1:{py_port}/metrics")
            dn_metrics = request_json("GET", f"http://127.0.0.1:{dn_port}/metrics")
            py_counters = normalize_metrics(py_metrics, py_errors)
            dn_counters = normalize_metrics(dn_metrics, dn_errors)
            if first_divergence is None and py_counters != dn_counters:
                first_divergence = {
                    "batch": batch,
                    "elapsedSeconds": round(time.perf_counter() - started, 2),
                    "python": py_counters,
                    "dotnet": dn_counters,
                }
            if batch % 5 == 0:
                samples.append(
                    {
                        "elapsedSeconds": round(time.perf_counter() - started, 2),
                        "python": {
                            "process": process_sample(py_process.pid),
                            "metrics": py_metrics,
                            "requestErrors": py_errors,
                        },
                        "dotnet": {
                            "process": process_sample(dn_process.pid),
                            "metrics": dn_metrics,
                            "requestErrors": dn_errors,
                        },
                    }
                )
            batch += 1
        final_py_metrics = request_json("GET", f"http://127.0.0.1:{py_port}/metrics")
        final_dn_metrics = request_json("GET", f"http://127.0.0.1:{dn_port}/metrics")
        final_py_counters = normalize_metrics(final_py_metrics, py_errors)
        final_dn_counters = normalize_metrics(final_dn_metrics, dn_errors)
        if first_divergence is None and final_py_counters != final_dn_counters:
            first_divergence = {
                "batch": batch,
                "elapsedSeconds": round(time.perf_counter() - started, 2),
                "python": final_py_counters,
                "dotnet": final_dn_counters,
            }

        return {
            "durationSeconds": duration,
            "concurrency": args.long_running_concurrency,
            "batchSize": args.long_running_batch,
            "samples": samples,
            "firstDivergence": first_divergence,
            "finalCountersMatch": final_py_counters == final_dn_counters,
            "final": {
                "elapsedSeconds": round(time.perf_counter() - started, 2),
                "python": {
                    "process": process_sample(py_process.pid),
                    "metrics": final_py_metrics,
                    "counters": final_py_counters,
                    "requestErrors": py_errors,
                },
                "dotnet": {
                    "process": process_sample(dn_process.pid),
                    "metrics": final_dn_metrics,
                    "counters": final_dn_counters,
                    "requestErrors": dn_errors,
                },
            },
        }
    finally:
        stop_process(py_process)
        stop_process(dn_process)
        delete_sqlite_files(py_db)
        delete_sqlite_files(dn_db)


def start_runtime(
    runtime: str,
    db_path: Path,
    sqlite_mode: str,
    port: int,
    seed_events: list[SharedEvent],
    args: argparse.Namespace,
) -> subprocess.Popen:
    if runtime == "python":
        os.environ["SUPPORT_OPS_SQLITE_MODE"] = sqlite_mode
        from support_operations_intelligence_platform.core.database import create_session_factory
        from support_operations_intelligence_platform.core.settings import get_settings

        get_settings.cache_clear()
        factory = create_session_factory(sqlite_url(db_path))
        session = factory()
        seed_python_database(session, seed_events)
        session.close()

        env = os.environ.copy()
        env["SUPPORT_OPS_DATABASE_URL"] = sqlite_url(db_path)
        env["SUPPORT_OPS_SQLITE_MODE"] = sqlite_mode
        env["SUPPORT_OPS_ACTION_TIMEOUT_SECONDS"] = "0.001"
        return subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "support_operations_intelligence_platform.api.app:create_app",
                "--factory",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                "--log-level",
                "warning",
            ],
            cwd=ROOT,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    api_dll = ROOT / "dotnet" / "src" / "OpsIntelligence.Api" / "bin" / "Debug" / "net10.0" / "OpsIntelligence.Api.dll"
    return subprocess.Popen(
        [
            args.dotnet,
            str(api_dll),
            "--urls",
            f"http://127.0.0.1:{port}",
            "--OpsDb:Path",
            str(db_path),
            "--OpsDb:OptimizeForLocalThroughput",
            str(sqlite_mode == "wal").lower(),
            "--OpsProcessing:WorkerEnabled",
            "false",
            "--OpsProcessing:RetryDelayMilliseconds",
            "0",
        ],
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def seed_python_database(session: Any, events: list[SharedEvent]) -> None:
    from support_operations_intelligence_platform.models import Asset, AutomationRule

    asset_ids = sorted({event.asset_id for event in events})
    session.add_all(
        Asset(external_id=asset_id, name=f"Synthetic {asset_id[-24:]}", group="benchmark")
        for asset_id in asset_ids
    )
    session.add_all(
        [
            AutomationRule(
                name="Critical synthetic diagnostic",
                category="offline",
                minimum_severity=80,
                cooldown_minutes=5,
                action_type="collect_diagnostics",
            ),
            AutomationRule(
                name="Warning synthetic incident",
                category="degraded",
                minimum_severity=50,
                cooldown_minutes=5,
                action_type="none",
            ),
        ]
    )
    session.commit()


def to_python_payload(event: SharedEvent) -> Any:
    from support_operations_intelligence_platform.schemas import EventCreate

    return EventCreate(
        asset_external_id=event.asset_id,
        source=event.source,
        category=event.category,
        severity=event.severity,
        message=event.message,
        executor_mode=event.executor_mode,
    )


def python_metrics(session: Any) -> dict[str, int]:
    from support_operations_intelligence_platform.models import Action, ActionState, AuditLog, Incident, OperationalEvent

    actions = session.query(Action).all()
    return {
        "events": session.query(OperationalEvent).count(),
        "incidents": session.query(Incident).count(),
        "actions": len(actions),
        "cooldownSuppressions": session.query(AuditLog).filter(AuditLog.event_type == "event_suppressed").count(),
        "succeededActions": sum(action.state == ActionState.SUCCEEDED.value for action in actions),
        "failedActions": sum(action.state == ActionState.FAILED.value for action in actions),
        "retryAttempts": sum(max(action.attempts - 1, 0) for action in actions),
        "permanentFailures": sum(action.state == ActionState.FAILED.value and "permanent" in action.detail for action in actions),
    }


def post_event(base_url: str, runtime: str, event: SharedEvent) -> tuple[float, bool]:
    if runtime == "python":
        body = {
            "asset_external_id": event.asset_id,
            "source": event.source,
            "category": event.category,
            "severity": event.severity,
            "message": event.message,
            "executor_mode": event.executor_mode,
        }
    else:
        body = {
            "assetId": event.asset_id,
            "source": event.source,
            "category": event.category,
            "severity": event.severity,
            "message": event.message,
            "executorMode": event.executor_mode,
        }
    started = time.perf_counter()
    try:
        request_json("POST", f"{base_url}/events", body)
        return (time.perf_counter() - started) * 1000, True
    except Exception:
        return (time.perf_counter() - started) * 1000, False


def run_http_batch(runtime: str, base_url: str, events: list[SharedEvent], concurrency: int) -> int:
    errors = 0
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = [executor.submit(post_event, base_url, runtime, event) for event in events]
        for future in as_completed(futures):
            _latency, ok = future.result()
            errors += 0 if ok else 1
    return errors


def drain_actions(base_url: str) -> None:
    for _ in range(5):
        result = request_json("POST", f"{base_url}/maintenance/process-actions")
        if int(result.get("processed", result.get("processedActions", 0)) or 0) == 0:
            break


def request_json(method: str, url: str, body: dict[str, Any] | None = None) -> Any:
    data = None if body is None else json.dumps(body).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        text = response.read().decode("utf-8")
        if not text:
            return {}
        return json.loads(text)


def wait_for_health(base_url: str) -> None:
    deadline = time.time() + 30
    last_error: Exception | None = None
    while time.time() < deadline:
        try:
            request_json("GET", f"{base_url}/health")
            return
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            last_error = exc
            time.sleep(0.25)
    raise RuntimeError(f"Timed out waiting for {base_url}") from last_error


def process_sample(pid: int) -> dict[str, float]:
    if os.name != "nt":
        return {"cpuSeconds": 0.0, "workingSetMb": 0.0}
    command = (
        "$p=Get-Process -Id "
        + str(pid)
        + " -ErrorAction SilentlyContinue; "
        + "if($p){ [pscustomobject]@{cpu=$p.CPU; ws=[math]::Round($p.WorkingSet64/1MB,2)} | ConvertTo-Json -Compress }"
    )
    completed = subprocess.run(
        ["powershell", "-NoProfile", "-Command", command],
        text=True,
        capture_output=True,
        check=False,
    )
    if not completed.stdout.strip():
        return {"cpuSeconds": 0.0, "workingSetMb": 0.0}
    data = json.loads(completed.stdout)
    return {"cpuSeconds": float(data.get("cpu") or 0), "workingSetMb": float(data.get("ws") or 0)}


def normalize_metrics(metrics: dict[str, Any], errors: int) -> dict[str, int]:
    return {
        "events": int(metrics.get("events", 0)),
        "incidents": int(metrics.get("incidents", 0)),
        "actions": int(metrics.get("actions", 0)),
        "cooldown_suppressions": int(metrics.get("cooldownSuppressions", 0)),
        "succeeded_actions": int(metrics.get("succeededActions", 0)),
        "failed_actions": int(metrics.get("failedActions", 0)),
        "retry_attempts": int(metrics.get("retryAttempts", 0)),
        "permanent_failures": int(metrics.get("permanentFailures", 0)),
        "errors": errors,
    }


def normalized_counter_subset(run: dict[str, Any]) -> dict[str, int]:
    return {
        "events": int(run.get("events", 0)),
        "incidents": int(run.get("incidents", 0)),
        "actions": int(run.get("actions", 0)),
        "cooldown_suppressions": int(run.get("cooldownSuppressions", 0)),
        "succeeded_actions": int(run.get("succeededActions", 0)),
        "failed_actions": int(run.get("failedActions", 0)),
        "retry_attempts": int(run.get("retryAttempts", 0)),
        "permanent_failures": int(run.get("permanentFailures", 0)),
        "errors": int(run.get("errors", 0)),
    }


def sqlite_url(path: Path) -> str:
    return f"sqlite:///{path.resolve().as_posix()}"


def delete_sqlite_files(path: Path) -> None:
    for candidate in (path, Path(f"{path}-wal"), Path(f"{path}-shm")):
        try:
            candidate.unlink(missing_ok=True)
        except OSError:
            pass


def stop_process(process: subprocess.Popen) -> None:
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()


def percentile(values: list[float], percentile_value: int) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = math.ceil((percentile_value / 100) * len(ordered)) - 1
    return round(ordered[max(0, min(index, len(ordered) - 1))], 2)


def summarize_runs(runs: list[dict[str, Any]], key: str) -> dict[str, float]:
    values = [float(run[key]) for run in runs]
    return {
        "min": round(min(values), 2),
        "median": round(median(values), 2),
        "mean": round(mean(values), 2),
        "p95": percentile(values, 95),
    }


def render_markdown(results: dict[str, Any]) -> str:
    lines = [
        "# Python vs .NET Benchmark Results",
        "",
        "Independent clean-room benchmark using synthetic data.",
        "",
        "## Equivalence",
        "",
        f"- Fixture: `{results['fixture']}`",
        f"- Seed: `{results['seed']}`",
        f"- Equivalence match: `{results['equivalence'].get('match')}`",
        "",
        "| Runtime | Events | Incidents | Actions | Suppressions | Succeeded | Failed | Retries | Permanent failures | Errors |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    expected = results["equivalence"].get("expected", {})
    lines.append(counter_row("expected", expected))
    lines.append(counter_row("python", results["equivalence"].get("python", {})))
    lines.append(counter_row("dotnet", results["equivalence"].get("dotnet", {})))
    lines.extend(["", "## ENGINE", ""])
    engine_baseline = {}
    for item in results["engine"]:
        if item["runtime"] == "python":
            engine_baseline[(item["sqliteMode"], item["count"])] = summarize_runs(item["runs"], "eventsPerSecond")["median"]
    lines.append("| SQLite | Count | Runtime | ms median | ms mean | ms p95 | events/s median | Delta vs Python | CPU ms mean | Memory MB start->end |")
    lines.append("| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |")
    for item in results["engine"]:
        runs = item["runs"]
        ms = summarize_runs(runs, "totalMilliseconds")
        eps = summarize_runs(runs, "eventsPerSecond")
        cpu = summarize_runs(runs, "cpuMilliseconds")
        memory = f"{runs[0]['workingSetStartMb']} -> {runs[-1]['workingSetEndMb']}"
        delta = percent_delta(eps["median"], engine_baseline.get((item["sqliteMode"], item["count"])))
        lines.append(
            f"| {item['sqliteMode']} | {item['count']} | {item['runtime']} | {ms['median']} | {ms['mean']} | {ms['p95']} | {eps['median']} | {delta} | {cpu['mean']} | {memory} |"
        )
    lines.extend(["", "## HTTP", ""])
    if results["http"]:
        http_baseline = {
            (item["sqliteMode"], item["concurrency"]): item["requestsPerSecond"]
            for item in results["http"]
            if item["runtime"] == "python"
        }
        lines.append("| SQLite | Concurrency | Runtime | req/s | Delta vs Python | p50 ms | p95 ms | p99 ms | CPU ms | Memory MB | Functional match |")
        lines.append("| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |")
        for item in results["http"]:
            delta = percent_delta(item["requestsPerSecond"], http_baseline.get((item["sqliteMode"], item["concurrency"])))
            lines.append(
                f"| {item['sqliteMode']} | {item['concurrency']} | {item['runtime']} | {item['requestsPerSecond']} | {delta} | {item['p50Milliseconds']} | {item['p95Milliseconds']} | {item['p99Milliseconds']} | {item['cpuMilliseconds']} | {item['workingSetStartMb']} -> {item['workingSetEndMb']} | {item['functionalMatch']} |"
            )
    else:
        lines.append("HTTP benchmark was not executed in this run.")
    lines.extend(["", "## SQLITE", ""])
    lines.append("SQLite impact is represented by the ENGINE tables for `standard` versus `wal` with the same fixture and counters.")
    lines.extend(["", "## CONCURRENCY", ""])
    lines.append("Concurrency impact is represented by the HTTP tables across configured client concurrency levels.")
    lines.extend(["", "## LONG-RUNNING", ""])
    if results["long_running"]:
        long_running = results["long_running"]
        samples = long_running.get("samples", []) if isinstance(long_running, dict) else long_running
        if isinstance(long_running, dict):
            lines.append(f"- Final counter match: `{long_running.get('finalCountersMatch')}`")
            first_divergence = long_running.get("firstDivergence")
            if first_divergence:
                lines.append(f"- First divergence: batch `{first_divergence.get('batch')}` at `{first_divergence.get('elapsedSeconds')}` seconds.")
            else:
                lines.append("- First divergence: none observed.")
            final = long_running.get("final", {})
            if final:
                lines.append(
                    f"- Final events: Python `{final.get('python', {}).get('counters', {}).get('events', 0)}`, "
                    f".NET `{final.get('dotnet', {}).get('counters', {}).get('events', 0)}`."
                )
                lines.append(
                    f"- Final request errors: Python `{final.get('python', {}).get('requestErrors', 0)}`, "
                    f".NET `{final.get('dotnet', {}).get('requestErrors', 0)}`."
                )
            lines.append("")
        lines.append("| Elapsed s | Python events | Python MB | .NET events | .NET MB |")
        lines.append("| ---: | ---: | ---: | ---: | ---: |")
        for sample in samples:
            lines.append(
                f"| {sample['elapsedSeconds']} | {sample['python']['metrics'].get('events', 0)} | {sample['python']['process']['workingSetMb']} | {sample['dotnet']['metrics'].get('events', 0)} | {sample['dotnet']['process']['workingSetMb']} |"
            )
    else:
        lines.append("Long-running benchmark was not executed in this run.")
    lines.extend(["", "## Notes", ""])
    for note in results["notes"]:
        lines.append(f"- {note}")
    if not results["notes"]:
        lines.append("- No notes.")
    lines.extend(["", "## Decision Checklist", ""])
    lines.append("Use these results to answer whether .NET was faster, where, whether it matters, whether Python is sufficient, and whether SQLite/HTTP/ORM/locking dominated any scenario.")
    return "\n".join(lines) + "\n"


def percent_delta(value: float, baseline: float | None) -> str:
    if baseline is None or baseline == 0:
        return "n/a"
    return f"{round(((value - baseline) / baseline) * 100, 2)}%"


def counter_row(label: str, counters: dict[str, Any]) -> str:
    return (
        f"| {label} | {counters.get('events', 0)} | {counters.get('incidents', 0)} | "
        f"{counters.get('actions', 0)} | {counters.get('cooldown_suppressions', 0)} | "
        f"{counters.get('succeeded_actions', 0)} | {counters.get('failed_actions', 0)} | "
        f"{counters.get('retry_attempts', 0)} | {counters.get('permanent_failures', 0)} | "
        f"{counters.get('errors', 0)} |"
    )


if __name__ == "__main__":
    main()

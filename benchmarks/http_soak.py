from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path
from typing import Any

import httpx


ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "benchmarks" / "results"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--duration-seconds", type=int, default=1800)
    parser.add_argument("--interval-seconds", type=float, default=1.0)
    parser.add_argument("--sample-seconds", type=int, default=60)
    parser.add_argument("--python-port", type=int, default=18110)
    parser.add_argument("--dotnet-port", type=int, default=18111)
    return parser.parse_args()


def wait_health(url: str, timeout_seconds: float = 30) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"{url}/health", timeout=2) as response:
                if response.status == 200:
                    return
        except Exception:
            time.sleep(0.5)
    raise RuntimeError(f"Server did not become healthy: {url}")


def start_servers(args: argparse.Namespace) -> dict[str, tuple[str, subprocess.Popen[str]]]:
    python_db = Path(tempfile.gettempdir()) / f"ops-soak-python-{time.time_ns()}.sqlite3"
    dotnet_db = Path(tempfile.gettempdir()) / f"ops-soak-dotnet-{time.time_ns()}.sqlite3"
    python_env = os.environ.copy()
    python_env["SUPPORT_OPS_DATABASE_URL"] = f"sqlite:///{python_db.as_posix()}"
    dotnet_env = os.environ.copy()
    dotnet_env["OPS_DB_PATH"] = str(dotnet_db)
    dotnet_env["OPS_ENABLE_BACKGROUND"] = "false"

    python_process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "support_operations_intelligence_platform.api.app:create_app",
            "--factory",
            "--host",
            "127.0.0.1",
            "--port",
            str(args.python_port),
        ],
        cwd=ROOT,
        env=python_env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    dotnet_process = subprocess.Popen(
        [
            "dotnet",
            "run",
            "--no-build",
            "--project",
            "dotnet/src/OpsIntelligence.Api/OpsIntelligence.Api.csproj",
            "-c",
            "Debug",
            "--",
            "--urls",
            f"http://127.0.0.1:{args.dotnet_port}",
        ],
        cwd=ROOT,
        env=dotnet_env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    servers = {
        "python": (f"http://127.0.0.1:{args.python_port}", python_process),
        "dotnet": (f"http://127.0.0.1:{args.dotnet_port}", dotnet_process),
    }
    for url, _process in servers.values():
        wait_health(url)
    return servers


def event_payload(index: int) -> dict[str, Any]:
    severity = 90 if index % 3 else 65
    category = "offline" if index % 2 else "battery_low"
    return {
        "asset_id": f"SOAK-{index % 200:04d}",
        "source": "soak-runner",
        "category": category,
        "severity": severity,
        "occurred_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "message": f"Synthetic long-running soak event {index}",
        "executor_mode": "transient_failure" if index % 11 == 0 else "success",
    }


def seed_python_assets(base_url: str) -> None:
    with httpx.Client(base_url=base_url, timeout=20) as client:
        client.delete("/admin/reset")
        for index in range(200):
            asset_id = f"SOAK-{index:04d}"
            response = client.post(
                "/assets",
                json={"external_id": asset_id, "name": f"Synthetic soak asset {asset_id}", "group": "soak"},
            )
            if response.status_code not in (200, 409):
                raise RuntimeError(f"Asset seed failed: {response.status_code} {response.text}")


def reset_dotnet(base_url: str) -> None:
    with httpx.Client(base_url=base_url, timeout=20) as client:
        client.delete("/admin/reset")


def main() -> None:
    args = parse_args()
    RESULTS.mkdir(parents=True, exist_ok=True)
    servers = start_servers(args)
    rows: list[dict[str, Any]] = []
    counters = {stack: {"sent": 0, "errors": 0} for stack in servers}
    started = time.monotonic()
    next_sample = started + args.sample_seconds
    try:
        seed_python_assets(servers["python"][0])
        reset_dotnet(servers["dotnet"][0])
        clients = {
            stack: httpx.Client(base_url=url, timeout=10)
            for stack, (url, _process) in servers.items()
        }
        try:
            event_index = 0
            while time.monotonic() - started < args.duration_seconds:
                payload = event_payload(event_index)
                for stack, client in clients.items():
                    try:
                        response = client.post("/events", json=payload)
                        if response.status_code >= 400:
                            counters[stack]["errors"] += 1
                        else:
                            counters[stack]["sent"] += 1
                    except httpx.HTTPError:
                        counters[stack]["errors"] += 1

                if event_index % 30 == 0:
                    for client in clients.values():
                        try:
                            client.post("/maintenance/process-actions")
                        except httpx.HTTPError:
                            pass

                now = time.monotonic()
                if now >= next_sample:
                    sample = {
                        "elapsed_seconds": round(now - started, 3),
                        "counters": {stack: values.copy() for stack, values in counters.items()},
                    }
                    for stack, client in clients.items():
                        try:
                            sample[stack] = client.get("/metrics").json()
                        except httpx.HTTPError as exc:
                            sample[stack] = {"error": type(exc).__name__}
                    rows.append(sample)
                    print(json.dumps(sample, sort_keys=True), flush=True)
                    next_sample += args.sample_seconds
                event_index += 1
                time.sleep(args.interval_seconds)
        finally:
            for client in clients.values():
                client.close()
    finally:
        for _url, process in servers.values():
            process.terminate()
        for _url, process in servers.values():
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()

    timestamp = time.strftime("%Y%m%d-%H%M%S")
    path = RESULTS / f"http_soak_{timestamp}.json"
    result = {
        "duration_seconds": args.duration_seconds,
        "interval_seconds": args.interval_seconds,
        "sample_seconds": args.sample_seconds,
        "rows": rows,
    }
    path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"file": str(path.relative_to(ROOT)), "samples": len(rows)}, sort_keys=True))


if __name__ == "__main__":
    main()

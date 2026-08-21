from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
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

try:
    import psutil
except ImportError:  # pragma: no cover
    psutil = None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workload", default="specification/workloads/workload_1000.jsonl")
    parser.add_argument("--concurrency", default="1,10,25,50,100")
    parser.add_argument("--requests", type=int, default=200)
    parser.add_argument("--python-port", type=int, default=18010)
    parser.add_argument("--dotnet-port", type=int, default=18011)
    return parser.parse_args()


def load_payloads(path: Path, limit: int) -> list[dict[str, Any]]:
    rows = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            rows.append(json.loads(line))
            if len(rows) >= limit:
                break
    return rows


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
    python_db = Path(tempfile.gettempdir()) / f"ops-http-python-{time.time_ns()}.sqlite3"
    dotnet_db = Path(tempfile.gettempdir()) / f"ops-http-dotnet-{time.time_ns()}.sqlite3"
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


async def prepare_stack(stack: str, base_url: str, payloads: list[dict[str, Any]]) -> None:
    async with httpx.AsyncClient(base_url=base_url, timeout=20) as client:
        await client.delete("/admin/reset")
        if stack == "python":
            for asset_id in sorted({str(payload["asset_id"]) for payload in payloads}):
                response = await client.post(
                    "/assets",
                    json={"external_id": asset_id, "name": f"Synthetic asset {asset_id}", "group": "http"},
                )
                if response.status_code not in (200, 409):
                    raise RuntimeError(f"Asset seed failed: {response.status_code} {response.text}")


async def run_load(base_url: str, payloads: list[dict[str, Any]], concurrency: int) -> dict[str, Any]:
    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
    for payload in payloads:
        queue.put_nowait(payload)
    latencies: list[float] = []
    errors = 0
    timeouts = 0

    async def worker() -> None:
        nonlocal errors, timeouts
        async with httpx.AsyncClient(base_url=base_url, timeout=httpx.Timeout(10.0)) as client:
            while True:
                try:
                    payload = queue.get_nowait()
                except asyncio.QueueEmpty:
                    return
                started = time.perf_counter()
                try:
                    response = await client.post("/events", json=payload)
                    if response.status_code >= 400:
                        errors += 1
                except httpx.TimeoutException:
                    timeouts += 1
                except httpx.HTTPError:
                    errors += 1
                finally:
                    latencies.append((time.perf_counter() - started) * 1000)
                    queue.task_done()

    started = time.perf_counter()
    await asyncio.gather(*(worker() for _ in range(concurrency)))
    elapsed = time.perf_counter() - started
    ordered = sorted(latencies)
    return {
        "requests": len(payloads),
        "concurrency": concurrency,
        "elapsed_ms": round(elapsed * 1000, 3),
        "rps": round(len(payloads) / elapsed, 2),
        "p50_ms": percentile(ordered, 0.50),
        "p95_ms": percentile(ordered, 0.95),
        "p99_ms": percentile(ordered, 0.99),
        "mean_ms": round(statistics.fmean(latencies), 3) if latencies else 0,
        "errors": errors,
        "timeouts": timeouts,
    }


def percentile(values: list[float], percentile_value: float) -> float:
    if not values:
        return 0
    index = max(0, min(len(values) - 1, round((len(values) - 1) * percentile_value)))
    return round(values[index], 3)


def process_snapshot(process: subprocess.Popen[str]) -> dict[str, float | None]:
    if psutil is None:
        return {"cpu_seconds": None, "rss_mb": None}
    try:
        proc = psutil.Process(process.pid)
        cpu = proc.cpu_times()
        return {
            "cpu_seconds": round(cpu.user + cpu.system, 3),
            "rss_mb": round(proc.memory_info().rss / 1024 / 1024, 2),
        }
    except psutil.Error:
        return {"cpu_seconds": None, "rss_mb": None}


async def main_async() -> None:
    args = parse_args()
    RESULTS.mkdir(parents=True, exist_ok=True)
    payloads = load_payloads(ROOT / args.workload, args.requests)
    concurrency_levels = [int(item) for item in args.concurrency.split(",") if item.strip()]
    servers = start_servers(args)
    rows = []
    try:
        for stack, (base_url, process) in servers.items():
            for concurrency in concurrency_levels:
                await prepare_stack(stack, base_url, payloads)
                before = process_snapshot(process)
                result = await run_load(base_url, payloads, concurrency)
                after = process_snapshot(process)
                metrics = fetch_metrics(base_url)
                rows.append(
                    {
                        "stack": stack,
                        "base_url": base_url,
                        "workload": Path(args.workload).name,
                        **result,
                        "server_cpu_seconds_delta": cpu_delta(before, after),
                        "server_rss_mb": after["rss_mb"],
                        "metrics": metrics,
                    }
                )
                print(f"{stack} c={concurrency} rps={result['rps']} errors={result['errors']}", flush=True)
    finally:
        for _url, process in servers.values():
            process.terminate()
        for _url, process in servers.values():
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()

    timestamp = time.strftime("%Y%m%d-%H%M%S")
    path = RESULTS / f"http_summary_{timestamp}.json"
    path.write_text(json.dumps(rows, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"results": rows, "file": str(path.relative_to(ROOT))}, indent=2, sort_keys=True))


def cpu_delta(before: dict[str, float | None], after: dict[str, float | None]) -> float | None:
    if before["cpu_seconds"] is None or after["cpu_seconds"] is None:
        return None
    return round(float(after["cpu_seconds"]) - float(before["cpu_seconds"]), 3)


def fetch_metrics(base_url: str) -> dict[str, Any]:
    try:
        return httpx.get(f"{base_url}/metrics", timeout=30).json()
    except httpx.HTTPError as exc:
        return {"error": type(exc).__name__}


if __name__ == "__main__":
    asyncio.run(main_async())

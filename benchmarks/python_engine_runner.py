from __future__ import annotations

import argparse
import ctypes
import json
import os
import sys
import tempfile
import time
from pathlib import Path

from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from support_operations_intelligence_platform.contract import load_workload, process_contract_events  # noqa: E402
from support_operations_intelligence_platform.core.database import create_session_factory  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workload", required=True)
    parser.add_argument("--db", default=None)
    parser.add_argument("--wal", action="store_true")
    return parser.parse_args()


def working_set_mb() -> float | None:
    if os.name == "nt":
        class ProcessMemoryCounters(ctypes.Structure):
            _fields_ = [
                ("cb", ctypes.c_ulong),
                ("PageFaultCount", ctypes.c_ulong),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        psapi = ctypes.WinDLL("psapi.dll")
        kernel32 = ctypes.WinDLL("kernel32.dll")
        kernel32.GetCurrentProcess.restype = ctypes.c_void_p
        psapi.GetProcessMemoryInfo.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ProcessMemoryCounters),
            ctypes.c_ulong,
        ]
        psapi.GetProcessMemoryInfo.restype = ctypes.c_int
        counters = ProcessMemoryCounters()
        counters.cb = ctypes.sizeof(ProcessMemoryCounters)
        handle = kernel32.GetCurrentProcess()
        success = psapi.GetProcessMemoryInfo(
            handle,
            ctypes.byref(counters),
            counters.cb,
        )
        if success:
            return round(counters.WorkingSetSize / 1024 / 1024, 2)
        return None

    try:
        import resource

        usage = resource.getrusage(resource.RUSAGE_SELF)
        return round(usage.ru_maxrss / 1024, 2)
    except Exception:
        return None


def main() -> None:
    args = parse_args()
    workload = load_workload(args.workload)
    db_path = Path(args.db) if args.db else Path(tempfile.gettempdir()) / f"ops-python-bench-{os.getpid()}-{time.time_ns()}.sqlite3"
    database_url = f"sqlite:///{db_path.resolve().as_posix()}"
    factory = create_session_factory(database_url)
    session = factory()
    try:
        if args.wal:
            session.execute(text("PRAGMA journal_mode=WAL;"))
            session.execute(text("PRAGMA synchronous=NORMAL;"))
        cpu_start = time.process_time()
        start = time.perf_counter()
        summary = process_contract_events(session, workload)
        session.commit()
        elapsed = time.perf_counter() - start
        cpu_ms = (time.process_time() - cpu_start) * 1000
        result = {
            "stack": "python",
            "workload": Path(args.workload).name,
            "wal": bool(args.wal),
            "elapsed_ms": round(elapsed * 1000, 3),
            "events_per_second": round(len(workload) / elapsed, 2),
            "cpu_ms": round(cpu_ms, 3),
            "working_set_mb": working_set_mb(),
            "processed_actions": summary["actions"],
            **summary,
            "errors": 0,
        }
        print(json.dumps(result, indent=2, sort_keys=True))
    finally:
        session.close()


if __name__ == "__main__":
    main()

from __future__ import annotations

import json
import random
from datetime import UTC, datetime, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKLOAD_DIR = ROOT / "specification" / "workloads"
SIZES = (100, 1_000, 10_000, 50_000, 100_000)
CATEGORIES = ("offline", "battery_low", "latency", "temperature", "sync_delay")
SOURCES = ("north-gateway", "warehouse", "edge-agent", "lab-rig", "support-simulator")
EXECUTOR_MODES = ("success", "success", "success", "transient_failure", "permanent_failure")


def build_event(index: int, rng: random.Random, start: datetime) -> dict[str, object]:
    severity_roll = index % 10
    if severity_roll in (0, 1):
        severity = rng.randint(10, 45)
    elif severity_roll in (2, 3, 4):
        severity = rng.randint(50, 79)
    else:
        severity = rng.randint(80, 99)

    category = CATEGORIES[(index + rng.randint(0, 3)) % len(CATEGORIES)]
    return {
        "asset_id": f"ASSET-{rng.randint(1, 120):04d}",
        "source": SOURCES[index % len(SOURCES)],
        "category": category,
        "severity": severity,
        "occurred_at": (start + timedelta(seconds=index * 17)).isoformat().replace("+00:00", "Z"),
        "message": f"Synthetic {category} event #{index}",
        "executor_mode": EXECUTOR_MODES[(index + rng.randint(0, 4)) % len(EXECUTOR_MODES)],
    }


def write_workload(size: int) -> dict[str, object]:
    rng = random.Random(20260820 + size)
    start = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
    path = WORKLOAD_DIR / f"workload_{size}.jsonl"
    counts = {"normal": 0, "warning": 0, "critical": 0}
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for index in range(size):
            event = build_event(index, rng, start)
            if event["severity"] < 50:
                counts["normal"] += 1
            elif event["severity"] < 80:
                counts["warning"] += 1
            else:
                counts["critical"] += 1
            handle.write(json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n")
    return {"file": str(path.relative_to(ROOT)), "events": size, **counts}


def main() -> None:
    WORKLOAD_DIR.mkdir(parents=True, exist_ok=True)
    manifest = {
        "seed_base": 20260820,
        "generated_by": "benchmarks/generate_workloads.py",
        "workloads": [write_workload(size) for size in SIZES],
    }
    manifest_path = WORKLOAD_DIR / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

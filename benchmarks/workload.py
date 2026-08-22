from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class SharedEvent:
    asset_id: str
    source: str
    category: str
    severity: int
    occurred_at: str
    message: str
    executor_mode: str


@dataclass(frozen=True)
class ExpectedCounters:
    events: int
    incidents: int
    actions: int
    cooldown_suppressions: int
    succeeded_actions: int
    failed_actions: int
    retry_attempts: int
    permanent_failures: int
    errors: int = 0


def event_at(index: int, seed: int = 424242) -> SharedEvent:
    group = index // 20
    position = index % 20
    timestamp = datetime(2026, 1, 1, tzinfo=UTC) + timedelta(seconds=index)
    source = f"synthetic-source-{seed % 997}"

    if position == 0:
        return SharedEvent(
            asset_id=f"SYN-{seed}-{group:06d}-critical",
            source=source,
            category="offline",
            severity=92,
            occurred_at=timestamp.isoformat(),
            message=f"critical synthetic event {index}",
            executor_mode="success",
        )
    if position == 1:
        return SharedEvent(
            asset_id=f"SYN-{seed}-{group:06d}-critical",
            source=source,
            category="offline",
            severity=91,
            occurred_at=timestamp.isoformat(),
            message=f"cooldown duplicate synthetic event {index}",
            executor_mode="success",
        )
    if position == 2:
        return SharedEvent(
            asset_id=f"SYN-{seed}-{group:06d}-warning",
            source=source,
            category="degraded",
            severity=64,
            occurred_at=timestamp.isoformat(),
            message=f"warning synthetic event {index}",
            executor_mode="success",
        )
    if position == 3:
        return SharedEvent(
            asset_id=f"SYN-{seed}-{group:06d}-transient",
            source=source,
            category="offline",
            severity=93,
            occurred_at=timestamp.isoformat(),
            message=f"transient synthetic event {index}",
            executor_mode="transient_then_success",
        )
    if position == 4:
        return SharedEvent(
            asset_id=f"SYN-{seed}-{group:06d}-permanent",
            source=source,
            category="offline",
            severity=94,
            occurred_at=timestamp.isoformat(),
            message=f"permanent synthetic event {index}",
            executor_mode="permanent_failure",
        )

    return SharedEvent(
        asset_id=f"SYN-{seed}-{group:06d}-normal-{position:02d}",
        source=source,
        category="heartbeat",
        severity=15,
        occurred_at=timestamp.isoformat(),
        message=f"normal synthetic event {index}",
        executor_mode="success",
    )


def generate_events(count: int, seed: int = 424242) -> list[SharedEvent]:
    return [event_at(index, seed) for index in range(count)]


def expected_counters(count: int) -> ExpectedCounters:
    incidents = 0
    actions = 0
    suppressions = 0
    succeeded = 0
    failed = 0
    retries = 0
    permanent = 0
    for index in range(count):
        position = index % 20
        if position in (0, 2, 3, 4):
            incidents += 1
        if position in (0, 3, 4):
            actions += 1
        if position == 1:
            suppressions += 1
        if position in (0, 3):
            succeeded += 1
        if position == 4:
            failed += 1
            permanent += 1
        if position == 3:
            retries += 1
    return ExpectedCounters(
        events=count,
        incidents=incidents,
        actions=actions,
        cooldown_suppressions=suppressions,
        succeeded_actions=succeeded,
        failed_actions=failed,
        retry_attempts=retries,
        permanent_failures=permanent,
    )


def write_jsonl(path: Path, events: Iterable[SharedEvent]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for event in events:
            handle.write(json.dumps(asdict(event), separators=(",", ":")) + "\n")


def read_jsonl(path: Path, count: int | None = None) -> list[SharedEvent]:
    events: list[SharedEvent] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if count is not None and len(events) >= count:
                break
            events.append(SharedEvent(**json.loads(line)))
    return events

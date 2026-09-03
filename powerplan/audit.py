"""Append-only decision log.

Every plan run writes one JSON object per line: the inputs that produced it
(hashed, so you can prove two runs saw the same fleet), the objective weights,
every candidate considered, and the choice. This is the part reviewers actually
care about -- a scheduler nobody can audit will not be trusted with a megawatt.
"""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from .engine import Plan
from .models import Fleet, Workload


def fingerprint(obj) -> str:
    """Stable short hash of any dataclass tree / dict / list."""
    payload = json.dumps(_plain(obj), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def _plain(obj):
    if hasattr(obj, "__dataclass_fields__"):
        return asdict(obj)
    if isinstance(obj, (list, tuple)):
        return [_plain(o) for o in obj]
    return obj


def record(
    plan: Plan,
    fleet: Fleet,
    workloads: list[Workload],
    path: str | Path = "audit.jsonl",
    scenario: str = "baseline",
) -> str:
    run_id = str(uuid.uuid4())
    entry = {
        "run_id": run_id,
        "ts": datetime.now(timezone.utc).isoformat(),
        "scenario": scenario,
        "actor": os.environ.get("USER", "unknown"),
        "fleet_fingerprint": fingerprint(fleet),
        "workload_fingerprint": fingerprint(workloads),
        "weights": plan.weights,
        "notes": plan.notes,
        "totals": {
            "cost_usd": round(plan.total_cost, 2),
            "carbon_kg": round(plan.total_carbon_kg, 2),
            "energy_kwh": round(plan.total_energy_kwh, 2),
            "makespan_hours": round(plan.makespan_hours, 2),
        },
        "decisions": [
            {
                "workload_id": p.workload_id,
                "chosen": asdict(p.chosen),
                "runner_up": asdict(p.runner_up) if p.runner_up else None,
                "candidates_considered": p.considered,
                "rejections": [asdict(r) for r in p.rejected],
            }
            for p in plan.placements
        ],
        "unplaced": [
            {"workload_id": wid, "rejections": [asdict(r) for r in rej]}
            for wid, rej in plan.unplaced
        ],
    }
    with Path(path).open("a") as fh:
        fh.write(json.dumps(entry) + "\n")
    return run_id

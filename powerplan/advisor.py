"""Weight advisor: propose objective weights that meet a goal.

A deterministic search over a fixed weight grid. It uses no language model and
never applies anything: it returns a `Proposal` for a person to approve. A
proposal never trades away placed work -- a grid set is only considered when it
places the same number of workloads at each priority as the baseline plan.
"""

from __future__ import annotations

import copy
from collections import Counter
from dataclasses import dataclass, field

from .engine import DEFAULT_WEIGHTS, Plan, plan
from .models import Fleet, Workload

# Every weight set in steps of 0.05 that sums to 1 (231 sets).
GRID: list[dict] = [
    {"cost": c / 20, "carbon": k / 20, "runtime": (20 - c - k) / 20}
    for c in range(0, 21)
    for k in range(0, 21 - c)
]

_METRICS = ("cost", "carbon")
_KEYS = ("cost", "carbon", "runtime")
_TOLERANCE = 1e-9

Location = tuple  # (site_id, pool_id, start_hour)


@dataclass
class Proposal:
    metric: str
    reduction: float
    feasible: bool
    weights: dict
    distance: float
    baseline: Plan
    proposed: Plan
    moved: list[tuple[str, Location | None, Location]] = field(default_factory=list)


def _metric_value(result: Plan, metric: str) -> float:
    return result.total_cost if metric == "cost" else result.total_carbon_kg


def _priority_counts(result: Plan, priorities: dict[str, int]) -> Counter:
    return Counter(priorities[p.workload_id] for p in result.placements)


def _locations(result: Plan) -> dict[str, Location]:
    return {
        p.workload_id: (p.chosen.site_id, p.chosen.pool_id, p.chosen.start_hour)
        for p in result.placements
    }


def _distance(weights: dict, base: dict) -> float:
    return round(sum(abs(weights[k] - base[k]) for k in _KEYS), 9)


def advise(
    fleet: Fleet,
    workloads: list[Workload],
    metric: str,
    reduction: float,
    base_weights: dict | None = None,
) -> Proposal:
    """Find the grid weights nearest `base_weights` that cut `metric` by
    `reduction` (a fraction, 0 <= reduction < 1) without placing less work.

    The caller's fleet is never modified. When no candidate reaches the goal,
    the candidate with the lowest metric is returned with `feasible` False.
    """
    if metric not in _METRICS:
        raise ValueError(f"metric must be one of {_METRICS}, got {metric!r}")
    if not (0 <= reduction < 1):
        raise ValueError(f"reduction must satisfy 0 <= reduction < 1, got {reduction!r}")
    base = dict(DEFAULT_WEIGHTS if base_weights is None else base_weights)

    work_fleet = copy.deepcopy(fleet)
    priorities = {w.workload_id: w.priority for w in workloads}

    baseline = plan(work_fleet, workloads, base)
    baseline_value = _metric_value(baseline, metric)
    baseline_counts = _priority_counts(baseline, priorities)
    target = baseline_value * (1 - reduction) + _TOLERANCE

    # (weights, distance, metric value, plan)
    candidates: list[tuple[dict, float, float, Plan]] = []
    for weights in GRID:
        result = plan(work_fleet, workloads, dict(weights))
        if _priority_counts(result, priorities) != baseline_counts:
            continue
        candidates.append(
            (weights, _distance(weights, base), _metric_value(result, metric), result)
        )

    reaching = [c for c in candidates if c[2] <= target]
    if reaching:
        feasible = True
        best = min(reaching, key=lambda c: (c[1], c[2], c[0]["cost"], c[0]["carbon"]))
    else:
        feasible = False
        best = min(candidates, key=lambda c: (c[2], c[1], c[0]["cost"], c[0]["carbon"]))

    weights, distance, _, proposed = best

    before = _locations(baseline)
    moved = []
    for placement in proposed.placements:
        after = (
            placement.chosen.site_id,
            placement.chosen.pool_id,
            placement.chosen.start_hour,
        )
        was = before.get(placement.workload_id)
        if was != after:
            moved.append((placement.workload_id, was, after))

    return Proposal(
        metric=metric,
        reduction=reduction,
        feasible=feasible,
        weights=dict(weights),
        distance=distance,
        baseline=baseline,
        proposed=proposed,
        moved=moved,
    )

"""Exact reference search over the same candidates the greedy engine sees.

The greedy in `engine.py` is never replaced; this module only measures how far
it is from a true optimum under one shared objective. Stdlib only.

Objective
---------
Reference totals are taken over workloads that have at least one option:
``C_ref = sum(min cost)``, ``K_ref = sum(min carbon)``, ``R_ref = sum(min runtime)``.
A placed option contributes
``w_cost*cost/C_ref + w_carbon*carbon/K_ref + w_runtime*runtime/R_ref``
(a term is 0 when its reference is 0). Plans are compared lexicographically:
more placed workloads at each priority level first, then lower total score.
"""

from __future__ import annotations

from dataclasses import dataclass

from .engine import DEFAULT_WEIGHTS, _allowed_starts, _window_hours
from .models import Fleet, Site, Workload


@dataclass(frozen=True)
class Option:
    """One concrete way to run a workload: pool plus start hour."""

    workload_id: str
    site_id: str
    pool_id: str
    start_hour: int
    gpu_count: int
    facility_kw: float
    runtime_hours: float
    cost_usd: float
    carbon_kg: float
    hours: tuple[int, ...]


@dataclass
class Objective:
    placed_by_priority: dict[int, int]
    score: float
    total_cost_usd: float
    total_carbon_kg: float


# ---------------------------------------------------------------------------
# options
# ---------------------------------------------------------------------------

def _integrate(
    site: Site, facility_kw: float, start_hour: int, runtime_hours: float
) -> tuple[float, float]:
    """Exact cost ($) and carbon (kg) of running at `facility_kw` from `start_hour`.

    Slot ``i`` uses hour ``(start + i) % 24`` for ``min(1, runtime - i)`` hours,
    exactly as the engine integrates a window.
    """
    cost = 0.0
    carbon = 0.0
    i = 0
    while runtime_hours - i > 1e-9:
        chunk = min(1.0, runtime_hours - i)
        hour = (int(start_hour) + i) % 24
        cost += facility_kw * chunk * site.price_at(hour)
        carbon += facility_kw * chunk * site.carbon_at(hour) / 1000.0
        i += 1
    return cost, carbon


def options_for(w: Workload, fleet: Fleet) -> list[Option]:
    """Every feasible (site, pool, start) option for `w` on an empty fleet.

    Callers should `fleet.reset()` first; only static limits are checked here
    (pool size, memory, residency, deadline, and the site's power ceiling).
    """
    result: list[Option] = []
    for site in fleet.sites:
        if not site.online:
            continue
        if w.allowed_regions and site.region not in w.allowed_regions:
            continue
        for pool in site.pools:
            if w.accelerator_allowlist and pool.accelerator not in w.accelerator_allowlist:
                continue
            if pool.total < w.gpu_count:
                continue
            if pool.memory_gb < w.min_memory_gb:
                continue
            runtime = w.runtime_hours(pool)
            if w.deadline_hours is not None and w.deadline_hours < runtime:
                continue
            facility_kw = site.facility_kw(pool.draw_kw(w.gpu_count))
            if facility_kw > site.power_capacity_kw - site.baseline_load_kw:
                continue
            for start in _allowed_starts(w, runtime):
                cost, carbon = _integrate(site, facility_kw, start, runtime)
                result.append(
                    Option(
                        workload_id=w.workload_id,
                        site_id=site.site_id,
                        pool_id=pool.pool_id,
                        start_hour=start,
                        gpu_count=w.gpu_count,
                        facility_kw=facility_kw,
                        runtime_hours=runtime,
                        cost_usd=cost,
                        carbon_kg=carbon,
                        hours=tuple(_window_hours(start, runtime)),
                    )
                )
    return result


# ---------------------------------------------------------------------------
# objective
# ---------------------------------------------------------------------------

def reference_totals(
    options_by_workload: dict[str, list[Option]],
) -> tuple[float, float, float]:
    """(C_ref, K_ref, R_ref) over workloads that have at least one option."""
    c_ref = k_ref = r_ref = 0.0
    for options in options_by_workload.values():
        if not options:
            continue
        c_ref += min(o.cost_usd for o in options)
        k_ref += min(o.carbon_kg for o in options)
        r_ref += min(o.runtime_hours for o in options)
    return c_ref, k_ref, r_ref


def contribution(
    option: Option, weights: dict, refs: tuple[float, float, float]
) -> float:
    """Score an option adds to a plan; lower is better."""
    c_ref, k_ref, r_ref = refs
    total = 0.0
    if c_ref > 0:
        total += weights["cost"] * option.cost_usd / c_ref
    if k_ref > 0:
        total += weights["carbon"] * option.carbon_kg / k_ref
    if r_ref > 0:
        total += weights["runtime"] * option.runtime_hours / r_ref
    return total


def evaluate(
    assignment: dict[str, Option | None],
    workloads: list[Workload],
    options_by_workload: dict[str, list[Option]],
    weights: dict | None = None,
) -> Objective:
    """Score an assignment (workload_id -> Option or None) under the shared objective."""
    weights = weights or DEFAULT_WEIGHTS
    refs = reference_totals(options_by_workload)
    placed: dict[int, int] = {}
    score = 0.0
    cost = 0.0
    carbon = 0.0
    for w in workloads:
        option = assignment.get(w.workload_id)
        if option is None:
            continue
        placed[w.priority] = placed.get(w.priority, 0) + 1
        score += contribution(option, weights, refs)
        cost += option.cost_usd
        carbon += option.carbon_kg
    return Objective(
        placed_by_priority=dict(sorted(placed.items())),
        score=score,
        total_cost_usd=cost,
        total_carbon_kg=carbon,
    )

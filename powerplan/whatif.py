"""What happens if equipment or grid capacity fails.

Apply a perturbation to a copy of the fleet, re-plan, and diff against the
baseline: what moved, what became unplaceable, what it cost.
"""

from __future__ import annotations

import copy

from .engine import Plan, plan as make_plan
from .models import Fleet, Workload


def site_offline(fleet: Fleet, site_id: str) -> Fleet:
    f = copy.deepcopy(fleet)
    f.site(site_id).online = False
    return f


def curtail(fleet: Fleet, site_id: str, fraction: float) -> Fleet:
    """Utility caps the site at (1 - fraction) of its normal ceiling."""
    f = copy.deepcopy(fleet)
    s = f.site(site_id)
    s.power_capacity_kw *= max(0.0, 1.0 - fraction)
    return f


def pool_degraded(fleet: Fleet, site_id: str, pool_id: str, lost: int) -> Fleet:
    """`lost` accelerators fail hardware checks and leave the pool."""
    f = copy.deepcopy(fleet)
    p = f.site(site_id).pool(pool_id)
    p.total = max(0, p.total - lost)
    p.available = min(p.available, p.total)
    return f


def price_spike(fleet: Fleet, site_id: str, multiplier: float) -> Fleet:
    f = copy.deepcopy(fleet)
    f.site(site_id).price_per_kwh *= multiplier
    return f


def diff(baseline: Plan, scenario: Plan) -> str:
    base = {p.workload_id: p.chosen for p in baseline.placements}
    scen = {p.workload_id: p.chosen for p in scenario.placements}

    lines = [
        f"cost      ${baseline.total_cost:,.0f} -> ${scenario.total_cost:,.0f} "
        f"({scenario.total_cost - baseline.total_cost:+,.0f})",
        f"carbon    {baseline.total_carbon_kg:,.0f} -> "
        f"{scenario.total_carbon_kg:,.0f} kg CO2e "
        f"({scenario.total_carbon_kg - baseline.total_carbon_kg:+,.0f})",
        f"makespan  {baseline.makespan_hours:.1f}h -> "
        f"{scenario.makespan_hours:.1f}h",
    ]

    moved = [
        (wid, base[wid], scen[wid])
        for wid in base
        if wid in scen
        and (base[wid].site_id, base[wid].pool_id)
        != (scen[wid].site_id, scen[wid].pool_id)
    ]
    for wid, b, s in moved:
        lines.append(
            f"MOVED   {wid}: {b.site_id}/{b.pool_id} -> {s.site_id}/{s.pool_id} "
            f"({s.cost_usd - b.cost_usd:+,.0f} USD, "
            f"{s.runtime_hours - b.runtime_hours:+.1f}h)"
        )

    dropped = [wid for wid in base if wid not in scen]
    for wid in dropped:
        lines.append(f"DROPPED {wid}: no feasible placement under this scenario")

    if not moved and not dropped:
        lines.append("no placement changes")
    return "\n".join(lines)


def run_scenario(
    fleet: Fleet,
    workloads: list[Workload],
    perturbed: Fleet,
    weights: dict | None = None,
) -> tuple[Plan, Plan]:
    return make_plan(fleet, workloads, weights), make_plan(
        perturbed, workloads, weights
    )

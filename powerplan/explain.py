"""Turn a Placement into a sentence a capacity planner would accept.

The rule: never claim a winner is better on every axis. State what it gave up.
"""

from __future__ import annotations

from .engine import Candidate, Placement, Plan


_WORDS = {
    "$": ("cheaper", "more expensive", "same cost"),
    " kg CO2e": ("cleaner", "dirtier", "same carbon"),
    "h": ("faster", "slower", "same runtime"),
}


def _delta(chosen: float, other: float, unit: str) -> str:
    better, worse, same = _WORDS[unit]
    diff = other - chosen
    if abs(diff) < 1e-6:
        return same
    word = better if diff > 0 else worse
    if unit == "$":
        return f"${abs(diff):,.0f} {word}"
    return f"{abs(diff):,.1f}{unit} {word}"


def explain(p: Placement) -> str:
    c = p.chosen
    head = (
        f"{p.workload_name} ({p.workload_id}) -> {c.site_id}/{c.pool_id} "
        f"[{c.accelerator}]"
    )
    facts = (
        f"  {c.runtime_hours:.1f}h - {c.facility_kw:.0f}kW facility - "
        f"{c.energy_kwh:,.0f} kWh - ${c.cost_usd:,.0f} - "
        f"{c.carbon_kg:,.0f} kg CO2e"
    )
    weights = (
        "  score "
        + " + ".join(f"{k} {v:.3f}" for k, v in c.components.items())
        + f" = {c.score:.3f}"
    )

    lines = [head, facts, weights]

    # Add start hour information if deferred
    if c.deferred_for_capacity:
        # Hour 0 was full: the start hour is forced, so claim no saving.
        lines.append(
            f"  starts at hour {c.start_hour:.0f} (UTC); "
            f"hour 0 had no power headroom"
        )
    elif c.start_hour > 0:
        cost_saved = c.deferral_saved_usd
        carbon_saved = c.deferral_saved_kg
        
        if cost_saved >= 0 and carbon_saved >= 0:
            lines.append(
                f"  starts at hour {c.start_hour:.0f} (UTC); "
                f"deferring saved ${cost_saved:,.0f} and {carbon_saved:,.0f} kg CO2e"
            )
        elif cost_saved >= 0 and carbon_saved < 0:
            lines.append(
                f"  starts at hour {c.start_hour:.0f} (UTC); "
                f"deferring saved ${cost_saved:,.0f} but emits {-carbon_saved:,.0f} kg more"
            )
        elif cost_saved < 0 and carbon_saved >= 0:
            lines.append(
                f"  starts at hour {c.start_hour:.0f} (UTC); "
                f"deferring cost ${-cost_saved:,.0f} more but saved {carbon_saved:,.0f} kg CO2e"
            )
        else:
            lines.append(
                f"  starts at hour {c.start_hour:.0f} (UTC); "
                f"deferring cost ${-cost_saved:,.0f} more and emits {-carbon_saved:,.0f} kg more"
            )

    r: Candidate | None = p.runner_up
    if r is None:
        lines.append("  only feasible candidate.")
    else:
        lines.append(
            f"  beat {r.site_id}/{r.pool_id}: "
            f"{_delta(c.cost_usd, r.cost_usd, '$')}, "
            f"{_delta(c.carbon_kg, r.carbon_kg, ' kg CO2e')}, "
            f"{_delta(c.runtime_hours, r.runtime_hours, 'h')}"
        )
        tradeoffs = []
        if c.cost_usd > r.cost_usd:
            tradeoffs.append(f"costs ${c.cost_usd - r.cost_usd:,.0f} more")
        if c.carbon_kg > r.carbon_kg:
            tradeoffs.append(f"emits {c.carbon_kg - r.carbon_kg:,.0f} kg more")
        if c.runtime_hours > r.runtime_hours:
            tradeoffs.append(f"runs {c.runtime_hours - r.runtime_hours:.1f}h slower")
        if tradeoffs:
            lines.append("  tradeoff accepted: " + "; ".join(tradeoffs) + ".")

    if p.rejected:
        top = p.rejected[:3]
        lines.append(
            "  ruled out: "
            + "; ".join(f"{r.site_id}/{r.pool_id} ({r.reason})" for r in top)
            + (f"; +{len(p.rejected) - 3} more" if len(p.rejected) > 3 else "")
        )
    return "\n".join(lines)


def summarise(plan: Plan) -> str:
    deferred_count = sum(1 for p in plan.placements if p.chosen.start_hour > 0)
    
    lines = [
        f"placed {len(plan.placements)} workload(s), "
        f"{len(plan.unplaced)} unplaced",
        f"total cost      ${plan.total_cost:,.0f}",
        f"total energy    {plan.total_energy_kwh:,.0f} kWh",
        f"total carbon    {plan.total_carbon_kg:,.0f} kg CO2e",
        f"makespan        {plan.makespan_hours:.1f} h",
        f"deferred        {deferred_count} workload(s)",
    ]
    for wid, rejections in plan.unplaced:
        why = "; ".join(f"{r.site_id}/{r.pool_id}: {r.reason}" for r in rejections[:3])
        lines.append(f"UNPLACED {wid} -- {why}")
    return "\n".join(lines)

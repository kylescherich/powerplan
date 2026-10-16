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

from .engine import (
    DEFAULT_WEIGHTS,
    Plan,
    _allowed_starts,
    _order,
    _window_hours,
    plan,
)
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


# ---------------------------------------------------------------------------
# exact search
# ---------------------------------------------------------------------------

class SearchTooLarge(RuntimeError):
    """The exact search exceeded its node budget."""


@dataclass
class OptimalResult:
    assignment: dict[str, Option | None]
    objective: Objective
    nodes: int


def solve(
    fleet: Fleet,
    workloads: list[Workload],
    weights: dict | None = None,
    max_nodes: int = 200_000,
) -> OptimalResult:
    """Exact branch and bound over every workload's options (or unplaced).

    Depth-first in the engine's workload order. Each workload tries its options
    sorted by ``(contribution, site_id, pool_id, start_hour)`` and then
    "unplaced". The first best plan found is kept (strict improvement only).
    Does not change the fleet's planning state. Raises `SearchTooLarge` when
    more than `max_nodes` nodes are explored.
    """
    weights = weights or DEFAULT_WEIGHTS
    options_by_workload = {
        w.workload_id: options_for(w, fleet) for w in workloads
    }
    refs = reference_totals(options_by_workload)
    order = _order(workloads)
    n = len(order)
    levels = sorted({w.priority for w in workloads})
    level_index = {p: i for i, p in enumerate(levels)}
    n_levels = len(levels)

    ranked: list[list[tuple[float, Option]]] = []
    for w in order:
        scored = [
            (contribution(o, weights, refs), o)
            for o in options_by_workload[w.workload_id]
        ]
        scored.sort(
            key=lambda item: (
                item[0],
                item[1].site_id,
                item[1].pool_id,
                item[1].start_hour,
            )
        )
        ranked.append(scored)

    # Optimistic remainders: everything with options placed at its minimum.
    suffix_counts = [[0] * n_levels for _ in range(n + 1)]
    suffix_min = [0.0] * (n + 1)
    for i in range(n - 1, -1, -1):
        suffix_counts[i] = list(suffix_counts[i + 1])
        suffix_min[i] = suffix_min[i + 1]
        if ranked[i]:
            suffix_counts[i][level_index[order[i].priority]] += 1
            suffix_min[i] += ranked[i][0][0]

    pool_total = {
        (site.site_id, pool.pool_id): pool.total
        for site in fleet.sites
        for pool in site.pools
    }
    pool_used = {key: 0 for key in pool_total}
    site_room = {
        site.site_id: site.power_capacity_kw - site.baseline_load_kw
        for site in fleet.sites
    }
    load = {site.site_id: [0.0] * 24 for site in fleet.sites}

    placed = [0] * n_levels
    chosen: list[Option | None] = [None] * n
    best_key: tuple | None = None
    best_choice: list[Option | None] | None = None
    nodes = 0

    def too_large() -> SearchTooLarge:
        return SearchTooLarge(
            f"problem is too large for the stdlib search "
            f"(more than {max_nodes} nodes); a real solver is needed"
        )

    def bound_key(i: int, score: float) -> tuple:
        counts = suffix_counts[i]
        return tuple(-(placed[k] + counts[k]) for k in range(n_levels)) + (
            round(score + suffix_min[i], 9),
        )

    def usable(option: Option) -> bool:
        pool_key = (option.site_id, option.pool_id)
        if pool_used[pool_key] + option.gpu_count > pool_total[pool_key]:
            return False
        room = site_room[option.site_id]
        committed = load[option.site_id]
        return all(
            option.facility_kw <= room - committed[h] for h in option.hours
        )

    def dfs(i: int, score: float) -> None:
        nonlocal best_key, best_choice, nodes
        key = bound_key(i, score)
        if best_key is not None and key >= best_key:
            return
        if i == n:
            best_key = key
            best_choice = list(chosen)
            return

        level = level_index[order[i].priority]
        for contrib, option in ranked[i]:
            if not usable(option):
                continue
            nodes += 1
            if nodes > max_nodes:
                raise too_large()
            pool_key = (option.site_id, option.pool_id)
            old_load = load[option.site_id]
            new_load = list(old_load)
            for h in option.hours:
                new_load[h] += option.facility_kw
            load[option.site_id] = new_load
            pool_used[pool_key] += option.gpu_count
            placed[level] += 1
            chosen[i] = option
            dfs(i + 1, score + contrib)
            chosen[i] = None
            placed[level] -= 1
            pool_used[pool_key] -= option.gpu_count
            load[option.site_id] = old_load

        nodes += 1
        if nodes > max_nodes:
            raise too_large()
        dfs(i + 1, score)

    try:
        dfs(0, 0.0)
    except RecursionError:
        raise too_large() from None

    assert best_choice is not None  # the all-unplaced dive always completes
    assignment = {
        w.workload_id: choice for w, choice in zip(order, best_choice)
    }
    objective = evaluate(assignment, workloads, options_by_workload, weights)
    return OptimalResult(assignment=assignment, objective=objective, nodes=nodes)


def greedy_assignment(
    fleet: Fleet,
    workloads: list[Workload],
    weights: dict | None = None,
) -> tuple[dict[str, Option | None], dict[str, list[Option]], Plan]:
    """Run the engine's greedy and express its result as Options.

    Returns ``(assignment, options_by_workload, plan)``. Each placement maps to
    the Option with the same ``(site_id, pool_id, start_hour)``; unplaced
    workloads map to None.
    """
    result = plan(fleet, workloads, weights)
    options_by_workload = {
        w.workload_id: options_for(w, fleet) for w in workloads
    }
    assignment: dict[str, Option | None] = {
        w.workload_id: None for w in workloads
    }
    for placement in result.placements:
        chosen = placement.chosen
        match = next(
            (
                o
                for o in options_by_workload[placement.workload_id]
                if (o.site_id, o.pool_id, o.start_hour)
                == (chosen.site_id, chosen.pool_id, chosen.start_hour)
            ),
            None,
        )
        if match is None:
            raise ValueError(
                f"{placement.workload_id}: greedy placement "
                f"{chosen.site_id}/{chosen.pool_id}@{chosen.start_hour} "
                f"has no matching option"
            )
        assignment[placement.workload_id] = match
    return assignment, options_by_workload, result


# ---------------------------------------------------------------------------
# gap report
# ---------------------------------------------------------------------------

@dataclass
class GapReport:
    """Greedy versus exact optimum under one shared objective."""

    greedy: Objective
    optimum: Objective
    same_work_placed: bool
    score_gap: float | None
    moved: list[tuple[str, str, str]]


def _label(option: Option | None) -> str:
    if option is None:
        return "unplaced"
    return f"{option.site_id}/{option.pool_id}@{option.start_hour}"


def compare(
    fleet: Fleet,
    workloads: list[Workload],
    weights: dict | None = None,
    max_nodes: int = 200_000,
) -> GapReport:
    """Measure the greedy against the exact optimum; never replaces greedy numbers.

    Raises `SearchTooLarge` when the exact search exceeds `max_nodes`.
    """
    weights = weights or DEFAULT_WEIGHTS
    greedy_assign, options_by_workload, _ = greedy_assignment(
        fleet, workloads, weights
    )
    greedy = evaluate(greedy_assign, workloads, options_by_workload, weights)
    optimal = solve(fleet, workloads, weights, max_nodes=max_nodes)
    optimum = optimal.objective

    same = greedy.placed_by_priority == optimum.placed_by_priority
    gap = greedy.score - optimum.score if same else None

    moved: list[tuple[str, str, str]] = []
    for w in sorted(workloads, key=lambda item: item.workload_id):
        g_label = _label(greedy_assign.get(w.workload_id))
        o_label = _label(optimal.assignment.get(w.workload_id))
        if g_label != o_label:
            moved.append((w.workload_id, g_label, o_label))

    return GapReport(
        greedy=greedy,
        optimum=optimum,
        same_work_placed=same,
        score_gap=gap,
        moved=moved,
    )


def _placed_text(placed: dict[int, int]) -> str:
    if not placed:
        return "none"
    return ", ".join(f"P{p} {placed[p]}" for p in sorted(placed))


def format_gap(report: GapReport) -> str:
    """Render the gap report as plain text."""
    g, o = report.greedy, report.optimum
    eps = 1e-9

    def row(label: str, body: str) -> str:
        return f"  {label.ljust(20)}{body}"

    if report.same_work_placed and report.score_gap is not None:
        gap_text = f"gap {report.score_gap:.4f}"
    else:
        gap_text = "gap n/a (different work placed)"

    lines = [
        "greedy vs exact optimum (same objective, same constraints)",
        f"  placed by priority  greedy {_placed_text(g.placed_by_priority)}"
        f"  optimum {_placed_text(o.placed_by_priority)}",
        row(
            "objective score",
            f"greedy {g.score:.4f}  optimum {o.score:.4f}  {gap_text}",
        ),
        row(
            "total cost",
            f"greedy ${g.total_cost_usd:,.0f}  optimum ${o.total_cost_usd:,.0f}",
        ),
        row(
            "total carbon",
            f"greedy {g.total_carbon_kg:,.0f} kg  "
            f"optimum {o.total_carbon_kg:,.0f} kg",
        ),
    ]

    worse = []
    if o.total_cost_usd > g.total_cost_usd + eps:
        worse.append("cost")
    if o.total_carbon_kg > g.total_carbon_kg + eps:
        worse.append("carbon")
    if worse:
        lines.append(f"  note: the optimum is worse on {' and '.join(worse)}")

    if report.moved:
        moved = "; ".join(
            f"{wid} {before} -> {after}" for wid, before, after in report.moved
        )
        lines.append(f"  moved: {moved}")
    else:
        lines.append("  moved: none")
    return "\n".join(lines)

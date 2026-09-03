"""Placement engine.

Design notes
------------
The scheduler is deliberately a *transparent greedy* rather than a black-box
solver. For each workload it enumerates every feasible (site, pool) candidate,
scores them on a normalised weighted objective, and keeps the full ranked list
so the explainer can say why the runner-up lost.

Greedy is not globally optimal. That is a real limitation and it is recorded in
every plan (`plan.notes`) rather than hidden. Swapping in a MILP over the same
Candidate list is the natural next step -- the objective and constraints below
are already written as pure functions of a candidate.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .models import AcceleratorPool, Fleet, Site, Workload

# Objective weights. Lower score is better; weights should sum to ~1.
DEFAULT_WEIGHTS = {"cost": 0.45, "carbon": 0.25, "runtime": 0.30}


@dataclass
class Candidate:
    site_id: str
    pool_id: str
    accelerator: str
    runtime_hours: float
    it_kw: float
    facility_kw: float
    energy_kwh: float
    cost_usd: float
    carbon_kg: float
    score: float = 0.0
    components: dict = field(default_factory=dict)


@dataclass
class Rejection:
    site_id: str
    pool_id: str
    reason: str


@dataclass
class Placement:
    workload_id: str
    workload_name: str
    chosen: Candidate
    runner_up: Candidate | None
    considered: int
    rejected: list[Rejection]


@dataclass
class Plan:
    placements: list[Placement] = field(default_factory=list)
    unplaced: list[tuple[str, list[Rejection]]] = field(default_factory=list)
    weights: dict = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    @property
    def total_cost(self) -> float:
        return sum(p.chosen.cost_usd for p in self.placements)

    @property
    def total_carbon_kg(self) -> float:
        return sum(p.chosen.carbon_kg for p in self.placements)

    @property
    def total_energy_kwh(self) -> float:
        return sum(p.chosen.energy_kwh for p in self.placements)

    @property
    def makespan_hours(self) -> float:
        return max((p.chosen.runtime_hours for p in self.placements), default=0.0)


# ---------------------------------------------------------------------------
# feasibility
# ---------------------------------------------------------------------------

def _infeasible_reason(
    w: Workload, site: Site, pool: AcceleratorPool
) -> str | None:
    if not site.online:
        return "site offline"
    if w.allowed_regions and site.region not in w.allowed_regions:
        return f"region {site.region} not in residency allowlist"
    if w.accelerator_allowlist and pool.accelerator not in w.accelerator_allowlist:
        return f"{pool.accelerator} not in accelerator allowlist"
    if pool.available < w.gpu_count:
        return f"needs {w.gpu_count} accelerators, {pool.available} free"
    if pool.memory_gb < w.min_memory_gb:
        return f"{pool.memory_gb:.0f}GB HBM < {w.min_memory_gb:.0f}GB required"

    facility_kw = site.facility_kw(pool.draw_kw(w.gpu_count))
    if facility_kw > site.headroom_kw:
        return (
            f"needs {facility_kw:.0f}kW, only {site.headroom_kw:.0f}kW headroom"
        )
    if w.deadline_hours is not None and w.runtime_hours(pool) > w.deadline_hours:
        return (
            f"runtime {w.runtime_hours(pool):.1f}h exceeds "
            f"{w.deadline_hours:.1f}h deadline"
        )
    return None


def _build_candidate(w: Workload, site: Site, pool: AcceleratorPool) -> Candidate:
    hours = w.runtime_hours(pool)
    it_kw = pool.draw_kw(w.gpu_count)
    facility_kw = site.facility_kw(it_kw)
    energy = facility_kw * hours
    return Candidate(
        site_id=site.site_id,
        pool_id=pool.pool_id,
        accelerator=pool.accelerator,
        runtime_hours=hours,
        it_kw=it_kw,
        facility_kw=facility_kw,
        energy_kwh=energy,
        cost_usd=energy * site.price_per_kwh,
        carbon_kg=energy * site.carbon_g_per_kwh / 1000.0,
    )


# ---------------------------------------------------------------------------
# scoring
# ---------------------------------------------------------------------------

def _normalise(values: list[float]) -> list[float]:
    lo, hi = min(values), max(values)
    if hi - lo < 1e-12:
        return [0.0] * len(values)
    return [(v - lo) / (hi - lo) for v in values]


def _score(candidates: list[Candidate], weights: dict) -> None:
    cost_n = _normalise([c.cost_usd for c in candidates])
    carbon_n = _normalise([c.carbon_kg for c in candidates])
    time_n = _normalise([c.runtime_hours for c in candidates])
    for c, cn, kn, tn in zip(candidates, cost_n, carbon_n, time_n):
        c.components = {
            "cost": weights["cost"] * cn,
            "carbon": weights["carbon"] * kn,
            "runtime": weights["runtime"] * tn,
        }
        c.score = sum(c.components.values())


# ---------------------------------------------------------------------------
# planning
# ---------------------------------------------------------------------------

def _order(workloads: list[Workload]) -> list[Workload]:
    """Highest priority first, then tightest deadline, then biggest job."""
    return sorted(
        workloads,
        key=lambda w: (
            w.priority,
            w.deadline_hours if w.deadline_hours is not None else 1e9,
            -w.gpu_count,
        ),
    )


def plan(
    fleet: Fleet,
    workloads: list[Workload],
    weights: dict | None = None,
) -> Plan:
    weights = weights or DEFAULT_WEIGHTS
    fleet.reset()
    result = Plan(weights=dict(weights))
    result.notes.append(
        "Greedy priority-ordered placement; not proven globally optimal."
    )

    for w in _order(workloads):
        candidates: list[Candidate] = []
        rejected: list[Rejection] = []

        for site in fleet.sites:
            for pool in site.pools:
                reason = _infeasible_reason(w, site, pool)
                if reason:
                    rejected.append(Rejection(site.site_id, pool.pool_id, reason))
                else:
                    candidates.append(_build_candidate(w, site, pool))

        if not candidates:
            result.unplaced.append((w.workload_id, rejected))
            continue

        _score(candidates, weights)
        candidates.sort(key=lambda c: (c.score, c.cost_usd))
        best = candidates[0]

        # commit resources
        site = fleet.site(best.site_id)
        site.pool(best.pool_id).available -= w.gpu_count
        site.committed_kw += best.facility_kw

        result.placements.append(
            Placement(
                workload_id=w.workload_id,
                workload_name=w.name,
                chosen=best,
                runner_up=candidates[1] if len(candidates) > 1 else None,
                considered=len(candidates),
                rejected=rejected,
            )
        )

    return result

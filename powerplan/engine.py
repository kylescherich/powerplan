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

import math
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
    deferred_for_capacity: bool = False
    start_hour: int = 0
    deferral_saved_usd: float = 0.0
    deferral_saved_kg: float = 0.0


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
        return max(
            (p.chosen.start_hour + p.chosen.runtime_hours for p in self.placements),
            default=0.0
        )


# ---------------------------------------------------------------------------
# time window
# ---------------------------------------------------------------------------

def _window_hours(start_hour: int, runtime_hours: float) -> list[int]:
    """Hour-of-day indices (0-23) a job occupies.

    The runtime is rounded up to whole hours, capped at 24 (a job longer than a
    day occupies every hour once), and indices wrap past midnight.
    """
    count = min(24, max(0, math.ceil(runtime_hours - 1e-9)))
    return [(int(start_hour) + i) % 24 for i in range(count)]


def _allowed_starts(w: Workload, runtime_hours: float) -> list[int]:
    """Start hours a workload may use, before looking at capacity.

    Non-interruptible jobs start at hour 0. Interruptible jobs may start at
    0..23, or 0..min(23, floor(deadline - runtime)) when they have a deadline.
    """
    if not w.interruptible:
        return [0]
    if w.deadline_hours is None:
        last = 23
    else:
        last = min(23, math.floor(w.deadline_hours - runtime_hours))
    return list(range(0, last + 1))


def _feasible_starts(
    w: Workload, site: Site, facility_kw: float, runtime_hours: float
) -> list[int]:
    """Allowed starts whose whole window has enough power headroom."""
    return [
        s
        for s in _allowed_starts(w, runtime_hours)
        if all(
            facility_kw <= site.headroom_kw_at(h)
            for h in _window_hours(s, runtime_hours)
        )
    ]


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
    runtime = w.runtime_hours(pool)
    # If the deadline leaves no allowed start, the deadline check below reports it.
    if _allowed_starts(w, runtime) and not _feasible_starts(
        w, site, facility_kw, runtime
    ):
        if not w.interruptible:
            tightest = min(
                site.headroom_kw_at(h) for h in _window_hours(0, runtime)
            )
            return f"needs {facility_kw:.0f}kW, only {tightest:.0f}kW headroom"
        return (
            f"needs {facility_kw:.0f}kW, no allowed start hour has that headroom"
        )
    if w.deadline_hours is not None and w.runtime_hours(pool) > w.deadline_hours:
        return (
            f"runtime {w.runtime_hours(pool):.1f}h exceeds "
            f"{w.deadline_hours:.1f}h deadline"
        )
    return None


def _build_candidate(
    w: Workload, site: Site, pool: AcceleratorPool, weights: dict
) -> Candidate:
    hours = w.runtime_hours(pool)
    it_kw = pool.draw_kw(w.gpu_count)
    facility_kw = site.facility_kw(it_kw)
    energy = facility_kw * hours

    feasible = _feasible_starts(w, site, facility_kw, hours)
    if not feasible:
        raise ValueError(
            f"{w.workload_id} has no feasible start on {site.site_id}/{pool.pool_id}"
        )
    # Hour 0 is allowed whenever any start is, so this means "hour 0 was full".
    deferred = 0 not in feasible
    
    # If no curves, use scalar pricing; start at the earliest feasible hour
    if site.price_curve is None and site.carbon_curve is None:
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
            deferred_for_capacity=deferred,
            start_hour=feasible[0],
            deferral_saved_usd=0.0,
            deferral_saved_kg=0.0,
        )
    
    # Time-integrated cost and carbon
    def integrate_window(start: float, duration: float) -> tuple[float, float]:
        """Integrate cost and carbon over a time window."""
        cost = 0.0
        carbon = 0.0
        h = start
        remaining = duration
        
        while remaining > 1e-9:
            chunk = min(1.0, remaining)
            price = site.price_at(h) if site.price_curve else site.price_per_kwh
            carbon_intensity = site.carbon_at(h) if site.carbon_curve else site.carbon_g_per_kwh
            
            cost += facility_kw * chunk * price
            carbon += facility_kw * chunk * carbon_intensity / 1000.0
            
            h += chunk
            remaining -= chunk
        
        return cost, carbon
    
    # Hour-0 values are the reference for the start-choice objective and for
    # deferral_saved_* (hour-0 value minus chosen value), even if hour 0 is full.
    
    cost_at_zero, carbon_at_zero = integrate_window(0.0, hours)
    
    # Compute objective using ratios to hour-0 values
    def compute_objective(cost: float, carbon: float) -> float:
        cost_ratio = cost / cost_at_zero if cost_at_zero > 0 else 0.0
        carbon_ratio = carbon / carbon_at_zero if carbon_at_zero > 0 else 0.0
        return weights["cost"] * cost_ratio + weights["carbon"] * carbon_ratio
    
    # Start from the earliest feasible start; later starts must be strictly
    # better, so ties go to the earliest.
    best_start = feasible[0]
    best_cost, best_carbon = integrate_window(float(best_start), hours)
    best_objective = compute_objective(best_cost, best_carbon)
    
    # Only feasible starts are considered: allowed by the deadline rule and with
    # enough power headroom in every hour of the window.
    
    for start in feasible[1:]:
        cost, carbon = integrate_window(float(start), hours)
        objective = compute_objective(cost, carbon)
        
        if objective < best_objective:
            best_objective = objective
            best_start = start
            best_cost = cost
            best_carbon = carbon
    
    return Candidate(
        site_id=site.site_id,
        pool_id=pool.pool_id,
        accelerator=pool.accelerator,
        runtime_hours=hours,
        it_kw=it_kw,
        facility_kw=facility_kw,
        energy_kwh=energy,
        cost_usd=best_cost,
        carbon_kg=best_carbon,
        deferred_for_capacity=deferred,
        start_hour=best_start,
        deferral_saved_usd=cost_at_zero - best_cost,
        deferral_saved_kg=carbon_at_zero - best_carbon,
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
    result.notes.append(
        "Power headroom is checked per hour of each job's window (time-slicing of capacity over the 24-hour window); greedy order decides who gets contested hours."
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
                    candidates.append(_build_candidate(w, site, pool, weights))

        if not candidates:
            result.unplaced.append((w.workload_id, rejected))
            continue

        _score(candidates, weights)
        candidates.sort(key=lambda c: (c.score, c.cost_usd))
        best = candidates[0]

        # commit resources
        site = fleet.site(best.site_id)
        site.pool(best.pool_id).available -= w.gpu_count
        for hour in _window_hours(best.start_hour, best.runtime_hours):
            site.committed_kw_by_hour[hour] += best.facility_kw
        site.committed_kw = max(site.committed_kw_by_hour)

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

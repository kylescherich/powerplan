"""Domain model for the power-aware compute scheduler.

Everything is a plain dataclass so the whole model is serialisable to JSON and
easy to diff in an audit log. No external dependencies.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any


@dataclass
class AcceleratorPool:
    """A homogeneous block of accelerators inside one site."""

    pool_id: str
    accelerator: str          # e.g. "H100-SXM"
    total: int                # physically installed
    available: int            # not currently committed
    tdp_watts: float          # per-accelerator design power
    memory_gb: float          # HBM per accelerator
    perf: float = 1.0         # throughput vs. the reference accelerator (perf=1.0)
    utilization: float = 0.85  # fraction of TDP actually drawn under load

    def draw_kw(self, count: int) -> float:
        """IT-side power draw, in kW, for `count` accelerators under load."""
        return count * self.tdp_watts * self.utilization / 1000.0


@dataclass
class Site:
    """A datacenter / colo / edge facility with a hard electrical ceiling."""

    site_id: str
    region: str
    power_capacity_kw: float      # utility + switchgear ceiling
    baseline_load_kw: float       # cooling, networking, already-running jobs
    pue: float                    # facility power / IT power
    price_per_kwh: float          # blended $/kWh for the planning window
    carbon_g_per_kwh: float       # grid intensity for the planning window
    pools: list[AcceleratorPool] = field(default_factory=list)
    online: bool = True
    price_curve: list[float] | None = None
    carbon_curve: list[float] | None = None

    # --- mutable planning state -------------------------------------------
    committed_kw: float = 0.0

    def __post_init__(self):
        """Validate curve fields if present."""
        if self.price_curve is not None:
            if len(self.price_curve) != 24:
                raise ValueError(f"{self.site_id}: price_curve must have exactly 24 values, got {len(self.price_curve)}")
            if any(v < 0 for v in self.price_curve):
                raise ValueError(f"{self.site_id}: price_curve values must be non-negative")
        
        if self.carbon_curve is not None:
            if len(self.carbon_curve) != 24:
                raise ValueError(f"{self.site_id}: carbon_curve must have exactly 24 values, got {len(self.carbon_curve)}")
            if any(v < 0 for v in self.carbon_curve):
                raise ValueError(f"{self.site_id}: carbon_curve values must be non-negative")

    @property
    def headroom_kw(self) -> float:
        """Facility-side power still available for new work."""
        if not self.online:
            return 0.0
        return self.power_capacity_kw - self.baseline_load_kw - self.committed_kw

    def facility_kw(self, it_kw: float) -> float:
        return it_kw * self.pue

    def price_at(self, hour: float) -> float:
        """Return price at the given hour (uses curve if available, else scalar)."""
        if self.price_curve is None:
            return self.price_per_kwh
        index = int(hour) % 24
        return self.price_curve[index]

    def carbon_at(self, hour: float) -> float:
        """Return carbon intensity at the given hour (uses curve if available, else scalar)."""
        if self.carbon_curve is None:
            return self.carbon_g_per_kwh
        index = int(hour) % 24
        return self.carbon_curve[index]

    def pool(self, pool_id: str) -> AcceleratorPool:
        for p in self.pools:
            if p.pool_id == pool_id:
                return p
        raise KeyError(pool_id)


@dataclass
class Workload:
    """A job to be placed.

    `ref_hours` is wall-clock runtime on a reference accelerator (perf == 1.0)
    at the requested `gpu_count`. Actual runtime scales by the pool's perf.
    """

    workload_id: str
    name: str
    gpu_count: int
    ref_hours: float
    min_memory_gb: float = 0.0
    priority: int = 3                     # 1 = highest
    deadline_hours: float | None = None   # must finish within this window
    allowed_regions: list[str] = field(default_factory=list)  # empty = anywhere
    accelerator_allowlist: list[str] = field(default_factory=list)
    interruptible: bool = False

    def runtime_hours(self, pool: AcceleratorPool) -> float:
        return self.ref_hours / max(pool.perf, 1e-9)


@dataclass
class Fleet:
    sites: list[Site]

    def site(self, site_id: str) -> Site:
        for s in self.sites:
            if s.site_id == site_id:
                return s
        raise KeyError(site_id)

    def reset(self) -> None:
        for s in self.sites:
            s.committed_kw = 0.0
            for p in s.pools:
                p.available = p.total


# ---------------------------------------------------------------------------
# (de)serialisation
# ---------------------------------------------------------------------------

def load_fleet(path: str | Path) -> Fleet:
    raw = json.loads(Path(path).read_text())
    sites = []
    for s in raw["sites"]:
        pools = [AcceleratorPool(**p) for p in s.pop("pools", [])]
        sites.append(Site(pools=pools, **s))
    return Fleet(sites=sites)


def load_workloads(path: str | Path) -> list[Workload]:
    raw = json.loads(Path(path).read_text())
    return [Workload(**w) for w in raw["workloads"]]


def to_dict(obj: Any) -> dict:
    return asdict(obj)

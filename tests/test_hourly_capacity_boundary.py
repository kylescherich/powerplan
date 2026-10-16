"""Exact-fit boundary for per-hour power headroom.

Fixture: 1 kW per GPU, one site with 100 kW capacity, no baseline load.
A (80 kW, 5 h) and B (20 kW, 3 h) fill hours 0-2 to exactly the ceiling;
C (21 kW, 1 h, interruptible) cannot fit until A has finished.
"""

from powerplan.engine import plan
from powerplan.models import AcceleratorPool, Fleet, Site, Workload


def make_fleet() -> Fleet:
    pool = AcceleratorPool(
        pool_id="p",
        accelerator="X",
        total=200,
        available=200,
        tdp_watts=1000,
        memory_gb=80,
        perf=1.0,
        utilization=1.0,
    )
    site = Site(
        site_id="S",
        region="r",
        power_capacity_kw=100,
        baseline_load_kw=0,
        pue=1.0,
        price_per_kwh=0.10,
        carbon_g_per_kwh=100,
        pools=[pool],
    )
    return Fleet(sites=[site])


def make_job(workload_id, gpus, hours, priority, interruptible=False) -> Workload:
    return Workload(
        workload_id=workload_id,
        name=workload_id,
        gpu_count=gpus,
        ref_hours=hours,
        priority=priority,
        interruptible=interruptible,
    )


def run_plan():
    fleet = make_fleet()
    workloads = [
        make_job("A", 80, 5, priority=1),
        make_job("B", 20, 3, priority=2),
        make_job("C", 21, 1, priority=3, interruptible=True),
    ]
    result = plan(fleet, workloads)
    assert len(result.placements) >= 1
    return fleet, result


def placed(result, workload_id):
    for p in result.placements:
        if p.workload_id == workload_id:
            return p
    raise AssertionError(f"{workload_id} was not placed")


def test_exact_fit_is_allowed():
    _, result = run_plan()
    assert placed(result, "B").chosen.start_hour == 0
    assert result.unplaced == []


def test_committed_kw_by_hour_after_exact_fit():
    fleet, result = run_plan()
    site = fleet.site("S")
    expected = [100.0] * 3 + [80.0] * 2 + [21.0] + [0.0] * 18
    assert len(expected) == 24
    assert site.committed_kw_by_hour == expected
    assert site.committed_kw == 100


def test_c_is_deferred_for_capacity_to_hour_5():
    _, result = run_plan()
    c = placed(result, "C").chosen
    assert c.start_hour == 5
    assert c.deferred_for_capacity is True

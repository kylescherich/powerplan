"""Exact search where site power, not accelerator count, is the binding limit."""

import pytest

from powerplan.models import AcceleratorPool, Fleet, Site, Workload
from powerplan.optimal import compare, solve

WEIGHTS = {"cost": 1.0, "carbon": 0.0, "runtime": 0.0}
EPS = 1e-9


def make_site(site_id, region, price, power_capacity_kw) -> Site:
    return Site(
        site_id=site_id,
        region=region,
        power_capacity_kw=power_capacity_kw,
        baseline_load_kw=0.0,
        pue=1.0,
        price_per_kwh=price,
        carbon_g_per_kwh=100.0,
        pools=[
            AcceleratorPool(
                pool_id="p" + site_id,
                accelerator="X",
                total=200,
                available=200,
                tdp_watts=1000.0,
                memory_gb=80.0,
                perf=1.0,
                utilization=1.0,
            )
        ],
    )


def make_fleet() -> Fleet:
    return Fleet(
        sites=[
            make_site("S1", "r1", 0.10, 100.0),
            make_site("S2", "r2", 0.30, 1000.0),
        ]
    )


def make_job(workload_id, priority, interruptible=False) -> Workload:
    return Workload(
        workload_id=workload_id,
        name=workload_id,
        gpu_count=60,
        ref_hours=2.0,
        priority=priority,
        interruptible=interruptible,
    )


def fixture_w(b_interruptible=False):
    fleet = make_fleet()
    workloads = [
        make_job("A", 1),
        make_job("B", 2, interruptible=b_interruptible),
    ]
    return fleet, workloads


def test_power_decides_which_site_each_workload_gets():
    fleet, workloads = fixture_w()
    result = solve(fleet, workloads, WEIGHTS)

    a = result.assignment["A"]
    b = result.assignment["B"]
    assert (a.site_id, a.start_hour) == ("S1", 0)
    assert (b.site_id, b.start_hour) == ("S2", 0)
    assert result.objective.placed_by_priority == {1: 1, 2: 1}
    assert result.objective.score == pytest.approx(2.0, abs=EPS)
    assert result.objective.total_cost_usd == pytest.approx(48.0, abs=EPS)


def test_power_is_checked_per_hour_not_per_window():
    fleet, workloads = fixture_w(b_interruptible=True)
    result = solve(fleet, workloads, WEIGHTS)

    a = result.assignment["A"]
    b = result.assignment["B"]
    assert (a.site_id, a.start_hour) == ("S1", 0)
    # Hours 0-1 are full; starts 2..22 tie on score and the earliest is kept.
    assert (b.site_id, b.start_hour) == ("S1", 2)
    assert result.objective.placed_by_priority == {1: 1, 2: 1}
    assert result.objective.score == pytest.approx(1.0, abs=EPS)
    assert result.objective.total_cost_usd == pytest.approx(24.0, abs=EPS)


def test_compare_finds_greedy_already_optimal_when_power_binds():
    fleet, workloads = fixture_w()
    report = compare(fleet, workloads, WEIGHTS)

    assert report.same_work_placed is True
    assert report.score_gap == pytest.approx(0.0, abs=EPS)
    assert report.moved == []

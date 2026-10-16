"""Step 2: the engine commits facility power per hour of a job's window."""

import pytest

from powerplan.engine import plan
from powerplan.models import AcceleratorPool, Fleet, Site, Workload


def make_fleet(price_curve=None) -> Fleet:
    """One site where 1 GPU draws exactly 1 kW of facility power."""
    pool = AcceleratorPool(
        pool_id="pool-a",
        accelerator="TEST-GPU",
        total=200,
        available=200,
        tdp_watts=1000.0,
        memory_gb=80.0,
        perf=1.0,
        utilization=1.0,
    )
    site = Site(
        site_id="site-a",
        region="test-region",
        power_capacity_kw=10000.0,
        baseline_load_kw=0.0,
        pue=1.0,
        price_per_kwh=0.2,
        carbon_g_per_kwh=300.0,
        pools=[pool],
        price_curve=price_curve,
    )
    return Fleet(sites=[site])


def make_job(workload_id, gpus, hours, interruptible=False, priority=3) -> Workload:
    return Workload(
        workload_id=workload_id,
        name=workload_id,
        gpu_count=gpus,
        ref_hours=hours,
        priority=priority,
        interruptible=interruptible,
    )


def expected(values_by_hour: dict[int, float]) -> list[float]:
    return [values_by_hour.get(h, 0.0) for h in range(24)]


def test_a_five_hour_job_fills_hours_0_to_4():
    fleet = make_fleet()
    result = plan(fleet, [make_job("A", 80, 5.0)])
    site = fleet.sites[0]
    assert result.placements[0].chosen.start_hour == 0
    assert site.committed_kw_by_hour == pytest.approx(
        expected({h: 80.0 for h in range(5)})
    )
    assert site.committed_kw == pytest.approx(80.0)


def test_h_fractional_job_rounds_window_up():
    fleet = make_fleet()
    plan(fleet, [make_job("H", 10, 1.5)])
    site = fleet.sites[0]
    assert site.committed_kw_by_hour == pytest.approx(
        expected({0: 10.0, 1: 10.0})
    )


def test_l_long_job_fills_all_24_hours_once():
    fleet = make_fleet()
    plan(fleet, [make_job("L", 10, 30.0)])
    site = fleet.sites[0]
    assert site.committed_kw_by_hour == pytest.approx([10.0] * 24)
    assert site.committed_kw == pytest.approx(10.0)


def test_window_wraps_past_midnight():
    curve = [0.2] * 24
    for h in (22, 23, 0, 1):
        curve[h] = 0.01
    fleet = make_fleet(price_curve=curve)
    result = plan(fleet, [make_job("A", 80, 4.0, interruptible=True)])
    site = fleet.sites[0]
    assert result.placements[0].chosen.start_hour == 22
    assert site.committed_kw_by_hour == pytest.approx(
        expected({22: 80.0, 23: 80.0, 0: 80.0, 1: 80.0})
    )


def test_overlapping_jobs_add_up():
    fleet = make_fleet()
    result = plan(
        fleet,
        [
            make_job("P", 10, 2.0, priority=1),
            make_job("Q", 10, 3.0, priority=2),
        ],
    )
    site = fleet.sites[0]
    assert [p.chosen.start_hour for p in result.placements] == [0, 0]
    assert site.committed_kw_by_hour == pytest.approx(
        expected({0: 20.0, 1: 20.0, 2: 10.0})
    )
    assert site.committed_kw == pytest.approx(20.0)

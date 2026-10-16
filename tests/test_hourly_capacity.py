"""Per-hour power headroom: feasible starts, rejection, flag and plan note."""

import dataclasses
from pathlib import Path

from powerplan.engine import Candidate, plan
from powerplan.models import (
    AcceleratorPool,
    Fleet,
    Site,
    Workload,
    load_fleet,
    load_workloads,
)

DATA = Path(__file__).resolve().parent.parent / "data"

NOTE = (
    "Power headroom is checked per hour of each job's window "
    "(time-slicing of capacity over the 24-hour window); "
    "greedy order decides who gets contested hours."
)
OLD_NOTE = (
    "Power headroom checked at placement time; "
    "no explicit time-slicing of capacity."
)


def make_fleet(price_curve=None) -> Fleet:
    """One site, 100 kW usable, 1 kW per GPU."""
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
        price_curve=price_curve,
    )
    return Fleet(sites=[site])


def make_job(workload_id, gpus, hours, priority=3, interruptible=False) -> Workload:
    return Workload(
        workload_id=workload_id,
        name=workload_id,
        gpu_count=gpus,
        ref_hours=hours,
        priority=priority,
        interruptible=interruptible,
    )


def placed(result, workload_id):
    matches = [p for p in result.placements if p.workload_id == workload_id]
    assert matches, f"{workload_id} was not placed"
    return matches[0].chosen


def unplaced_reasons(result, workload_id) -> list[str]:
    for wid, rejections in result.unplaced:
        if wid == workload_id:
            return [r.reason for r in rejections]
    raise AssertionError(f"{workload_id} was not reported as unplaced")


def dip_curve() -> list[float]:
    curve = [0.2] * 24
    for hour in (22, 23, 0, 1):
        curve[hour] = 0.01
    return curve


def test_contention_interruptible_job_waits():
    fleet = make_fleet()
    a = make_job("A", 80, 5, priority=1)
    b = make_job("B", 80, 3, priority=2, interruptible=True)
    result = plan(fleet, [a, b])

    assert len(result.placements) >= 1
    assert placed(result, "A").start_hour == 0
    chosen_b = placed(result, "B")
    assert chosen_b.start_hour == 5
    assert chosen_b.deferred_for_capacity is True

    site = fleet.site("S")
    assert site.committed_kw_by_hour == [80.0] * 8 + [0.0] * 16
    assert site.committed_kw == 80.0


def test_contention_non_interruptible_job_is_rejected():
    fleet = make_fleet()
    a = make_job("A", 80, 5, priority=1)
    b = make_job("B", 80, 3, priority=2)
    result = plan(fleet, [a, b])

    assert len(result.placements) >= 1
    assert placed(result, "A").start_hour == 0
    assert unplaced_reasons(result, "B") == ["needs 80kW, only 20kW headroom"]


def test_job_longer_than_a_day_fills_every_hour():
    fleet = make_fleet()
    long_job = make_job("L", 80, 30, priority=1)
    c = make_job("C", 80, 1, priority=2, interruptible=True)
    result = plan(fleet, [long_job, c])

    assert len(result.placements) >= 1
    assert placed(result, "L").start_hour == 0
    assert unplaced_reasons(result, "C") == [
        "needs 80kW, no allowed start hour has that headroom"
    ]


def test_windows_wrap_past_midnight():
    fleet = make_fleet(price_curve=dip_curve())
    a = make_job("A", 80, 4, priority=1, interruptible=True)
    b = make_job("B", 80, 2, priority=2)
    result = plan(fleet, [a, b])

    assert len(result.placements) >= 1
    chosen_a = placed(result, "A")
    assert chosen_a.start_hour == 22
    assert chosen_a.deferred_for_capacity is False

    expected = [0.0] * 24
    for hour in (22, 23, 0, 1):
        expected[hour] = 80.0
    assert fleet.site("S").committed_kw_by_hour == expected
    assert unplaced_reasons(result, "B") == ["needs 80kW, only 20kW headroom"]


def test_zero_hour_zero_cost_does_not_error():
    curve = [0.1] * 24
    curve[0] = 0.0
    fleet = make_fleet(price_curve=curve)
    z = make_job("Z", 1, 1, interruptible=True)
    weights = {"cost": 1.0, "carbon": 0.0, "runtime": 0.0}
    result = plan(fleet, [z], weights)

    assert len(result.placements) >= 1
    chosen = placed(result, "Z")
    assert chosen.start_hour == 0
    assert chosen.deferred_for_capacity is False


def test_real_data_has_no_regression():
    fleet = load_fleet(DATA / "fleet.json")
    workloads = load_workloads(DATA / "workloads.json")
    result = plan(fleet, workloads)

    assert len(result.placements) >= 1
    assert result.unplaced == []

    starts = {p.workload_id: p.chosen.start_hour for p in result.placements}
    assert starts["W-003"] == 10
    assert starts["W-005"] == 8
    for workload_id, start in starts.items():
        if workload_id not in ("W-003", "W-005"):
            assert start == 0, workload_id

    for site in fleet.sites:
        limit = site.power_capacity_kw - site.baseline_load_kw
        for hour, committed in enumerate(site.committed_kw_by_hour):
            assert committed <= limit + 1e-6, (site.site_id, hour)


def test_plan_note_is_the_exact_sentence():
    fleet = make_fleet()
    result = plan(fleet, [make_job("A", 10, 1)])

    assert len(result.placements) >= 1
    assert NOTE in result.notes
    assert OLD_NOTE not in result.notes


def test_deferred_for_capacity_field_position():
    names = [f.name for f in dataclasses.fields(Candidate)]
    components = names.index("components")
    flag = names.index("deferred_for_capacity")
    start = names.index("start_hour")
    assert components < flag < start
    assert flag == components + 1
    assert start == flag + 1
    assert names[-3:] == ["start_hour", "deferral_saved_usd", "deferral_saved_kg"]

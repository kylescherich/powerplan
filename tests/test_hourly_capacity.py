"""Per-hour capacity: feasible starts, rejection reasons, deferral flag, notes."""

import dataclasses
from pathlib import Path

import pytest

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

NEW_NOTE = (
    "Power headroom checked per hour of the day; "
    "interruptible jobs may start later to find capacity."
)
OLD_NOTE = (
    "Power headroom checked at placement time; "
    "no explicit time-slicing of capacity."
)


def make_fleet(
    price_curve=None, capacity_kw=150.0, baseline_kw=50.0
) -> Fleet:
    """One site; 1 kW facility draw per GPU; headroom = capacity - baseline."""
    pool = AcceleratorPool(
        pool_id="p1",
        accelerator="H100-SXM",
        total=400,
        available=400,
        tdp_watts=1000.0,
        memory_gb=80.0,
        perf=1.0,
        utilization=1.0,
    )
    site = Site(
        site_id="S1",
        region="us-central",
        power_capacity_kw=capacity_kw,
        baseline_load_kw=baseline_kw,
        pue=1.0,
        price_per_kwh=0.1,
        carbon_g_per_kwh=100.0,
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


def placed(result):
    return {p.workload_id: p for p in result.placements}


def unplaced_reason(result, workload_id):
    for wid, rejections in result.unplaced:
        if wid == workload_id:
            return rejections[0].reason
    raise AssertionError(f"{workload_id} was not unplaced")


def test_contention_interruptible_waits():
    fleet = make_fleet()
    a = make_job("A", 80, 5, priority=1)
    b = make_job("B", 80, 3, priority=2, interruptible=True)
    result = plan(fleet, [a, b])

    by_id = placed(result)
    assert by_id["A"].chosen.start_hour == 0
    assert by_id["A"].chosen.deferred_for_capacity is False
    assert by_id["B"].chosen.start_hour == 5
    assert by_id["B"].chosen.deferred_for_capacity is True

    site = fleet.sites[0]
    assert site.committed_kw_by_hour[0:8] == pytest.approx([80.0] * 8)
    assert site.committed_kw_by_hour[8:24] == pytest.approx([0.0] * 16)
    assert site.committed_kw == pytest.approx(80.0)


def test_contention_non_interruptible_is_rejected():
    fleet = make_fleet()
    a = make_job("A", 80, 5, priority=1)
    b = make_job("B", 80, 3, priority=2)
    result = plan(fleet, [a, b])

    assert [p.workload_id for p in result.placements] == ["A"]
    assert unplaced_reason(result, "B") == "needs 80kW, only 20kW headroom"


def test_long_job_fills_every_hour():
    fleet = make_fleet()
    long_job = make_job("L", 80, 30, priority=1)
    c = make_job("C", 80, 1, priority=2, interruptible=True)
    result = plan(fleet, [long_job, c])

    by_id = placed(result)
    assert by_id["L"].chosen.start_hour == 0
    assert "C" not in by_id
    assert (
        unplaced_reason(result, "C")
        == "needs 80kW, no allowed start hour has that headroom"
    )
    assert fleet.sites[0].committed_kw_by_hour == pytest.approx([80.0] * 24)


def test_windows_wrap_past_midnight():
    curve = [0.2] * 24
    for hour in (22, 23, 0, 1):
        curve[hour] = 0.01
    fleet = make_fleet(price_curve=curve)
    a = make_job("A", 80, 4, priority=1, interruptible=True)
    b = make_job("B", 80, 2, priority=2)
    result = plan(fleet, [a, b])

    by_id = placed(result)
    assert by_id["A"].chosen.start_hour == 22

    expected = [0.0] * 24
    for hour in (22, 23, 0, 1):
        expected[hour] = 80.0
    assert fleet.sites[0].committed_kw_by_hour == pytest.approx(expected)

    assert "B" not in by_id
    assert unplaced_reason(result, "B") == "needs 80kW, only 20kW headroom"


def test_zero_baseline_and_zero_cost_hour():
    curve = [0.1] * 24
    curve[0] = 0.0
    fleet = make_fleet(price_curve=curve, capacity_kw=100.0, baseline_kw=0.0)
    z = make_job("Z", 1, 1, interruptible=True)
    weights = {"cost": 1.0, "carbon": 0.0, "runtime": 0.0}
    result = plan(fleet, [z], weights)

    by_id = placed(result)
    assert not result.unplaced
    assert by_id["Z"].chosen.start_hour == 0
    assert by_id["Z"].chosen.deferred_for_capacity is False


def test_real_data_has_no_regression():
    fleet = load_fleet(DATA / "fleet.json")
    workloads = load_workloads(DATA / "workloads.json")
    result = plan(fleet, workloads)

    assert result.unplaced == []
    starts = {p.workload_id: p.chosen.start_hour for p in result.placements}
    assert starts["W-003"] == 10
    assert starts["W-005"] == 8
    for wid, start in starts.items():
        if wid not in ("W-003", "W-005"):
            assert start == 0, wid

    for site in fleet.sites:
        limit = site.power_capacity_kw - site.baseline_load_kw
        for hour, committed in enumerate(site.committed_kw_by_hour):
            assert committed <= limit + 1e-6, (site.site_id, hour)


def test_notes_have_new_sentence_and_not_the_old_one():
    result = plan(make_fleet(), [])
    assert NEW_NOTE in result.notes
    assert OLD_NOTE not in result.notes


def test_deferred_for_capacity_field_order():
    names = [f.name for f in dataclasses.fields(Candidate)]
    assert "deferred_for_capacity" in names
    assert names.index("components") < names.index("deferred_for_capacity")
    assert names.index("deferred_for_capacity") < names.index("start_hour")

"""Explanation of capacity-forced starts, plus doc checks."""

from pathlib import Path

from powerplan.engine import plan
from powerplan.explain import explain
from powerplan.models import AcceleratorPool, Fleet, Site, Workload

ROOT = Path(__file__).resolve().parent.parent


def make_fleet(price_curve=None) -> Fleet:
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


def make_job(workload_id, gpus, hours, priority, interruptible=False) -> Workload:
    return Workload(
        workload_id=workload_id,
        name=f"job-{workload_id.lower()}",
        gpu_count=gpus,
        ref_hours=hours,
        priority=priority,
        interruptible=interruptible,
    )


def boundary_plan():
    jobs = [
        make_job("A", 80, 5, 1),
        make_job("B", 20, 3, 2),
        make_job("C", 21, 1, 3, interruptible=True),
    ]
    result = plan(make_fleet(), jobs)
    assert len(result.placements) >= 1
    return result


def placed(result, workload_id):
    return next(p for p in result.placements if p.workload_id == workload_id)


def test_capacity_deferred_explanation_has_no_saving_claim():
    placement = placed(boundary_plan(), "C")
    assert placement.chosen.deferred_for_capacity is True
    text = explain(placement)
    assert "hour 0 had no power headroom" in text
    assert "  starts at hour 5 (UTC); hour 0 had no power headroom" in text.split("\n")
    assert "saved" not in text
    assert "emits" not in text


def test_price_deferral_still_reports_saving():
    curve = [0.10] * 24
    curve[5] = 0.01
    curve[6] = 0.01
    result = plan(make_fleet(price_curve=curve), [make_job("P", 2, 2, 3, True)])
    assert len(result.placements) >= 1
    placement = placed(result, "P")
    assert placement.chosen.start_hour > 0
    assert placement.chosen.deferred_for_capacity is False
    text = explain(placement)
    assert "saved" in text
    assert "hour 0 had no power headroom" not in text


def test_placement_at_hour_zero_has_no_start_hour_line():
    placement = placed(boundary_plan(), "A")
    assert placement.chosen.start_hour == 0
    assert "starts at hour" not in explain(placement)


def test_readme_mentions_per_hour_headroom():
    assert "per hour" in (ROOT / "README.md").read_text()


def test_handoff_mentions_time_indexed():
    assert "time-indexed" in (ROOT / "HANDOFF.md").read_text()

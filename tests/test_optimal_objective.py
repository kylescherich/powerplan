from pathlib import Path

import pytest

from powerplan.engine import plan
from powerplan.models import (
    AcceleratorPool,
    Fleet,
    Site,
    Workload,
    load_fleet,
    load_workloads,
)
from powerplan.optimal import Objective, Option, evaluate, options_for

DATA = Path(__file__).resolve().parent.parent / "data"
COST_ONLY = {"cost": 1.0, "carbon": 0.0, "runtime": 0.0}


def make_site(site_id, region, price, memory_gb=80.0) -> Site:
    pool = AcceleratorPool(
        pool_id="p" + site_id,
        accelerator="X",
        total=100,
        available=100,
        tdp_watts=1000,
        memory_gb=memory_gb,
        perf=1.0,
        utilization=1.0,
    )
    return Site(
        site_id=site_id,
        region=region,
        power_capacity_kw=1000,
        baseline_load_kw=0,
        pue=1.0,
        price_per_kwh=price,
        carbon_g_per_kwh=100,
        pools=[pool],
    )


def make_job(workload_id, priority, **kwargs) -> Workload:
    return Workload(
        workload_id=workload_id,
        name=workload_id,
        gpu_count=80,
        ref_hours=1.0,
        priority=priority,
        **kwargs,
    )


def fixture_x():
    fleet = Fleet(
        sites=[
            make_site("S1", "r1", 0.05),
            make_site("S2", "r2", 0.20, memory_gb=40.0),
        ]
    )
    workloads = [make_job("A", 1), make_job("B", 2, min_memory_gb=80)]
    return fleet, workloads


def fixture_y():
    fleet = Fleet(
        sites=[
            make_site("S1", "r1", 0.10),
            make_site("S2", "r2", 0.11),
            make_site("S3", "r3", 0.50),
        ]
    )
    workloads = [
        make_job("A", 1, allowed_regions=["r1", "r2"]),
        make_job("B", 2, allowed_regions=["r1", "r3"]),
    ]
    return fleet, workloads


def options_map(fleet, workloads):
    fleet.reset()
    return {w.workload_id: options_for(w, fleet) for w in workloads}


def pick(options, site_id, start_hour=0):
    return next(
        o for o in options if o.site_id == site_id and o.start_hour == start_hour
    )


def test_real_data_option_counts():
    fleet = load_fleet(DATA / "fleet.json")
    workloads = load_workloads(DATA / "workloads.json")
    counts = {
        k: len(v) for k, v in options_map(fleet, workloads).items()
    }
    assert counts == {
        "W-001": 2,
        "W-002": 1,
        "W-003": 144,
        "W-004": 1,
        "W-005": 144,
        "W-006": 5,
    }


def test_options_are_frozen_with_window_hours():
    fleet, workloads = fixture_y()
    opts = options_map(fleet, workloads)["A"]
    assert isinstance(opts[0], Option)
    assert opts[0].hours == (0,)
    with pytest.raises(Exception):
        opts[0].cost_usd = 0.0


def test_matching_option_equals_engine_chosen_on_real_data():
    fleet = load_fleet(DATA / "fleet.json")
    workloads = load_workloads(DATA / "workloads.json")
    result = plan(fleet, workloads)
    assert result.placements
    by_workload = options_map(fleet, workloads)
    for placement in result.placements:
        chosen = placement.chosen
        matches = [
            o
            for o in by_workload[placement.workload_id]
            if (o.site_id, o.pool_id, o.start_hour)
            == (chosen.site_id, chosen.pool_id, chosen.start_hour)
        ]
        assert len(matches) == 1
        assert matches[0].cost_usd == pytest.approx(chosen.cost_usd, abs=1e-9)
        assert matches[0].carbon_kg == pytest.approx(chosen.carbon_kg, abs=1e-9)


def test_evaluate_fixture_y():
    fleet, workloads = fixture_y()
    opts = options_map(fleet, workloads)

    greedy = evaluate(
        {"A": pick(opts["A"], "S1"), "B": pick(opts["B"], "S3")},
        workloads,
        opts,
        COST_ONLY,
    )
    assert isinstance(greedy, Objective)
    assert greedy.placed_by_priority == {1: 1, 2: 1}
    assert greedy.score == pytest.approx(3.0)
    assert greedy.total_cost_usd == pytest.approx(48.0)

    better = evaluate(
        {"A": pick(opts["A"], "S2"), "B": pick(opts["B"], "S1")},
        workloads,
        opts,
        COST_ONLY,
    )
    assert better.score == pytest.approx(1.05)
    assert better.total_cost_usd == pytest.approx(16.8)


def test_evaluate_fixture_x_unplaced_workload():
    fleet, workloads = fixture_x()
    opts = options_map(fleet, workloads)
    result = evaluate(
        {"A": pick(opts["A"], "S1"), "B": None}, workloads, opts, COST_ONLY
    )
    assert result.placed_by_priority == {1: 1}
    assert result.score == pytest.approx(0.5)
    assert result.total_cost_usd == pytest.approx(4.0)

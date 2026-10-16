"""Exact search: fixtures, real data, size limit, brute-force cross-check."""

import itertools
from pathlib import Path

import pytest

from powerplan.models import (
    AcceleratorPool,
    Fleet,
    Site,
    Workload,
    load_fleet,
    load_workloads,
)
from powerplan.optimal import (
    SearchTooLarge,
    evaluate,
    greedy_assignment,
    options_for,
    solve,
)

DATA = Path(__file__).resolve().parents[1] / "data"
WEIGHTS = {"cost": 1.0, "carbon": 0.0, "runtime": 0.0}


def make_site(site_id, region, price, memory_gb=80.0) -> Site:
    return Site(
        site_id=site_id,
        region=region,
        power_capacity_kw=1000,
        baseline_load_kw=0,
        pue=1.0,
        price_per_kwh=price,
        carbon_g_per_kwh=100,
        pools=[
            AcceleratorPool(
                pool_id="p" + site_id,
                accelerator="X",
                total=100,
                available=100,
                tdp_watts=1000,
                memory_gb=memory_gb,
                perf=1.0,
                utilization=1.0,
            )
        ],
    )


def make_job(workload_id, priority, gpu_count=80, **kwargs) -> Workload:
    return Workload(
        workload_id=workload_id,
        name=workload_id,
        gpu_count=gpu_count,
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
    workloads = [
        make_job("A", 1),
        make_job("B", 2, min_memory_gb=80),
    ]
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


def fixture_z():
    fleet = Fleet(
        sites=[
            make_site("S1", "r1", 0.10),
            make_site("S2", "r2", 0.11),
        ]
    )
    workloads = [make_job("A", 1, gpu_count=10)]
    return fleet, workloads


def real_data():
    return load_fleet(DATA / "fleet.json"), load_workloads(DATA / "workloads.json")


def sites_of(assignment):
    return {
        wid: (None if o is None else o.site_id) for wid, o in assignment.items()
    }


def choice_of(assignment):
    return {
        wid: (None if o is None else (o.site_id, o.pool_id, o.start_hour))
        for wid, o in assignment.items()
    }


def key_of(objective, workloads):
    levels = sorted({w.priority for w in workloads})
    return tuple(-objective.placed_by_priority.get(p, 0) for p in levels) + (
        round(objective.score, 9),
    )


def brute_force_key(fleet, workloads, weights):
    options_by_workload = {
        w.workload_id: options_for(w, fleet) for w in workloads
    }
    pool_totals = {
        (s.site_id, p.pool_id): p.total for s in fleet.sites for p in s.pools
    }
    room = {s.site_id: s.power_capacity_kw - s.baseline_load_kw for s in fleet.sites}
    choices = [options_by_workload[w.workload_id] + [None] for w in workloads]
    best = None
    for combo in itertools.product(*choices):
        used = {}
        load = {}
        for option in combo:
            if option is None:
                continue
            pool_key = (option.site_id, option.pool_id)
            used[pool_key] = used.get(pool_key, 0) + option.gpu_count
            hours = load.setdefault(option.site_id, [0.0] * 24)
            for h in option.hours:
                hours[h] += option.facility_kw
        if any(used[k] > pool_totals[k] for k in used):
            continue
        if any(
            max(hours) > room[site_id] + 1e-9 for site_id, hours in load.items()
        ):
            continue
        assignment = {
            w.workload_id: option for w, option in zip(workloads, combo)
        }
        key = key_of(
            evaluate(assignment, workloads, options_by_workload, weights),
            workloads,
        )
        if best is None or key < best:
            best = key
    return best


def test_fixture_x_optimum_places_both_workloads():
    fleet, workloads = fixture_x()
    result = solve(fleet, workloads, WEIGHTS)
    assert sites_of(result.assignment) == {"A": "S2", "B": "S1"}
    assert result.objective.placed_by_priority == {1: 1, 2: 1}
    assert result.objective.score == pytest.approx(2.5)
    assert result.objective.total_cost_usd == pytest.approx(20.0)
    assert result.nodes > 0


def test_fixture_y_optimum():
    fleet, workloads = fixture_y()
    result = solve(fleet, workloads, WEIGHTS)
    assert sites_of(result.assignment) == {"A": "S2", "B": "S1"}
    assert result.objective.score == pytest.approx(1.05)
    assert result.objective.total_cost_usd == pytest.approx(16.8)


def test_fixture_z_optimum_is_the_cheapest_site():
    fleet, workloads = fixture_z()
    result = solve(fleet, workloads, WEIGHTS)
    assert sites_of(result.assignment) == {"A": "S1"}
    assert result.objective.score == pytest.approx(1.0)


def test_greedy_assignment_on_fixture_x_leaves_b_unplaced():
    fleet, workloads = fixture_x()
    assignment, options_by_workload, result = greedy_assignment(
        fleet, workloads, WEIGHTS
    )
    assert sites_of(assignment) == {"A": "S1", "B": None}
    assert set(options_by_workload) == {"A", "B"}
    assert [u[0] for u in result.unplaced] == ["B"]
    objective = evaluate(assignment, workloads, options_by_workload, WEIGHTS)
    assert objective.placed_by_priority == {1: 1}
    assert objective.score == pytest.approx(0.5)
    assert objective.total_cost_usd == pytest.approx(4.0)


def test_real_data_optimum_assignment_and_score():
    fleet, workloads = real_data()
    result = solve(fleet, workloads)
    assert choice_of(result.assignment) == {
        "W-001": ("SITE-OR", "or-h100", 0),
        "W-002": ("SITE-EU", "eu-h100", 0),
        "W-003": ("SITE-OR", "or-h100", 10),
        "W-004": ("SITE-OR", "or-mi300", 0),
        "W-005": ("SITE-TX", "tx-h100", 12),
        "W-006": ("SITE-OR", "or-mi300", 0),
    }
    assert result.objective.score == pytest.approx(1.111864, abs=1e-6)
    assert result.objective.placed_by_priority == {1: 1, 2: 2, 3: 1, 4: 1, 5: 1}


def test_real_data_search_too_large():
    fleet, workloads = real_data()
    with pytest.raises(SearchTooLarge, match="too large for the stdlib search"):
        solve(fleet, workloads, max_nodes=10)


def test_search_too_large_is_a_runtime_error():
    assert issubclass(SearchTooLarge, RuntimeError)


@pytest.mark.parametrize("builder", [fixture_x, fixture_y])
def test_solve_matches_brute_force(builder):
    fleet, workloads = builder()
    result = solve(fleet, workloads, WEIGHTS)
    assert key_of(result.objective, workloads) == brute_force_key(
        fleet, workloads, WEIGHTS
    )


def test_solve_does_not_change_fleet_state():
    fleet, workloads = real_data()
    solve(fleet, workloads)
    for site in fleet.sites:
        assert site.committed_kw_by_hour == [0.0] * 24
        assert site.committed_kw == 0.0
        for pool in site.pools:
            assert pool.available == pool.total

from pathlib import Path

import pytest

from powerplan.advisor import GRID, advise
from powerplan.models import load_fleet, load_workloads

DATA = Path(__file__).resolve().parent.parent / "data"
TOL = 1e-6
# The oracle amounts are quoted to 4 decimals, so compare to within half a unit
# in the last place.
AMOUNT_TOL = 5e-5


def real_data():
    return load_fleet(DATA / "fleet.json"), load_workloads(DATA / "workloads.json")


def run(metric, reduction):
    fleet, workloads = real_data()
    return advise(fleet, workloads, metric, reduction)


def test_grid_has_231_sets_summing_to_one():
    assert len(GRID) == 231
    for weights in GRID:
        assert sum(weights.values()) == pytest.approx(1.0, abs=1e-12)


def test_carbon_cut_50_percent_is_feasible():
    result = run("carbon", 0.5)
    assert result.feasible is True
    assert result.weights["cost"] == pytest.approx(0.30, abs=TOL)
    assert result.weights["carbon"] == pytest.approx(0.35, abs=TOL)
    assert result.weights["runtime"] == pytest.approx(0.35, abs=TOL)
    assert result.distance == pytest.approx(0.3, abs=TOL)
    assert result.baseline.total_carbon_kg == pytest.approx(5640.4916, abs=AMOUNT_TOL)
    assert result.proposed.total_carbon_kg == pytest.approx(2255.3593, abs=AMOUNT_TOL)
    assert result.proposed.total_cost == pytest.approx(1310.0439, abs=AMOUNT_TOL)
    assert result.moved == [
        ("W-001", ("SITE-TX", "tx-h100", 0), ("SITE-OR", "or-h100", 0)),
        ("W-003", ("SITE-OR", "or-h100", 10), ("SITE-EU", "eu-h100", 10)),
        ("W-005", ("SITE-OR", "or-h100", 8), ("SITE-TX", "tx-h100", 10)),
    ]


def test_cost_cut_15_percent_is_not_reachable():
    result = run("cost", 0.15)
    assert result.feasible is False
    assert result.weights["cost"] == pytest.approx(0.90, abs=TOL)
    assert result.weights["carbon"] == pytest.approx(0.05, abs=TOL)
    assert result.weights["runtime"] == pytest.approx(0.05, abs=TOL)
    assert result.distance == pytest.approx(0.9, abs=TOL)
    assert result.baseline.total_cost == pytest.approx(1127.8018, abs=AMOUNT_TOL)
    assert result.proposed.total_cost == pytest.approx(1110.158, abs=AMOUNT_TOL)
    assert result.proposed.total_carbon_kg == pytest.approx(6041.0721, abs=AMOUNT_TOL)


def test_zero_reduction_returns_the_base_weights():
    result = run("carbon", 0.0)
    assert result.feasible is True
    assert result.weights["cost"] == pytest.approx(0.45, abs=TOL)
    assert result.weights["carbon"] == pytest.approx(0.25, abs=TOL)
    assert result.weights["runtime"] == pytest.approx(0.30, abs=TOL)
    assert result.distance == pytest.approx(0.0, abs=TOL)
    assert result.moved == []


def test_cost_cut_1_percent_is_feasible():
    result = run("cost", 0.01)
    assert result.feasible is True
    assert result.weights["cost"] == pytest.approx(0.45, abs=TOL)
    assert result.weights["carbon"] == pytest.approx(0.00, abs=TOL)
    assert result.weights["runtime"] == pytest.approx(0.55, abs=TOL)
    assert result.distance == pytest.approx(0.5, abs=TOL)
    assert result.proposed.total_cost == pytest.approx(1111.6261, abs=AMOUNT_TOL)


def test_callers_fleet_is_unchanged_and_bad_arguments_raise():
    fleet, workloads = real_data()
    advise(fleet, workloads, "carbon", 0.5)
    for site in fleet.sites:
        assert site.committed_kw_by_hour == [0.0] * 24
        for pool in site.pools:
            assert pool.available == pool.total

    with pytest.raises(ValueError):
        advise(fleet, workloads, "power", 0.1)
    with pytest.raises(ValueError):
        advise(fleet, workloads, "carbon", 1.0)

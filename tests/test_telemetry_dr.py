import json
from pathlib import Path

import pytest

from powerplan.engine import DEFAULT_WEIGHTS, plan
from powerplan.models import load_fleet, load_workloads
from powerplan.optimal import compare
from powerplan.telemetry import DREvent, apply_dr, parse_dr_events

DATA = Path(__file__).resolve().parent.parent / "data"
TOL = 1e-9


def real_data():
    return load_fleet(DATA / "fleet.json"), load_workloads(DATA / "workloads.json")


def fleet_with(*events):
    fleet, _ = real_data()
    apply_dr(fleet, list(events))
    return fleet


def or_event():
    return DREvent("SITE-OR", 8, 16, 650)


def placements_by_id(result):
    return {p.workload_id: p for p in result.placements}


def dr_text(**overrides):
    event = {"site_id": "SITE-OR", "start_hour": 8, "end_hour": 16, "limit_kw": 650}
    event.update(overrides)
    return json.dumps({"events": [event]})


def test_limit_lowers_headroom_and_room_in_window():
    fleet = fleet_with(or_event())
    site = fleet.site("SITE-OR")
    expected = {7: 2100, 8: 150, 15: 150, 16: 2100}
    for hour, value in expected.items():
        assert site.headroom_kw_at(hour) == pytest.approx(value, abs=TOL)
        assert site.room_kw_at(hour) == pytest.approx(value, abs=TOL)


def test_overlapping_events_keep_the_lower_limit():
    fleet = fleet_with(
        DREvent("SITE-TX", 10, 14, 3000), DREvent("SITE-TX", 12, 20, 2000)
    )
    limits = fleet.site("SITE-TX").power_limit_kw_by_hour
    assert limits[9] is None
    assert limits[10] == 3000
    assert limits[11] == 3000
    for hour in range(12, 20):
        assert limits[hour] == 2000
    assert limits[20] is None


def test_limit_above_capacity_does_not_raise_the_ceiling():
    fleet = fleet_with(DREvent("SITE-TX", 0, 24, 9999))
    assert fleet.site("SITE-TX").headroom_kw_at(5) == pytest.approx(3300, abs=TOL)


def test_plan_honours_limit_and_reset_keeps_it():
    fleet, workloads = real_data()
    apply_dr(fleet, [or_event()])
    result = plan(fleet, workloads)
    by_id = placements_by_id(result)

    expected = {
        "W-001": ("SITE-TX", "tx-h100", 0),
        "W-002": ("SITE-EU", "eu-h100", 0),
        "W-004": ("SITE-OR", "or-mi300", 0),
        "W-006": ("SITE-OR", "or-h100", 0),
        "W-003": ("SITE-OR", "or-h100", 10),
        "W-005": ("SITE-OR", "or-h100", 16),
    }
    assert result.unplaced == []
    for workload_id, (site_id, pool_id, start) in expected.items():
        chosen = by_id[workload_id].chosen
        assert (chosen.site_id, chosen.pool_id, chosen.start_hour) == (
            site_id,
            pool_id,
            start,
        )
    assert by_id["W-005"].chosen.deferred_for_capacity is True

    fleet.reset()
    assert fleet.site("SITE-OR").power_limit_kw_by_hour[8] == 650


def test_w005_starts_at_hour_8_without_the_event():
    fleet, workloads = real_data()
    by_id = placements_by_id(plan(fleet, workloads))
    assert by_id["W-005"].chosen.start_hour == 8


def test_non_interruptible_job_is_rejected_under_a_tight_limit():
    fleet, workloads = real_data()
    apply_dr(fleet, [DREvent("SITE-EU", 0, 24, 440)])
    result = plan(fleet, workloads)

    assert "W-002" not in placements_by_id(result)
    rejections = dict(result.unplaced)["W-002"]
    eu = [(r.pool_id, r.reason) for r in rejections if r.site_id == "SITE-EU"]
    assert eu == [
        ("eu-h100", "needs 47kW, only 20kW headroom"),
        ("eu-l40s", "needs 22kW, only 20kW headroom"),
    ]


def test_exact_search_honours_the_limit():
    fleet, workloads = real_data()
    apply_dr(fleet, [or_event()])
    report = compare(fleet, workloads, DEFAULT_WEIGHTS)
    assert report.same_work_placed is True
    assert report.score_gap == pytest.approx(0.0, abs=TOL)
    assert report.moved == []


@pytest.mark.parametrize(
    "overrides",
    [
        {"start_hour": 8, "end_hour": 8},
        {"end_hour": 25},
        {"limit_kw": -1},
    ],
)
def test_invalid_events_raise_value_error(overrides):
    with pytest.raises(ValueError, match="event 0"):
        parse_dr_events(dr_text(**overrides))


def test_event_in_last_hour_with_zero_limit_is_accepted():
    events = parse_dr_events(
        dr_text(start_hour=23, end_hour=24, limit_kw=0)
    )
    assert events == [DREvent("SITE-OR", 23, 24, 0)]


def test_valid_event_parses():
    assert parse_dr_events(dr_text()) == [or_event()]


def test_apply_dr_unknown_site_names_it_and_changes_nothing():
    fleet, _ = real_data()
    events = [or_event(), DREvent("SITE-XX", 0, 1, 10)]
    with pytest.raises(ValueError, match="SITE-XX"):
        apply_dr(fleet, events)
    assert fleet.site("SITE-OR").power_limit_kw_by_hour == [None] * 24

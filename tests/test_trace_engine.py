"""Spans emitted by the planner (`plan(..., tracer=...)`)."""

import itertools
from pathlib import Path

import pytest

from powerplan.engine import plan
from powerplan.models import load_fleet, load_workloads
from powerplan.trace import Tracer
from powerplan.whatif import site_offline

DATA = Path(__file__).resolve().parent.parent / "data"
TOL = 1e-9


def make_tracer() -> Tracer:
    ticks = itertools.count()
    counter = itertools.count(1)

    def clock() -> int:
        return next(ticks) * 1000

    def new_id(nbytes: int) -> str:
        return format(next(counter), "x").zfill(2 * nbytes)

    return Tracer(clock=clock, new_id=new_id)


def real_data():
    return load_fleet(DATA / "fleet.json"), load_workloads(DATA / "workloads.json")


def traced_plan(fleet=None):
    real_fleet, workloads = real_data()
    tracer = make_tracer()
    result = plan(fleet if fleet is not None else real_fleet, workloads, tracer=tracer)
    return result, tracer


def place_span(tracer: Tracer, workload_id: str) -> dict:
    matches = [
        s
        for s in tracer.spans
        if s["name"] == "powerplan.place"
        and s["attributes"]["workload.id"] == workload_id
    ]
    assert len(matches) == 1
    return matches[0]


def test_seven_spans_in_planning_order_sharing_one_trace():
    _, tracer = traced_plan()
    spans = tracer.spans
    assert len(spans) == 7
    assert [s["name"] for s in spans[:6]] == ["powerplan.place"] * 6
    assert [s["attributes"]["workload.id"] for s in spans[:6]] == [
        "W-001",
        "W-002",
        "W-004",
        "W-006",
        "W-003",
        "W-005",
    ]
    root = spans[-1]
    assert root["name"] == "powerplan.plan"
    assert root["parent_span_id"] is None
    assert all(s["parent_span_id"] == root["span_id"] for s in spans[:6])
    assert len({s["trace_id"] for s in spans}) == 1


def test_root_span_attributes():
    _, tracer = traced_plan()
    attrs = tracer.spans[-1]["attributes"]
    assert attrs["workloads.count"] == 6
    assert attrs["placements.count"] == 6
    assert attrs["unplaced.count"] == 0
    assert attrs["weights.cost"] == pytest.approx(0.45, abs=TOL)
    assert attrs["weights.carbon"] == pytest.approx(0.25, abs=TOL)
    assert attrs["weights.runtime"] == pytest.approx(0.30, abs=TOL)


def test_w001_placement_and_runner_up():
    _, tracer = traced_plan()
    attrs = place_span(tracer, "W-001")["attributes"]
    assert attrs["candidates.considered"] == 2
    assert attrs["candidates.rejected"] == 4
    assert attrs["placement.outcome"] == "placed"
    assert attrs["placement.site_id"] == "SITE-TX"
    assert attrs["placement.pool_id"] == "tx-h100"
    assert attrs["placement.start_hour"] == 0
    assert attrs["placement.score"] == pytest.approx(0.25, abs=TOL)
    assert attrs["runner_up.site_id"] == "SITE-OR"
    assert attrs["runner_up.pool_id"] == "or-h100"
    assert attrs["runner_up.score_margin"] == pytest.approx(0.2, abs=TOL)


def test_deferred_start_hours():
    _, tracer = traced_plan()
    for workload_id, start_hour in (("W-003", 10), ("W-005", 8)):
        attrs = place_span(tracer, workload_id)["attributes"]
        assert attrs["placement.outcome"] == "placed"
        assert attrs["placement.site_id"] == "SITE-OR"
        assert attrs["placement.pool_id"] == "or-h100"
        assert attrs["placement.start_hour"] == start_hour


def test_no_runner_up_means_no_runner_up_keys():
    _, tracer = traced_plan()
    attrs = place_span(tracer, "W-002")["attributes"]
    assert attrs["candidates.considered"] == 1
    assert attrs["placement.score"] == pytest.approx(0.0, abs=TOL)
    assert not [k for k in attrs if k.startswith("runner_up.")]


def test_unplaced_workload_span_lists_every_rejection():
    fleet, _ = real_data()
    result, tracer = traced_plan(site_offline(fleet, "SITE-OR"))
    attrs = place_span(tracer, "W-004")["attributes"]
    assert attrs["placement.outcome"] == "unplaced"
    assert attrs["candidates.considered"] == 0
    assert attrs["candidates.rejected"] == 6
    assert attrs["rejection.reasons"] == [
        "SITE-TX/tx-h100: 80GB HBM < 140GB required",
        "SITE-TX/tx-a100: 80GB HBM < 140GB required",
        "SITE-OR/or-h100: site offline",
        "SITE-OR/or-mi300: site offline",
        "SITE-EU/eu-h100: 80GB HBM < 140GB required",
        "SITE-EU/eu-l40s: 48GB HBM < 140GB required",
    ]
    assert "placement.site_id" not in attrs
    assert not [k for k in attrs if k.startswith("runner_up.")]
    assert tracer.spans[-1]["attributes"]["unplaced.count"] == 1
    assert len(result.unplaced) == 1


def test_tracing_changes_nothing():
    fleet_a, workloads_a = real_data()
    fleet_b, workloads_b = real_data()
    plain = plan(fleet_a, workloads_a)
    traced = plan(fleet_b, workloads_b, tracer=make_tracer())

    def key(result):
        return [
            (
                p.workload_id,
                p.chosen.site_id,
                p.chosen.pool_id,
                p.chosen.start_hour,
                p.chosen.score,
            )
            for p in result.placements
        ]

    assert key(plain) == key(traced)
    assert plain.unplaced == traced.unplaced


def test_no_tracer_records_nothing_and_raises_nothing():
    fleet, workloads = real_data()
    bystander = make_tracer()
    result = plan(fleet, workloads, tracer=None)
    assert len(result.placements) == 6
    assert bystander.spans == []

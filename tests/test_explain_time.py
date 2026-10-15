"""Tests for time-aware explanations."""

from __future__ import annotations

from powerplan.engine import Candidate, Placement, Plan
from powerplan.explain import explain, summarise


def test_deferred_placement_mentions_start_hour():
    """explain() mentions start hour when workload is deferred."""
    chosen = Candidate(
        site_id="us-west",
        pool_id="h100",
        accelerator="H100",
        runtime_hours=2.0,
        it_kw=40.0,
        facility_kw=50.0,
        energy_kwh=100.0,
        cost_usd=150.0,
        carbon_kg=8.0,
        start_hour=10.0,
        deferral_saved_usd=50.0,
        deferral_saved_kg=7.0,
        score=0.6,
        components={"cost": 0.4, "carbon": 0.2},
    )
    
    placement = Placement(
        workload_id="w1",
        workload_name="training-job",
        chosen=chosen,
        runner_up=None,
        rejected=[],
        considered=1,
    )
    
    output = explain(placement)
    assert "hour 10" in output
    assert "saved" in output
    assert "$50" in output
    assert "7 kg CO2e" in output


def test_placement_at_hour_zero_has_no_start_line():
    """explain() does not mention start hour when workload starts immediately."""
    chosen = Candidate(
        site_id="us-west",
        pool_id="h100",
        accelerator="H100",
        runtime_hours=2.0,
        it_kw=40.0,
        facility_kw=50.0,
        energy_kwh=100.0,
        cost_usd=200.0,
        carbon_kg=10.0,
        start_hour=0.0,
        deferral_saved_usd=0.0,
        deferral_saved_kg=0.0,
        score=0.5,
        components={"cost": 0.3, "carbon": 0.2},
    )
    
    placement = Placement(
        workload_id="w1",
        workload_name="training-job",
        chosen=chosen,
        runner_up=None,
        rejected=[],
        considered=1,
    )
    
    output = explain(placement)
    assert "starts at hour" not in output
    assert "deferring" not in output


def test_deferral_saved_money_but_emitted_more():
    """explain() correctly reports when deferral saved money but increased carbon."""
    chosen = Candidate(
        site_id="us-west",
        pool_id="h100",
        accelerator="H100",
        runtime_hours=2.0,
        it_kw=40.0,
        facility_kw=50.0,
        energy_kwh=100.0,
        cost_usd=150.0,
        carbon_kg=20.0,
        start_hour=8.0,
        deferral_saved_usd=50.0,
        deferral_saved_kg=-5.0,
        score=0.6,
        components={"cost": 0.5, "carbon": 0.1},
    )
    
    placement = Placement(
        workload_id="w1",
        workload_name="training-job",
        chosen=chosen,
        runner_up=None,
        rejected=[],
        considered=1,
    )
    
    output = explain(placement)
    assert "hour 8" in output
    assert "saved $50" in output
    assert "emits 5 kg more" in output
    # Should not claim both improved
    lines = output.split('\n')
    deferral_line = [line for line in lines if 'starts at hour' in line][0]
    assert 'saved' in deferral_line and 'but emits' in deferral_line


def test_deferral_cost_more_but_saved_carbon():
    """explain() correctly reports when deferral cost more but reduced carbon."""
    chosen = Candidate(
        site_id="us-east",
        pool_id="a100",
        accelerator="A100",
        runtime_hours=2.5,
        it_kw=50.0,
        facility_kw=60.0,
        energy_kwh=150.0,
        cost_usd=250.0,
        carbon_kg=5.0,
        start_hour=12.0,
        deferral_saved_usd=-50.0,
        deferral_saved_kg=15.0,
        score=0.7,
        components={"cost": 0.2, "carbon": 0.5},
    )
    
    placement = Placement(
        workload_id="w2",
        workload_name="inference-job",
        chosen=chosen,
        runner_up=None,
        rejected=[],
        considered=1,
    )
    
    output = explain(placement)
    assert "hour 12" in output
    assert "cost $50 more" in output
    assert "saved 15 kg CO2e" in output


def test_summarise_reports_deferred_count():
    """summarise() includes count of deferred workloads."""
    chosen1 = Candidate(
        site_id="us-west",
        pool_id="h100",
        accelerator="H100",
        runtime_hours=2.0,
        it_kw=40.0,
        facility_kw=50.0,
        energy_kwh=100.0,
        cost_usd=200.0,
        carbon_kg=10.0,
        start_hour=0.0,
        deferral_saved_usd=0.0,
        deferral_saved_kg=0.0,
        score=0.5,
        components={},
    )
    
    chosen2 = Candidate(
        site_id="us-east",
        pool_id="a100",
        accelerator="A100",
        runtime_hours=3.0,
        it_kw=50.0,
        facility_kw=60.0,
        energy_kwh=180.0,
        cost_usd=300.0,
        carbon_kg=15.0,
        start_hour=10.0,
        deferral_saved_usd=25.0,
        deferral_saved_kg=3.0,
        score=0.6,
        components={},
    )
    
    chosen3 = Candidate(
        site_id="eu-west",
        pool_id="v100",
        accelerator="V100",
        runtime_hours=4.0,
        it_kw=30.0,
        facility_kw=40.0,
        energy_kwh=160.0,
        cost_usd=250.0,
        carbon_kg=12.0,
        start_hour=5.0,
        deferral_saved_usd=10.0,
        deferral_saved_kg=2.0,
        score=0.55,
        components={},
    )
    
    placements = [
        Placement(
            workload_id="w1",
            workload_name="job1",
            chosen=chosen1,
            runner_up=None,
            rejected=[],
            considered=1,
        ),
        Placement(
            workload_id="w2",
            workload_name="job2",
            chosen=chosen2,
            runner_up=None,
            rejected=[],
            considered=1,
        ),
        Placement(
            workload_id="w3",
            workload_name="job3",
            chosen=chosen3,
            runner_up=None,
            rejected=[],
            considered=1,
        ),
    ]
    
    plan = Plan(placements=placements)
    
    output = summarise(plan)
    assert "deferred        2 workload(s)" in output

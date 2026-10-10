"""Tests for explain and audit modules."""

from __future__ import annotations

import json
from pathlib import Path

from powerplan.audit import fingerprint, record
from powerplan.engine import Candidate, Placement, Plan, Rejection
from powerplan.explain import explain, summarise
from powerplan.models import AcceleratorPool, Fleet, Site, Workload


def test_explain_mentions_chosen_site():
    """explain() output includes the chosen site and pool."""
    chosen = Candidate(
        site_id="us-west",
        pool_id="h100",
        accelerator="H100",
        runtime_hours=2.0,
        facility_kw=50.0,
        energy_kwh=100.0,
        cost_usd=200.0,
        carbon_kg=10.0,
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
    assert "us-west" in output
    assert "h100" in output
    assert "H100" in output


def test_explain_mentions_every_reject_reason():
    """explain() output includes rejection reasons."""
    chosen = Candidate(
        site_id="us-west",
        pool_id="h100",
        accelerator="H100",
        runtime_hours=2.0,
        facility_kw=50.0,
        energy_kwh=100.0,
        cost_usd=200.0,
        carbon_kg=10.0,
        score=0.5,
        components={"cost": 0.3, "carbon": 0.2},
    )
    
    rejections = [
        Rejection(site_id="us-east", pool_id="a100", reason="insufficient memory"),
        Rejection(site_id="eu-west", pool_id="v100", reason="power headroom exceeded"),
        Rejection(site_id="ap-south", pool_id="h100", reason="data residency"),
    ]
    
    placement = Placement(
        workload_id="w1",
        workload_name="training-job",
        chosen=chosen,
        runner_up=None,
        rejected=rejections,
        considered=4,
    )
    
    output = explain(placement)
    assert "insufficient memory" in output
    assert "power headroom exceeded" in output
    assert "data residency" in output
    assert "us-east" in output
    assert "eu-west" in output
    assert "ap-south" in output


def test_explain_shows_runner_up_comparison():
    """explain() shows comparison with runner-up candidate."""
    chosen = Candidate(
        site_id="us-west",
        pool_id="h100",
        accelerator="H100",
        runtime_hours=2.0,
        facility_kw=50.0,
        energy_kwh=100.0,
        cost_usd=200.0,
        carbon_kg=10.0,
        score=0.6,
        components={"cost": 0.4, "carbon": 0.2},
    )
    
    runner_up = Candidate(
        site_id="us-east",
        pool_id="a100",
        accelerator="A100",
        runtime_hours=2.5,
        facility_kw=60.0,
        energy_kwh=150.0,
        cost_usd=250.0,
        carbon_kg=20.0,
        score=0.5,
        components={"cost": 0.3, "carbon": 0.2},
    )
    
    placement = Placement(
        workload_id="w1",
        workload_name="training-job",
        chosen=chosen,
        runner_up=runner_up,
        rejected=[],
        considered=2,
    )
    
    output = explain(placement)
    assert "us-east/a100" in output
    assert "beat" in output


def test_summarise_counts_match_plan():
    """summarise() counts match the actual plan contents."""
    chosen1 = Candidate(
        site_id="us-west",
        pool_id="h100",
        accelerator="H100",
        runtime_hours=2.0,
        facility_kw=50.0,
        energy_kwh=100.0,
        cost_usd=200.0,
        carbon_kg=10.0,
        score=0.5,
        components={},
    )
    
    chosen2 = Candidate(
        site_id="us-east",
        pool_id="a100",
        accelerator="A100",
        runtime_hours=3.0,
        facility_kw=60.0,
        energy_kwh=180.0,
        cost_usd=300.0,
        carbon_kg=15.0,
        score=0.6,
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
    ]
    
    unplaced = [
        ("w3", [Rejection(site_id="us-west", pool_id="h100", reason="no capacity")]),
    ]
    
    plan = Plan(placements=placements, unplaced=unplaced)
    
    output = summarise(plan)
    assert "placed 2 workload(s)" in output
    assert "1 unplaced" in output
    assert "500" in output  # total cost
    assert "280" in output  # total energy
    assert "25" in output   # total carbon


def test_fingerprint_stable_for_equal_input():
    """fingerprint() returns same hash for identical inputs."""
    pool = AcceleratorPool(
        pool_id="h100",
        accelerator="H100",
        count=8,
        available=8,
        memory_gb=80,
        tdp_watts=700,
        perf=1.0,
    )
    
    site = Site(
        site_id="us-west",
        pools=[pool],
        capacity_kw=100.0,
        drawn_kw=0.0,
        pue=1.2,
        price_per_kwh=0.10,
        carbon_g_per_kwh=400.0,
        allowed_residency=["us"],
    )
    
    fleet1 = Fleet(sites=[site])
    fleet2 = Fleet(sites=[site])
    
    fp1 = fingerprint(fleet1)
    fp2 = fingerprint(fleet2)
    
    assert fp1 == fp2
    assert isinstance(fp1, str)
    assert len(fp1) == 16  # short hash


def test_fingerprint_differs_for_different_input():
    """fingerprint() returns different hashes for different inputs."""
    pool1 = AcceleratorPool(
        pool_id="h100",
        accelerator="H100",
        count=8,
        available=8,
        memory_gb=80,
        tdp_watts=700,
        perf=1.0,
    )
    
    pool2 = AcceleratorPool(
        pool_id="a100",
        accelerator="A100",
        count=8,
        available=8,
        memory_gb=40,
        tdp_watts=400,
        perf=0.8,
    )
    
    site1 = Site(
        site_id="us-west",
        pools=[pool1],
        capacity_kw=100.0,
        drawn_kw=0.0,
        pue=1.2,
        price_per_kwh=0.10,
        carbon_g_per_kwh=400.0,
        allowed_residency=["us"],
    )
    
    site2 = Site(
        site_id="us-west",
        pools=[pool2],
        capacity_kw=100.0,
        drawn_kw=0.0,
        pue=1.2,
        price_per_kwh=0.10,
        carbon_g_per_kwh=400.0,
        allowed_residency=["us"],
    )
    
    fleet1 = Fleet(sites=[site1])
    fleet2 = Fleet(sites=[site2])
    
    fp1 = fingerprint(fleet1)
    fp2 = fingerprint(fleet2)
    
    assert fp1 != fp2


def test_audit_record_appends_valid_json_lines(tmp_path):
    """audit.record() appends valid JSON lines to the audit log."""
    audit_file = tmp_path / "audit.jsonl"
    
    chosen = Candidate(
        site_id="us-west",
        pool_id="h100",
        accelerator="H100",
        runtime_hours=2.0,
        facility_kw=50.0,
        energy_kwh=100.0,
        cost_usd=200.0,
        carbon_kg=10.0,
        score=0.5,
        components={"cost": 0.3, "carbon": 0.2},
    )
    
    placement = Placement(
        workload_id="w1",
        workload_name="job1",
        chosen=chosen,
        runner_up=None,
        rejected=[],
        considered=1,
    )
    
    plan = Plan(placements=[placement])
    
    pool = AcceleratorPool(
        pool_id="h100",
        accelerator="H100",
        count=8,
        available=8,
        memory_gb=80,
        tdp_watts=700,
        perf=1.0,
    )
    
    site = Site(
        site_id="us-west",
        pools=[pool],
        capacity_kw=100.0,
        drawn_kw=0.0,
        pue=1.2,
        price_per_kwh=0.10,
        carbon_g_per_kwh=400.0,
        allowed_residency=["us"],
    )
    
    fleet = Fleet(sites=[site])
    
    workload = Workload(
        workload_id="w1",
        name="job1",
        gpu_count=1,
        gpu_memory_gb=40,
        ref_hours=2.0,
        residency=["us"],
    )
    
    run_id = record(plan, fleet, [workload], path=audit_file)
    
    assert audit_file.exists()
    assert isinstance(run_id, str)
    
    # Read and validate JSON
    lines = audit_file.read_text().strip().split("\n")
    assert len(lines) == 1
    
    entry = json.loads(lines[0])
    assert entry["run_id"] == run_id
    assert "ts" in entry
    assert "fleet_fingerprint" in entry
    assert "workload_fingerprint" in entry
    assert len(entry["decisions"]) == 1
    assert entry["decisions"][0]["workload_id"] == "w1"


def test_audit_record_never_rewrites_earlier_lines(tmp_path):
    """audit.record() appends without modifying existing entries."""
    audit_file = tmp_path / "audit.jsonl"
    
    chosen = Candidate(
        site_id="us-west",
        pool_id="h100",
        accelerator="H100",
        runtime_hours=2.0,
        facility_kw=50.0,
        energy_kwh=100.0,
        cost_usd=200.0,
        carbon_kg=10.0,
        score=0.5,
        components={},
    )
    
    placement = Placement(
        workload_id="w1",
        workload_name="job1",
        chosen=chosen,
        runner_up=None,
        rejected=[],
        considered=1,
    )
    
    plan = Plan(placements=[placement])
    
    pool = AcceleratorPool(
        pool_id="h100",
        accelerator="H100",
        count=8,
        available=8,
        memory_gb=80,
        tdp_watts=700,
        perf=1.0,
    )
    
    site = Site(
        site_id="us-west",
        pools=[pool],
        capacity_kw=100.0,
        drawn_kw=0.0,
        pue=1.2,
        price_per_kwh=0.10,
        carbon_g_per_kwh=400.0,
        allowed_residency=["us"],
    )
    
    fleet = Fleet(sites=[site])
    
    workload = Workload(
        workload_id="w1",
        name="job1",
        gpu_count=1,
        gpu_memory_gb=40,
        ref_hours=2.0,
        residency=["us"],
    )
    
    # First record
    run_id1 = record(plan, fleet, [workload], path=audit_file)
    first_content = audit_file.read_text()
    
    # Second record
    run_id2 = record(plan, fleet, [workload], path=audit_file)
    second_content = audit_file.read_text()
    
    # Verify first entry is unchanged
    assert second_content.startswith(first_content)
    
    # Verify we have two lines
    lines = second_content.strip().split("\n")
    assert len(lines) == 2
    
    # Verify both are valid JSON with different run_ids
    entry1 = json.loads(lines[0])
    entry2 = json.loads(lines[1])
    assert entry1["run_id"] == run_id1
    assert entry2["run_id"] == run_id2
    assert run_id1 != run_id2

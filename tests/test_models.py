"""Tests for powerplan.models"""

import json
from pathlib import Path

import pytest

from powerplan.models import (
    AcceleratorPool,
    Fleet,
    Site,
    Workload,
    load_fleet,
    load_workloads,
    to_dict,
)


def test_accelerator_pool_draw_kw():
    """Test AcceleratorPool.draw_kw calculates power draw correctly."""
    pool = AcceleratorPool(
        pool_id="test_pool",
        accelerator="H100",
        total=8,
        available=8,
        tdp_watts=700,
        memory_gb=80,
        perf=1.0,
    )
    
    # Test drawing power for 4 accelerators (with default utilization=0.85)
    assert pool.draw_kw(4) == 2.38  # 4 * 700W * 0.85 = 2380W = 2.38kW
    
    # Test drawing power for all accelerators
    assert pool.draw_kw(8) == 4.76  # 8 * 700W * 0.85 = 4760W = 4.76kW
    
    # Test drawing power for 0 accelerators
    assert pool.draw_kw(0) == 0.0


def test_site_headroom_kw():
    """Test Site.headroom_kw calculates available power correctly."""
    pool1 = AcceleratorPool(
        pool_id="pool1",
        accelerator="H100",
        total=4,
        available=4,
        tdp_watts=700,
        memory_gb=80,
        perf=1.0,
    )
    pool2 = AcceleratorPool(
        pool_id="pool2",
        accelerator="A100",
        total=8,
        available=8,
        tdp_watts=400,
        memory_gb=40,
        perf=0.8,
    )
    
    site = Site(
        site_id="test_site",
        region="us-west",
        power_capacity_kw=100.0,
        baseline_load_kw=0.0,
        pue=1.2,
        price_per_kwh=0.10,
        carbon_g_per_kwh=200,
        pools=[pool1, pool2],
    )
    
    # Initially, no power is committed
    assert site.headroom_kw == 100.0
    
    # Commit some power
    site.committed_kw = 10.0
    # Headroom = 100.0 - 0.0 (baseline) - 10.0 (committed) = 90.0kW
    assert site.headroom_kw == 90.0


def test_site_facility_kw():
    """Test Site.facility_kw applies PUE correctly."""
    site = Site(
        site_id="test_site",
        region="us-west",
        power_capacity_kw=100.0,
        baseline_load_kw=0.0,
        pue=1.5,
        price_per_kwh=0.10,
        carbon_g_per_kwh=200,
        pools=[],
    )
    
    # Test PUE multiplication
    assert site.facility_kw(10.0) == 15.0  # 10kW * 1.5 PUE
    assert site.facility_kw(0.0) == 0.0
    assert site.facility_kw(50.0) == 75.0


def test_site_pool():
    """Test Site.pool retrieves the correct pool by ID."""
    pool1 = AcceleratorPool(
        pool_id="h100_pool",
        accelerator="H100",
        total=4,
        available=4,
        tdp_watts=700,
        memory_gb=80,
        perf=1.0,
    )
    pool2 = AcceleratorPool(
        pool_id="a100_pool",
        accelerator="A100",
        total=8,
        available=8,
        tdp_watts=400,
        memory_gb=40,
        perf=0.8,
    )
    
    site = Site(
        site_id="test_site",
        region="us-west",
        power_capacity_kw=100.0,
        baseline_load_kw=0.0,
        pue=1.2,
        price_per_kwh=0.10,
        carbon_g_per_kwh=200,
        pools=[pool1, pool2],
    )
    
    # Test retrieving existing pools
    assert site.pool("h100_pool") == pool1
    assert site.pool("a100_pool") == pool2
    
    # Test error on unknown pool ID
    with pytest.raises(KeyError):
        site.pool("unknown_pool")


def test_workload_runtime_hours():
    """Test Workload.runtime_hours scales by pool performance."""
    workload = Workload(
        workload_id="test_job",
        name="test_workload",
        gpu_count=4,
        ref_hours=10.0,
        min_memory_gb=40,
    )
    
    # Pool with perf=1.0 (reference performance)
    pool_ref = AcceleratorPool(
        pool_id="ref_pool",
        accelerator="H100",
        total=8,
        available=8,
        tdp_watts=700,
        memory_gb=80,
        perf=1.0,
    )
    assert workload.runtime_hours(pool_ref) == 10.0
    
    # Pool with perf=2.0 (twice as fast)
    pool_fast = AcceleratorPool(
        pool_id="fast_pool",
        accelerator="H200",
        total=8,
        available=8,
        tdp_watts=800,
        memory_gb=96,
        perf=2.0,
    )
    assert workload.runtime_hours(pool_fast) == 5.0
    
    # Pool with perf=0.5 (half as fast)
    pool_slow = AcceleratorPool(
        pool_id="slow_pool",
        accelerator="V100",
        total=8,
        available=8,
        tdp_watts=300,
        memory_gb=32,
        perf=0.5,
    )
    assert workload.runtime_hours(pool_slow) == 20.0


def test_fleet_site():
    """Test Fleet.site retrieves the correct site by ID."""
    site1 = Site(
        site_id="site_a",
        region="us-west",
        power_capacity_kw=100.0,
        baseline_load_kw=0.0,
        pue=1.2,
        price_per_kwh=0.10,
        carbon_g_per_kwh=200,
        pools=[],
    )
    site2 = Site(
        site_id="site_b",
        region="us-east",
        power_capacity_kw=150.0,
        baseline_load_kw=0.0,
        pue=1.3,
        price_per_kwh=0.12,
        carbon_g_per_kwh=300,
        pools=[],
    )
    
    fleet = Fleet(sites=[site1, site2])
    
    # Test retrieving existing sites
    assert fleet.site("site_a") == site1
    assert fleet.site("site_b") == site2
    
    # Test error on unknown site ID
    with pytest.raises(KeyError):
        fleet.site("unknown_site")


def test_fleet_reset():
    """Test Fleet.reset restores all pool availability."""
    pool1 = AcceleratorPool(
        pool_id="pool1",
        accelerator="H100",
        total=8,
        available=4,  # Some in use
        tdp_watts=700,
        memory_gb=80,
        perf=1.0,
    )
    pool2 = AcceleratorPool(
        pool_id="pool2",
        accelerator="A100",
        total=16,
        available=10,  # Some in use
        tdp_watts=400,
        memory_gb=40,
        perf=0.8,
    )
    
    site = Site(
        site_id="test_site",
        region="us-west",
        power_capacity_kw=100.0,
        baseline_load_kw=0.0,
        pue=1.2,
        price_per_kwh=0.10,
        carbon_g_per_kwh=200,
        pools=[pool1, pool2],
    )
    
    fleet = Fleet(sites=[site])
    
    # Verify pools are partially allocated and site has committed power
    assert pool1.available == 4
    assert pool2.available == 10
    site.committed_kw = 50.0
    
    # Reset the fleet
    fleet.reset()
    
    # Verify all pools are fully available and committed power is reset
    assert pool1.available == 8
    assert pool2.available == 16
    assert site.committed_kw == 0.0


def test_load_fleet_roundtrip():
    """Test load_fleet can load and round-trip the fleet data file."""
    fleet = load_fleet("data/fleet.json")
    
    # Verify fleet loaded successfully
    assert isinstance(fleet, Fleet)
    assert len(fleet.sites) > 0
    
    # Verify we can convert back to dict
    fleet_dict = to_dict(fleet)
    assert "sites" in fleet_dict
    assert isinstance(fleet_dict["sites"], list)
    
    # Verify round-trip produces valid JSON
    json_str = json.dumps(fleet_dict)
    reloaded = json.loads(json_str)
    assert reloaded == fleet_dict
    
    # Verify sites have expected structure
    for site_dict in fleet_dict["sites"]:
        assert "site_id" in site_dict
        assert "region" in site_dict
        assert "carbon_g_per_kwh" in site_dict
        assert "price_per_kwh" in site_dict
        assert "pue" in site_dict
        assert "power_capacity_kw" in site_dict
        assert "pools" in site_dict


def test_load_workloads_roundtrip():
    """Test load_workloads can load and round-trip the workloads data file."""
    workloads = load_workloads("data/workloads.json")
    
    # Verify workloads loaded successfully
    assert isinstance(workloads, list)
    assert len(workloads) > 0
    
    # Verify we can convert back to dict
    workloads_list = [to_dict(w) for w in workloads]
    assert isinstance(workloads_list, list)
    
    # Verify round-trip produces valid JSON
    json_str = json.dumps(workloads_list)
    reloaded = json.loads(json_str)
    assert reloaded == workloads_list
    
    # Verify workloads have expected structure
    for workload_dict in workloads_list:
        assert "workload_id" in workload_dict
        assert "name" in workload_dict
        assert "gpu_count" in workload_dict
        assert "ref_hours" in workload_dict
        assert "min_memory_gb" in workload_dict


def test_to_dict_with_nested_dataclasses():
    """Test to_dict handles nested dataclasses correctly."""
    pool = AcceleratorPool(
        pool_id="test_pool",
        accelerator="H100",
        total=8,
        available=8,
        tdp_watts=700,
        memory_gb=80,
        perf=1.0,
    )
    
    site = Site(
        site_id="test_site",
        region="us-west",
        power_capacity_kw=100.0,
        baseline_load_kw=0.0,
        pue=1.2,
        price_per_kwh=0.10,
        carbon_g_per_kwh=200,
        pools=[pool],
    )
    
    fleet = Fleet(sites=[site])
    
    # Convert to dict
    fleet_dict = to_dict(fleet)
    
    # Verify structure
    assert isinstance(fleet_dict, dict)
    assert "sites" in fleet_dict
    assert isinstance(fleet_dict["sites"], list)
    assert len(fleet_dict["sites"]) == 1
    
    site_dict = fleet_dict["sites"][0]
    assert site_dict["site_id"] == "test_site"
    assert "pools" in site_dict
    assert isinstance(site_dict["pools"], list)
    assert len(site_dict["pools"]) == 1
    
    pool_dict = site_dict["pools"][0]
    assert pool_dict["pool_id"] == "test_pool"
    assert pool_dict["accelerator"] == "H100"
    assert pool_dict["total"] == 8

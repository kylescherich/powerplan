"""Tests for the start-hour rule in _build_candidate."""

from dataclasses import fields

from powerplan.engine import plan
from powerplan.models import AcceleratorPool, Fleet, Site, Workload


def test_weights_decide_not_units_cost_favored():
    """When cost weight is higher, choose the hour with lower cost ratio."""
    site = Site(
        site_id="s1",
        region="us-east",
        online=True,
        power_capacity_kw=1000.0,
        baseline_load_kw=0.0,
        pue=1.5,
        price_per_kwh=0.10,
        carbon_g_per_kwh=300.0,
        pools=[
            AcceleratorPool(
                pool_id="p1",
                accelerator="H100",
                total=8,
                available=8,
                memory_gb=80.0,
                tdp_watts=700.0,
                perf=1.0,
            )
        ],
        price_curve=[0.10] * 5 + [0.05] + [0.10] * 18,  # 50% cheaper at hour 5
        carbon_curve=[300.0] * 15 + [240.0] + [300.0] * 8,  # 20% cleaner at hour 15
    )
    fleet = Fleet(sites=[site])
    workload = Workload(
        workload_id="w1",
        name="test",
        gpu_count=1,
        min_memory_gb=40.0,
        ref_hours=1.0,
        interruptible=True,
    )
    
    result = plan(fleet, [workload], weights={"cost": 0.5, "carbon": 0.5, "runtime": 0.0})
    
    assert len(result.placements) == 1
    assert result.placements[0].chosen.start_hour == 5


def test_weights_decide_not_units_carbon_favored():
    """When carbon weight is higher, choose the hour with lower carbon ratio."""
    site = Site(
        site_id="s1",
        region="us-east",
        online=True,
        power_capacity_kw=1000.0,
        baseline_load_kw=0.0,
        pue=1.5,
        price_per_kwh=0.10,
        carbon_g_per_kwh=300.0,
        pools=[
            AcceleratorPool(
                pool_id="p1",
                accelerator="H100",
                total=8,
                available=8,
                memory_gb=80.0,
                tdp_watts=700.0,
                perf=1.0,
            )
        ],
        price_curve=[0.10] * 5 + [0.05] + [0.10] * 18,  # 50% cheaper at hour 5
        carbon_curve=[300.0] * 15 + [240.0] + [300.0] * 8,  # 20% cleaner at hour 15
    )
    fleet = Fleet(sites=[site])
    workload = Workload(
        workload_id="w1",
        name="test",
        gpu_count=1,
        min_memory_gb=40.0,
        ref_hours=1.0,
        interruptible=True,
    )
    
    result = plan(fleet, [workload], weights={"cost": 0.1, "carbon": 0.9, "runtime": 0.0})
    
    assert len(result.placements) == 1
    assert result.placements[0].chosen.start_hour == 15


def test_long_jobs_can_defer():
    """A 30h job can defer even though it's longer than 24h."""
    site = Site(
        site_id="s1",
        region="us-east",
        online=True,
        power_capacity_kw=10000.0,
        baseline_load_kw=0.0,
        pue=1.5,
        price_per_kwh=0.20,
        carbon_g_per_kwh=300.0,
        pools=[
            AcceleratorPool(
                pool_id="p1",
                accelerator="H100",
                total=8,
                available=8,
                memory_gb=80.0,
                tdp_watts=700.0,
                perf=1.0,
            )
        ],
        price_curve=[0.20] * 6 + [0.05] * 18,  # Expensive hours 0-5, cheap otherwise
        carbon_curve=[300.0] * 24,
    )
    fleet = Fleet(sites=[site])
    workload = Workload(
        workload_id="w1",
        name="long_job",
        gpu_count=1,
        min_memory_gb=40.0,
        ref_hours=30.0,
        interruptible=True,
    )
    
    result = plan(fleet, [workload], weights={"cost": 1.0, "carbon": 0.0, "runtime": 0.0})
    
    assert len(result.placements) == 1
    # Should start at hour 6 or later to avoid expensive hours 0-5
    assert result.placements[0].chosen.start_hour >= 6


def test_late_starts_wrap():
    """A 6h job can start at hour 23 and wrap around."""
    # Cheapest for hours 23, 0, 1, 2, 3, 4
    price_curve = [0.05] * 5 + [0.20] * 18 + [0.05]
    site = Site(
        site_id="s1",
        region="us-east",
        online=True,
        power_capacity_kw=1000.0,
        baseline_load_kw=0.0,
        pue=1.5,
        price_per_kwh=0.20,
        carbon_g_per_kwh=300.0,
        pools=[
            AcceleratorPool(
                pool_id="p1",
                accelerator="H100",
                total=8,
                available=8,
                memory_gb=80.0,
                tdp_watts=700.0,
                perf=1.0,
            )
        ],
        price_curve=price_curve,
        carbon_curve=[300.0] * 24,
    )
    fleet = Fleet(sites=[site])
    workload = Workload(
        workload_id="w1",
        name="wrap_job",
        gpu_count=1,
        min_memory_gb=40.0,
        ref_hours=6.0,
        interruptible=True,
    )
    
    result = plan(fleet, [workload], weights={"cost": 1.0, "carbon": 0.0, "runtime": 0.0})
    
    assert len(result.placements) == 1
    assert result.placements[0].chosen.start_hour == 23


def test_start_hour_is_int_for_deferred():
    """start_hour is an int type for deferred placements."""
    site = Site(
        site_id="s1",
        region="us-east",
        online=True,
        power_capacity_kw=1000.0,
        baseline_load_kw=0.0,
        pue=1.5,
        price_per_kwh=0.10,
        carbon_g_per_kwh=300.0,
        pools=[
            AcceleratorPool(
                pool_id="p1",
                accelerator="H100",
                total=8,
                available=8,
                memory_gb=80.0,
                tdp_watts=700.0,
                perf=1.0,
            )
        ],
        price_curve=[0.10] * 5 + [0.05] + [0.10] * 18,
        carbon_curve=[300.0] * 24,
    )
    fleet = Fleet(sites=[site])
    workload = Workload(
        workload_id="w1",
        name="test",
        gpu_count=1,
        min_memory_gb=40.0,
        ref_hours=1.0,
        interruptible=True,
    )
    
    result = plan(fleet, [workload], weights={"cost": 1.0, "carbon": 0.0, "runtime": 0.0})
    
    assert len(result.placements) == 1
    assert isinstance(result.placements[0].chosen.start_hour, int)


def test_start_hour_is_int_for_non_deferred():
    """start_hour is an int type for non-deferred placements."""
    site = Site(
        site_id="s1",
        region="us-east",
        online=True,
        power_capacity_kw=1000.0,
        baseline_load_kw=0.0,
        pue=1.5,
        price_per_kwh=0.10,
        carbon_g_per_kwh=300.0,
        pools=[
            AcceleratorPool(
                pool_id="p1",
                accelerator="H100",
                total=8,
                available=8,
                memory_gb=80.0,
                tdp_watts=700.0,
                perf=1.0,
            )
        ],
        price_curve=[0.10] * 24,
        carbon_curve=[300.0] * 24,
    )
    fleet = Fleet(sites=[site])
    workload = Workload(
        workload_id="w1",
        name="test",
        gpu_count=1,
        min_memory_gb=40.0,
        ref_hours=1.0,
        interruptible=False,
    )
    
    result = plan(fleet, [workload], weights={"cost": 1.0, "carbon": 0.0, "runtime": 0.0})
    
    assert len(result.placements) == 1
    assert isinstance(result.placements[0].chosen.start_hour, int)
    assert result.placements[0].chosen.start_hour == 0


def test_candidate_field_order():
    """The last three fields of Candidate are start_hour, deferral_saved_usd, deferral_saved_kg."""
    from powerplan.engine import Candidate
    
    all_fields = fields(Candidate)
    last_three = [f.name for f in all_fields[-3:]]
    
    assert last_three == ["start_hour", "deferral_saved_usd", "deferral_saved_kg"]

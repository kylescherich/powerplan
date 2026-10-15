import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from powerplan.engine import plan  # noqa: E402
from powerplan.models import (  # noqa: E402
    AcceleratorPool,
    Fleet,
    Site,
    Workload,
    load_fleet,
    load_workloads,
)

DATA = Path(__file__).resolve().parents[1] / "data"


def test_site_without_curves_uses_scalar_pricing():
    """A site without curves gives exactly today's numbers."""
    pool = AcceleratorPool(
        pool_id="p1",
        accelerator="H100",
        total=64,
        available=64,
        tdp_watts=700,
        memory_gb=80,
        perf=1.0,
        utilization=0.88,
    )
    site = Site(
        site_id="s1",
        region="us-test",
        power_capacity_kw=1000,
        baseline_load_kw=100,
        pue=1.2,
        price_per_kwh=0.10,
        carbon_g_per_kwh=400,
        pools=[pool],
    )
    fleet = Fleet(sites=[site])
    workload = Workload(
        workload_id="w1",
        name="test",
        gpu_count=8,
        ref_hours=5.0,
    )
    
    p = plan(fleet, [workload])
    assert len(p.placements) >= 1
    
    chosen = p.placements[0].chosen
    assert chosen.start_hour == 0.0
    assert abs(chosen.cost_usd - chosen.energy_kwh * 0.10) < 1e-6
    assert abs(chosen.carbon_kg - chosen.energy_kwh * 0.4) < 1e-6


def test_interruptible_job_defers_to_cheaper_hour():
    """An interruptible job on a site with expensive hour 0 starts later."""
    pool = AcceleratorPool(
        pool_id="p1",
        accelerator="H100",
        total=64,
        available=64,
        tdp_watts=700,
        memory_gb=80,
        perf=1.0,
        utilization=0.88,
    )
    # Price curve: expensive at hour 0, cheap at hour 10
    price_curve = [0.20] * 10 + [0.05] * 14
    site = Site(
        site_id="s1",
        region="us-test",
        power_capacity_kw=1000,
        baseline_load_kw=100,
        pue=1.2,
        price_per_kwh=0.10,  # scalar fallback
        carbon_g_per_kwh=400,
        price_curve=price_curve,
        pools=[pool],
    )
    fleet = Fleet(sites=[site])
    workload = Workload(
        workload_id="w1",
        name="test",
        gpu_count=8,
        ref_hours=2.0,
        interruptible=True,
    )
    
    p = plan(fleet, [workload])
    assert len(p.placements) >= 1
    
    chosen = p.placements[0].chosen
    assert chosen.start_hour > 0
    assert chosen.deferral_saved_usd > 0
    
    # Verify cost is lower than starting at hour 0
    # At hour 0: 2 hours at 0.20 $/kWh
    # At hour 10+: 2 hours at 0.05 $/kWh
    facility_kw = site.facility_kw(pool.draw_kw(8))
    cost_at_zero = facility_kw * 2.0 * 0.20
    assert chosen.cost_usd < cost_at_zero


def test_non_interruptible_job_starts_at_hour_zero():
    """The same job with interruptible=False starts at hour 0."""
    pool = AcceleratorPool(
        pool_id="p1",
        accelerator="H100",
        total=64,
        available=64,
        tdp_watts=700,
        memory_gb=80,
        perf=1.0,
        utilization=0.88,
    )
    # Price curve: expensive at hour 0, cheap at hour 10
    price_curve = [0.20] * 10 + [0.05] * 14
    site = Site(
        site_id="s1",
        region="us-test",
        power_capacity_kw=1000,
        baseline_load_kw=100,
        pue=1.2,
        price_per_kwh=0.10,
        carbon_g_per_kwh=400,
        price_curve=price_curve,
        pools=[pool],
    )
    fleet = Fleet(sites=[site])
    workload = Workload(
        workload_id="w1",
        name="test",
        gpu_count=8,
        ref_hours=2.0,
        interruptible=False,
    )
    
    p = plan(fleet, [workload])
    assert len(p.placements) >= 1
    
    chosen = p.placements[0].chosen
    assert chosen.start_hour == 0.0


def test_deadline_constrains_start_hour():
    """The deadline binds: job starts earlier than unconstrained optimum."""
    pool = AcceleratorPool(
        pool_id="p1",
        accelerator="H100",
        total=64,
        available=64,
        tdp_watts=700,
        memory_gb=80,
        perf=1.0,
        utilization=0.88,
    )
    # Price curve: expensive early, cheap at hour 20
    price_curve = [0.20] * 20 + [0.02] * 4
    site = Site(
        site_id="s1",
        region="us-test",
        power_capacity_kw=1000,
        baseline_load_kw=100,
        pue=1.2,
        price_per_kwh=0.10,
        carbon_g_per_kwh=400,
        price_curve=price_curve,
        pools=[pool],
    )
    fleet = Fleet(sites=[site])
    
    # Job with tight deadline
    workload_deadline = Workload(
        workload_id="w1",
        name="test-deadline",
        gpu_count=8,
        ref_hours=3.0,
        interruptible=True,
        deadline_hours=10.0,  # Must finish by hour 10
    )
    
    # Same job without deadline
    workload_no_deadline = Workload(
        workload_id="w2",
        name="test-no-deadline",
        gpu_count=8,
        ref_hours=3.0,
        interruptible=True,
    )
    
    p_deadline = plan(Fleet(sites=[site]), [workload_deadline])
    assert len(p_deadline.placements) >= 1
    
    fleet_fresh = Fleet(sites=[Site(
        site_id="s1",
        region="us-test",
        power_capacity_kw=1000,
        baseline_load_kw=100,
        pue=1.2,
        price_per_kwh=0.10,
        carbon_g_per_kwh=400,
        price_curve=price_curve,
        pools=[AcceleratorPool(
            pool_id="p1",
            accelerator="H100",
            total=64,
            available=64,
            tdp_watts=700,
            memory_gb=80,
            perf=1.0,
            utilization=0.88,
        )],
    )])
    p_no_deadline = plan(fleet_fresh, [workload_no_deadline])
    assert len(p_no_deadline.placements) >= 1
    
    chosen_deadline = p_deadline.placements[0].chosen
    chosen_no_deadline = p_no_deadline.placements[0].chosen
    
    # Deadline-constrained job must finish by hour 10
    assert chosen_deadline.start_hour + chosen_deadline.runtime_hours <= 10.0 + 1e-6
    
    # Unconstrained job starts later (at cheaper hour 20)
    assert chosen_no_deadline.start_hour > chosen_deadline.start_hour


def test_integration_fractional_and_wraparound():
    """Integration by hand: fractional hours and wraparound past hour 23."""
    pool = AcceleratorPool(
        pool_id="p1",
        accelerator="H100",
        total=64,
        available=64,
        tdp_watts=700,
        memory_gb=80,
        perf=1.0,
        utilization=0.88,
    )
    
    # Simple price curve for manual verification
    price_curve = [float(h) for h in range(24)]  # hour 0 = $0, hour 1 = $1, etc.
    
    site = Site(
        site_id="s1",
        region="us-test",
        power_capacity_kw=1000,
        baseline_load_kw=100,
        pue=1.2,
        price_per_kwh=0.10,
        carbon_g_per_kwh=400,
        price_curve=price_curve,
        pools=[pool],
    )
    fleet = Fleet(sites=[site])
    
    # Test 1: 1.5 hour job starting at hour 5
    # Should use: 1.0 hour at price[5]=5.0, 0.5 hour at price[6]=6.0
    # Expected cost = facility_kw * (1.0 * 5.0 + 0.5 * 6.0) = facility_kw * 8.0
    workload_short = Workload(
        workload_id="w1",
        name="short",
        gpu_count=8,
        ref_hours=1.5,
        interruptible=False,
    )
    
    # Manually set start hour by making it non-interruptible and starting at 0
    # Then we'll check a different approach
    # Actually, let's create a site with curves starting at different points
    
    # For simplicity, test with interruptible=False which starts at 0
    fleet1 = Fleet(sites=[Site(
        site_id="s1",
        region="us-test",
        power_capacity_kw=1000,
        baseline_load_kw=100,
        pue=1.2,
        price_per_kwh=0.10,
        carbon_g_per_kwh=400,
        price_curve=price_curve,
        pools=[AcceleratorPool(
            pool_id="p1",
            accelerator="H100",
            total=64,
            available=64,
            tdp_watts=700,
            memory_gb=80,
            perf=1.0,
            utilization=0.88,
        )],
    )])
    
    p1 = plan(fleet1, [workload_short])
    assert len(p1.placements) >= 1
    
    chosen1 = p1.placements[0].chosen
    facility_kw = site.facility_kw(pool.draw_kw(8))
    
    # Starting at hour 0: 1.0 hour at price[0]=0.0, 0.5 hour at price[1]=1.0
    expected_cost_1 = facility_kw * (1.0 * 0.0 + 0.5 * 1.0)
    assert abs(chosen1.cost_usd - expected_cost_1) < 1e-6
    
    # Test 2: 30 hour job wraps past hour 23
    # Starting at hour 0, goes through all 24 hours and wraps to hours 0-5
    workload_long = Workload(
        workload_id="w2",
        name="long",
        gpu_count=8,
        ref_hours=30.0,
        interruptible=False,
    )
    
    fleet2 = Fleet(sites=[Site(
        site_id="s1",
        region="us-test",
        power_capacity_kw=10000,  # Large capacity
        baseline_load_kw=100,
        pue=1.2,
        price_per_kwh=0.10,
        carbon_g_per_kwh=400,
        price_curve=price_curve,
        pools=[AcceleratorPool(
            pool_id="p1",
            accelerator="H100",
            total=64,
            available=64,
            tdp_watts=700,
            memory_gb=80,
            perf=1.0,
            utilization=0.88,
        )],
    )])
    
    p2 = plan(fleet2, [workload_long])
    assert len(p2.placements) >= 1
    
    chosen2 = p2.placements[0].chosen
    
    # Manual calculation: hours 0-23 (full cycle) + hours 0-5 (6 more hours)
    # Sum of 0..23 = 23*24/2 = 276
    # Sum of 0..5 = 5*6/2 = 15
    # Total = 276 + 15 = 291
    expected_cost_2 = facility_kw * 291.0
    assert abs(chosen2.cost_usd - expected_cost_2) < 1e-3


def test_data_files_interruptible_workloads_defer():
    """On data files with default weights: interruptible jobs start after hour 0."""
    fleet = load_fleet(DATA / "fleet.json")
    workloads = load_workloads(DATA / "workloads.json")
    
    p = plan(fleet, workloads)
    assert len(p.placements) >= 1
    
    # W-003 and W-005 are interruptible
    w003 = next((pl for pl in p.placements if pl.workload_id == "W-003"), None)
    w005 = next((pl for pl in p.placements if pl.workload_id == "W-005"), None)
    
    if w003:
        assert w003.chosen.start_hour > 0
    if w005:
        assert w005.chosen.start_hour > 0
    
    # All non-interruptible workloads start at 0
    non_interruptible_ids = ["W-001", "W-002", "W-004", "W-006"]
    for wid in non_interruptible_ids:
        pl = next((pl for pl in p.placements if pl.workload_id == wid), None)
        if pl:
            assert pl.chosen.start_hour == 0.0


def test_makespan_includes_start_hour():
    """makespan_hours equals the largest start_hour + runtime_hours."""
    pool = AcceleratorPool(
        pool_id="p1",
        accelerator="H100",
        total=128,
        available=128,
        tdp_watts=700,
        memory_gb=80,
        perf=1.0,
        utilization=0.88,
    )
    
    # Price curve that encourages deferral
    price_curve = [0.20] * 15 + [0.05] * 9
    
    site = Site(
        site_id="s1",
        region="us-test",
        power_capacity_kw=10000,
        baseline_load_kw=100,
        pue=1.2,
        price_per_kwh=0.10,
        carbon_g_per_kwh=400,
        price_curve=price_curve,
        pools=[pool],
    )
    fleet = Fleet(sites=[site])
    
    workloads = [
        Workload(
            workload_id="w1",
            name="early",
            gpu_count=8,
            ref_hours=2.0,
            interruptible=False,  # starts at 0
        ),
        Workload(
            workload_id="w2",
            name="deferred",
            gpu_count=8,
            ref_hours=3.0,
            interruptible=True,  # will defer to hour 15+
        ),
    ]
    
    p = plan(fleet, workloads)
    assert len(p.placements) >= 1
    
    # Find the maximum end time
    max_end = 0.0
    for pl in p.placements:
        end_time = pl.chosen.start_hour + pl.chosen.runtime_hours
        max_end = max(max_end, end_time)
    
    assert abs(p.makespan_hours - max_end) < 1e-6


def test_plan_notes_mention_power_headroom():
    """The plan.notes sentence about power headroom is present."""
    pool = AcceleratorPool(
        pool_id="p1",
        accelerator="H100",
        total=64,
        available=64,
        tdp_watts=700,
        memory_gb=80,
        perf=1.0,
        utilization=0.88,
    )
    site = Site(
        site_id="s1",
        region="us-test",
        power_capacity_kw=1000,
        baseline_load_kw=100,
        pue=1.2,
        price_per_kwh=0.10,
        carbon_g_per_kwh=400,
        pools=[pool],
    )
    fleet = Fleet(sites=[site])
    workload = Workload(
        workload_id="w1",
        name="test",
        gpu_count=8,
        ref_hours=5.0,
    )
    
    p = plan(fleet, [workload])
    
    # Check that the power headroom note is present
    assert any("power headroom" in note.lower() for note in p.notes)
    assert any("time-slicing" in note.lower() for note in p.notes)

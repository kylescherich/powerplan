"""Tests for whatif scenario functions."""

import copy
from powerplan.models import load_fleet, load_workloads
from powerplan.whatif import (
    site_offline,
    curtail,
    pool_degraded,
    price_spike,
    diff,
    run_scenario,
)
from powerplan.engine import plan


def test_site_offline_returns_new_fleet():
    """site_offline should return a new fleet and leave the input untouched."""
    original = load_fleet("data/fleet.json")
    original_sites_count = len(original.sites)
    original_first_site_id = original.sites[0].site_id
    original_first_site_online = original.sites[0].online
    
    modified = site_offline(original, original_first_site_id)
    
    # Original should be unchanged
    assert len(original.sites) == original_sites_count
    assert original.sites[0].site_id == original_first_site_id
    assert original.sites[0].online == original_first_site_online
    
    # Modified should be different
    assert modified is not original
    modified_site = modified.site(original_first_site_id)
    assert modified_site.online == False


def test_curtail_returns_new_fleet():
    """curtail should return a new fleet and leave the input untouched."""
    original = load_fleet("data/fleet.json")
    site_id = original.sites[0].site_id
    original_capacity = original.sites[0].power_capacity_kw
    
    modified = curtail(original, site_id, 0.5)
    
    # Original should be unchanged
    assert original.sites[0].power_capacity_kw == original_capacity
    
    # Modified should be different
    assert modified is not original
    modified_site = modified.site(site_id)
    assert modified_site.power_capacity_kw == original_capacity * 0.5


def test_pool_degraded_returns_new_fleet():
    """pool_degraded should return a new fleet and leave the input untouched."""
    original = load_fleet("data/fleet.json")
    site_id = original.sites[0].site_id
    pool_id = original.sites[0].pools[0].pool_id
    original_total = original.sites[0].pools[0].total
    
    modified = pool_degraded(original, site_id, pool_id, 1)
    
    # Original should be unchanged
    assert original.site(site_id).pool(pool_id).total == original_total
    
    # Modified should be different
    assert modified is not original
    modified_pool = modified.site(site_id).pool(pool_id)
    assert modified_pool.total == original_total - 1


def test_price_spike_returns_new_fleet():
    """price_spike should return a new fleet and leave the input untouched."""
    original = load_fleet("data/fleet.json")
    site_id = original.sites[0].site_id
    original_price = original.sites[0].price_per_kwh
    
    modified = price_spike(original, site_id, 2.0)
    
    # Original should be unchanged
    assert original.sites[0].price_per_kwh == original_price
    
    # Modified should be different
    assert modified is not original
    modified_site = modified.site(site_id)
    assert modified_site.price_per_kwh == original_price * 2.0


def test_diff_output_names_moved_workloads():
    """diff should name the workloads that moved between plans."""
    fleet = load_fleet("data/fleet.json")
    workloads = load_workloads("data/workloads.json")
    
    # Create baseline plan
    baseline = plan(fleet, workloads)
    
    # Find a site that has at least one placement
    site_with_placements = None
    for site in fleet.sites:
        placements_at_site = [p for p in baseline.placements if p.site_id == site.site_id]
        if placements_at_site:
            site_with_placements = site.site_id
            break
    
    assert site_with_placements is not None, "No site has any placements in baseline plan"
    
    # Take that site offline and re-plan
    fleet.reset()
    perturbed = site_offline(fleet, site_with_placements)
    scenario = plan(perturbed, workloads)
    
    # Find workloads that moved to different sites
    moved_workloads = []
    for baseline_placement in baseline.placements:
        # Find the same workload in the scenario plan
        scenario_placement = next(
            (p for p in scenario.placements if p.workload_id == baseline_placement.workload_id),
            None
        )
        if scenario_placement and scenario_placement.site_id != baseline_placement.site_id:
            moved_workloads.append(baseline_placement.workload_id)
    
    # The test must fail if no workloads moved
    assert len(moved_workloads) > 0, (
        f"No workloads moved when site {site_with_placements} was taken offline. "
        "This test requires at least one workload to move to validate diff() output."
    )
    
    # Get diff output
    output = diff(baseline, scenario)
    
    # Should be a non-empty string
    assert isinstance(output, str)
    assert len(output) > 0, "diff() output should not be empty when workloads moved"
    
    # Every moved workload should be named in the output
    for workload_id in moved_workloads:
        assert workload_id in output, (
            f"Workload {workload_id} moved sites but is not mentioned in diff() output"
        )


def test_run_scenario_on_data_files():
    """run_scenario should work with the actual data files."""
    fleet = load_fleet("data/fleet.json")
    workloads = load_workloads("data/workloads.json")
    
    # Create a perturbed fleet
    perturbed = site_offline(fleet, fleet.sites[0].site_id)
    
    # Run scenario should return a tuple of (baseline_plan, scenario_plan)
    result = run_scenario(fleet, workloads, perturbed)
    
    assert isinstance(result, tuple)
    assert len(result) == 2
    # Both should be Plan objects
    from powerplan.engine import Plan
    assert isinstance(result[0], Plan)
    assert isinstance(result[1], Plan)


def test_run_scenario_with_weights():
    """run_scenario should accept weights parameter."""
    fleet = load_fleet("data/fleet.json")
    workloads = load_workloads("data/workloads.json")
    
    perturbed = curtail(fleet, fleet.sites[0].site_id, 0.8)
    
    weights = {"cost": 0.5, "carbon": 0.3, "runtime": 0.2}
    result = run_scenario(fleet, workloads, perturbed, weights=weights)
    
    assert isinstance(result, tuple)
    assert len(result) == 2

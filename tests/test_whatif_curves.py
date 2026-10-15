"""Tests for whatif scenario functions with price curves."""

from powerplan.models import load_fleet, load_workloads
from powerplan.whatif import price_spike
from powerplan.engine import plan


def test_price_spike_doubles_every_curve_value():
    """price_spike should multiply every value in the price_curve."""
    fleet = load_fleet("data/fleet.json")
    site = fleet.site("SITE-OR")
    
    # Verify SITE-OR has a price curve
    assert site.price_curve is not None
    assert len(site.price_curve) == 24
    
    original_curve = site.price_curve.copy()
    
    # Apply price spike
    modified = price_spike(fleet, "SITE-OR", 2.0)
    modified_site = modified.site("SITE-OR")
    
    # Every curve value should be doubled
    for i, (original_val, modified_val) in enumerate(
        zip(original_curve, modified_site.price_curve)
    ):
        assert modified_val == original_val * 2.0, (
            f"Hour {i}: expected {original_val * 2.0}, got {modified_val}"
        )


def test_price_spike_leaves_original_curve_unchanged():
    """price_spike should not modify the original fleet's curve."""
    fleet = load_fleet("data/fleet.json")
    site = fleet.site("SITE-OR")
    
    assert site.price_curve is not None
    original_curve = site.price_curve.copy()
    
    # Apply price spike
    modified = price_spike(fleet, "SITE-OR", 2.0)
    
    # Original fleet's curve should be unchanged
    assert site.price_curve == original_curve
    for i, (original_val, current_val) in enumerate(
        zip(original_curve, site.price_curve)
    ):
        assert current_val == original_val, (
            f"Hour {i}: original fleet was modified"
        )


def test_price_spike_works_on_site_without_curve():
    """price_spike should work on sites that only have scalar price_per_kwh."""
    fleet = load_fleet("data/fleet.json")
    
    # Find a site without a price curve (or create test scenario)
    # For this test, we'll use SITE-TX which should have a curve,
    # but we'll verify the function handles None gracefully
    site = fleet.site("SITE-TX")
    original_price = site.price_per_kwh
    
    # Temporarily remove the curve to test the None case
    site.price_curve = None
    
    modified = price_spike(fleet, "SITE-TX", 1.5)
    modified_site = modified.site("SITE-TX")
    
    # Scalar price should be multiplied
    assert modified_site.price_per_kwh == original_price * 1.5
    # Curve should still be None
    assert modified_site.price_curve is None


def test_spiked_fleet_increases_or_placement_costs():
    """A plan on a price-spiked fleet should have higher costs for OR placements."""
    fleet = load_fleet("data/fleet.json")
    workloads = load_workloads("data/workloads.json")
    
    # Create baseline plan
    baseline = plan(fleet, workloads)
    
    # Find placements at SITE-OR in baseline
    or_placements_baseline = [
        p for p in baseline.placements if p.chosen.site_id == "SITE-OR"
    ]
    
    # Reset fleet and apply price spike
    fleet.reset()
    spiked = price_spike(fleet, "SITE-OR", 2.0)
    spiked_plan = plan(spiked, workloads)
    
    # Find placements at SITE-OR in spiked plan
    or_placements_spiked = [
        p for p in spiked_plan.placements if p.chosen.site_id == "SITE-OR"
    ]
    
    # If there are still placements at OR in the spiked plan, they should cost more
    if or_placements_spiked:
        # Find a workload that stayed at OR
        for baseline_p in or_placements_baseline:
            spiked_p = next(
                (
                    p
                    for p in or_placements_spiked
                    if p.workload_id == baseline_p.workload_id
                ),
                None,
            )
            if spiked_p:
                # This workload stayed at OR, so its cost should be higher
                assert spiked_p.chosen.cost_usd > baseline_p.chosen.cost_usd, (
                    f"Workload {baseline_p.workload_id} at SITE-OR should cost more "
                    f"after price spike: baseline=${baseline_p.chosen.cost_usd:.2f}, "
                    f"spiked=${spiked_p.chosen.cost_usd:.2f}"
                )
                # Found at least one, test passes
                return
    
    # Alternative: if no workloads stayed at OR, that's also valid
    # (they all moved away due to higher prices)
    # In this case, we verify that fewer or no workloads are at OR
    assert len(or_placements_spiked) <= len(or_placements_baseline), (
        "Price spike should not increase placements at SITE-OR"
    )

"""Tests for time-of-day price and carbon curves."""

import pytest

from powerplan.models import Site, AcceleratorPool, load_fleet


def test_curve_with_23_values_raises_error():
    """A curve with 23 values should raise ValueError."""
    with pytest.raises(ValueError, match="must have exactly 24 values"):
        Site(
            site_id="test",
            region="test",
            power_capacity_kw=100.0,
            baseline_load_kw=0.0,
            pue=1.2,
            price_per_kwh=0.10,
            carbon_g_per_kwh=200,
            price_curve=[0.1] * 23,  # Only 23 values
        )


def test_curve_with_negative_value_raises_error():
    """A curve with negative values should raise ValueError."""
    with pytest.raises(ValueError, match="must be non-negative"):
        Site(
            site_id="test",
            region="test",
            power_capacity_kw=100.0,
            baseline_load_kw=0.0,
            pue=1.2,
            price_per_kwh=0.10,
            carbon_g_per_kwh=200,
            price_curve=[0.1] * 23 + [-0.05],  # Last value is negative
        )


def test_carbon_curve_with_23_values_raises_error():
    """A carbon curve with 23 values should raise ValueError."""
    with pytest.raises(ValueError, match="must have exactly 24 values"):
        Site(
            site_id="test",
            region="test",
            power_capacity_kw=100.0,
            baseline_load_kw=0.0,
            pue=1.2,
            price_per_kwh=0.10,
            carbon_g_per_kwh=200,
            carbon_curve=[200.0] * 23,  # Only 23 values
        )


def test_carbon_curve_with_negative_value_raises_error():
    """A carbon curve with negative values should raise ValueError."""
    with pytest.raises(ValueError, match="must be non-negative"):
        Site(
            site_id="test",
            region="test",
            power_capacity_kw=100.0,
            baseline_load_kw=0.0,
            pue=1.2,
            price_per_kwh=0.10,
            carbon_g_per_kwh=200,
            carbon_curve=[200.0] * 23 + [-10.0],  # Last value is negative
        )


def test_price_at_returns_curve_value():
    """price_at should return the value from the curve at the given hour."""
    curve = [0.1 + i * 0.01 for i in range(24)]  # 0.1, 0.11, 0.12, ..., 0.33
    site = Site(
        site_id="test",
        region="test",
        power_capacity_kw=100.0,
        baseline_load_kw=0.0,
        pue=1.2,
        price_per_kwh=0.10,
        carbon_g_per_kwh=200,
        price_curve=curve,
    )
    
    assert site.price_at(0) == 0.1
    assert site.price_at(5) == 0.15
    assert site.price_at(23) == 0.33


def test_price_at_wraps_hour():
    """price_at should wrap hours >= 24 back to the curve."""
    curve = [0.1 + i * 0.01 for i in range(24)]
    site = Site(
        site_id="test",
        region="test",
        power_capacity_kw=100.0,
        baseline_load_kw=0.0,
        pue=1.2,
        price_per_kwh=0.10,
        carbon_g_per_kwh=200,
        price_curve=curve,
    )
    
    # Hour 25 should wrap to index 1
    assert site.price_at(25) == 0.11
    # Hour 48 should wrap to index 0
    assert site.price_at(48) == 0.1
    # Hour 50 should wrap to index 2
    assert site.price_at(50) == 0.12


def test_price_at_falls_back_to_scalar():
    """price_at should return the scalar price when no curve is present."""
    site = Site(
        site_id="test",
        region="test",
        power_capacity_kw=100.0,
        baseline_load_kw=0.0,
        pue=1.2,
        price_per_kwh=0.15,
        carbon_g_per_kwh=200,
    )
    
    # Should return scalar for any hour
    assert site.price_at(0) == 0.15
    assert site.price_at(12) == 0.15
    assert site.price_at(25) == 0.15


def test_carbon_at_returns_curve_value():
    """carbon_at should return the value from the curve at the given hour."""
    curve = [100.0 + i * 10.0 for i in range(24)]  # 100, 110, 120, ..., 330
    site = Site(
        site_id="test",
        region="test",
        power_capacity_kw=100.0,
        baseline_load_kw=0.0,
        pue=1.2,
        price_per_kwh=0.10,
        carbon_g_per_kwh=200,
        carbon_curve=curve,
    )
    
    assert site.carbon_at(0) == 100.0
    assert site.carbon_at(5) == 150.0
    assert site.carbon_at(23) == 330.0


def test_carbon_at_wraps_hour():
    """carbon_at should wrap hours >= 24 back to the curve."""
    curve = [100.0 + i * 10.0 for i in range(24)]
    site = Site(
        site_id="test",
        region="test",
        power_capacity_kw=100.0,
        baseline_load_kw=0.0,
        pue=1.2,
        price_per_kwh=0.10,
        carbon_g_per_kwh=200,
        carbon_curve=curve,
    )
    
    # Hour 25 should wrap to index 1
    assert site.carbon_at(25) == 110.0
    # Hour 48 should wrap to index 0
    assert site.carbon_at(48) == 100.0
    # Hour 50 should wrap to index 2
    assert site.carbon_at(50) == 120.0


def test_carbon_at_falls_back_to_scalar():
    """carbon_at should return the scalar carbon when no curve is present."""
    site = Site(
        site_id="test",
        region="test",
        power_capacity_kw=100.0,
        baseline_load_kw=0.0,
        pue=1.2,
        price_per_kwh=0.10,
        carbon_g_per_kwh=250,
    )
    
    # Should return scalar for any hour
    assert site.carbon_at(0) == 250
    assert site.carbon_at(12) == 250
    assert site.carbon_at(25) == 250


def test_load_fleet_curves_mean_within_1_percent():
    """Curves in data/fleet.json should have means within 1% of scalars."""
    fleet = load_fleet("data/fleet.json")
    
    for site in fleet.sites:
        # Check price curve
        if site.price_curve is not None:
            assert len(site.price_curve) == 24
            mean_price = sum(site.price_curve) / 24
            scalar_price = site.price_per_kwh
            percent_diff = abs(mean_price - scalar_price) / scalar_price * 100
            assert percent_diff < 1.0, (
                f"{site.site_id}: price curve mean {mean_price:.4f} differs from "
                f"scalar {scalar_price:.4f} by {percent_diff:.2f}%"
            )
        
        # Check carbon curve
        if site.carbon_curve is not None:
            assert len(site.carbon_curve) == 24
            mean_carbon = sum(site.carbon_curve) / 24
            scalar_carbon = site.carbon_g_per_kwh
            percent_diff = abs(mean_carbon - scalar_carbon) / scalar_carbon * 100
            assert percent_diff < 1.0, (
                f"{site.site_id}: carbon curve mean {mean_carbon:.2f} differs from "
                f"scalar {scalar_carbon:.2f} by {percent_diff:.2f}%"
            )


def test_load_fleet_all_sites_have_curves():
    """All sites in data/fleet.json should have both curves."""
    fleet = load_fleet("data/fleet.json")
    
    for site in fleet.sites:
        assert site.price_curve is not None, f"{site.site_id} missing price_curve"
        assert site.carbon_curve is not None, f"{site.site_id} missing carbon_curve"
        assert len(site.price_curve) == 24
        assert len(site.carbon_curve) == 24

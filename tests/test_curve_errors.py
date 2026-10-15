"""Test that curve validation errors include site_id and field name."""

import pytest
from powerplan.models import Site, AcceleratorPool


def test_price_curve_wrong_length_includes_site_and_field():
    """Error message for wrong-length price_curve includes site_id and field name."""
    with pytest.raises(ValueError) as exc_info:
        Site(
            site_id="SITE-X",
            region="us-west",
            power_capacity_kw=1000,
            baseline_load_kw=100,
            pue=1.5,
            price_per_kwh=0.10,
            carbon_g_per_kwh=400,
            price_curve=[0.1] * 23  # Wrong length
        )
    
    message = str(exc_info.value)
    assert "SITE-X" in message
    assert "price_curve" in message


def test_price_curve_negative_value_includes_site_and_field():
    """Error message for negative price_curve value includes site_id and field name."""
    with pytest.raises(ValueError) as exc_info:
        Site(
            site_id="SITE-Y",
            region="us-east",
            power_capacity_kw=1000,
            baseline_load_kw=100,
            pue=1.5,
            price_per_kwh=0.10,
            carbon_g_per_kwh=400,
            price_curve=[0.1] * 23 + [-0.05]  # Negative value
        )
    
    message = str(exc_info.value)
    assert "SITE-Y" in message
    assert "price_curve" in message


def test_carbon_curve_wrong_length_includes_site_and_field():
    """Error message for wrong-length carbon_curve includes site_id and field name."""
    with pytest.raises(ValueError) as exc_info:
        Site(
            site_id="SITE-Z",
            region="eu-central",
            power_capacity_kw=1000,
            baseline_load_kw=100,
            pue=1.5,
            price_per_kwh=0.10,
            carbon_g_per_kwh=400,
            carbon_curve=[300] * 25  # Wrong length
        )
    
    message = str(exc_info.value)
    assert "SITE-Z" in message
    assert "carbon_curve" in message


def test_carbon_curve_negative_value_includes_site_and_field():
    """Error message for negative carbon_curve value includes site_id and field name."""
    with pytest.raises(ValueError) as exc_info:
        Site(
            site_id="SITE-A",
            region="ap-south",
            power_capacity_kw=1000,
            baseline_load_kw=100,
            pue=1.5,
            price_per_kwh=0.10,
            carbon_g_per_kwh=400,
            carbon_curve=[300] * 23 + [-50]  # Negative value
        )
    
    message = str(exc_info.value)
    assert "SITE-A" in message
    assert "carbon_curve" in message

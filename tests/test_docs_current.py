"""Verify documentation reflects current implementation."""

from pathlib import Path


def test_handoff_no_longer_says_interruptible_unused():
    """HANDOFF.md should not claim interruptible is unused."""
    handoff = Path("HANDOFF.md").read_text()
    assert "is declared and read by nothing" not in handoff


def test_readme_mentions_price_curve():
    """README.md should document the price_curve field."""
    readme = Path("README.md").read_text()
    assert "price_curve" in readme


def test_readme_mentions_start_hour():
    """README.md should document start hour scheduling."""
    readme = Path("README.md").read_text()
    assert "start hour" in readme


def test_handoff_mentions_time_indexed():
    """HANDOFF.md should note time-indexed capacity is not modelled."""
    handoff = Path("HANDOFF.md").read_text()
    assert "time-indexed" in handoff

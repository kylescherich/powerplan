from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def read(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def test_readme_mentions_compare_optimal():
    assert "--compare-optimal" in read("README.md")


def test_handoff_no_longer_claims_no_time_dimension():
    assert "No time dimension at all" not in read("HANDOFF.md")


def test_handoff_mentions_exact_search():
    assert "exact search" in read("HANDOFF.md")

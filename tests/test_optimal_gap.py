"""Gap report (greedy vs exact optimum) and the --compare-optimal CLI flag."""

from pathlib import Path

import pytest

from powerplan import cli
from powerplan.cli import main
from powerplan.models import (
    AcceleratorPool,
    Fleet,
    Site,
    Workload,
    load_fleet,
    load_workloads,
)
from powerplan.optimal import SearchTooLarge, compare, format_gap

DATA = Path(__file__).resolve().parent.parent / "data"
WEIGHTS = {"cost": 1.0, "carbon": 0.0, "runtime": 0.0}


def make_site(site_id, region, price, memory_gb=80.0) -> Site:
    pool = AcceleratorPool(
        pool_id="p" + site_id,
        accelerator="X",
        total=100,
        available=100,
        tdp_watts=1000,
        memory_gb=memory_gb,
        perf=1.0,
        utilization=1.0,
    )
    return Site(
        site_id=site_id,
        region=region,
        power_capacity_kw=1000,
        baseline_load_kw=0,
        pue=1.0,
        price_per_kwh=price,
        carbon_g_per_kwh=100,
        pools=[pool],
    )


def make_job(workload_id, priority, gpu_count=80, **kwargs) -> Workload:
    return Workload(
        workload_id=workload_id,
        name=workload_id,
        gpu_count=gpu_count,
        ref_hours=1.0,
        priority=priority,
        **kwargs,
    )


def fixture_x():
    fleet = Fleet(
        sites=[
            make_site("S1", "r1", 0.05),
            make_site("S2", "r2", 0.20, memory_gb=40.0),
        ]
    )
    workloads = [
        make_job("A", 1),
        make_job("B", 2, min_memory_gb=80),
    ]
    return fleet, workloads


def fixture_y():
    fleet = Fleet(
        sites=[
            make_site("S1", "r1", 0.10),
            make_site("S2", "r2", 0.11),
            make_site("S3", "r3", 0.50),
        ]
    )
    workloads = [
        make_job("A", 1, allowed_regions=["r1", "r2"]),
        make_job("B", 2, allowed_regions=["r1", "r3"]),
    ]
    return fleet, workloads


def fixture_z():
    fleet = Fleet(
        sites=[
            make_site("S1", "r1", 0.10),
            make_site("S2", "r2", 0.11),
        ]
    )
    workloads = [make_job("A", 1, gpu_count=10)]
    return fleet, workloads


def test_fixture_y_report():
    fleet, workloads = fixture_y()
    report = compare(fleet, workloads, WEIGHTS)
    assert report.same_work_placed is True
    assert report.score_gap == pytest.approx(1.95, abs=1e-9)
    assert report.moved == [
        ("A", "S1/pS1@0", "S2/pS2@0"),
        ("B", "S3/pS3@0", "S1/pS1@0"),
    ]


def test_fixture_x_report_different_work_placed():
    fleet, workloads = fixture_x()
    report = compare(fleet, workloads, WEIGHTS)
    assert report.same_work_placed is False
    assert report.score_gap is None
    text = format_gap(report)
    assert "gap n/a (different work placed)" in text
    assert "note: the optimum is worse on cost" in text
    assert ("B", "unplaced", "S1/pS1@0") in report.moved


def test_fixture_z_has_nothing_moved_and_no_note():
    fleet, workloads = fixture_z()
    report = compare(fleet, workloads, WEIGHTS)
    assert report.moved == []
    assert report.score_gap == pytest.approx(0.0, abs=1e-9)
    text = format_gap(report)
    assert "moved: none" in text
    assert "note:" not in text


def test_format_gap_layout_on_fixture_y():
    fleet, workloads = fixture_y()
    lines = format_gap(compare(fleet, workloads, WEIGHTS)).splitlines()
    assert lines[0] == "greedy vs exact optimum (same objective, same constraints)"
    assert lines[1] == "  placed by priority  greedy P1 1, P2 1  optimum P1 1, P2 1"
    assert lines[2] == (
        "  objective score     greedy 3.0000  optimum 1.0500  gap 1.9500"
    )
    assert lines[3] == "  total cost          greedy $48  optimum $17"
    assert lines[4] == "  total carbon        greedy 16 kg  optimum 16 kg"
    assert lines[5] == (
        "  moved: A S1/pS1@0 -> S2/pS2@0; B S3/pS3@0 -> S1/pS1@0"
    )
    assert len(lines) == 6


def real_text():
    fleet = load_fleet(DATA / "fleet.json")
    workloads = load_workloads(DATA / "workloads.json")
    return format_gap(compare(fleet, workloads))


def test_real_data_text():
    text = real_text()
    assert "greedy 1.4734  optimum 1.1119  gap 0.3615" in text
    assert "greedy $1,128  optimum $1,307" in text
    assert "greedy 5,640 kg  optimum 2,211 kg" in text
    assert "note: the optimum is worse on cost" in text
    assert "worse on cost and carbon" not in text
    assert (
        "moved: W-001 SITE-TX/tx-h100@0 -> SITE-OR/or-h100@0; "
        "W-005 SITE-OR/or-h100@8 -> SITE-TX/tx-h100@12; "
        "W-006 SITE-OR/or-h100@0 -> SITE-OR/or-mi300@0"
    ) in text


def cli_args(tmp_path, *extra):
    return [
        "plan",
        "--fleet",
        str(DATA / "fleet.json"),
        "--workloads",
        str(DATA / "workloads.json"),
        "--audit",
        str(tmp_path / "audit.jsonl"),
        *extra,
    ]


def test_cli_compare_optimal_prints_gap(tmp_path, capsys):
    code = main(cli_args(tmp_path, "--compare-optimal"))
    out = capsys.readouterr().out
    assert code == 0
    assert "greedy vs exact optimum" in out
    audit_pos = out.index("audit run_id")
    assert audit_pos < out.index("greedy vs exact optimum")


def test_cli_without_flag_has_no_gap(tmp_path, capsys):
    code = main(cli_args(tmp_path))
    out = capsys.readouterr().out
    assert code == 0
    assert "greedy vs exact optimum" not in out


def test_cli_search_too_large_returns_3(tmp_path, capsys, monkeypatch):
    def too_big(*args, **kwargs):
        raise SearchTooLarge("problem is too large for the stdlib search")

    monkeypatch.setattr(cli, "compare", too_big)
    code = main(cli_args(tmp_path, "--compare-optimal"))
    captured = capsys.readouterr()
    assert code == 3
    assert "audit run_id" in captured.out
    assert "greedy vs exact optimum" not in captured.out
    assert "too large for the stdlib search" in captured.err

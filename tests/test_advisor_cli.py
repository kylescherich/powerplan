"""Tests for the `advise` command and its docs."""

import shutil
from pathlib import Path

import pytest

from powerplan.cli import main

ROOT = Path(__file__).resolve().parents[1]
GOAL_ERROR = "goal must look like cost:15 or carbon:50"


@pytest.fixture
def workdir(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    shutil.copy(ROOT / "data" / "fleet.json", data_dir / "fleet.json")
    shutil.copy(ROOT / "data" / "workloads.json", data_dir / "workloads.json")
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_carbon_goal_prints_the_proposal(workdir, capsys):
    exit_code = main(["advise", "--goal", "carbon:50"])

    assert exit_code == 0
    captured = capsys.readouterr()
    assert captured.out.splitlines() == [
        "goal: cut carbon by 50% (baseline 5,640 kg CO2e)",
        "proposal: cost 0.30, carbon 0.35, runtime 0.35 "
        "(distance 0.30 from current weights)",
        "result: carbon 2,255 kg CO2e (-60.0%), cost $1,310 (+16.2%)",
        "moved: W-001 SITE-TX/tx-h100@0 -> SITE-OR/or-h100@0",
        "moved: W-003 SITE-OR/or-h100@10 -> SITE-EU/eu-h100@10",
        "moved: W-005 SITE-OR/or-h100@8 -> SITE-TX/tx-h100@10",
        "to apply: python -m powerplan plan "
        "--w-cost 0.30 --w-carbon 0.35 --w-runtime 0.35",
    ]
    assert not (workdir / "audit.jsonl").exists()


def test_unreachable_cost_goal_returns_1(workdir, capsys):
    exit_code = main(["advise", "--goal", "cost:15%"])

    assert exit_code == 1
    lines = capsys.readouterr().out.splitlines()
    assert lines[0] == "goal: cut cost by 15% (baseline $1,128)"
    assert lines[1] == (
        "not reachable without placing less work; closest: "
        "cost 0.90, carbon 0.05, runtime 0.05 "
        "(distance 0.90 from current weights)"
    )
    assert lines[2] == "result: cost $1,110 (-1.6%), carbon 6,041 kg CO2e (+7.1%)"
    assert lines[-1].startswith("to apply: python -m powerplan plan ")


@pytest.mark.parametrize("goal", ["bogus:5", "carbon:100"])
def test_bad_goal_returns_2(workdir, capsys, goal):
    exit_code = main(["advise", "--goal", goal])

    assert exit_code == 2
    captured = capsys.readouterr()
    assert GOAL_ERROR in captured.err
    assert captured.out == ""


def test_docs_describe_the_advisor():
    assert "never applies" in (ROOT / "README.md").read_text()
    assert "0.05" in (ROOT / "HANDOFF.md").read_text()

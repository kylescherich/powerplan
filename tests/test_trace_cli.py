"""Tests for `plan --trace` and the docs that describe it."""

import json
import shutil
from pathlib import Path

import powerplan.cli
from powerplan.cli import main
from powerplan.optimal import SearchTooLarge

ROOT = Path(__file__).resolve().parent.parent


def setup_workdir(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    shutil.copy(ROOT / "data" / "fleet.json", data_dir / "fleet.json")
    shutil.copy(ROOT / "data" / "workloads.json", data_dir / "workloads.json")
    monkeypatch.chdir(tmp_path)
    return tmp_path / "t.jsonl"


def test_plan_trace_writes_spans_and_reports_count(tmp_path, monkeypatch, capsys):
    p = setup_workdir(tmp_path, monkeypatch)

    exit_code = main(["plan", "--trace", str(p)])

    assert exit_code == 0
    lines = p.read_text().splitlines()
    assert len(lines) == 7
    assert json.loads(lines[-1])["name"] == "powerplan.plan"
    out = capsys.readouterr().out
    assert out.splitlines()[-1] == f"trace: 7 spans -> {p}"


def test_plan_trace_with_compare_optimal(tmp_path, monkeypatch, capsys):
    p = setup_workdir(tmp_path, monkeypatch)

    exit_code = main(["plan", "--compare-optimal", "--trace", str(p)])

    assert exit_code == 0
    out = capsys.readouterr().out
    assert out.splitlines()[-1] == f"trace: 7 spans -> {p}"


def test_trace_still_written_when_search_too_large(tmp_path, monkeypatch, capsys):
    p = setup_workdir(tmp_path, monkeypatch)

    def too_large(*args, **kwargs):
        raise SearchTooLarge("too large")

    monkeypatch.setattr(powerplan.cli, "compare", too_large)

    exit_code = main(["plan", "--compare-optimal", "--trace", str(p)])

    assert exit_code == 3
    assert len(p.read_text().splitlines()) == 7
    captured = capsys.readouterr()
    assert captured.out.splitlines()[-1] == f"trace: 7 spans -> {p}"
    assert "too large" in captured.err


def test_no_trace_by_default(tmp_path, monkeypatch, capsys):
    setup_workdir(tmp_path, monkeypatch)

    exit_code = main(["plan"])

    assert exit_code == 0
    out = capsys.readouterr().out
    assert not any(line.startswith("trace:") for line in out.splitlines())
    assert {entry.name for entry in tmp_path.iterdir()} == {"audit.jsonl", "data"}


def test_docs_mention_the_span_log_and_flag():
    assert "span log" in (ROOT / "README.md").read_text()
    assert "--trace" in (ROOT / "HANDOFF.md").read_text()

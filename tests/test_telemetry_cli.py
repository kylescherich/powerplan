"""Tests for `plan --telemetry`."""

import shutil
from pathlib import Path

from powerplan.cli import main

ROOT = Path(__file__).resolve().parent.parent


def setup_workdir(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    shutil.copy("data/fleet.json", data_dir / "fleet.json")
    shutil.copy("data/workloads.json", data_dir / "workloads.json")
    shutil.copytree("examples/telemetry", tmp_path / "tel")
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_plan_with_telemetry_defers_w005(tmp_path, monkeypatch, capsys):
    setup_workdir(tmp_path, monkeypatch)

    assert main(["plan", "--telemetry", "tel"]) == 0

    out = capsys.readouterr().out
    assert (
        out.splitlines()[0]
        == "telemetry: 3 GPU power samples, 1 demand-response events"
    )
    blocks = [b for b in out.split("\n\n") if "(W-005)" in b]
    assert len(blocks) == 1
    assert "starts at hour 16" in blocks[0]


def test_plan_with_telemetry_and_compare_optimal(tmp_path, monkeypatch, capsys):
    setup_workdir(tmp_path, monkeypatch)

    assert main(["plan", "--telemetry", "tel", "--compare-optimal"]) == 0

    out = capsys.readouterr().out
    assert "gap 0.0000" in out
    assert "moved: none" in out


def test_empty_telemetry_directory_returns_2(tmp_path, monkeypatch, capsys):
    setup_workdir(tmp_path, monkeypatch)
    (tmp_path / "empty").mkdir()

    assert main(["plan", "--telemetry", "empty"]) == 2

    captured = capsys.readouterr()
    assert "no telemetry files in" in captured.err
    assert captured.out == ""


def test_only_dr_events_file_is_enough(tmp_path, monkeypatch, capsys):
    setup_workdir(tmp_path, monkeypatch)
    only_dr = tmp_path / "only_dr"
    only_dr.mkdir()
    shutil.copy("tel/dr_events.json", only_dr / "dr_events.json")

    assert main(["plan", "--telemetry", "only_dr"]) == 0

    first = capsys.readouterr().out.splitlines()[0]
    assert first == "telemetry: 0 GPU power samples, 1 demand-response events"


def test_docs_mention_replay_and_flag():
    assert "replay" in (ROOT / "README.md").read_text()
    assert "--telemetry" in (ROOT / "HANDOFF.md").read_text()

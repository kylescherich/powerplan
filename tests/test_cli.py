"""Tests for powerplan.cli module."""

import shutil
from pathlib import Path

import pytest

from powerplan.cli import main


def test_plan_basic(tmp_path, monkeypatch, capsys):
    """Test basic plan command."""
    # Copy data files to tmp_path
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    shutil.copy("data/fleet.json", data_dir / "fleet.json")
    shutil.copy("data/workloads.json", data_dir / "workloads.json")
    
    monkeypatch.chdir(tmp_path)
    
    exit_code = main(["plan"])
    
    assert exit_code == 0
    captured = capsys.readouterr()
    assert len(captured.out) > 0
    # Check that at least one site is mentioned (SITE-OR, SITE-TX, or SITE-EU)
    assert any(site in captured.out for site in ["SITE-OR", "SITE-TX", "SITE-EU"])


def test_plan_with_weights(tmp_path, monkeypatch, capsys):
    """Test plan command with custom weights."""
    # Copy data files to tmp_path
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    shutil.copy("data/fleet.json", data_dir / "fleet.json")
    shutil.copy("data/workloads.json", data_dir / "workloads.json")
    
    monkeypatch.chdir(tmp_path)
    
    exit_code = main(["plan", "--w-carbon", "0.6", "--w-cost", "0.2", "--w-runtime", "0.2"])
    
    assert exit_code == 0
    captured = capsys.readouterr()
    assert len(captured.out) > 0
    assert any(site in captured.out for site in ["SITE-OR", "SITE-TX", "SITE-EU"])


def test_whatif_offline(tmp_path, monkeypatch, capsys):
    """Test whatif with --offline."""
    # Copy data files to tmp_path
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    shutil.copy("data/fleet.json", data_dir / "fleet.json")
    shutil.copy("data/workloads.json", data_dir / "workloads.json")
    
    monkeypatch.chdir(tmp_path)
    
    exit_code = main(["whatif", "--offline", "SITE-OR"])
    
    assert exit_code == 0
    captured = capsys.readouterr()
    assert len(captured.out) > 0
    assert any(site in captured.out for site in ["SITE-OR", "SITE-TX", "SITE-EU"])


def test_whatif_curtail(tmp_path, monkeypatch, capsys):
    """Test whatif with --curtail."""
    # Copy data files to tmp_path
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    shutil.copy("data/fleet.json", data_dir / "fleet.json")
    shutil.copy("data/workloads.json", data_dir / "workloads.json")
    
    monkeypatch.chdir(tmp_path)
    
    exit_code = main(["whatif", "--curtail", "SITE-TX:0.45"])
    
    assert exit_code == 0
    captured = capsys.readouterr()
    assert len(captured.out) > 0
    assert any(site in captured.out for site in ["SITE-OR", "SITE-TX", "SITE-EU"])


def test_whatif_degrade(tmp_path, monkeypatch, capsys):
    """Test whatif with --degrade."""
    # Copy data files to tmp_path
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    shutil.copy("data/fleet.json", data_dir / "fleet.json")
    shutil.copy("data/workloads.json", data_dir / "workloads.json")
    
    monkeypatch.chdir(tmp_path)
    
    exit_code = main(["whatif", "--degrade", "SITE-OR:or-mi300:64"])
    
    assert exit_code == 0
    captured = capsys.readouterr()
    assert len(captured.out) > 0
    assert any(site in captured.out for site in ["SITE-OR", "SITE-TX", "SITE-EU"])


def test_whatif_price(tmp_path, monkeypatch, capsys):
    """Test whatif with --price."""
    # Copy data files to tmp_path
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    shutil.copy("data/fleet.json", data_dir / "fleet.json")
    shutil.copy("data/workloads.json", data_dir / "workloads.json")
    
    monkeypatch.chdir(tmp_path)
    
    exit_code = main(["whatif", "--price", "SITE-TX:2.5"])
    
    assert exit_code == 0
    captured = capsys.readouterr()
    assert len(captured.out) > 0
    assert any(site in captured.out for site in ["SITE-OR", "SITE-TX", "SITE-EU"])


def test_invalid_argument(tmp_path, monkeypatch):
    """Test that invalid arguments result in non-zero exit code."""
    # Copy data files to tmp_path
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    shutil.copy("data/fleet.json", data_dir / "fleet.json")
    shutil.copy("data/workloads.json", data_dir / "workloads.json")
    
    monkeypatch.chdir(tmp_path)
    
    # argparse raises SystemExit on invalid arguments
    with pytest.raises(SystemExit) as exc_info:
        main(["--invalid-argument"])
    
    # Assert non-zero exit code
    assert exc_info.value.code != 0

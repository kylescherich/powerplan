import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from powerplan import whatif  # noqa: E402
from powerplan.engine import plan  # noqa: E402
from powerplan.models import load_fleet, load_workloads  # noqa: E402

DATA = Path(__file__).resolve().parents[1] / "data"


def fresh():
    return load_fleet(DATA / "fleet.json"), load_workloads(DATA / "workloads.json")


def test_data_residency_is_honoured():
    fleet, workloads = fresh()
    p = plan(fleet, workloads)
    eu = next(x for x in p.placements if x.workload_id == "W-002")
    assert eu.chosen.site_id == "SITE-EU"


def test_memory_constraint_filters_pools():
    fleet, workloads = fresh()
    p = plan(fleet, workloads)
    # W-004 needs 140GB HBM; only MI300X (192GB) qualifies.
    rlhf = next(x for x in p.placements if x.workload_id == "W-004")
    assert rlhf.chosen.accelerator == "MI300X"


def test_power_headroom_never_exceeded():
    fleet, workloads = fresh()
    plan(fleet, workloads)
    for site in fleet.sites:
        assert site.committed_kw <= site.power_capacity_kw - site.baseline_load_kw + 1e-6


def test_accelerator_counts_never_oversubscribed():
    fleet, workloads = fresh()
    plan(fleet, workloads)
    for site in fleet.sites:
        for pool in site.pools:
            assert 0 <= pool.available <= pool.total


def test_carbon_weight_shifts_placement_to_clean_grid():
    fleet, workloads = fresh()
    cheap = plan(fleet, workloads, {"cost": 1.0, "carbon": 0.0, "runtime": 0.0})
    fleet, workloads = fresh()
    clean = plan(fleet, workloads, {"cost": 0.0, "carbon": 1.0, "runtime": 0.0})
    assert clean.total_carbon_kg < cheap.total_carbon_kg


def test_site_failure_triggers_replan():
    fleet, workloads = fresh()
    broken = whatif.site_offline(fleet, "SITE-OR")
    base, scen = whatif.run_scenario(fleet, workloads, broken, None)
    assert all(p.chosen.site_id != "SITE-OR" for p in scen.placements)
    assert "SITE-OR" in whatif.diff(base, scen) or scen.total_cost != base.total_cost


def test_every_placement_records_its_rejects():
    fleet, workloads = fresh()
    p = plan(fleet, workloads)
    assert all(x.considered >= 1 for x in p.placements)
    assert any(x.rejected for x in p.placements)


def test_audit_entry_is_valid_json(tmp_path):
    from powerplan import audit

    fleet, workloads = fresh()
    p = plan(fleet, workloads)
    log = tmp_path / "audit.jsonl"
    run_id = audit.record(p, fleet, workloads, log)
    entry = json.loads(log.read_text().strip())
    assert entry["run_id"] == run_id
    assert entry["decisions"]
    assert entry["fleet_fingerprint"]

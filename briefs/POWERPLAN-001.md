# POWERPLAN-001 — tests for the untested modules (no production code changes)

- From → To: HUB → devws-cloud runner
- Created: 2026-10-10
- Status: queued
- unattended: yes
- model: sonnet
- Decision: DEC-125 (CTR-DEVWS-CLOUD-001)

## Goal
`tests/test_engine.py` covers `engine.py` (8 tests). `models.py`, `whatif.py`, `explain.py`, `audit.py` and `cli.py` have no tests. Add them, one module per step, following `CLAUDE.md`: stdlib only, pytest, never change behaviour to make a test pass. **Do not edit anything under `powerplan/`.** If a test exposes a real bug, keep the test, mark it `@pytest.mark.xfail(strict=True, reason="...")` with the reason, and name it in the report; a follow-up brief fixes the code.

Read `README.md`, `HANDOFF.md` and `CLAUDE.md` first; `data/fleet.json` and `data/workloads.json` are the fixtures to use (copy them with `tmp_path` when a test mutates them).

## Step 1 — models
Add `tests/test_models.py`: `AcceleratorPool.draw_kw`, `Site.headroom_kw` / `facility_kw` / `pool` (including the unknown-id error), `Workload.runtime_hours`, `Fleet.site` / `reset`, `load_fleet` / `load_workloads` round-trip on the data files, `to_dict`.

Live command:
`python3 -m pytest tests -q`

## Step 2 — whatif
Add `tests/test_whatif.py`: `site_offline`, `curtail`, `pool_degraded`, `price_spike` each return a **new** fleet and leave the input untouched; `diff` output names the moved workloads; `run_scenario` on the data files.

Live command:
`python3 -m pytest tests -q`

## Step 3 — explain and audit
Add `tests/test_explain_audit.py`: `explain` mentions the chosen site and every reject's reason; `summarise` counts match the plan; `audit.fingerprint` is stable for equal input and differs for different input; `audit.record` appends valid JSON lines and never rewrites earlier lines (use `tmp_path`).

Live command:
`python3 -m pytest tests -q`

## Step 4 — cli
Add `tests/test_cli.py` calling `powerplan.cli.main(argv)` directly (no subprocess): `plan`, `plan --w-carbon 0.6 --w-cost 0.2 --w-runtime 0.2`, each `whatif` form from the README, and one invalid argument → non-zero exit. Capture output with `capsys`; audit log to `tmp_path` if the CLI allows a path, otherwise run in `tmp_path` via `monkeypatch.chdir`.

Live command:
`python3 -m pytest tests -q`

## Report (`reports/POWERPLAN-001.md` on branch `brief/POWERPLAN-001`)
Real output only (DEC-062): start/end UTC, host/user, per-step Aider exit and cost line, the full final `python3 -m pytest tests -q` output, test count before (8) and after, `git log --oneline -5`, the list of any `xfail` tests with their reasons, and one line of deviations. Every leak/validity assertion first asserts the output is non-empty (DEC-071).

## Rules
Branch `brief/POWERPLAN-001` only; never write `main`. Files under `powerplan/`, `data/`, `README.md`, `HANDOFF.md`, `CLAUDE.md` are read-only for this brief. Stop at the first failing step and still write the report. No new dependencies.

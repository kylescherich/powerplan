# POWERPLAN-002 — finish POWERPLAN-001: cli tests and one vacuous test (no production code changes)

- From → To: HUB → devws-cloud runner
- Created: 2026-10-10
- Status: queued
- unattended: yes
- model: sonnet
- Decision: DEC-126 (CTR-DEVWS-CLOUD-001)

## Goal
`main` now contains the POWERPLAN-001 tests (Kyle merged the branch). POWERPLAN-001 step 4 produced no file, and `tests/test_whatif.py::test_diff_output_names_moved_workloads` asserts nothing (`len(output) >= 0`). Fix both. **Do not edit anything under `powerplan/`.** Same rules as POWERPLAN-001: stdlib only, strict `xfail` with a reason for any real bug, never change behaviour to make a test pass.

## Step 1 — cli
Add `tests/test_cli.py` calling `powerplan.cli.main(argv)` directly (no subprocess): `["plan"]`, `["plan", "--w-carbon", "0.6", "--w-cost", "0.2", "--w-runtime", "0.2"]`, each `whatif` form from the README (`--offline SITE-OR`, `--curtail SITE-TX:0.45`, `--degrade SITE-OR:or-mi300:64`, `--price SITE-TX:2.5`), and one invalid argument that must give a non-zero exit (argparse raises `SystemExit`; assert its code). Capture output with `capsys` and assert it is non-empty and names at least one site. Run inside `tmp_path` via `monkeypatch.chdir` after copying `data/` there, so the audit log never lands in the repo.

Live command:
`python3 -m pytest tests/test_cli.py -q`

## Step 2 — make the diff test real
Rewrite `test_diff_output_names_moved_workloads`: take the baseline plan, find a site that holds at least one placement, take it offline, re-plan, and assert that every workload whose site changed is named in `diff(baseline, scenario)` and that the output is non-empty. If no workload moves for any site in the data, the test must fail loudly, not pass.

Live command:
`python3 -m pytest tests/test_whatif.py -q`

## Step 3 — whole suite
No file changes. Live command only.

Live command:
`python3 -m pytest tests -q`

## Rules
Branch `brief/POWERPLAN-002` only; never write `main`. `powerplan/`, `data/`, `README.md`, `HANDOFF.md`, `CLAUDE.md` read-only. Stop at the first failing step and still write the report. No new dependencies.

# POWERPLAN-011 — exact search: tests where power is the binding limit

- From → To: HUB → devws-cloud runner
- Created: 2026-10-16
- Status: queued
- unattended: yes
- model: anthropic/claude-sonnet-5-5
- Decision: DEC-275 (DEC-261 oracle per rule; CTR-DEVWS-CLOUD-001 0.1.5)

## Goal
The exact search in `powerplan/optimal.py` is on `main` and correct, but no test has a case where **site power** (not accelerator count) decides the optimum, so removing the per-hour power check from the search would go unnoticed. This brief adds that test. **Test only: do not change any file under `powerplan/`.** If a test you write fails, re-read the expected values below; if you still think the code is wrong, say so in your reply and stop. Every existing test file is read-only.

**Fixture W** (built inside the test): two sites, each with `baseline_load_kw=0`, `pue=1.0`, `carbon_g_per_kwh=100` and one pool (`pool_id="p"+site_id`, `accelerator="X"`, `total=200`, `available=200`, `tdp_watts=1000`, `memory_gb=80`, `perf=1.0`, `utilization=1.0`): S1 region r1, `price_per_kwh=0.10`, **`power_capacity_kw=100`**; S2 region r2, `price_per_kwh=0.30`, `power_capacity_kw=1000`. Weights `{"cost": 1.0, "carbon": 0.0, "runtime": 0.0}`. Workloads A (60 GPUs, `ref_hours=2`, priority 1) and B (60 GPUs, `ref_hours=2`, priority 2). Both would fit S1 by accelerator count, but 60 + 60 = 120 kW > 100 kW. The expected values were computed by the Hub in advance; they are the oracle.

## Step 1 — power-bound optimum tests
Add `tests/test_optimal_power.py`:
1. **Power decides:** `solve` on fixture W (both not interruptible) gives A → S1 start 0 and B → S2 start 0; placed {1: 1, 2: 1}; score 2.0 (±1e-9); total cost 48.0 (±1e-9).
2. **Per hour, not per window:** same fixture but B `interruptible=True` → A → S1 start 0, **B → S1 start 2** (hours 0–1 are full; starts 2 … 22 tie on score and the search keeps the earliest); score 1.0 (±1e-9); total cost 24.0 (±1e-9).
3. `compare` on case 1 reports `same_work_placed` True, `score_gap` 0.0 (±1e-9) and `moved` empty (the greedy finds the same plan here).

Files: tests/test_optimal_power.py powerplan/optimal.py powerplan/engine.py powerplan/models.py

Live command:
`python3 -m pytest tests/test_optimal_power.py tests -q`

## Rules
Branch `brief/POWERPLAN-011` only; never write `main`. Everything under `powerplan/`, the data folder, the repo guide file and every existing test file are read-only. No new dependencies. If a test fails, name it and stop — do not edit code or existing tests.

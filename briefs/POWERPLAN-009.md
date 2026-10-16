# POWERPLAN-009 — per-hour power headroom: boundary test, explanation and docs

- From → To: HUB → devws-cloud runner
- Created: 2026-10-16
- Status: queued
- unattended: yes
- model: anthropic/claude-sonnet-5-5
- Decision: DEC-272 (DEC-263 four-dimension acceptance; DEC-266 `Files:` rule; CTR-DEVWS-CLOUD-001 0.1.4)

## Goal
Per-hour power headroom is already on `main` (`Site.committed_kw_by_hour`, `Site.headroom_kw_at`, per-hour feasibility, `Candidate.deferred_for_capacity`, the new `plan.notes` sentence). This brief adds one missing boundary test and finishes the feature's explanation and docs. Rules of this repo: stdlib only; the greedy stays greedy and honest; never drop a constraint to place a workload.

Every step's `Files:` line names `powerplan/models.py` and `powerplan/engine.py` so both are always in view. **Do not change the engine or the model in this brief** — they are correct; if a test you write fails, re-read the expected values below before touching any code, and if you still think the code is wrong, say so in your reply and stop. Do not edit any file outside the step's `Files:` line. Every existing test file is read-only: if an existing test fails, the fix is in the code you wrote in this brief, never in the test.

**Test fixture** (1 kW per GPU), built inside each test: one site `S`, region `r`, `power_capacity_kw=100`, `baseline_load_kw=0`, `pue=1.0`, `price_per_kwh=0.10`, `carbon_g_per_kwh=100`, one pool `p` (`accelerator="X"`, `total=200`, `available=200`, `tdp_watts=1000`, `memory_gb=80`, `perf=1.0`, `utilization=1.0`). Every placement test first asserts the plan has at least one placement. The expected values below were computed by the Hub in advance; they are the oracle.

## Step 1 — exact-fit boundary test (test only)
Add `tests/test_hourly_capacity_boundary.py` (fixture above): A (80 GPUs, 5 h, priority 1, not interruptible), B (20 GPUs, 3 h, priority 2, not interruptible) and C (21 GPUs, 1 h, priority 3, interruptible) in one plan →
1. **An exact fit is allowed:** B is placed at hour 0 (80 + 20 = 100 = capacity); nothing is unplaced.
2. `committed_kw_by_hour` is 100 for hours 0–2, 80 for hours 3–4, 21 for hour 5, and 0 for hours 6–23; `committed_kw == 100`.
3. C starts at hour 5 with `deferred_for_capacity` True (21 kW does not fit in hours 0–4).

No change to `powerplan/` in this step.

Files: tests/test_hourly_capacity_boundary.py powerplan/engine.py powerplan/models.py

Live command:
`python3 -m pytest tests/test_hourly_capacity_boundary.py tests -q`

## Step 2 — explanation and docs
`powerplan/explain.py`: in `explain()`, when the chosen candidate's `deferred_for_capacity` is True, the start-hour line reads exactly `  starts at hour H (UTC); hour 0 had no power headroom` (H = the start hour) and does **not** claim any saving or extra emission. When it is False, the existing start-hour wording is unchanged.
`README.md`: a short paragraph explaining per-hour headroom (a job only uses capacity in the hours it runs; an interruptible job may start later when early hours are full; the words `per hour` must appear).
`HANDOFF.md`: move time-indexed power capacity from "not modelled" to done (keep the words `time-indexed` in the text); still not modelled: mid-run preemption, site-local time, sourced curve data; update the "Written at commit" line to the current `main` commit.

Add `tests/test_capacity_explain_docs.py`: using the step-1 plan, C's explanation contains `hour 0 had no power headroom` and does not contain `saved` or `emits`; a placement deferred for price (a site with a price curve, no capacity pressure, an interruptible job that starts after hour 0) still contains `saved`; a placement at hour 0 has no start-hour line; `README.md` contains `per hour`; `HANDOFF.md` contains `time-indexed`.

Files: powerplan/explain.py README.md HANDOFF.md tests/test_capacity_explain_docs.py powerplan/engine.py powerplan/models.py

Live command:
`python3 -m pytest tests/test_capacity_explain_docs.py tests -q`

## Rules
Branch `brief/POWERPLAN-009` only; never write `main`. The repo guide file, the data folder, and every existing test file are read-only. No new dependencies. Stop at the first failing step and still write the report; if an existing test breaks, name it and stop — do not edit it.

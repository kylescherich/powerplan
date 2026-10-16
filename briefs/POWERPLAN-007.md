# POWERPLAN-007 — power headroom per hour (third attempt; wider Files: lines)

- From → To: HUB → devws-cloud runner
- Created: 2026-10-16
- Status: queued
- unattended: yes
- model: anthropic/claude-sonnet-5-5
- Decision: DEC-270 (DEC-263 four-dimension acceptance; DEC-266 `Files:` rule; CTR-DEVWS-CLOUD-001 0.1.4)

## Goal
Earlier attempts stopped before finishing and are not merged, so this brief starts again from `main`. Today a placed job's power is committed against its site for the whole 24-hour window, whatever hour it starts. Make power headroom **per hour**: a job only uses capacity in the hours it actually runs, and an interruptible job may start later when the early hours are full. Rules of this repo: stdlib only; the greedy stays greedy and honest; never drop a constraint to place a workload.

Every step's `Files:` line names `powerplan/models.py` and `powerplan/engine.py` so both are always in view; change only what that step asks for. Files marked read-only below must not be edited even though they are listed. Do not edit any file outside the step's `Files:` line; if you think another file must change, say so in your reply and stop.

## Design (fixed; do not change it)
- **Window:** a job starting at hour `s` with runtime `r` occupies hours `(s + i) % 24` for `i` in `0 … min(24, ceil(r)) − 1` (a 1.5 h job occupies 2 hours; a job of 24 h or more occupies all 24).
- **Site state:** `Site.committed_kw_by_hour: list[float]` (24 zeros, a new field placed after `committed_kw`, default via `field(default_factory=...)`); `Site.headroom_kw_at(hour)` = `0` if offline, else `power_capacity_kw − baseline_load_kw − committed_kw_by_hour[hour % 24]`. `Fleet.reset()` zeroes the list too. Keep `committed_kw` and `headroom_kw` as they are, with `committed_kw` set to `max(committed_kw_by_hour)` after every commit (the peak).
- **Allowed starts** (unchanged from POWERPLAN-004): non-interruptible → `[0]`; interruptible → `0 … 23`, or `0 … min(23, floor(deadline − runtime))` with a deadline.
- **Feasible starts:** the allowed starts `s` where the job's facility kW ≤ `headroom_kw_at(h)` for **every** hour `h` of its window.
- **Rejection:** if no start is feasible the `(site, pool)` is rejected. Non-interruptible reason: `needs {kW}kW, only {H}kW headroom` (H = the smallest hourly headroom in the hour-0 window, `:.0f`). Interruptible reason: `needs {kW}kW, no allowed start hour has that headroom`.
- **Start choice:** only among feasible starts. No curves → the earliest feasible start. With curves → the POWERPLAN-004 rule (ratio to the **hour-0** values, ties → earliest) applied to the feasible starts only. `deferral_saved_*` stay "hour-0 value minus chosen value".
- **Capacity flag:** `Candidate.deferred_for_capacity: bool = False` (new field placed right after `components` and **before** `start_hour` — an existing test requires the last three fields to stay `start_hour`, `deferral_saved_usd`, `deferral_saved_kg`) — True when hour 0 was an allowed start but not feasible.
- **Commit:** add the job's facility kW to `committed_kw_by_hour[h]` for every hour of its window, then `committed_kw = max(committed_kw_by_hour)`.
- **Note:** replace the power-headroom sentence in `plan.notes` with exactly: `Power headroom is checked per hour of each job's window (time-slicing of capacity over the 24-hour window); greedy order decides who gets contested hours.`
- **Existing tests must keep passing unchanged** (all 84 on `main`). Do not edit any existing test file. If one breaks, stop and name it.

**Test fixture used in steps 2 and 3** (1 kW per GPU), built inside each test: one site `S`, region `r`, `power_capacity_kw=100`, `baseline_load_kw=0`, `pue=1.0`, `price_per_kwh=0.10`, `carbon_g_per_kwh=100`, one pool `p` (`accelerator="X"`, `total=200`, `available=200`, `tdp_watts=1000`, `memory_gb=80`, `perf=1.0`, `utilization=1.0`). Every placement test first asserts the plan has at least one placement. The expected values below were computed by the Hub in advance; they are the oracle.

## Step 1 — the model
The model only: the new `Site` field, `headroom_kw_at`, and the `reset` change. No engine changes in this step.

Add `tests/test_hourly_capacity_model.py`: a new site has 24 zeros; `headroom_kw_at(h)` = capacity − baseline − that hour's commitment, wraps (`hour 25` → index 1), is 0 for an offline site; `Fleet.reset()` zeroes the list.

Files: powerplan/models.py powerplan/engine.py tests/test_hourly_capacity_model.py

Live command:
`python3 -m pytest tests/test_hourly_capacity_model.py tests -q`

## Step 2 — the engine commits per hour (feasibility unchanged)
`powerplan/engine.py`: add a helper that returns a job's window hours (Design: Window) and change the commit to fill `committed_kw_by_hour` for the window, then `committed_kw = max(committed_kw_by_hour)`. Do **not** change feasibility, start choice, rejection reasons or notes in this step.

Add `tests/test_hourly_commit.py` (fixture above, each job planned alone unless stated):
1. A (80 GPUs, 5 h, not interruptible) → `committed_kw_by_hour` is 80 for hours 0–4 and 0 for hours 5–23; `committed_kw == 80`.
2. H (10 GPUs, 1.5 h, not interruptible) → 10 at hours 0 and 1, 0 elsewhere.
3. L (10 GPUs, 30 h, not interruptible) → 10 at all 24 hours.
4. Wrap: price curve 0.2 everywhere except 0.01 at hours 22, 23, 0, 1; A (80 GPUs, 4 h, interruptible) → starts 22; 80 at hours 22, 23, 0, 1 and 0 elsewhere.
5. Overlap adds up: P (10 GPUs, 2 h, priority 1, not interruptible) and Q (10 GPUs, 3 h, priority 2, not interruptible) in one plan → both start 0; 20 at hours 0–1, 10 at hour 2, 0 elsewhere; `committed_kw == 20`.

Files: powerplan/engine.py powerplan/models.py tests/test_hourly_commit.py

Live command:
`python3 -m pytest tests/test_hourly_commit.py tests -q`

## Step 3 — feasible starts, rejection, start choice, flag, note
`powerplan/engine.py`: feasible starts, rejection reasons, start choice among feasible starts, `deferred_for_capacity` (in `Candidate` in `engine.py`, after `components`, before `start_hour`), and the `plan.notes` sentence. The old whole-window check in `_infeasible_reason` (`facility_kw > site.headroom_kw`) is replaced by the per-hour rule.

Add `tests/test_hourly_capacity.py` (fixture above):
1. **Contention, interruptible waits:** A (80 GPUs, 5 h, priority 1, not interruptible) and B (80 GPUs, 3 h, priority 2, interruptible). A starts 0; **B starts 5** with `deferred_for_capacity` True; `committed_kw_by_hour` is 80 for hours 0–7 and 0 for hours 8–23; `committed_kw == 80`.
2. **Contention, non-interruptible is rejected:** same, but B not interruptible → B unplaced with reason `needs 80kW, only 20kW headroom`.
3. **A 24 h+ job fills every hour:** L (80 GPUs, 30 h, priority 1) and C (80 GPUs, 1 h, priority 2, interruptible) → L at 0, C unplaced with reason `needs 80kW, no allowed start hour has that headroom`.
4. **Windows wrap past midnight:** price curve 0.2 everywhere except 0.01 at hours 22, 23, 0, 1. A (80 GPUs, 4 h, priority 1, interruptible) and B (80 GPUs, 2 h, priority 2, not interruptible) → **A starts 22**; `committed_kw_by_hour` is 80 at hours 22, 23, 0, 1 and 0 elsewhere; B unplaced (`needs 80kW, only 20kW headroom`).
5. **Zero baseline:** price curve 0.1 everywhere except 0.0 at hour 0; Z (1 GPU, 1 h, interruptible); weights cost 1, carbon 0, runtime 0 → no error, Z starts 0, `deferred_for_capacity` False.
6. **No regression on the real data:** on `data/fleet.json` + `data/workloads.json` with default weights, W-003 starts 10, W-005 starts 8, every other workload starts 0, nothing unplaced, and no hour of any site exceeds capacity − baseline.
7. The new `plan.notes` sentence is present and the old sentence `Power headroom checked at placement time; no explicit time-slicing of capacity.` is gone.
8. `deferred_for_capacity` comes after `components` and before `start_hour` in `dataclasses.fields(Candidate)`.

Files: powerplan/engine.py powerplan/models.py tests/test_hourly_capacity.py data/fleet.json data/workloads.json

(`data/fleet.json` and `data/workloads.json` are listed only so test 6 can read them: **read-only, do not edit**.)

Live command:
`python3 -m pytest tests/test_hourly_capacity.py tests -q`

## Step 4 — explanation and docs
`powerplan/explain.py`: when `deferred_for_capacity` is True, the start-hour line reads `  starts at hour H (UTC); hour 0 had no power headroom` and does **not** claim any saving. Otherwise unchanged.
`README.md`: explain per-hour headroom. `HANDOFF.md`: move time-indexed power capacity from "not modelled" to done (keep the words `time-indexed` in the text); still not modelled: mid-run preemption, site-local time, sourced curve data; update the "Written at commit" line.

Add `tests/test_capacity_explain_docs.py`: a capacity-deferred placement's explanation contains `no power headroom` and not `saved`; a normal deferred placement still says `saved`; `README.md` mentions `per hour`; `HANDOFF.md` mentions `time-indexed`.

Files: powerplan/explain.py powerplan/engine.py powerplan/models.py README.md HANDOFF.md tests/test_capacity_explain_docs.py

Live command:
`python3 -m pytest tests/test_capacity_explain_docs.py tests -q`

## Rules
Branch `brief/POWERPLAN-007` only; never write `main`. The repo guide file, the data folder, and every existing test file are read-only. No new dependencies. Stop at the first failing step and still write the report; if an existing test breaks, name it and stop — do not edit it.

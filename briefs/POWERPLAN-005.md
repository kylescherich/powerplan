# POWERPLAN-005 — power headroom per hour (time-indexed capacity)

- From → To: HUB → devws-cloud runner
- Created: 2026-10-15
- Status: queued
- unattended: yes
- model: anthropic/claude-sonnet-5-5
- Decision: DEC-264 (DEC-263 four-dimension acceptance; CTR-DEVWS-CLOUD-001 0.1.3)

## Goal
Today a placed job's power is committed against its site for the whole 24-hour window, whatever hour it starts (the note in `plan.notes` says so). Make power headroom **per hour**: a job only uses capacity in the hours it actually runs, and an interruptible job may start later when the early hours are full. Follow `CLAUDE.md` and `HANDOFF.md` (stdlib only; greedy stays greedy and honest; never drop a constraint to place a workload).

## Design (fixed; do not change it)
- **Window:** a job starting at hour `s` with runtime `r` occupies hours `(s + i) % 24` for `i` in `0 … min(24, ceil(r)) − 1` (a 1.5 h job occupies 2 hours; a job of 24 h or more occupies all 24).
- **Site state:** `Site.committed_kw_by_hour: list[float]` (24 zeros, a new field placed after `committed_kw`, default via `field(default_factory=...)`); `Site.headroom_kw_at(hour)` = `0` if offline, else `power_capacity_kw − baseline_load_kw − committed_kw_by_hour[hour % 24]`. `Fleet.reset()` zeroes the list too. Keep `committed_kw` and `headroom_kw` as they are, with `committed_kw` set to `max(committed_kw_by_hour)` after every commit (the peak).
- **Allowed starts** (unchanged from POWERPLAN-004): non-interruptible → `[0]`; interruptible → `0 … 23`, or `0 … min(23, floor(deadline − runtime))` with a deadline.
- **Feasible starts:** the allowed starts `s` where the job's facility kW ≤ `headroom_kw_at(h)` for **every** hour `h` of its window.
- **Rejection:** if no start is feasible the `(site, pool)` is rejected. Non-interruptible reason: `needs {kW}kW, only {H}kW headroom` (H = the smallest hourly headroom in the hour-0 window, `:.0f`). Interruptible reason: `needs {kW}kW, no allowed start hour has that headroom`.
- **Start choice:** only among feasible starts. No curves → the earliest feasible start. With curves → the POWERPLAN-004 rule (ratio to the **hour-0** values, ties → earliest) applied to the feasible starts only. `deferral_saved_*` stay "hour-0 value minus chosen value".
- **Capacity flag:** `Candidate.deferred_for_capacity: bool = False` (new, last field) — True when hour 0 was an allowed start but not feasible.
- **Commit:** add the job's facility kW to `committed_kw_by_hour[h]` for every hour of its window, then `committed_kw = max(committed_kw_by_hour)`.
- **Note:** replace the power-headroom sentence in `plan.notes` with exactly: `Power headroom is checked per hour of each job's window (time-slicing of capacity over the 24-hour window); greedy order decides who gets contested hours.`
- **Existing tests must keep passing unchanged** (all 84). Do not edit any existing test file. If one breaks, stop and name it.

## Step 1 — the model
`powerplan/models.py`: the new field, `headroom_kw_at`, and the `reset` change.

Add `tests/test_hourly_capacity_model.py`: a new site has 24 zeros; `headroom_kw_at(h)` = capacity − baseline − that hour's commitment, wraps (`hour 25` → index 1), is 0 for an offline site; `Fleet.reset()` zeroes the list.

Files: powerplan/models.py tests/test_hourly_capacity_model.py

Live command:
`python3 -m pytest tests/test_hourly_capacity_model.py tests -q`

## Step 2 — the engine
`powerplan/engine.py`: window, allowed/feasible starts, rejection reasons, start choice, capacity flag, commit, note.

Add `tests/test_hourly_capacity.py`. Every test builds this fixture (1 kW per GPU) and first asserts the plan is not empty: one site `S`, region `r`, `power_capacity_kw=100`, `baseline_load_kw=0`, `pue=1.0`, `price_per_kwh=0.10`, `carbon_g_per_kwh=100`, one pool `p` (`accelerator="X"`, `total=200`, `available=200`, `tdp_watts=1000`, `memory_gb=80`, `perf=1.0`, `utilization=1.0`). Expected results (the Hub computed these in advance; they are the oracle):
1. **Contention, interruptible waits:** A (80 GPUs, 5 h, priority 1, not interruptible) and B (80 GPUs, 3 h, priority 2, interruptible). A starts 0; **B starts 5** with `deferred_for_capacity` True; `committed_kw_by_hour` is 80 for hours 0–7 and 0 for hours 8–23; `committed_kw == 80`.
2. **Contention, non-interruptible is rejected:** same, but B not interruptible → B unplaced with reason `needs 80kW, only 20kW headroom`.
3. **A 24 h+ job fills every hour:** L (80 GPUs, 30 h, priority 1) and C (80 GPUs, 1 h, priority 2, interruptible) → L at 0, C unplaced with reason `needs 80kW, no allowed start hour has that headroom`.
4. **Windows wrap past midnight:** price curve 0.2 everywhere except 0.01 at hours 22, 23, 0, 1. A (80 GPUs, 4 h, priority 1, interruptible) and B (80 GPUs, 2 h, priority 2, not interruptible) → **A starts 22**; `committed_kw_by_hour` is 80 at hours 22, 23, 0, 1 and 0 elsewhere; B unplaced (`needs 80kW, only 20kW headroom`).
5. **Zero baseline:** price curve 0.1 everywhere except 0.0 at hour 0; Z (1 GPU, 1 h, interruptible); weights cost 1, carbon 0, runtime 0 → no error, Z starts 0.
6. **No regression on the real data:** on `data/fleet.json` + `data/workloads.json` with default weights, W-003 starts 10, W-005 starts 8, every other workload starts 0, nothing unplaced, and no hour of any site exceeds capacity − baseline.

Files: powerplan/engine.py tests/test_hourly_capacity.py

Live command:
`python3 -m pytest tests/test_hourly_capacity.py tests -q`

## Step 3 — explanation and docs
`powerplan/explain.py`: when `deferred_for_capacity` is True, the start-hour line reads `  starts at hour H (UTC); hour 0 had no power headroom` and does **not** claim any saving. Otherwise unchanged.
`README.md`: explain per-hour headroom. `HANDOFF.md`: move time-indexed power capacity from "not modelled" to done (keep the words `time-indexed` in the text); still not modelled: mid-run preemption, site-local time, sourced curve data; update the "Written at commit" line.

Add `tests/test_capacity_explain_docs.py`: a capacity-deferred placement's explanation contains `no power headroom` and not `saved`; a normal deferred placement still says `saved`; `README.md` mentions `per hour`; `HANDOFF.md` mentions `time-indexed`.

Files: powerplan/explain.py README.md HANDOFF.md tests/test_capacity_explain_docs.py

Live command:
`python3 -m pytest tests/test_capacity_explain_docs.py tests -q`

## Rules
Branch `brief/POWERPLAN-005` only; never write `main`. `CLAUDE.md`, `data/`, and every existing test file are read-only. No new dependencies. Stop at the first failing step and still write the report; if an existing test breaks, name it and stop — do not edit it.

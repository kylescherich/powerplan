# POWERPLAN-010 — exact reference search; report the greedy gap

- From → To: HUB → devws-cloud runner
- Created: 2026-10-16
- Status: queued
- unattended: yes
- model: anthropic/claude-sonnet-5-5
- Decision: DEC-274 (Kyle: stdlib exact search, not a solver dependency; DEC-263 four-dimension acceptance; CTR-DEVWS-CLOUD-001 0.1.5)

## Goal
Roadmap item 2: compare the greedy against a true optimum over the same candidates and **report the gap explicitly — never replace the greedy's numbers**. Kyle chose a **stdlib-only exact search** (branch and bound) instead of a solver dependency: exact for small fleets like the sample data, and it refuses with a clear error when a problem is too large. The greedy in `powerplan/engine.py` is **not changed** by this brief. Rules of this repo: stdlib only; never drop a constraint to place a workload; never claim a winner is better on every axis.

Every step's `Files:` line names `powerplan/engine.py` and `powerplan/models.py` so both are in view; **do not edit either**. Do not edit any file outside the step's `Files:` line. Every existing test file is read-only: if an existing test fails, the fix is in the code you wrote in this brief, never in the test; if you cannot fix it, stop and name the test.

## Design (fixed; do not change it)
New module `powerplan/optimal.py`. It may import from `powerplan.engine` (`DEFAULT_WEIGHTS`, `_allowed_starts`, `_order`, `_window_hours`, `plan`) and `powerplan.models`.

- **Option** (frozen dataclass): `workload_id, site_id, pool_id, start_hour, gpu_count, facility_kw, runtime_hours, cost_usd, carbon_kg, hours` (`hours` = tuple of window hours from `_window_hours(start_hour, runtime_hours)`).
- **`options_for(w, fleet) -> list[Option]`**, judged on an **empty** fleet (call `fleet.reset()` first in the callers): for each online site and each pool, skip unless the region is allowed (empty allowlist = anywhere), the accelerator is allowed (empty = any), `pool.total >= w.gpu_count`, `pool.memory_gb >= w.min_memory_gb`, and the deadline (if any) is `>= w.runtime_hours(pool)`. `facility_kw = site.facility_kw(pool.draw_kw(w.gpu_count))`; skip the pool if `facility_kw > power_capacity_kw − baseline_load_kw`. One Option per start in `_allowed_starts(w, runtime)`. Cost and carbon are integrated exactly as the engine does: slot `i` uses hour `(start + i) % 24` for `min(1, runtime − i)` hours; `cost = Σ facility_kw × hours × site.price_at(h)`, `carbon_kg = Σ facility_kw × hours × site.carbon_at(h) / 1000`.
- **Objective** (one definition for greedy and optimum, independent of order): reference totals over workloads that have at least one option: `C_ref = Σ_w min cost`, `K_ref = Σ_w min carbon`, `R_ref = Σ_w min runtime`. A placed option contributes `w_cost·cost/C_ref + w_carbon·carbon/K_ref + w_runtime·runtime/R_ref` (a term is 0 if its ref is 0). A plan's **key** is compared lexicographically: first, for each priority level from 1 (most important) upward, **more placed workloads is better**; then **lower total score is better**. Round the score to 9 decimals inside the key.
- **`Objective`** dataclass: `placed_by_priority: dict[int, int]`, `score: float`, `total_cost_usd: float`, `total_carbon_kg: float`. **`evaluate(assignment, workloads, options_by_workload, weights) -> Objective`** where `assignment` maps workload_id → Option or None.
- **`solve(fleet, workloads, weights=None, max_nodes=200_000) -> OptimalResult`** (`assignment`, `objective`, `nodes`): depth-first over workloads in `_order(workloads)`; per workload try its options sorted by `(contribution, site_id, pool_id, start_hour)`, then "unplaced" last. An option is usable only if its pool still has `gpu_count` accelerators (pool total minus options already chosen) and its site has `facility_kw` of headroom (capacity − baseline − chosen load) in **every** hour of its window. Prune a branch when its optimistic key (every remaining workload with options placed at its minimum contribution) is `>=` the best key found so far. Keep the **first** best found (strict `<`). Count one node per option tried and one per "unplaced" branch; when the count exceeds `max_nodes`, raise **`SearchTooLarge`** (a `RuntimeError`) with a message containing `too large for the stdlib search`.
- **`greedy_assignment(fleet, workloads, weights=None)`** → `(assignment, options_by_workload, plan)`: run the engine's `plan`, then map each placement to the Option with the same `(site_id, pool_id, start_hour)`; unplaced → None.
- **`compare(fleet, workloads, weights=None, max_nodes=200_000) -> GapReport`** with `greedy: Objective`, `optimum: Objective`, `same_work_placed: bool` (equal `placed_by_priority`), `score_gap: float | None` (`greedy.score − optimum.score` when `same_work_placed`, else None), `moved: list[tuple[str, str, str]]` (workload_id, greedy `SITE/POOL@H` or `unplaced`, optimum likewise; only workloads whose choice differs, in workload-id order).
- **`format_gap(report) -> str`**, exactly these lines (numbers as shown):
  ```
  greedy vs exact optimum (same objective, same constraints)
    placed by priority  greedy P1 1, P2 2, ...  optimum P1 1, P2 2, ...
    objective score     greedy 1.4734  optimum 1.1119  gap 0.3615
    total cost          greedy $1,128  optimum $1,307
    total carbon        greedy 5,640 kg  optimum 2,211 kg
    note: the optimum is worse on cost
    moved: W-001 SITE-TX/tx-h100@0 -> SITE-OR/or-h100@0; W-005 SITE-OR/or-h100@8 -> SITE-TX/tx-h100@12; W-006 SITE-OR/or-h100@0 -> SITE-OR/or-mi300@0
  ```
  (This is the real-data output; the Hub's prototype produced exactly these lines.)
  Priorities ascending; score `:.4f`; cost `$` + `:,.0f`; carbon `:,.0f` + ` kg`. When `same_work_placed` is False the score line ends `gap n/a (different work placed)` instead of `gap X`. When nothing moved the last line is `  moved: none`. Add one more line after the carbon line **only** when the optimum is worse on cost or on carbon: `  note: the optimum is worse on cost` / `worse on carbon` / `worse on cost and carbon` — never claim it is better on every axis.

**Test fixtures** (built inside the tests): sites with `power_capacity_kw=1000`, `baseline_load_kw=0`, `pue=1.0`, `carbon_g_per_kwh=100`, one pool each (`pool_id="p"+site_id`, `accelerator="X"`, `total=100`, `available=100`, `tdp_watts=1000`, `memory_gb=80` unless stated, `perf=1.0`, `utilization=1.0`); workloads 80 GPUs, 1 h, as stated. Weights `{"cost": 1.0, "carbon": 0.0, "runtime": 0.0}` unless stated.
- **X (greedy leaves higher-priority work unplaced):** S1 region r1 price 0.05; S2 region r2 price 0.20, `memory_gb=40`. A priority 1; B priority 2, `min_memory_gb=80`. Greedy: A→S1, B unplaced, placed {1: 1}, score 0.5, cost 4.0. Optimum: A→S2, B→S1, placed {1: 1, 2: 1}, score 2.5, cost 20.0.
- **Y (both placed, greedy costs more):** S1 r1 price 0.10; S2 r2 price 0.11; S3 r3 price 0.50. A priority 1 `allowed_regions=["r1","r2"]`; B priority 2 `allowed_regions=["r1","r3"]`. Greedy: A→S1, B→S3, score 3.0, cost 48.0. Optimum: A→S2, B→S1, score 1.05, cost 16.8; `score_gap` 1.95.
- **Z (no gap):** S1 r1 price 0.10; S2 r2 price 0.11; one workload A (10 GPUs, 1 h, priority 1). Greedy = optimum = S1, score 1.0, `moved` empty.
- **Real data** (`data/fleet.json` + `data/workloads.json`, default weights; both files read-only): option counts W-001 2, W-002 1, W-003 144, W-004 1, W-005 144, W-006 5. Greedy score 1.473375 (±1e-6), optimum score 1.111864 (±1e-6); same work placed (P1 1, P2 2, P3 1, P4 1, P5 1). Optimum assignment: W-001 SITE-OR/or-h100@0, W-002 SITE-EU/eu-h100@0, W-003 SITE-OR/or-h100@10, W-004 SITE-OR/or-mi300@0, W-005 SITE-TX/tx-h100@12, W-006 SITE-OR/or-mi300@0 (the Hub checked by brute force over all 1,513,800 combinations: this optimum is unique). Totals: greedy cost $1,128 / carbon 5,640 kg; optimum $1,307 / 2,211 kg.

## Step 1 — options and the objective
`powerplan/optimal.py`: `Option`, `options_for`, the integration helper, `Objective`, `evaluate` (no search yet).

Add `tests/test_optimal_objective.py`: real-data option counts; for each greedy placement on the real data the matching Option's `cost_usd` and `carbon_kg` equal the engine's `chosen` values (±1e-9); `evaluate` on fixture Y gives score 3.0 for {A: S1, B: S3} and 1.05 for {A: S2, B: S1}; on fixture X {A: S1, B: None} gives placed {1: 1} and score 0.5.

Files: powerplan/optimal.py tests/test_optimal_objective.py powerplan/engine.py powerplan/models.py data/fleet.json data/workloads.json

Live command:
`python3 -m pytest tests/test_optimal_objective.py tests -q`

## Step 2 — the exact search
`powerplan/optimal.py`: `SearchTooLarge`, `OptimalResult`, `solve`, `greedy_assignment`.

Add `tests/test_optimal_search.py`: fixtures X, Y and Z give the optimum stated above; the real data gives the optimum assignment and score stated above; `solve(..., max_nodes=10)` on the real data raises `SearchTooLarge` with `too large for the stdlib search`; **a brute-force cross-check** written in the test (`itertools.product` over each workload's options plus None, checking pool and per-hour power limits) gives the same key as `solve` on fixtures X and Y; `solve` leaves the fleet's `committed_kw_by_hour` at all zeros after it returns (it must not change fleet state).

Files: powerplan/optimal.py tests/test_optimal_search.py powerplan/engine.py powerplan/models.py data/fleet.json data/workloads.json

Live command:
`python3 -m pytest tests/test_optimal_search.py tests -q`

## Step 3 — the gap report and the CLI flag
`powerplan/optimal.py`: `GapReport`, `compare`, `format_gap`. `powerplan/cli.py`: add `--compare-optimal` to the `plan` subcommand only; when given, after the normal plan output and the audit line, print a blank line and `format_gap(compare(...))` with the same fleet, workloads and weights; on `SearchTooLarge` print the error message to stderr and return 3 (the normal plan output has already been printed). Without the flag the output is unchanged.

Add `tests/test_optimal_gap.py`: fixture Y report has `same_work_placed` True, `score_gap` 1.95 (±1e-9), and `moved` [("A", "S1/pS1@0", "S2/pS2@0"), ("B", "S3/pS3@0", "S1/pS1@0")]; fixture X report has `same_work_placed` False, `score_gap` None, and its text contains `gap n/a (different work placed)`; fixture Z text contains `moved: none` and no `note:` line; the real-data text contains `greedy 1.4734  optimum 1.1119  gap 0.3615`, `greedy $1,128  optimum $1,307`, `greedy 5,640 kg  optimum 2,211 kg` and `note: the optimum is worse on cost`; `main(["plan", "--compare-optimal", "--audit", <tmp file>])` returns 0 and its stdout contains `greedy vs exact optimum`; without the flag stdout does not contain it.

Files: powerplan/optimal.py powerplan/cli.py tests/test_optimal_gap.py powerplan/engine.py powerplan/models.py data/fleet.json data/workloads.json

Live command:
`python3 -m pytest tests/test_optimal_gap.py tests -q`

## Step 4 — docs
`README.md`: a short section on `plan --compare-optimal` (what it compares, that the greedy's numbers are never replaced, the lexicographic objective, and the size limit). `HANDOFF.md`: roadmap item 2 marked done as a stdlib exact search (not a MILP), with the size limit and that a real solver is the step when fleets outgrow it; replace the stale paragraph that begins `**No time dimension at all.**` with an accurate one (jobs now have start hours and per-hour power, but there is still no queueing beyond 24 hours and no preemption).

Add `tests/test_optimal_docs.py`: `README.md` contains `--compare-optimal`; `HANDOFF.md` no longer contains `No time dimension at all` and contains `exact search`.

Files: README.md HANDOFF.md tests/test_optimal_docs.py powerplan/engine.py powerplan/models.py

Live command:
`python3 -m pytest tests/test_optimal_docs.py tests -q`

## Rules
Branch `brief/POWERPLAN-010` only; never write `main`. The repo guide file, the data folder, every existing test file, `powerplan/engine.py` and `powerplan/models.py` are read-only. No new dependencies. Stop at the first failing step and still write the report; if an existing test breaks, name it and stop — do not edit it.

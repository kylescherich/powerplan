# POWERPLAN-003 — time-of-day price/carbon curves; make `interruptible` real

- From → To: HUB → devws-cloud runner
- Created: 2026-10-15
- Status: queued
- unattended: yes
- model: sonnet
- Decision: DEC-253 (DEC-128 design, DEC-149 acceptance; CTR-DEVWS-CLOUD-001 0.1.3)

## Goal
Roadmap item 1 in `HANDOFF.md`: `Workload.interruptible` is declared and read by nothing, and sites have one price and one carbon number for the whole window. Add 24-hour price and carbon curves per site, choose a **start hour** as well as a site, integrate cost and carbon over the hours the job actually runs, and let interruptible jobs start later in cheaper/cleaner hours while deadlines stay binding.

Read `CLAUDE.md`, `HANDOFF.md` and `README.md` first and follow them: stdlib only, pytest, every change ships with a test, the greedy stays greedy and honest (no heuristics to make it look better), never claim a winner is better on every axis, never drop a constraint to place a workload.

## Design (fixed; do not change it)
- **Hours:** 24 hourly slots, hour 0 = the start of the planning window, UTC. Site-local time is out of scope.
- **Curves:** `Site.price_curve` and `Site.carbon_curve`, optional, each exactly 24 non-negative floats ($/kWh and gCO2e/kWh). Absent → the existing scalar `price_per_kwh` / `carbon_g_per_kwh` is used for every hour (flat curve). Wrong length or a negative value → `ValueError` naming the site and the field (check in `__post_init__`). Scalar fields stay; in the data file they are the curve means.
- **Integration:** a run of `runtime` hours starting at hour `s` draws `facility_kw` in each slot; slot `i` (0-based) uses hour `(s + i) % 24` and lasts `min(1, runtime - i)` hours (the last slot may be fractional; runs longer than 24 h wrap). `cost = Σ kWh × price`, `carbon_kg = Σ kWh × carbon / 1000`. `energy_kwh` is unchanged (`facility_kw × runtime`).
- **Start hour:** non-interruptible jobs start at 0. An interruptible job may start at any whole hour `s` in `0 … L`, where `L = 23` with no deadline, else `L = min(23, floor(deadline_hours − runtime))`. Per `(site, pool)` the engine picks the `s` that minimises `w_cost × cost(s)/cost(0) + w_carbon × carbon(s)/carbon(0)` (a term is 0 if its hour-0 value is 0); **ties → the earliest hour**. Runtime never changes with `s`. This keeps one candidate per `(site, pool)`, so scoring, ranking and the runner-up work exactly as today.
- **`Candidate`** gains, **at the end with defaults**: `start_hour: int = 0`, `deferral_saved_usd: float = 0.0`, `deferral_saved_kg: float = 0.0` (hour-0 value minus chosen value). `cost_usd` / `carbon_kg` are the integrated values at the chosen hour.
- **`Plan.makespan_hours`** = max of `start_hour + runtime_hours`.
- **Feasibility is unchanged.** Power headroom stays a single number per site: a placed job's facility kW is committed for the whole window, whatever its start hour (conservative). Add this sentence to `plan.notes` on every run: `Power headroom is checked as if every placed job ran for the whole window; time-indexed capacity is not modelled.` `interruptible` means "may start later within its deadline"; stopping a job mid-run is not modelled.
- **Existing tests must keep passing unchanged.** Do not edit any existing test file. If a change breaks an existing test, stop at that step and name the test in the report.

## Step 1 — curves in the model and the data
In `powerplan/models.py` add the two optional curve fields to `Site` (after `online`), the `__post_init__` check, and `Site.price_at(hour)` / `Site.carbon_at(hour)` (curve value at `hour % 24`, or the scalar when there is no curve). In `data/fleet.json` add these curves (keep every other value as it is):

- SITE-TX `price_curve` [0.087, 0.084, 0.078, 0.072, 0.066, 0.06, 0.057, 0.054, 0.051, 0.048, 0.042, 0.039, 0.039, 0.042, 0.045, 0.051, 0.057, 0.06, 0.063, 0.066, 0.069, 0.072, 0.078, 0.084]
- SITE-TX `carbon_curve` [395.2, 414.9, 434.7, 454.5, 454.5, 434.7, 434.7, 434.7, 434.7, 434.7, 414.9, 414.9, 395.2, 395.2, 395.2, 395.2, 375.4, 355.7, 335.9, 316.1, 316.1, 335.9, 355.7, 375.4]
- SITE-OR `price_curve` [0.1198, 0.1157, 0.1074, 0.0991, 0.0909, 0.0826, 0.0785, 0.0744, 0.0702, 0.0661, 0.0578, 0.0537, 0.0537, 0.0578, 0.062, 0.0702, 0.0785, 0.0826, 0.0868, 0.0909, 0.095, 0.0991, 0.1074, 0.1157]
- SITE-OR `carbon_curve` [114.0, 126.0, 132.0, 138.0, 144.0, 144.0, 138.0, 138.0, 138.0, 138.0, 132.0, 132.0, 126.0, 126.0, 120.0, 120.0, 114.0, 108.0, 102.0, 96.0, 90.0, 90.0, 96.0, 102.0]
- SITE-EU `price_curve` [0.2097, 0.2024, 0.188, 0.1735, 0.159, 0.1446, 0.1374, 0.1301, 0.1229, 0.1157, 0.1012, 0.094, 0.094, 0.1012, 0.1084, 0.1229, 0.1374, 0.1446, 0.1518, 0.159, 0.1663, 0.1735, 0.188, 0.2024]
- SITE-EU `carbon_curve` [230.2, 216.7, 216.7, 216.7, 230.2, 243.7, 270.8, 297.9, 311.4, 297.9, 270.8, 257.3, 243.7, 243.7, 257.3, 270.8, 297.9, 325.0, 338.5, 325.0, 297.9, 270.8, 257.3, 243.7]

Add `tests/test_curves.py`: a 23-value curve and a negative value each raise `ValueError`; `price_at` / `carbon_at` return the curve value, wrap (`hour 25` → index 1), and fall back to the scalar without a curve; `load_fleet` on `data/fleet.json` gives every site two 24-value curves whose means are within 1 % of the site's scalar.

Files: powerplan/models.py data/fleet.json tests/test_curves.py

Live command:
`python3 -m pytest tests/test_curves.py tests/test_models.py -q`

## Step 2 — the engine chooses a start hour
In `powerplan/engine.py` implement the integration and start-hour rule above inside candidate building (pass the plan's weights in), the three new `Candidate` fields, the `makespan_hours` change and the `plan.notes` sentence. Keep `_order`, `_infeasible_reason`, `_score` and the commit logic as they are.

Add `tests/test_scheduling.py`, building small fleets/workloads in the test (not the data files) unless stated. Every test that looks at placements first asserts the plan has at least one placement. Required:
1. A site **without** curves gives exactly today's numbers: `cost == energy × price_per_kwh`, `carbon == energy × carbon_g_per_kwh / 1000`, `start_hour == 0`.
2. An interruptible job without a deadline on a site whose curve is expensive at hour 0 and cheap later starts **after** hour 0, and its cost is lower than the same job's cost at hour 0 (`deferral_saved_usd > 0`).
3. The same job with `interruptible=False` starts at hour 0.
4. **The deadline binds:** an interruptible job whose cheapest window would end after its deadline gets `start_hour + runtime_hours <= deadline_hours` and a start hour earlier than the unconstrained best.
5. Integration by hand: a 1.5 h job uses one full hour and half of the next; a 30 h job wraps past hour 23. Compare with a sum written out in the test.
6. On `data/fleet.json` + `data/workloads.json` with default weights: W-003 and W-005 (the interruptible ones) start after hour 0; every non-interruptible workload starts at 0.
7. `makespan_hours` equals the largest `start_hour + runtime_hours`.
8. The `plan.notes` sentence about power headroom is present.

Files: powerplan/engine.py powerplan/models.py tests/test_scheduling.py

Live command:
`python3 -m pytest tests/test_scheduling.py tests/test_engine.py -q`

## Step 3 — the explanation states the start hour
In `powerplan/explain.py`: when `start_hour > 0`, `explain()` adds the line `  starts at hour H (UTC); deferring saved $X and Y kg CO2e` (if one of the savings is negative, say what it cost instead, e.g. `… saved $X but emits Y kg more`; never claim both improved if one did not). `summarise()` adds `deferred   N workload(s)` after the makespan line. Nothing else in the wording changes.

Add `tests/test_explain_time.py`: a deferred placement mentions `hour 10` (or whatever start hour the test sets) and `saved`; a placement at hour 0 has no start-hour line; a deferral that saved money but emitted more carbon says so and does not say both improved; `summarise` reports the deferred count.

Files: powerplan/explain.py tests/test_explain_time.py

Live command:
`python3 -m pytest tests/test_explain_time.py tests/test_explain_audit.py -q`

## Step 4 — what-if price spikes act on the curve
In `powerplan/whatif.py`, `price_spike` multiplies `price_per_kwh` **and** every value of `price_curve` (when present), still on a copy. In `powerplan/cli.py` change the `--price` help text to say it multiplies the site's price curve. No other CLI change.

Add `tests/test_whatif_curves.py`: after `price_spike(fleet, "SITE-OR", 2.0)` every curve value is doubled and the original fleet's curve is unchanged; a spike on a site without a curve still works; a plan on the spiked fleet has OR placements costing more than in the baseline (or none placed there), asserted on real placements.

Files: powerplan/whatif.py powerplan/cli.py tests/test_whatif_curves.py

Live command:
`python3 -m pytest tests/test_whatif_curves.py tests/test_whatif.py tests/test_cli.py -q`

## Step 5 — README and HANDOFF
`README.md`: describe the curves (field names, flat-curve default), the start-hour rule, and what the plan output now shows. `HANDOFF.md`: rewrite the "deliberately unfinished" paragraph about `interruptible` (it is now used; say what is still not modelled: time-indexed power capacity, mid-run preemption, site-local time, sourced curve data), mark roadmap item 1 done, and update the "Written at commit" line. Do not change the other sections' meaning.

Add `tests/test_docs_current.py`: `HANDOFF.md` no longer contains `is declared and read by nothing`; `README.md` mentions `price_curve` and `start hour`; `HANDOFF.md` mentions `time-indexed`.

Files: README.md HANDOFF.md tests/test_docs_current.py

Live command:
`python3 -m pytest tests/test_docs_current.py -q`

## Step 6 — whole suite
No file changes. Live command only.

Live command:
`python3 -m pytest tests -q`

## Rules
Branch `brief/POWERPLAN-003` only; never write `main`. `CLAUDE.md`, `data/workloads.json` and every existing test file are read-only. No new dependencies. Stop at the first failing step and still write the report; if a step breaks an existing test, name the test and stop — do not edit it.

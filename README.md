# powerplan — a power-aware compute scheduler

Decides **where AI workloads should run** when accelerators are scarce, grid
capacity is finite, and electricity prices and carbon intensity differ by site.
Every decision is explained and written to an append-only audit log.

Zero runtime dependencies (Python 3.11+, stdlib only). `pytest` for tests.

## Run it

```bash
python -m powerplan plan
python -m powerplan plan --w-carbon 0.6 --w-cost 0.2 --w-runtime 0.2
python -m powerplan whatif --offline SITE-OR
python -m powerplan whatif --curtail SITE-TX:0.45
python -m powerplan whatif --degrade SITE-OR:or-mi300:64
python -m powerplan whatif --price SITE-TX:2.5
pytest tests -q
```

## The model

**Site** — power ceiling (kW), baseline load, PUE, $/kWh, gCO2e/kWh, region.
**AcceleratorPool** — count, TDP, HBM, throughput relative to a reference part.
**Workload** — accelerator count, reference runtime, HBM floor, priority,
deadline, data-residency allowlist.

Power is modelled end to end, not as a proxy:

```
it_kw       = gpu_count × tdp_watts × utilization / 1000
facility_kw = it_kw × pue                  ← what the utility actually sees
energy_kwh  = facility_kw × runtime_hours
cost        = energy_kwh × price_per_kwh
carbon_kg   = energy_kwh × carbon_g_per_kwh / 1000
runtime     = ref_hours / pool.perf
```

A placement is feasible only if the site is online, the region satisfies
residency, the pool has enough free accelerators and enough HBM, the deadline is
reachable at that pool's throughput, and `facility_kw ≤ site.headroom_kw`.

## The objective

Feasible candidates are min–max normalised across cost, carbon and runtime, then
combined with tunable weights (default 0.45 / 0.25 / 0.30). Lower is better.
Workloads are placed highest-priority-first, tightest-deadline next.

**This is greedy, not globally optimal.** That limitation is stated in every
plan's `notes` rather than hidden. Because the objective and constraints are
pure functions of a `Candidate`, dropping a MILP over the same candidate list is
a contained change — the natural v2.

## Why it's explainable

Each placement keeps its full ranked candidate list, so the explainer names the
runner-up, quantifies the gap on all three axes, and states the tradeoff the
winner accepted:

```
nightly-eval-sweep (W-003) -> SITE-OR/or-h100 [H100-SXM]
  6.0h - 34kW facility - 204 kWh - $17 - 25 kg CO2e
  score cost 0.048 + carbon 0.000 + runtime 0.000 = 0.048
  beat SITE-TX/tx-h100: $3 more expensive, 65.2 kg CO2e cleaner, same runtime
  tradeoff accepted: costs $3 more.
  ruled out: SITE-OR/or-mi300 (needs 48 accelerators, 32 free)
```

Infeasible options are reported with the binding constraint, which is usually
more useful than the winner.

## Failure and curtailment

`whatif` deep-copies the fleet, applies a perturbation (site outage, grid
curtailment, hardware attrition, price spike), re-plans, and diffs: what moved,
what it cost, what became unplaceable.

## Audit trail

`audit.jsonl`, one JSON object per run: timestamp, actor, scenario, SHA-256
fingerprints of the fleet and workload inputs, the weights used, totals, and
every decision with its runner-up and rejection reasons. Same fingerprints plus
same weights means the plan is reproducible.

## Layout

```
powerplan/models.py    domain types, JSON loading, power math
powerplan/engine.py    feasibility, scoring, greedy assignment
powerplan/explain.py   tradeoff narration
powerplan/whatif.py    perturbations and plan diffing
powerplan/audit.py     append-only decision log
data/                  sample 3-site fleet, 6-workload queue
tests/                 constraint, sensitivity and audit tests
```

## Roadmap

1. MILP / CP-SAT solver over the existing candidate list; report the greedy gap.
2. Time-of-day price and carbon curves; defer interruptible jobs into cheap or
   clean windows instead of running them immediately.
3. OpenTelemetry spans per placement decision → real observability, not prints.
4. Ingest live telemetry (DCGM power draw, utility demand-response signals)
   instead of static JSON.
5. An agent layer that takes "cut next month's energy bill 15% without missing a
   deadline", proposes weight changes, and shows the diff for human approval.

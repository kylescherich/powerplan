# powerplan — a power-aware compute scheduler

Decides **where AI workloads should run** when accelerators are scarce, grid
capacity is finite, and electricity prices and carbon intensity differ by site.
Every decision is explained and written to an append-only audit log.

Zero runtime dependencies (Python 3.11+, stdlib only). `pytest` for tests.

## Run it

```bash
python -m powerplan plan
python -m powerplan plan --w-carbon 0.6 --w-cost 0.2 --w-runtime 0.2
python -m powerplan plan --compare-optimal
python -m powerplan plan --trace trace.jsonl
python -m powerplan plan --telemetry examples/telemetry
python -m powerplan whatif --offline SITE-OR
python -m powerplan whatif --curtail SITE-TX:0.45
python -m powerplan whatif --degrade SITE-OR:or-mi300:64
python -m powerplan whatif --price SITE-TX:2.5
pytest tests -q
```

## The model

**Site** — power ceiling (kW), baseline load, PUE, $/kWh, gCO2e/kWh, region.
Sites may optionally specify `price_curve` and `carbon_curve` (24 hourly values)
instead of scalar pricing; if absent, the scalar is used as a flat curve.
**AcceleratorPool** — count, TDP, HBM, throughput relative to a reference part.
**Workload** — accelerator count, reference runtime, HBM floor, priority,
deadline, data-residency allowlist, interruptible flag.

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
reachable at that pool's throughput, and `facility_kw` fits the site's power
headroom in every hour of the job's run window (`site.headroom_kw_at(h)`).

Interruptible workloads may defer their start hour to minimise cost or carbon
within their deadline window. Non-interruptible jobs start at hour zero. The
plan output shows the chosen start hour and the integrated cost/carbon over the
run window.

Power headroom is checked per hour. A job only uses capacity in the hours it
runs, so a short job does not block the rest of the day, and two jobs may share
a site as long as their combined load fits in each hour. When the early hours
are full, an interruptible job may start later, at the first hour whose whole
window fits; a non-interruptible job that does not fit at hour zero is rejected
with the binding reason. The explanation says when a start was forced by
capacity rather than chosen for price or carbon.

## The objective

Feasible candidates are min–max normalised across cost, carbon and runtime, then
combined with tunable weights (default 0.45 / 0.25 / 0.30). Lower is better.
Workloads are placed highest-priority-first, tightest-deadline next.

**This is greedy, not globally optimal.** That limitation is stated in every
plan's `notes` rather than hidden. Because the objective and constraints are
pure functions of a `Candidate`, dropping a MILP over the same candidate list is
a contained change — the natural v2.

## Comparing against the exact optimum

`plan --compare-optimal` runs the normal greedy plan, prints it and the audit
line as usual, then prints a gap report: the greedy plan next to a true optimum
over the same candidates and the same constraints. The optimum comes from an
exact branch-and-bound search in `powerplan/optimal.py`, written with the
stdlib only (no solver dependency).

**The greedy's numbers are never replaced.** The report sits beside the greedy
plan; it does not change what the planner chose, and the greedy remains the plan
of record. The report names which workloads the optimum would move.

Greedy and optimum are scored by one objective, compared lexicographically:
first, for each priority level from 1 upward, more placed workloads is better;
only then does a lower total weighted score (cost, carbon and runtime, each
normalised against the workloads' reference totals) win. A plan that places
more high-priority work therefore beats a cheaper plan that places less. When
the two plans place different work, the score gap is reported as `n/a`. When the
optimum is worse than the greedy on cost or on carbon, the report says so
rather than claiming it is better on every axis.

**Size limit.** The search is exact, so it only suits small fleets such as the
sample data. It stops after 200,000 search nodes and refuses with a clear
`too large for the stdlib search` error; the CLI prints that to stderr and
exits with code 3 (the normal plan output has already been printed). Past that
size, a real solver is the next step.

## Why it's explainable

Each placement keeps its full ranked candidate list, so the explainer names the
runner-up, quantifies the gap on all three axes, and states the tradeoff the
winner accepted:

```
nightly-eval-sweep (W-003) -> SITE-OR/or-h100 [H100-SXM]
  start hour 0.0
  6.0h - 34kW facility - 204 kWh - $17 - 25 kg CO2e
  score cost 0.048 + carbon 0.000 + runtime 0.000 = 0.048
  beat SITE-TX/tx-h100: $3 more expensive, 65.2 kg CO2e cleaner, same runtime
  tradeoff accepted: costs $3 more.
  ruled out: SITE-OR/or-mi300 (needs 48 accelerators, 32 free)
```

For interruptible workloads that defer to a cheaper or cleaner hour, the
explanation quantifies what the deferral saved or cost.

Infeasible options are reported with the binding constraint, which is usually
more useful than the winner.

## Tracing

`plan --trace PATH` writes a span log in JSON lines: one root span
(`powerplan.plan`) and one span (`powerplan.place`) per placement decision,
each with the chosen site, start hour and runner-up margin. It is written after
the normal output, and the last stdout line reports the count:

```bash
python -m powerplan plan --trace trace.jsonl
# ...
# trace: 7 spans -> trace.jsonl
```

Without `--trace` nothing is traced and no file is written. `whatif` is not
traced. The spans are plain dicts shaped like OpenTelemetry spans; no
OpenTelemetry package or exporter is used.

## Replayed telemetry

`plan --telemetry DIR` replays telemetry snapshot files before planning. It
reads `DIR/dcgm.prom` and `DIR/dr_events.json`, whichever exist; if neither
exists it prints `no telemetry files in DIR` to stderr and exits with code 2.
GPU power is applied first, then demand-response limits, so the plan,
`--compare-optimal`, `--trace` and the audit record all see the adjusted fleet.
The first stdout line reports what was read:

```bash
python -m powerplan plan --telemetry examples/telemetry
# telemetry: 3 GPU power samples, 1 demand-response events
# ...
```

**`dcgm.prom`** is the text format NVIDIA's dcgm-exporter serves (Prometheus
exposition): `name{label="value",...} value [timestamp]`. Blank lines and `#`
lines are skipped, and the optional timestamp is ignored. Samples of
`DCGM_FI_DEV_POWER_USAGE` (watts) are summed per site and added to that site's
baseline load as `kW × PUE`. **Every power sample needs a `site` label** (real
dcgm-exporter output gets it from the scrape config); other metrics are
ignored. GPU availability is not taken from telemetry.

**`dr_events.json`** holds utility demand-response limits:

```json
{"events": [{"site_id": "SITE-OR", "start_hour": 8, "end_hour": 16, "limit_kw": 650}]}
```

The site may draw at most `limit_kw` during hours `[start_hour, end_hour)`
(end exclusive). Where events overlap the lower limit wins, and a limit above
the site's capacity does not raise the ceiling. Both the greedy plan and the
exact search respect it.

The samples in `examples/telemetry/` are synthetic. Nothing is polled over the
network; the files are replayed from disk.

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
powerplan/optimal.py   exact reference search and greedy-gap report
powerplan/explain.py   tradeoff narration
powerplan/whatif.py    perturbations and plan diffing
powerplan/audit.py     append-only decision log
powerplan/trace.py     stdlib span log (OpenTelemetry-shaped, no exporter)
powerplan/telemetry.py replayed demand-response events and dcgm-exporter power
data/                  sample 3-site fleet, 6-workload queue
tests/                 constraint, sensitivity and audit tests
```

## Roadmap

1. ~~Time-of-day price and carbon curves; defer interruptible jobs into cheap or
   clean windows instead of running them immediately.~~ **Done.**
2. ~~Report the greedy gap against an exact optimum.~~ **Done** as a stdlib
   exact search for small fleets (`plan --compare-optimal`); a MILP / CP-SAT
   solver is the step when fleets outgrow it.
3. ~~OpenTelemetry spans per placement decision → real observability, not prints.~~
   **Done** as an OpenTelemetry-shaped span log in JSON lines (`plan --trace`),
   with no exporter and no OpenTelemetry package; mapping to OTLP is the later
   step.
4. ~~Ingest live telemetry (DCGM power draw, utility demand-response signals)
   instead of static JSON.~~ **Done** as replay: `plan --telemetry DIR` reads
   telemetry files in real formats (dcgm-exporter text, demand-response
   events) with synthetic samples and no network polling; live polling is the
   later step.
5. An agent layer that takes "cut next month's energy bill 15% without missing a
   deadline", proposes weight changes, and shows the diff for human approval.

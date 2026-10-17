# HANDOFF.md

Context for anyone (including future me, or a fresh Claude session) picking this
up. The code says *what*. This says *why*, and what was deliberately left undone.

Written at commit `[CURRENT]`. If this file contradicts the code, the code wins —
but say so, because it means this went stale.

---

## What this is

A power-aware compute scheduler: given a fleet of datacenter sites with finite
electrical capacity and a queue of AI workloads, decide where each workload
runs. Optimises cost, carbon and runtime under hard constraints, explains every
decision, and logs the decision for audit.

It is a **portfolio project**. The engineering judgment on display is the
product — not the feature count. A reviewer should be able to open any file and
see deliberate choices, not accumulated code.

---

## Decisions made, and why

### Greedy placement instead of a solver

The engine enumerates feasible `(site, pool)` candidates per workload, scores
them, takes the best, commits the resources, moves on. Priority order first,
then tightest deadline.

This is **not globally optimal** and a MILP would beat it. That was the choice
anyway, for two reasons: an explainable greedy is more useful than an
inscrutable optimum for the demo this project exists to give, and a solver
dependency would break the stdlib-only constraint on day one.

The mitigation matters more than the limitation: `_infeasible_reason` and
`_score` are pure functions of a `Candidate`, and `plan()` already builds the
full candidate list before choosing. A MILP can consume that same list without
touching the domain model. The limitation is stated in `plan.notes` on every run
and in the README, deliberately, rather than hidden.

**Do not "fix" the greedy by adding heuristics that make it look better.** Either
leave it honest or replace it with a real solver and report the gap.

### The explainer keeps the runner-up

Every `Placement` stores the second-best candidate and the full rejection list.
This costs memory and looked like over-engineering at first.

It is the most important design decision in the project. It's what lets the
output say "chose Texas over Oregon: $181 cheaper, 3,595 kg CO2e dirtier" — a
scheduler that states the tradeoff it accepted rather than asserting it was
right. A capacity planner will not hand a megawatt to a black box. Everything in
`explain.py` depends on this being retained.

Related rule: **never claim a winner is better on every axis.** If it lost on
one, say so.

### Rejections are reported, not swallowed

When no candidate is feasible, the workload goes in `plan.unplaced` with the
binding reason per site. The tempting alternative — relaxing a constraint to get
a placement — is exactly the failure mode that makes schedulers untrustworthy.
Missing a deadline visibly beats blowing a power budget silently.

### Power is modelled end to end

`gpu_count × TDP × utilization → IT kW → × PUE → facility kW → kWh`. PUE is in
there because the utility bills for cooling too; a scheduler that only counts
GPU draw will overcommit a site. Headroom is checked against facility kW, not IT
kW. This is the part most likely to be wrong in a way that matters, and the part
worth defending in an interview.

### stdlib only

No numpy, no pandas, no solver. Partly a discipline constraint, partly because a
reviewer can clone and run it with zero setup. Adding a dependency is allowed
but it should be a decision, not a reflex — and the MILP is the case that will
justify breaking this.

---

## What's deliberately unfinished

**Time-of-day scheduling is basic.** Sites support 24-hour `price_curve` and
`carbon_curve` fields, and interruptible workloads defer their start hour to
minimise cost or carbon within their deadline window. Power capacity is now
time-indexed: `Site.committed_kw_by_hour` tracks the load in each hour, and a
job is feasible only if its facility kW fits the headroom in every hour of its
window. An interruptible job may start later when early hours are full
(`Candidate.deferred_for_capacity`), and the explanation says so. What is still
not modelled: mid-run preemption (a job holds its accelerators until
completion), site-local time zones (all hours are UTC-relative), and sourced
curve data (the sample curves are synthetic). Real utility tariffs and grid
carbon APIs (WattTime, Electricity Maps) are the credibility upgrade.

**The sample data is synthetic.** Prices, carbon intensities and PUEs are
plausible, not sourced. Real utility tariffs and WattTime/Electricity Maps
carbon data are the credibility upgrade. The fleet is shaped to make specific
things happen — SITE-EU exists to exercise data residency, MI300X's 192GB HBM
exists so W-004 has exactly one feasible home. That last one is intentional: it
makes `whatif --offline SITE-OR` drop a workload and expose a single-vendor
dependency, which is the best demo in the repo.

**Telemetry is replayed from files, not polled.** `plan --telemetry DIR`
replays dcgm-exporter power readings (`DIR/dcgm.prom`) and demand-response
events (`DIR/dr_events.json`) onto the fleet before planning. The sample
telemetry in `examples/telemetry/` is synthetic too. GPU availability is not
taken from telemetry (only measured power is added to a site's baseline load),
and there is no live polling.

**Time is modelled within one day only.** Jobs now have start hours, and power
is checked per hour of each job's window. There is still no queueing beyond the
24-hour window and no preemption, and `makespan` is the latest start plus
runtime, not a real multi-day schedule.

**Observability is a local span log, not OpenTelemetry.** `plan --trace PATH`
writes one root span (`powerplan.plan`) and one span per placement decision
(`powerplan.place`) as JSON lines, from the stdlib `Tracer` in
`powerplan/trace.py`. The spans are OpenTelemetry-shaped, but there is no
OpenTelemetry package and no exporter. Mapping them to OTLP and exporting them
is the later step. `whatif` is not traced.

---

## Working agreements

- Run `py -m pytest tests -q` before claiming anything works. Windows: `py`, not
  `python3`.
- Every feature ships with a test. The existing suite covers residency, memory
  filtering, power headroom, oversubscription, weight sensitivity, failure
  replanning, and audit validity — extend it, don't bypass it.
- Commit per working change, not per session. When an agent refactors four files
  and something breaks, `git diff` is the recovery tool.
- `audit.jsonl` is gitignored. It's a log; logs don't belong in version control.
- Push tradeoffs, don't just agree. If an approach here is wrong, say so.

---

## Roadmap, in the order I'd do it

1. ~~Time-of-day price and carbon curves; make `interruptible` mean something.~~
   **Done.**
2. ~~MILP or CP-SAT over the existing candidate list; report the greedy gap
   explicitly rather than quietly replacing the number.~~ **Done** as a stdlib
   exact search (branch and bound in `powerplan/optimal.py`), not a MILP.
   `plan --compare-optimal` reports the gap and never replaces the greedy's
   numbers. The search is exact only for small fleets: it stops after 200,000
   nodes with `SearchTooLarge` (CLI exit code 3). A real solver is the step
   when fleets outgrow it.
3. ~~OpenTelemetry spans per decision.~~ **Done** as a stdlib,
   OpenTelemetry-shaped span log (`plan --trace`); no exporter, and mapping to
   OTLP is the later step.
4. ~~Live telemetry ingest (DCGM power draw, utility demand-response signals) in
   place of static JSON.~~ **Done** as replay: `plan --telemetry DIR` reads
   dcgm-exporter text and demand-response events from files; no live polling.
5. ~~An agent layer that takes a goal like "cut next month's energy bill 15%
   without missing a deadline", proposes weight changes, and shows the diff for
   human approval.~~ **Done** as a deterministic, stdlib weight search
   (`advise --goal`, `powerplan/advisor.py`): no language model, nothing is
   auto-applied, and the command prints the `plan` flags for a person to run.
   The advisor searches a fixed 0.05 weight grid and never trades away placed
   work.

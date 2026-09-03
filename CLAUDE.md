# CLAUDE.md

Python project: a power-aware compute scheduler that places AI workloads
across datacenter sites under power, memory, residency and deadline
constraints. Portfolio piece — code quality is the product.

## Hard constraints

- stdlib only at runtime. pytest for tests. Do not add dependencies
  without asking me first.
- Every new feature ships with a test. Run `py -m pytest tests -q`
  before telling me something works.
- Placement is greedy and NOT globally optimal. This is a known,
  documented limitation, not a bug. MILP over the existing Candidate
  list is the planned v2.
- Never silently drop a constraint to make a workload placeable.
  Report it as unplaced with the binding reason.

Windows: use `py`, not `python3`.

## Style

Explain tradeoffs, don't just assert a choice is best. If you disagree
with an approach I propose, say so.

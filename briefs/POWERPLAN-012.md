# POWERPLAN-012 — roadmap item 3: a stdlib span log per placement decision

- From → To: HUB → devws-cloud runner
- Created: 2026-10-16
- Status: queued
- unattended: yes
- model: anthropic/claude-sonnet-5-5
- Decision: DEC-304 (roadmap item 3, Kyle chose the stdlib span log; DEC-263 four dimensions; DEC-303 standing rules; CTR-DEVWS-CLOUD-001 0.1.5)

## Goal
Roadmap item 3 ("OpenTelemetry spans per decision"), done the stdlib way: an **OpenTelemetry-shaped span log** written as JSON lines, with no OpenTelemetry package or exporter (this repo is stdlib only). A plan gets one root span and one child span per workload placement decision. Tracing is **off by default** and **never changes a plan's results**. The expected values below were computed by the Hub in advance from a prototype on `main` `4f7e0ed` (all 141 existing tests still green); they are the oracle.

## Design (fixed; do not change it)
**Span record** — a dict with exactly these 8 keys: `trace_id` (32 lowercase hex chars), `span_id` (16 hex), `parent_span_id` (the enclosing span's `span_id`, or `None` for a root), `name`, `start_time_unix_nano`, `end_time_unix_nano`, `attributes` (dict), `status` (`"OK"` or `"ERROR"`).

**`Tracer(clock=None, new_id=None)`** in the new module: `clock()` returns integer nanoseconds (default `time.time_ns`); `new_id(nbytes)` returns a hex string of `2*nbytes` chars (default `secrets.token_hex`). `tracer.spans` is the list of finished spans, appended **when a span ends** (so a child comes before its parent). `with tracer.span(name, **attributes) as attrs:` opens a span; `attrs` is that span's attributes dict and may be added to inside the block. A root span (none open) draws a new trace id with `new_id(16)` **before** its own `new_id(8)`; a nested span reuses the open trace id. Start time is read on entry, end time on exit. If the block raises, the span gets `status "ERROR"` and `attributes["exception.type"]` = the exception class name, is still recorded with its end time, and the exception propagates unchanged. `tracer.to_jsonl(path)` writes one `json.dumps(span, sort_keys=True)` per line and returns the number written.

**Engine** — `plan(fleet, workloads, weights=None, tracer=None)`. `tracer=None` (the default) records nothing and behaves exactly as today. With a tracer:
- Root span `powerplan.plan`, attributes on entry `workloads.count`, `weights.cost`, `weights.carbon`, `weights.runtime` (the weights actually used); added before it ends: `placements.count`, `unplaced.count`.
- One child span `powerplan.place` per workload, in the order the planner considers them, attributes `workload.id`, `workload.priority`, `candidates.considered` (feasible candidates), `candidates.rejected` (rejections), and `placement.outcome` = `"placed"` or `"unplaced"`.
- Placed: also `placement.site_id`, `placement.pool_id`, `placement.start_hour`, `placement.score`, `placement.deferred_for_capacity`; and, **only when a runner-up exists**, `runner_up.site_id`, `runner_up.pool_id`, `runner_up.score_margin` (= runner-up score − chosen score). No `runner_up.*` key at all when there is no runner-up.
- Unplaced: also `rejection.reasons` = a list of `"SITE/POOL: reason"` strings, one per rejection, in rejection order, using the existing reason text.

**CLI** — `plan --trace PATH`: after the existing output, writes the plan's spans to PATH and prints exactly `trace: N spans -> PATH` as the last line. Without `--trace`, no trace file is written and no `trace:` line is printed. `--compare-optimal` and `whatif` are not traced in this brief.

## Step 1 — the tracer
Add `powerplan/trace.py` with `Tracer` as designed. Add `tests/test_trace.py`. Test clock: `itertools.count()` × 1000, i.e. 0, 1000, 2000, …; test ids: a counter starting at 1, formatted as zero-padded hex of length `2*nbytes`.
1. Outer span `"a"` with an inner span `"b"`: `spans` is `[b, a]`; trace id `"0"*31 + "1"` on both; `a.span_id == "0000000000000002"`, `b.span_id == "0000000000000003"`; `b.parent_span_id == a.span_id`, `a.parent_span_id is None`; times a 0→3000, b 1000→2000; both `"OK"`.
2. Attributes given at open and added via `attrs` inside the block both appear.
3. A `ValueError` raised inside a span propagates; the span is recorded with `status "ERROR"`, `attributes["exception.type"] == "ValueError"` and an end time.
4. A second root span after the first has ended gets a different trace id.
5. `to_jsonl` returns the span count, writes that many lines, and each line parses to a dict with exactly the 8 keys.
6. With the defaults, `trace_id` is 32 and `span_id` 16 lowercase hex chars.

Files: powerplan/trace.py tests/test_trace.py

Live command:
`python3 -m pytest tests/test_trace.py tests -q`

## Step 2 — spans from the planner
`powerplan/engine.py`: the `tracer` parameter and spans as designed. Do not change any placement logic. Add `tests/test_trace_engine.py` (Step 1's test clock and ids; real data `data/fleet.json` + `data/workloads.json`, default weights):
1. 7 spans; the first six are `powerplan.place` for W-001, W-002, W-004, W-006, W-003, W-005 in that order, the last is `powerplan.plan`; every place span's parent is the root's `span_id`, all share one trace id.
2. Root: `workloads.count` 6, `placements.count` 6, `unplaced.count` 0, weights 0.45 / 0.25 / 0.30.
3. W-001: considered 2, rejected 4, placed at SITE-TX / tx-h100, start 0, score 0.25, runner-up SITE-OR / or-h100, margin 0.2 (all floats ±1e-9).
4. W-003 start_hour 10, W-005 start_hour 8 (both placed at SITE-OR / or-h100).
5. **Boundary — no runner-up:** W-002 (only one feasible candidate, score 0.0) has no key starting with `runner_up.`.
6. **Boundary — unplaced:** with SITE-OR taken offline (`whatif.site_offline`), W-004's span has outcome `"unplaced"`, considered 0, rejected 6 and `rejection.reasons` exactly: `SITE-TX/tx-h100: 80GB HBM < 140GB required`, `SITE-TX/tx-a100: 80GB HBM < 140GB required`, `SITE-OR/or-h100: site offline`, `SITE-OR/or-mi300: site offline`, `SITE-EU/eu-h100: 80GB HBM < 140GB required`, `SITE-EU/eu-l40s: 48GB HBM < 140GB required`; root `unplaced.count` 1.
7. **Tracing changes nothing:** on fresh copies of the real data, each placement's workload, site, pool, start hour and score are equal with and without a tracer; `tracer=None` records nothing and raises nothing.

Files: powerplan/engine.py powerplan/trace.py powerplan/models.py powerplan/whatif.py tests/test_trace_engine.py

Live command:
`python3 -m pytest tests/test_trace_engine.py tests -q`

## Step 3 — CLI flag and docs
`powerplan/cli.py`: `plan --trace PATH` as designed. `README.md`: roadmap item 3 marked done the way items 1 and 2 are (struck through, then **Done**), saying it is an OpenTelemetry-shaped span log in JSON lines with no exporter (the words `span log` must appear), plus a short usage example of `--trace`. `HANDOFF.md`: replace the paragraph that says observability is `print()` with the current state (`plan --trace` writes one root span and one span per placement decision; no OTel SDK or exporter; mapping to OTLP is the later step), keeping the words `--trace` in it; mark roadmap item 3 done; update the "Written at commit" line to the current `main` commit.
Add `tests/test_trace_cli.py` (copy the data into `tmp_path` and `chdir` there, as `tests/test_cli.py` does): `main(["plan", "--trace", <tmp>/t.jsonl])` returns 0, the file has 7 lines, its last line's `name` is `powerplan.plan`, and the printed output's last line is `trace: 7 spans -> <that path>`; `main(["plan"])` creates no trace file and prints no line starting `trace:`; `README.md` contains `span log`; `HANDOFF.md` contains `--trace`.

Files: powerplan/cli.py README.md HANDOFF.md tests/test_trace_cli.py tests/test_cli.py powerplan/engine.py powerplan/trace.py

Live command:
`python3 -m pytest tests/test_trace_cli.py tests -q`

## Rules
Branch `brief/POWERPLAN-012` only; never write `main`. The repo guide file and the data folder are read-only. No new dependencies (stdlib only at runtime).
- Change only files on the step's `Files:` line that the step asks you to change; every other file, and every existing test, is read-only.
- Never edit an existing test. If one fails after your change, do not bend the code to satisfy it against the documented behaviour: name the test and the conflict in your reply and stop.
- If you think a file that is not on the `Files:` line must change, do not edit it and do not work around it in another file: name the file and the reason in your reply and stop.
- If a requirement can be read two ways that give different results, do not choose: name both readings in your reply and stop without changing code.

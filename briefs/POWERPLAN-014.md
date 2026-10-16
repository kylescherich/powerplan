# POWERPLAN-014 — span log: `plan --trace` and docs (POWERPLAN-013 re-brief, both questions answered)

- From → To: HUB → devws-cloud runner
- Created: 2026-10-16
- Status: queued
- unattended: yes
- model: anthropic/claude-sonnet-5-5
- Decision: DEC-306 (POWERPLAN-013 stopped correctly with two questions; answered here; DEC-303 standing rules; CTR-DEVWS-CLOUD-001 0.1.5)

## Goal
`powerplan/trace.py` (`Tracer`) and `plan(..., tracer=None)` are on `main` and correct. This brief adds the command-line flag and the docs. **Do not change `powerplan/engine.py` or `powerplan/trace.py`.** The expected values were computed by the Hub in advance from a prototype on `main` `43f9774`; they are the oracle.

**CLI design (fixed):** `plan --trace PATH` traces the greedy plan (`plan(..., tracer=Tracer())`). At the end of the `plan` command — after the existing output, including the `--compare-optimal` gap report when that flag is given — it writes the spans with `Tracer.to_jsonl(PATH)` and prints exactly `trace: N spans -> PATH` to stdout as the last stdout line (N = spans written).
- **Answer to POWERPLAN-013's question 1:** when `--compare-optimal` fails with `SearchTooLarge`, the greedy plan was still computed and printed, so the trace is **still written** and the `trace:` line is **still printed** (after the existing error message on stderr), and the command still returns **3**.
- Without `--trace`: no trace file, no `trace:` line, behaviour exactly as today.
- `whatif` is not traced.

**Answer to POWERPLAN-013's question 2:** leave HANDOFF.md's "Written at commit" line **unchanged** in this brief (the Hub updates it after merge).

## Step 1 — CLI flag and docs
`powerplan/cli.py`: the `--trace PATH` option on `plan` as designed.
`README.md`: mark roadmap item 3 done the way items 1 and 2 are (struck through, then **Done**), saying it is an OpenTelemetry-shaped span log in JSON lines with no exporter (the words `span log` must appear), plus a short usage example of `--trace`.
`HANDOFF.md`: replace the paragraph that says observability is `print()` with the current state (`plan --trace` writes one root span and one span per placement decision; no OpenTelemetry package or exporter; mapping to OTLP is the later step), keeping the words `--trace` in it; mark roadmap item 3 done. Do not touch the "Written at commit" line.
Add `tests/test_trace_cli.py`. Each test copies `data/fleet.json` and `data/workloads.json` into `tmp_path/data` and `chdir`s to `tmp_path`, as `tests/test_cli.py` does; `p` = `tmp_path / "t.jsonl"`.
1. `main(["plan", "--trace", str(p)])` returns 0; `p` has 7 lines; the last line's `name` is `powerplan.plan`; the last line of captured stdout is `trace: 7 spans -> <str(p)>`.
2. `main(["plan", "--compare-optimal", "--trace", str(p)])` returns 0 and the last stdout line is the same `trace:` line.
3. **Boundary — search too large:** with `powerplan.cli.compare` monkeypatched to raise `SearchTooLarge("too large")`, `main(["plan", "--compare-optimal", "--trace", str(p)])` returns 3, `p` has 7 lines, and the last stdout line is the `trace:` line.
4. **Off by default:** `main(["plan"])` returns 0, no stdout line starts with `trace:`, and the entries directly in `tmp_path` are exactly `audit.jsonl` and `data` (the existing audit file is expected; nothing else is written).
5. `README.md` contains `span log`; `HANDOFF.md` contains `--trace`.

Files: powerplan/cli.py README.md HANDOFF.md tests/test_trace_cli.py tests/test_cli.py powerplan/engine.py powerplan/trace.py powerplan/optimal.py data/fleet.json data/workloads.json

Live command:
`python3 -m pytest tests/test_trace_cli.py tests -q`

## Rules
Branch `brief/POWERPLAN-014` only; never write `main`. The repo guide file and everything under `data/` are read-only. No new dependencies (stdlib only at runtime).
- Change only files on the step's `Files:` line that the step asks you to change; every other file, and every existing test, is read-only.
- Never edit an existing test. If one fails after your change, do not bend the code to satisfy it against the documented behaviour: name the test and the conflict in your reply and stop.
- If you think a file that is not on the `Files:` line must change, do not edit it and do not work around it in another file: name the file and the reason in your reply and stop.
- If a requirement can be read two ways that give different results, do not choose: name both readings in your reply and stop without changing code.

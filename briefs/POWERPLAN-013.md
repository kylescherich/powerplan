# POWERPLAN-013 — span log: `plan --trace` and docs (step 3 of POWERPLAN-012)

- From → To: HUB → devws-cloud runner
- Created: 2026-10-16
- Status: queued
- unattended: yes
- model: anthropic/claude-sonnet-5-5
- Decision: DEC-305 (POWERPLAN-012 steps 1–2 merged; its step 3 re-briefed; DEC-303 standing rules; CTR-DEVWS-CLOUD-001 0.1.5)

## Goal
`powerplan/trace.py` (`Tracer`) and `plan(..., tracer=None)` are on `main` and correct. This brief adds the command-line flag and the docs. **Do not change `powerplan/engine.py` or `powerplan/trace.py`.** The expected values were computed by the Hub in advance; they are the oracle.

**CLI design (fixed):** `plan --trace PATH`: after all existing output (including the `--compare-optimal` gap report when that flag is given), write the plan's spans with `Tracer.to_jsonl(PATH)` and print exactly `trace: N spans -> PATH` as the last line (N = spans written). Without `--trace`, no trace file is written and no `trace:` line is printed. Only the greedy plan is traced; `--compare-optimal` and `whatif` are not traced.

## Step 1 — CLI flag and docs
`powerplan/cli.py`: the `--trace` option on `plan` as designed.
`README.md`: mark roadmap item 3 done the way items 1 and 2 are (struck through, then **Done**), saying it is an OpenTelemetry-shaped span log in JSON lines with no exporter (the words `span log` must appear), plus a short usage example of `--trace`.
`HANDOFF.md`: replace the paragraph that says observability is `print()` with the current state (`plan --trace` writes one root span and one span per placement decision; no OpenTelemetry package or exporter; mapping to OTLP is the later step), keeping the words `--trace` in it; mark roadmap item 3 done; update the "Written at commit" line to the current `main` commit.
Add `tests/test_trace_cli.py` (copy `data/fleet.json` and `data/workloads.json` into `tmp_path` and `chdir` there, as `tests/test_cli.py` does):
1. `main(["plan", "--trace", <tmp>/t.jsonl])` returns 0; the file has 7 lines; its last line's `name` is `powerplan.plan`; the printed output's last line is `trace: 7 spans -> <that path>`.
2. `main(["plan"])` creates no trace file and prints no line starting with `trace:`.
3. `README.md` contains `span log`; `HANDOFF.md` contains `--trace`.

Files: powerplan/cli.py README.md HANDOFF.md tests/test_trace_cli.py tests/test_cli.py powerplan/engine.py powerplan/trace.py data/fleet.json data/workloads.json

Live command:
`python3 -m pytest tests/test_trace_cli.py tests -q`

## Rules
Branch `brief/POWERPLAN-013` only; never write `main`. The repo guide file and everything under `data/` are read-only. No new dependencies (stdlib only at runtime).
- Change only files on the step's `Files:` line that the step asks you to change; every other file, and every existing test, is read-only.
- Never edit an existing test. If one fails after your change, do not bend the code to satisfy it against the documented behaviour: name the test and the conflict in your reply and stop.
- If you think a file that is not on the `Files:` line must change, do not edit it and do not work around it in another file: name the file and the reason in your reply and stop.
- If a requirement can be read two ways that give different results, do not choose: name both readings in your reply and stop without changing code.

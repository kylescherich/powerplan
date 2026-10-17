# POWERPLAN-016 — roadmap item 4: replayed telemetry (demand-response limits + GPU power)

- From → To: HUB → devws-cloud runner
- Created: 2026-10-16
- Status: queued
- unattended: yes
- model: anthropic/claude-sonnet-5-5
- Decision: DEC-309 (Kyle chose "replay files": real formats, synthetic samples, no network; DEC-303 standing rules; CTR-DEVWS-CLOUD-001 0.1.5)

## Goal
Roadmap item 4, done as **replay**: the planner reads telemetry snapshot files in real formats instead of only static JSON. Two inputs:
- **Utility demand-response (DR) events:** a per-hour power limit for a site (e.g. "SITE-OR may draw at most 650 kW from 08:00 to 16:00"). Planning and the exact search must both respect it.
- **GPU power readings** in the text format that NVIDIA's dcgm-exporter serves (Prometheus exposition): measured draw of GPUs already running work, added to a site's baseline load.

No network code; stdlib only. The expected values below were computed by the Hub in advance from a prototype on `main` `96e819d` (all 160 existing tests stay green with it); they are the oracle.

## Design (fixed; do not change it)
**Model (`Site`):** new field `power_limit_kw_by_hour: list[float | None]`, default 24 × `None`, placed right after `committed_kw_by_hour`. It is an input: `Fleet.reset()` does **not** clear it. New method `room_kw_at(hour)` = 0 if offline, else `min(power_capacity_kw, limit) − baseline_load_kw` where `limit` is that hour's entry (index `int(hour) % 24`), or `power_capacity_kw` alone when the entry is `None`. `headroom_kw_at(hour)` becomes `room_kw_at(hour) − committed_kw_by_hour[hour]` (0 if offline, as today). `headroom_kw` (no hour) is unchanged.

**Exact search (`optimal`):** must use the same per-hour room: an option fits only if, for every hour `h` of its window, `facility_kw <= room_kw_at(h) − committed load at h`. The quick pre-filter becomes "skip if `facility_kw` exceeds the largest `room_kw_at(h)` over the 24 hours".

**New module `powerplan/telemetry.py`:**
- `DREvent(site_id, start_hour, end_hour, limit_kw)` (frozen dataclass). `parse_dr_events(text)` reads JSON `{"events": [{"site_id", "start_hour", "end_hour", "limit_kw"}, …]}`; hours are integers with `0 <= start_hour < end_hour <= 24` (end exclusive) and `limit_kw` is a number `>= 0`, else `ValueError` naming the event index. `apply_dr(fleet, events)` sets each hour in `[start_hour, end_hour)` to the event's limit, keeping the **lower** value where events overlap; an unknown site raises `ValueError` naming the site id.
- `parse_prometheus(text)` returns a list of `(name, labels, value)` tuples, one per sample line: `name{label="value",…} value [timestamp]`. Blank lines and lines starting with `#` are skipped; the optional integer timestamp is ignored; label values unescape `\"`, `\\` and `\n`. A line that is not a sample, has malformed labels or a non-numeric value raises `ValueError` containing `line N` (1-based).
- `POWER = "DCGM_FI_DEV_POWER_USAGE"` (watts). `gpu_it_kw_by_site(samples)` sums the `POWER` samples per `site` label, in kW (watts / 1000), ignoring all other metrics. A `POWER` sample with no `site` label, or a non-finite value, raises `ValueError` (real dcgm-exporter output gets the `site` label from the scrape config).
- `apply_gpu_power(fleet, it_kw_by_site)` adds `kW × site.pue` to each site's `baseline_load_kw` (measured IT draw of running work, converted to facility power); unknown site → `ValueError` naming it. GPU availability is not changed (a documented limitation).

**CLI (step 3):** `plan --telemetry DIR` reads `DIR/dcgm.prom` and `DIR/dr_events.json`, whichever exist; if neither exists it prints `no telemetry files in DIR` to stderr and returns 2. It applies GPU power first, then DR events, to the fleet before planning (so the plan, `--compare-optimal`, `--trace` and the audit record all see the adjusted fleet), and prints `telemetry: N GPU power samples, M demand-response events` as the **first** stdout line (N counts `POWER` samples only).

## Step 1 — demand-response limits (model, exact search, DR parsing)
`powerplan/models.py`, `powerplan/optimal.py` and the DR part of `powerplan/telemetry.py` as designed. Add `tests/test_telemetry_dr.py` (real data = `data/fleet.json` + `data/workloads.json`, default weights; floats ±1e-9):
1. Fresh fleet + `DREvent("SITE-OR", 8, 16, 650)`: SITE-OR `headroom_kw_at` is 2100 at hour 7, 150 at 8, 150 at 15, 2100 at 16; `room_kw_at` gives the same values.
2. **Overlap keeps the lower limit:** SITE-TX events (10, 14, 3000) and (12, 20, 2000) → `power_limit_kw_by_hour` is `None` at 9, 3000 at 10 and 11, 2000 at 12–19, `None` at 20.
3. **Boundary — limit above capacity:** SITE-TX (0, 24, 9999) → `headroom_kw_at(5) == 3300` (capacity still binds).
4. **Plans honour it, and reset keeps it:** with the SITE-OR event, `plan()` places W-001 SITE-TX/tx-h100 @0, W-002 SITE-EU/eu-h100 @0, W-004 SITE-OR/or-mi300 @0, W-006 SITE-OR/or-h100 @0, W-003 SITE-OR/or-h100 @10, and **W-005 SITE-OR/or-h100 @16 with `deferred_for_capacity` True** (it is @8 without the event); after `fleet.reset()` the limit at hour 8 is still 650.
5. **Boundary — non-interruptible job rejected:** SITE-EU (0, 24, 440) → W-002 unplaced; its SITE-EU rejections are `eu-h100: needs 47kW, only 20kW headroom` and `eu-l40s: needs 22kW, only 20kW headroom`.
6. **Exact search honours it:** with the SITE-OR event, `compare(fleet, workloads, weights)` gives `score_gap` 0.0, `moved` empty and `same_work_placed` True. (Without the per-hour room the search reports a false optimum that puts W-001 on SITE-OR during the limit, gap ≈ 0.3695.)
7. **Parsing:** `start_hour == end_hour`, `end_hour` 25 and `limit_kw` −1 each raise `ValueError`; an event (23, 24, 0) is accepted; `apply_dr` with site `"SITE-XX"` raises `ValueError` whose message contains `SITE-XX`.

Files: powerplan/models.py powerplan/optimal.py powerplan/telemetry.py tests/test_telemetry_dr.py powerplan/engine.py data/fleet.json data/workloads.json

Live command:
`python3 -m pytest tests/test_telemetry_dr.py tests -q`

## Step 2 — GPU power readings (dcgm-exporter text)
The Prometheus parsing and GPU-power part of `powerplan/telemetry.py` as designed. Add `tests/test_telemetry_dcgm.py`, using the sample text in Step 3 (`examples/telemetry/dcgm.prom`) embedded in the test as a string:
1. `parse_prometheus` returns 4 samples: three `DCGM_FI_DEV_POWER_USAGE` (SITE-TX 612.5, SITE-TX 587.5, SITE-OR 400.0; the third line's timestamp is ignored) and one `DCGM_FI_DEV_GPU_TEMP` (61.0); comment lines are skipped.
2. `gpu_it_kw_by_site` → SITE-TX 1.2, SITE-OR 0.4 (the temperature sample is ignored).
3. `apply_gpu_power` on a fresh fleet → SITE-TX `baseline_load_kw` 901.536, SITE-OR 500.46, SITE-EU unchanged at 420.
4. **Escapes:** `m{a="x\"y",b="c\\d"} 1.5` → labels `{"a": 'x"y', "b": "c\\d"}` (i.e. a backslash), value 1.5.
5. **Errors:** `m{a="x"} notanumber` and `m{a=x} 1` raise `ValueError` containing `line 1`; a `DCGM_FI_DEV_POWER_USAGE{gpu="0"} 5` sample (no `site` label) makes `gpu_it_kw_by_site` raise `ValueError`; `apply_gpu_power` with `{"SITE-XX": 1.0}` raises `ValueError` containing `SITE-XX`.

Files: powerplan/telemetry.py tests/test_telemetry_dcgm.py powerplan/models.py data/fleet.json data/workloads.json

Live command:
`python3 -m pytest tests/test_telemetry_dcgm.py tests -q`

## Step 3 — `plan --telemetry`, sample files, docs
`powerplan/cli.py`: `--telemetry DIR` on `plan` as designed. Create the two sample files exactly as below (synthetic; the UUIDs are made up).

`examples/telemetry/dcgm.prom`:
```
# HELP DCGM_FI_DEV_POWER_USAGE Power draw (in W).
# TYPE DCGM_FI_DEV_POWER_USAGE gauge
DCGM_FI_DEV_POWER_USAGE{gpu="0",UUID="GPU-0a1b2c3d-0000-0000-0000-000000000001",device="nvidia0",modelName="NVIDIA H100 80GB HBM3",Hostname="tx-node-01",site="SITE-TX",pool="tx-h100"} 612.5
DCGM_FI_DEV_POWER_USAGE{gpu="1",UUID="GPU-0a1b2c3d-0000-0000-0000-000000000002",device="nvidia1",modelName="NVIDIA H100 80GB HBM3",Hostname="tx-node-01",site="SITE-TX",pool="tx-h100"} 587.5
DCGM_FI_DEV_POWER_USAGE{gpu="0",UUID="GPU-0a1b2c3d-0000-0000-0000-000000000003",device="nvidia0",modelName="NVIDIA H100 80GB HBM3",Hostname="or-node-07",site="SITE-OR",pool="or-h100"} 400 1792195200000
# HELP DCGM_FI_DEV_GPU_TEMP GPU temperature (in C).
# TYPE DCGM_FI_DEV_GPU_TEMP gauge
DCGM_FI_DEV_GPU_TEMP{gpu="0",UUID="GPU-0a1b2c3d-0000-0000-0000-000000000001",Hostname="tx-node-01",site="SITE-TX",pool="tx-h100"} 61
```

`examples/telemetry/dr_events.json`:
```
{
  "events": [
    {"site_id": "SITE-OR", "start_hour": 8, "end_hour": 16, "limit_kw": 650}
  ]
}
```

`README.md`: mark roadmap item 4 done the way item 3 is (struck through, then **Done**), saying it replays telemetry files in real formats (dcgm-exporter text, demand-response events) with synthetic samples and no network polling (the word `replay` must appear); add a short section with the `--telemetry` usage and the two file formats, including that GPU power samples need a `site` label. `HANDOFF.md`: mark roadmap item 4 done; add a new paragraph right after the paragraph that starts **The sample data is synthetic.**, stating the current state: `plan --telemetry DIR` replays dcgm-exporter power readings and demand-response events; the sample telemetry is synthetic too; GPU availability is not taken from telemetry; there is no live polling. The words `--telemetry` must appear in it. Do not touch the "Written at commit" line.

Add `tests/test_telemetry_cli.py` (copy the two data files into `tmp_path/data` and `examples/telemetry/*` into `tmp_path/tel`, `chdir` to `tmp_path`, as `tests/test_cli.py` does):
1. `main(["plan", "--telemetry", "tel"])` returns 0; the first stdout line is `telemetry: 3 GPU power samples, 1 demand-response events`; the output contains `W-005` placed with `starts at hour 16`.
2. With `--compare-optimal` added, it returns 0 and the output contains `gap 0.0000` and `moved: none`.
3. **Boundary:** an empty directory → returns 2, stderr contains `no telemetry files in`; a directory holding only `dr_events.json` → returns 0 and the first line reports `0 GPU power samples, 1 demand-response events`.
4. `README.md` contains `replay`; `HANDOFF.md` contains `--telemetry`.

Files: powerplan/cli.py examples/telemetry/dcgm.prom examples/telemetry/dr_events.json README.md HANDOFF.md tests/test_telemetry_cli.py tests/test_cli.py powerplan/telemetry.py powerplan/models.py powerplan/engine.py powerplan/optimal.py powerplan/trace.py powerplan/explain.py powerplan/audit.py powerplan/whatif.py data/fleet.json data/workloads.json

Live command:
`python3 -m pytest tests/test_telemetry_cli.py tests -q`

## Rules
Branch `brief/POWERPLAN-016` only; never write `main`. The repo guide file and everything under `data/` are read-only. No new dependencies (stdlib only at runtime).
- Change only files on the step's `Files:` line that the step asks you to change; every other file, and every existing test, is read-only.
- Never edit an existing test. If one fails after your change, do not bend the code to satisfy it against the documented behaviour: name the test and the conflict in your reply and stop.
- If you think a file that is not on the `Files:` line must change, do not edit it and do not work around it in another file: name the file and the reason in your reply and stop.
- If a requirement can be read two ways that give different results, do not choose: name both readings in your reply and stop without changing code.

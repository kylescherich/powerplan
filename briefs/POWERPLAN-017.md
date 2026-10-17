# POWERPLAN-017 — roadmap item 5: weight advisor (`advise --goal`)

- From → To: HUB → devws-cloud runner
- Created: 2026-10-17
- Status: queued
- unattended: yes
- model: anthropic/claude-sonnet-5-5
- Decision: DEC-314 (Kyle: "do whatever we can today"; roadmap item 5 as a deterministic, stdlib advisor with human approval; DEC-303 standing rules; CTR-DEVWS-CLOUD-001 0.1.5)

## Goal
Roadmap item 5: take a goal like "cut carbon 50%" and **propose** objective weights that meet it, showing what would change, for a human to approve. Deterministic and stdlib-only: a search over a fixed weight grid, **no language model and no auto-apply**. The command prints the exact `plan` flags to run; a person decides. It never trades away placed work. The expected values below were computed by the Hub in advance from a prototype on `main` `964f009` (all 189 existing tests stay green with it); they are the oracle.

## Design (fixed; do not change it)
New module `powerplan/advisor.py`:
- `GRID`: every weight set `{"cost": c/20, "carbon": k/20, "runtime": (20-c-k)/20}` for integers `c` in 0…20 and `k` in 0…20−c (231 sets, step 0.05, summing to 1). Use exactly `c/20` etc. so values compare exactly.
- `advise(fleet, workloads, metric, reduction, base_weights=None)` → a `Proposal` dataclass with fields `metric`, `reduction`, `feasible`, `weights`, `distance`, `baseline` (Plan), `proposed` (Plan), `moved`.
  - `metric` is `"cost"` (plan `total_cost`) or `"carbon"` (plan `total_carbon_kg`); otherwise `ValueError`. `reduction` must satisfy `0 <= reduction < 1`; otherwise `ValueError`. `base_weights` defaults to `DEFAULT_WEIGHTS`.
  - Every plan is made on a **deep copy** of `fleet`; the caller's fleet is left unchanged.
  - Baseline = the plan with `base_weights`. A grid set is a **candidate** only if its plan places the same number of workloads at each priority as the baseline.
  - `distance` = sum over the three keys of |grid weight − base weight|, rounded to 9 decimals.
  - **Feasible** if some candidate's metric ≤ baseline metric × (1 − reduction) (+1e-9). Choose among those: smallest distance, then lower metric, then lower `cost` weight, then lower `carbon` weight.
  - **Not feasible:** choose the candidate with the lowest metric, then smallest distance, then lower `cost` weight, then lower `carbon` weight; `feasible` False.
  - `moved` = list of `(workload_id, (site, pool, start_hour) before, (site, pool, start_hour) after)` for workloads whose placement differs from the baseline, in the proposed plan's placement order.

CLI `advise --goal METRIC:PERCENT` (step 2), with the usual `--fleet`, `--workloads` and `--w-*` options (the `--w-*` values, normalised as `plan` does, are the base weights). `PERCENT` may end in `%`; metric must be `cost` or `carbon` and `0 <= PERCENT < 100`, else print `goal must look like cost:15 or carbon:50` to stderr and return 2. Output lines, in order (`{v:,.0f}` for amounts; percentages `{:+.1f}%` relative to the baseline; cost shown as `$N`, carbon as `N kg CO2e`):
1. `goal: cut METRIC by P% (baseline X)` (P printed with `:g`)
2. Feasible: `proposal: cost A, carbon B, runtime C (distance D from current weights)`; not feasible: `not reachable without placing less work; closest: cost A, carbon B, runtime C (distance D from current weights)` (weights and distance `:.2f`)
3. `result: <goal metric> <value> (<change>), <other metric> <value> (<change>)`
4. one `moved: W-ID SITE/POOL@H -> SITE/POOL@H` line per moved workload
5. last: `to apply: python -m powerplan plan --w-cost A --w-carbon B --w-runtime C`
Return 0 when feasible, 1 when not. No audit record is written.

## Step 1 — the advisor
Add `powerplan/advisor.py` as designed and `tests/test_advisor.py` (real data `data/fleet.json` + `data/workloads.json`, default base weights; floats ±1e-6):
1. `len(GRID) == 231`; every set sums to 1 (±1e-12).
2. **Carbon −50 % (feasible):** weights cost 0.30 / carbon 0.35 / runtime 0.35, distance 0.3; proposed carbon 2255.3593 kg vs baseline 5640.4916; proposed cost 1310.0439; `moved` = W-001 (SITE-TX, tx-h100, 0) → (SITE-OR, or-h100, 0), W-003 (SITE-OR, or-h100, 10) → (SITE-EU, eu-h100, 10), W-005 (SITE-OR, or-h100, 8) → (SITE-TX, tx-h100, 10), in that order.
3. **Boundary — cost −15 % (not reachable):** `feasible` False; weights 0.90 / 0.05 / 0.05, distance 0.9; proposed cost 1110.158 vs baseline 1127.8018; proposed carbon 6041.0721.
4. **Boundary — zero reduction:** carbon 0 % → feasible, the base weights themselves (0.45 / 0.25 / 0.30), distance 0.0, `moved` empty.
5. Cost −1 % → feasible, weights 0.45 / 0.00 / 0.55, distance 0.5, proposed cost 1111.6261.
6. The caller's fleet is unchanged after `advise` (every site's `committed_kw_by_hour` all 0 and every pool's `available == total`); `metric="power"` and `reduction=1.0` each raise `ValueError`.

Files: powerplan/advisor.py tests/test_advisor.py powerplan/engine.py powerplan/models.py data/fleet.json data/workloads.json

Live command:
`python3 -m pytest tests/test_advisor.py tests -q`

## Step 2 — `advise` command and docs
`powerplan/cli.py`: the `advise` subcommand as designed. `README.md`: mark roadmap item 5 done the way item 4 is (struck through, then **Done**), saying it is a deterministic weight search that proposes and never applies (the words `never applies` must appear), with a usage example. `HANDOFF.md`: mark item 5 done and add one sentence that the advisor searches a fixed 0.05 weight grid and never trades away placed work. Do not touch the "Written at commit" line.
Add `tests/test_advisor_cli.py` (copy the data into `tmp_path/data` and `chdir` there, as `tests/test_cli.py` does):
1. `main(["advise", "--goal", "carbon:50"])` returns 0 and prints exactly these lines:
   ```
   goal: cut carbon by 50% (baseline 5,640 kg CO2e)
   proposal: cost 0.30, carbon 0.35, runtime 0.35 (distance 0.30 from current weights)
   result: carbon 2,255 kg CO2e (-60.0%), cost $1,310 (+16.2%)
   moved: W-001 SITE-TX/tx-h100@0 -> SITE-OR/or-h100@0
   moved: W-003 SITE-OR/or-h100@10 -> SITE-EU/eu-h100@10
   moved: W-005 SITE-OR/or-h100@8 -> SITE-TX/tx-h100@10
   to apply: python -m powerplan plan --w-cost 0.30 --w-carbon 0.35 --w-runtime 0.35
   ```
2. `main(["advise", "--goal", "cost:15%"])` returns 1; line 2 is `not reachable without placing less work; closest: cost 0.90, carbon 0.05, runtime 0.05 (distance 0.90 from current weights)`; line 3 is `result: cost $1,110 (-1.6%), carbon 6,041 kg CO2e (+7.1%)`.
3. **Boundary:** `--goal bogus:5` and `--goal carbon:100` each return 2 with `goal must look like cost:15 or carbon:50` on stderr.
4. `README.md` contains `never applies`; `HANDOFF.md` contains `0.05`.

Files: powerplan/cli.py README.md HANDOFF.md tests/test_advisor_cli.py tests/test_cli.py powerplan/advisor.py powerplan/engine.py powerplan/models.py powerplan/optimal.py powerplan/trace.py powerplan/telemetry.py powerplan/explain.py powerplan/audit.py powerplan/whatif.py data/fleet.json data/workloads.json

Live command:
`python3 -m pytest tests/test_advisor_cli.py tests -q`

## Rules
Branch `brief/POWERPLAN-017` only; never write `main`. The repo guide file and everything under `data/` are read-only. No new dependencies (stdlib only at runtime).
- Change only files on the step's `Files:` line that the step asks you to change; every other file, and every existing test, is read-only.
- Never edit an existing test. If one fails after your change, do not bend the code to satisfy it against the documented behaviour: name the test and the conflict in your reply and stop.
- If you think a file that is not on the `Files:` line must change, do not edit it and do not work around it in another file: name the file and the reason in your reply and stop.
- If a requirement can be read two ways that give different results, do not choose: name both readings in your reply and stop without changing code.

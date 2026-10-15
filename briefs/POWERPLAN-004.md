# POWERPLAN-004 — make the start-hour rule match its design

- From → To: HUB → devws-cloud runner
- Created: 2026-10-15
- Status: queued
- unattended: yes
- model: sonnet
- Decision: DEC-254 (CTR-DEVWS-CLOUD-001 0.1.3)

## Goal
POWERPLAN-003 (now on `main`) added price/carbon curves and start hours, but the Hub's review found the start-hour choice does not follow the design in `briefs/POWERPLAN-003.md`. Fix exactly these points in `powerplan/engine.py` and `powerplan/models.py`, nothing else. Same rules as before: `CLAUDE.md`, stdlib only, every existing test file read-only (including the ones POWERPLAN-003 added), stop and name any existing test that breaks.

## Step 1 — the start-hour rule
In `_build_candidate` (`powerplan/engine.py`):
1. **Objective.** Today it adds dollars and kilograms (`w_cost × cost + w_carbon × carbon`), so whichever unit has the bigger numbers wins regardless of the weights. Use the ratio to the hour-0 values instead: `w_cost × cost(s)/cost(0) + w_carbon × carbon(s)/carbon(0)` (a term is 0 when its hour-0 value is 0). Ties → the earliest hour (keep the strict `<`).
2. **Range.** Today `max_start = 24 − runtime`, so a job longer than 24 h can never defer and a 6 h job cannot start after hour 18. Use `L = 23` without a deadline, else `L = min(23, floor(deadline_hours − runtime))`; curves already wrap (`hour % 24`).
3. **Type.** `start_hour` is an `int` (0 for non-interruptible and no-curve sites). Keep `deferral_saved_usd` / `deferral_saved_kg` as they are.
4. **Field order.** Move `start_hour`, `deferral_saved_usd`, `deferral_saved_kg` to the end of `Candidate`, after `components`, keeping their defaults.

Add `tests/test_start_hour_rule.py`, building small fleets in the test; each placement test first asserts the plan has a placement:
- **Weights decide, not units:** one site, flat price 0.10 except 0.05 at hour 5 (50 % cheaper); flat carbon 300 except 240 at hour 15 (20 % cleaner); a 1 h interruptible job; weights cost 0.5, carbon 0.5, runtime 0 → `start_hour == 5`. With weights cost 0.1, carbon 0.9 → `start_hour == 15`.
- **Long jobs can defer:** a 30 h interruptible job without a deadline on a site whose price is 0.20 for hours 0–5 and 0.05 otherwise → `start_hour >= 6`.
- **Late starts wrap:** a 6 h interruptible job on a site that is cheapest for hours 23, 0, 1, 2, 3, 4 → `start_hour == 23`.
- `start_hour` is an `int` for deferred and non-deferred placements.
- The last three fields of `dataclasses.fields(Candidate)` are `start_hour`, `deferral_saved_usd`, `deferral_saved_kg`.

Files: powerplan/engine.py tests/test_start_hour_rule.py

Live command:
`python3 -m pytest tests/test_start_hour_rule.py tests -q`

## Step 2 — curve errors name the site
In `powerplan/models.py` `Site.__post_init__`: start each `ValueError` message with the site id and the field, e.g. `SITE-X: price_curve must have exactly 24 values, got 23` and `SITE-X: carbon_curve must be non-negative`. Keep the rest of each message as it is now (existing tests match on it).

Add `tests/test_curve_errors.py`: for both fields and both errors, the message contains the site id and the field name.

Files: powerplan/models.py tests/test_curve_errors.py

Live command:
`python3 -m pytest tests/test_curve_errors.py tests -q`

## Rules
Branch `brief/POWERPLAN-004` only; never write `main`. Only `powerplan/engine.py`, `powerplan/models.py` and the two new test files may change. No new dependencies. Stop at the first failing step and still write the report; if an existing test breaks, name it and stop — do not edit it.

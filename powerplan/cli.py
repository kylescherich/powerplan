"""Command line interface.

    python -m powerplan plan   --fleet data/fleet.json --workloads data/workloads.json
    python -m powerplan whatif --fleet data/fleet.json --workloads data/workloads.json \
        --offline SITE-TX
    python -m powerplan whatif --curtail SITE-TX:0.4
"""

from __future__ import annotations

import argparse
import sys

from . import audit, explain, whatif
from .engine import DEFAULT_WEIGHTS, plan as make_plan
from .models import load_fleet, load_workloads
from .optimal import SearchTooLarge, compare, format_gap
from .trace import Tracer


def _weights(args) -> dict:
    w = dict(DEFAULT_WEIGHTS)
    if args.w_cost is not None:
        w["cost"] = args.w_cost
    if args.w_carbon is not None:
        w["carbon"] = args.w_carbon
    if args.w_runtime is not None:
        w["runtime"] = args.w_runtime
    total = sum(w.values())
    return {k: v / total for k, v in w.items()}


def _common(p: argparse.ArgumentParser) -> None:
    p.add_argument("--fleet", default="data/fleet.json")
    p.add_argument("--workloads", default="data/workloads.json")
    p.add_argument("--audit", default="audit.jsonl")
    p.add_argument("--w-cost", type=float)
    p.add_argument("--w-carbon", type=float)
    p.add_argument("--w-runtime", type=float)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="powerplan")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_plan = sub.add_parser("plan", help="produce and explain a placement plan")
    _common(p_plan)
    p_plan.add_argument(
        "--compare-optimal",
        action="store_true",
        help="also compare the greedy plan against an exact optimum",
    )
    p_plan.add_argument(
        "--trace",
        metavar="PATH",
        help="write an OpenTelemetry-shaped span log (JSON lines) to PATH",
    )

    p_what = sub.add_parser("whatif", help="perturb the fleet and diff the plan")
    _common(p_what)
    p_what.add_argument("--offline", metavar="SITE", help="take a site fully offline")
    p_what.add_argument(
        "--curtail", metavar="SITE:FRACTION", help="cut a site's power ceiling"
    )
    p_what.add_argument(
        "--degrade", metavar="SITE:POOL:N", help="N accelerators fail in a pool"
    )
    p_what.add_argument(
        "--price", metavar="SITE:MULT", help="multiply a site's price curve"
    )

    args = ap.parse_args(argv)
    fleet = load_fleet(args.fleet)
    workloads = load_workloads(args.workloads)
    weights = _weights(args)

    if args.cmd == "plan":
        tracer = Tracer() if args.trace else None
        result = make_plan(fleet, workloads, weights, tracer=tracer)
        print(explain.summarise(result))
        print()
        for p in result.placements:
            print(explain.explain(p))
            print()
        run_id = audit.record(result, fleet, workloads, args.audit)
        print(f"audit run_id {run_id} -> {args.audit}")
        exit_code = 0
        if args.compare_optimal:
            try:
                report = compare(fleet, workloads, weights)
            except SearchTooLarge as exc:
                print(str(exc), file=sys.stderr)
                exit_code = 3
            else:
                print()
                print(format_gap(report))
        if tracer is not None:
            count = tracer.to_jsonl(args.trace)
            print(f"trace: {count} spans -> {args.trace}")
        return exit_code

    # whatif
    perturbed = fleet
    label = []
    if args.offline:
        perturbed = whatif.site_offline(perturbed, args.offline)
        label.append(f"offline={args.offline}")
    if args.curtail:
        site, frac = args.curtail.split(":")
        perturbed = whatif.curtail(perturbed, site, float(frac))
        label.append(f"curtail={args.curtail}")
    if args.degrade:
        site, pool, n = args.degrade.split(":")
        perturbed = whatif.pool_degraded(perturbed, site, pool, int(n))
        label.append(f"degrade={args.degrade}")
    if args.price:
        site, mult = args.price.split(":")
        perturbed = whatif.price_spike(perturbed, site, float(mult))
        label.append(f"price={args.price}")

    if not label:
        print("no perturbation given; see --help", file=sys.stderr)
        return 2

    base, scen = whatif.run_scenario(fleet, workloads, perturbed, weights)
    scenario = ",".join(label)
    print(f"scenario: {scenario}\n")
    print(whatif.diff(base, scen))
    print()
    audit.record(scen, perturbed, workloads, args.audit, scenario=scenario)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

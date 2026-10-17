"""Command-line entry point for replaying and extending a prototype search."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .controller import HierExperiment
from .model import ActionKind, MacroAction


def _summary(candidate):
    evaluation = candidate.evaluation
    return {
        "candidate_id": candidate.candidate_id,
        "valid": evaluation.valid,
        "passed": evaluation.passed,
        "margin_db": evaluation.margin_db,
        "ripple_db": evaluation.ripple_db,
        "area_um2_est": evaluation.area_um2_est,
        "regions": [
            {
                "id": region.region_id,
                "inputs": [vars(signal) for signal in region.input_signals],
                "outputs": [vars(signal) for signal in region.output_signals],
                "area_um2_est": region.area_um2_est,
            }
            for region in candidate.regions
        ],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--margin", type=float, default=0.3)
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init")
    init.add_argument("--seed", type=Path, required=True)
    tune = sub.add_parser("tune")
    tune.add_argument("--parent", required=True)
    tune.add_argument("--set", action="append", default=[], metavar="KEY=JSON")
    tune.add_argument("--rationale", required=True)
    add = sub.add_parser("add")
    add.add_argument("--parent", required=True)
    add.add_argument("--program", type=Path, required=True)
    add.add_argument("--kind", choices=[k.value for k in ActionKind if k not in (ActionKind.ROOT, ActionKind.TUNE)],
                     required=True)
    add.add_argument("--region", action="append", default=[])
    add.add_argument("--rationale", required=True)
    attribute = sub.add_parser("attribute")
    attribute.add_argument("--candidate", required=True)
    attribute.add_argument("--extra-bits", type=int, default=4)
    args = parser.parse_args()

    experiment = HierExperiment(args.task, args.out, args.margin)
    if args.command == "init":
        candidate = experiment.add_root(args.seed.read_text())
        attribution = experiment.attribute(candidate.candidate_id)
        print(json.dumps({"candidate": _summary(candidate), "attribution": [vars(row) for row in attribution]},
                         ensure_ascii=False, indent=2))
    elif args.command == "tune":
        edits = {}
        for item in args.set:
            key, value = item.split("=", 1)
            edits[key] = json.loads(value)
        candidate = experiment.tune(args.parent, edits, args.rationale)
        print(json.dumps({"candidate": _summary(candidate),
                          "frontier_ids": [row.candidate_id for row in experiment.frontier()]},
                         ensure_ascii=False, indent=2))
    elif args.command == "add":
        candidate = experiment.add_source(
            args.program.read_text(),
            MacroAction(ActionKind(args.kind), args.region or ["root"], args.rationale),
            args.parent,
        )
        print(json.dumps({"candidate": _summary(candidate),
                          "frontier_ids": [row.candidate_id for row in experiment.frontier()]},
                         ensure_ascii=False, indent=2))
    elif args.command == "attribute":
        rows = experiment.attribute(args.candidate, args.extra_bits)
        print(json.dumps([vars(row) for row in rows], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

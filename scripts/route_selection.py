#!/usr/bin/env python3
"""Pure deterministic selection policy for snapshot route candidates."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


CORE_ROLES = {"semantic-core", "simplify", "test-effectiveness"}
HIGH_IMPACT_WEAK = {"security", "data-integrity", "reliability", "rollout"}


def select_routes(
    candidates: dict[str, list[dict[str, Any]]], classifier_selected: set[str] | None,
) -> dict[str, Any]:
    """Select core/strong routes, or bounded high-impact weak fallbacks on failure."""
    strong = {
        role for role, signals in candidates.items()
        if any(signal.get("strength") == "strong" for signal in signals)
    }
    weak = {
        role for role, signals in candidates.items()
        if any(signal.get("strength") == "weak" for signal in signals) and role not in strong
    }
    selected = CORE_ROLES | strong
    not_evaluated: dict[str, str] = {}
    if classifier_selected is not None:
        selected |= weak & classifier_selected
    else:
        # This four-role set is an add-on budget, never a global reviewer cap.
        selected |= weak & HIGH_IMPACT_WEAK
        for role in sorted(weak - HIGH_IMPACT_WEAK):
            not_evaluated[role] = "routing_classifier_failed"
    return {
        "selected": sorted(selected), "not_evaluated": not_evaluated,
        "strong_routes": sorted(strong), "weak_routes": sorted(weak),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", required=True, help="snapshot JSON containing route_candidates")
    classifier = parser.add_mutually_exclusive_group(required=True)
    classifier.add_argument("--classifier-result", help="JSON with status completed and selected reviewer names")
    classifier.add_argument("--classifier-failed", action="store_true")
    parser.add_argument("--output", default="-")
    args = parser.parse_args()
    try:
        snapshot = json.loads(Path(args.snapshot).read_text(encoding="utf-8"))
        candidates = snapshot.get("route_candidates")
        if not isinstance(candidates, dict):
            raise ValueError("snapshot.route_candidates must be an object")
        if args.classifier_failed:
            classifier_selected: set[str] | None = None
        else:
            result = json.loads(Path(args.classifier_result).read_text(encoding="utf-8"))
            if result.get("status") != "completed" or not isinstance(result.get("selected"), list) or not all(isinstance(role, str) for role in result["selected"]):
                raise ValueError("classifier result must have status completed and string selected array")
            classifier_selected = set(result["selected"])
        output = select_routes(candidates, classifier_selected)
        encoded = json.dumps(output, indent=2, sort_keys=True) + "\n"
        if args.output == "-":
            sys.stdout.write(encoded)
        else:
            Path(args.output).write_text(encoded, encoding="utf-8")
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"route_selection: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

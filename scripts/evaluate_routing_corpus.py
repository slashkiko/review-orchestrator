#!/usr/bin/env python3
"""Measure deterministic route candidate/selection quality against labeled fixtures."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import route_selection
import review_snapshot


HIGH_RISK = {"security", "data-integrity", "reliability", "rollout"}
CONDITIONAL = route_selection.HIGH_IMPACT_WEAK | {
    "language-idiom", "compatibility", "observability", "contract-design", "performance",
    "dependency", "accessibility", "docs-dx", "sensitive-data",
}


def corpus_error(message: str) -> ValueError:
    return ValueError(f"routing corpus: {message}")


def validate_corpus(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, dict) or set(value) != {"schema_version", "cases"} or value["schema_version"] != 1:
        raise corpus_error("unsupported schema")
    cases = value["cases"]
    if not isinstance(cases, list) or not cases:
        raise corpus_error("cases must be a non-empty array")
    names: set[str] = set()
    for case in cases:
        required = {"name", "files", "added_lines", "sensitive_candidates", "classifier", "expected_high_risk", "expected_strong"}
        if not isinstance(case, dict) or set(case) != required:
            raise corpus_error("case has an unsupported schema")
        if not isinstance(case["name"], str) or not case["name"] or case["name"] in names:
            raise corpus_error("case names must be unique non-empty strings")
        names.add(case["name"])
        if not isinstance(case["files"], list) or not isinstance(case["added_lines"], list) or not isinstance(case["sensitive_candidates"], list):
            raise corpus_error("raw change inputs must be arrays")
        if any(not isinstance(item, dict) or not isinstance(item.get("path"), str) or not isinstance(item.get("roles"), list) for item in case["files"]):
            raise corpus_error("raw file input is invalid")
        if any(not isinstance(item, list) or len(item) != 3 or not isinstance(item[0], str) or not isinstance(item[1], int) or not isinstance(item[2], str) for item in case["added_lines"]):
            raise corpus_error("raw added line input is invalid")
        classifier = case["classifier"]
        if classifier is not None and (not isinstance(classifier, list) or any(role not in CONDITIONAL for role in classifier)):
            raise corpus_error("classifier must be null or known route array")
        for field, allowed in (("expected_high_risk", HIGH_RISK), ("expected_strong", CONDITIONAL)):
            values = case[field]
            if not isinstance(values, list) or len(values) != len(set(values)) or any(route not in allowed for route in values):
                raise corpus_error(f"{field} is invalid")
    return cases


def ratio(numerator: int, denominator: int) -> float | None:
    return None if denominator == 0 else numerator / denominator


def evaluate(cases: list[dict[str, Any]]) -> dict[str, Any]:
    high_expected = high_caught = strong_correct = strong_selected = 0
    failures: list[str] = []
    for case in cases:
        candidates = review_snapshot.route_candidates(case["files"], [tuple(item) for item in case["added_lines"]], case["sensitive_candidates"])
        selected = set(route_selection.select_routes(candidates, None if case["classifier"] is None else set(case["classifier"]))["selected"])
        expected_high = set(case["expected_high_risk"])
        expected_strong = set(case["expected_strong"])
        high_expected += len(expected_high)
        high_caught += len(expected_high & selected)
        actual_strong = {role for role, signals in candidates.items() if any(signal["strength"] == "strong" for signal in signals) and role in selected}
        strong_selected += len(actual_strong)
        strong_correct += len(actual_strong & expected_strong)
        if not expected_high <= selected:
            failures.append(case["name"] + ": high-risk route missed")
    recall = ratio(high_caught, high_expected)
    precision = ratio(strong_correct, strong_selected)
    passed = recall is not None and precision is not None and recall >= 1.0 and precision >= 0.8
    return {
        "schema_version": 1, "metric_scope": "deterministic_candidate_and_selection_only",
        "host_e2e_classifier_metric": "not_run",
        "high_risk_recall": {"numerator": high_caught, "denominator": high_expected, "value": recall, "threshold": 1.0},
        "conditional_precision": {"numerator": strong_correct, "denominator": strong_selected, "value": precision, "threshold": 0.8},
        "case_count": len(cases), "failures": failures, "passed": passed,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", required=True)
    parser.add_argument("--output", default="-")
    args = parser.parse_args()
    try:
        output = evaluate(validate_corpus(json.loads(Path(args.corpus).read_text(encoding="utf-8"))))
        encoded = json.dumps(output, indent=2, sort_keys=True) + "\n"
        if args.output == "-":
            sys.stdout.write(encoded)
        else:
            Path(args.output).write_text(encoded, encoding="utf-8")
        return 0 if output["passed"] else 1
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"evaluate_routing_corpus: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

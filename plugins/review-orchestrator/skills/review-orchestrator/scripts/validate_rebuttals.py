#!/usr/bin/env python3
"""Validate rebuttal verdicts against the immutable snapshot they answer."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import validate_findings


VERDICTS = {"upheld", "weakened", "refuted", "unverifiable"}
COUNTER_EVIDENCE_VERDICTS = {"weakened", "refuted"}
REBUTTAL_FIELDS = {
    "rebuttal_of", "snapshot_hash", "verdict", "rationale",
    "narrowed_condition", "missing_evidence", "counter_evidence",
}
TARGET_FIELDS = {"reviewer", "finding_id"}


def validate_target(value: Any, where: str, errors: list[str]) -> tuple[str, str] | None:
    if not isinstance(value, dict):
        errors.append(f"{where} must be an object")
        return None
    validate_findings.exact_fields(value, TARGET_FIELDS, where, errors)
    validate_findings.require_string(value, "reviewer", where, errors)
    validate_findings.require_string(value, "finding_id", where, errors)
    if value.get("reviewer") not in validate_findings.REVIEWERS:
        errors.append(f"{where}.reviewer is invalid")
    if not isinstance(value.get("reviewer"), str) or not isinstance(value.get("finding_id"), str):
        return None
    return value["reviewer"], value["finding_id"]


def validate_rebuttal(
    value: Any, index: int, snapshot: dict[str, Any], errors: list[str],
) -> tuple[str, str] | None:
    where = f"rebuttals[{index}]"
    if not isinstance(value, dict):
        errors.append(f"{where} must be an object")
        return None
    validate_findings.exact_fields(value, REBUTTAL_FIELDS, where, errors)
    target = validate_target(value.get("rebuttal_of"), f"{where}.rebuttal_of", errors)
    if value.get("snapshot_hash") != snapshot.get("snapshot_hash"):
        errors.append(f"{where}.snapshot_hash does not match snapshot")
    verdict = value.get("verdict")
    if verdict not in VERDICTS:
        errors.append(f"{where}.verdict is invalid")
    validate_findings.require_string(value, "rationale", where, errors)

    if verdict == "weakened":
        validate_findings.require_string(value, "narrowed_condition", where, errors)
    elif value.get("narrowed_condition") is not None:
        errors.append(f"{where}.narrowed_condition is only valid for a weakened verdict")
    if verdict == "unverifiable":
        validate_findings.require_string(value, "missing_evidence", where, errors)
    elif value.get("missing_evidence") is not None:
        errors.append(f"{where}.missing_evidence is only valid for an unverifiable verdict")

    counter = value.get("counter_evidence")
    if verdict in COUNTER_EVIDENCE_VERDICTS:
        validate_findings.validate_evidence(counter, snapshot, f"{where}.counter_evidence", errors)
    elif counter != []:
        errors.append(f"{where}.counter_evidence must be empty unless the finding is weakened or refuted")
    return target


def validate(snapshot: dict[str, Any], document: Any) -> tuple[dict[str, Any], list[str]]:
    errors: list[str] = []
    if snapshot.get("schema_version") not in {3, 4}:
        errors.append("snapshot schema version is unsupported")
    calculated = validate_findings.snapshot_identity_hash(snapshot)
    if calculated is None or calculated != snapshot.get("snapshot_hash"):
        errors.append("snapshot canonical identity is invalid")
    if not isinstance(document, list):
        errors.append("rebuttals must be an array")
        return {"valid": False, "errors": errors, "verdicts": {}}, errors

    leak_paths, candidate_errors = validate_findings.candidate_sensitive_paths(snapshot, document)
    errors.extend(candidate_errors)
    errors.extend(
        f"{path} contains a raw sensitive value; use redacted candidate metadata"
        for path in leak_paths
    )

    seen: set[tuple[str, str]] = set()
    verdicts: dict[str, int] = {name: 0 for name in sorted(VERDICTS)}
    for index, item in enumerate(document):
        target = validate_rebuttal(item, index, snapshot, errors)
        if target is not None:
            if target in seen:
                errors.append(f"rebuttals[{index}] repeats a finding already rebutted")
            seen.add(target)
        if isinstance(item, dict) and item.get("verdict") in verdicts:
            verdicts[item["verdict"]] += 1
    return {"valid": not errors, "errors": errors, "verdicts": verdicts, "rebutted": len(seen)}, errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", required=True)
    parser.add_argument("--input", required=True, help="JSON array of rebuttal verdicts")
    parser.add_argument("--output", default="-")
    args = parser.parse_args()
    try:
        snapshot = json.loads(Path(args.snapshot).read_text(encoding="utf-8"))
        document = json.loads(Path(args.input).read_text(encoding="utf-8"))
        output, errors = validate(snapshot, document)
        encoded = json.dumps(output, indent=2, sort_keys=True) + "\n"
        if args.output == "-":
            sys.stdout.write(encoded)
        else:
            Path(args.output).write_text(encoded, encoding="utf-8")
        return 0 if not errors else 1
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"validate_rebuttals: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

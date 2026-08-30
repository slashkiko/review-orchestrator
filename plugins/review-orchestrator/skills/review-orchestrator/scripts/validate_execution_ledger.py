#!/usr/bin/env python3
"""Validate a host-neutral, main-owned reviewer execution ledger."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


VERSION = 1
TIERS = {"fast", "balanced", "deep"}
TERMINAL_STATUSES = {"completed", "failed", "timed_out", "cancelled", "not_started"}
SCHEMA_RESULTS = {"passed", "failed", "not_run"}
ACTUAL_EXPOSURE = {"reported", "not_exposed"}
CORE_ROLES = {"semantic-core", "simplify", "test-effectiveness"}
CONDITIONAL_ROLES = {
    "language-idiom", "security", "reliability", "data-integrity", "compatibility", "rollout",
    "observability", "contract-design", "performance", "dependency", "accessibility", "docs-dx",
    "sensitive-data",
}
AUXILIARY_ROLES = {"validator", "routing-classifier"}
KNOWN_ROLES = CORE_ROLES | CONDITIONAL_ROLES | AUXILIARY_ROLES
TOP_LEVEL_FIELDS = {"schema_version", "snapshot_hash", "selected_roles", "entries"}
ENTRY_FIELDS = {
    "role", "requested", "actual", "host_task_id", "attempt",
    "retry_or_escalation_reason", "terminal_status", "timeout_seconds",
    "schema_validation",
}


def error_if(condition: bool, message: str, errors: list[str]) -> None:
    if condition:
        errors.append(message)


def exact_fields(value: Any, expected: set[str], where: str, errors: list[str]) -> None:
    if not isinstance(value, dict):
        errors.append(f"{where} must be an object")
        return
    missing = sorted(expected - value.keys())
    unexpected = sorted(value.keys() - expected)
    if missing:
        errors.append(f"{where} missing fields: {', '.join(missing)}")
    if unexpected:
        errors.append(f"{where} has unexpected fields: {', '.join(unexpected)}")


def nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def validate_entry(entry: Any, index: int, errors: list[str]) -> None:
    where = f"entries[{index}]"
    exact_fields(entry, ENTRY_FIELDS, where, errors)
    if not isinstance(entry, dict):
        return
    error_if(not nonempty_string(entry.get("role")), f"{where}.role must be a non-empty string", errors)
    error_if(entry.get("role") not in KNOWN_ROLES, f"{where}.role is unknown", errors)
    requested = entry.get("requested")
    exact_fields(requested, {"tier", "model", "effort"}, f"{where}.requested", errors)
    if isinstance(requested, dict):
        error_if(requested.get("tier") not in TIERS, f"{where}.requested.tier is invalid", errors)
        error_if(requested.get("model") is not None and not nonempty_string(requested.get("model")), f"{where}.requested.model must be a non-empty string or null", errors)
        error_if(requested.get("effort") is not None and not nonempty_string(requested.get("effort")), f"{where}.requested.effort must be a non-empty string or null", errors)
    actual = entry.get("actual")
    exact_fields(actual, {"exposure", "model", "effort"}, f"{where}.actual", errors)
    if isinstance(actual, dict):
        error_if(actual.get("exposure") not in ACTUAL_EXPOSURE, f"{where}.actual.exposure is invalid", errors)
        for key in ("model", "effort"):
            error_if(actual.get(key) is not None and not nonempty_string(actual.get(key)), f"{where}.actual.{key} must be a non-empty string or null", errors)
        if actual.get("exposure") == "not_exposed":
            error_if(actual.get("model") is not None or actual.get("effort") is not None, f"{where}.actual must be null-valued when not exposed", errors)
        if actual.get("exposure") == "reported":
            error_if(not nonempty_string(actual.get("model")), f"{where}.actual.model is required when reported", errors)
    error_if(not nonempty_string(entry.get("host_task_id")), f"{where}.host_task_id must be a non-empty string", errors)
    attempt = entry.get("attempt")
    error_if(not isinstance(attempt, int) or isinstance(attempt, bool) or attempt < 1, f"{where}.attempt must be a positive integer", errors)
    retry = entry.get("retry_or_escalation_reason")
    error_if(retry is not None and not nonempty_string(retry), f"{where}.retry_or_escalation_reason must be a non-empty string or null", errors)
    error_if(entry.get("terminal_status") not in TERMINAL_STATUSES, f"{where}.terminal_status is invalid", errors)
    timeout = entry.get("timeout_seconds")
    error_if(not isinstance(timeout, int) or isinstance(timeout, bool) or timeout < 1, f"{where}.timeout_seconds must be a positive integer", errors)
    error_if(entry.get("schema_validation") not in SCHEMA_RESULTS, f"{where}.schema_validation is invalid", errors)
    terminal = entry.get("terminal_status")
    schema = entry.get("schema_validation")
    if terminal == "completed":
        error_if(schema not in {"passed", "failed"}, f"{where}.completed task must have passed or failed schema validation", errors)
    elif terminal in TERMINAL_STATUSES:
        error_if(schema != "not_run", f"{where}.non-completed task must have not_run schema validation", errors)


def validate(ledger: Any) -> tuple[dict[str, Any], list[str]]:
    errors: list[str] = []
    exact_fields(ledger, TOP_LEVEL_FIELDS, "ledger", errors)
    if not isinstance(ledger, dict):
        return {"valid": False, "coverage": "incomplete", "errors": errors}, errors
    error_if(ledger.get("schema_version") != VERSION, "ledger.schema_version is unsupported", errors)
    error_if(not isinstance(ledger.get("snapshot_hash"), str) or re.fullmatch(r"[0-9a-f]{64}", ledger["snapshot_hash"]) is None, "ledger.snapshot_hash must be lowercase 64-character hex", errors)
    selected = ledger.get("selected_roles")
    if not isinstance(selected, list) or not all(nonempty_string(role) for role in selected):
        errors.append("ledger.selected_roles must be an array of non-empty strings")
        selected = []
    elif len(set(selected)) != len(selected):
        errors.append("ledger.selected_roles must not contain duplicates")
    else:
        unknown = sorted(set(selected) - KNOWN_ROLES)
        if unknown:
            errors.append("ledger.selected_roles has unknown role(s): " + ", ".join(unknown))
        missing_core = sorted(CORE_ROLES - set(selected))
        if missing_core:
            errors.append("ledger.selected_roles is missing core role(s): " + ", ".join(missing_core))
    entries = ledger.get("entries")
    if not isinstance(entries, list):
        errors.append("ledger.entries must be an array")
        entries = []
    for index, entry in enumerate(entries):
        validate_entry(entry, index, errors)
    by_role: dict[str, list[dict[str, Any]]] = {}
    host_task_ids: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict) or not nonempty_string(entry.get("role")):
            continue
        by_role.setdefault(entry["role"], []).append(entry)
        task_id = entry.get("host_task_id")
        if nonempty_string(task_id):
            if task_id in host_task_ids:
                errors.append("ledger.host_task_id must be unique")
            host_task_ids.add(task_id)
    for role, attempts in by_role.items():
        values = sorted(item.get("attempt") for item in attempts if isinstance(item.get("attempt"), int) and not isinstance(item.get("attempt"), bool))
        if values != list(range(1, len(attempts) + 1)):
            errors.append(f"ledger attempts for {role} must start at 1 and be contiguous")
        for item in attempts:
            if item.get("attempt") != 1 and not nonempty_string(item.get("retry_or_escalation_reason")):
                errors.append(f"ledger attempt >1 for {role} requires retry_or_escalation_reason")
    recorded_roles = {entry.get("role") for entry in entries if isinstance(entry, dict) and nonempty_string(entry.get("role"))}
    unselected_roles = sorted(recorded_roles - set(selected))
    if unselected_roles:
        errors.append("ledger has entry for unselected role(s): " + ", ".join(unselected_roles))
    missing_roles = sorted(set(selected) - recorded_roles)
    if missing_roles:
        errors.append("ledger is missing selected role entries: " + ", ".join(missing_roles))
    coverage = "complete" if not errors and not missing_roles else "incomplete"
    return {"valid": not errors, "coverage": coverage, "missing_roles": missing_roles, "errors": errors}, errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", default="-")
    args = parser.parse_args()
    try:
        output, errors = validate(json.loads(Path(args.input).read_text(encoding="utf-8")))
        encoded = json.dumps(output, indent=2, sort_keys=True) + "\n"
        if args.output == "-":
            sys.stdout.write(encoded)
        else:
            Path(args.output).write_text(encoded, encoding="utf-8")
        return 0 if not errors else 1
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"validate_execution_ledger: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

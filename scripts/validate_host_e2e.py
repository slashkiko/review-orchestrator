#!/usr/bin/env python3
"""Validate a normalized, host-neutral review E2E run artifact."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any
import review_snapshot
import validate_execution_ledger
import route_selection


VERSION = 2
STATUS = {"passed", "failed", "blocked", "not_run", "unavailable"}


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def validate_fixture(value: Any) -> tuple[dict[str, Any] | None, list[str]]:
    expected = {"schema_version", "run_id", "snapshot_hash", "discovery"}
    if not isinstance(value, dict) or set(value) != expected or value.get("schema_version") != 2:
        return None, ["fixture has an unsupported schema"]
    if not isinstance(value.get("run_id"), str) or not value["run_id"] or not isinstance(value.get("snapshot_hash"), str) or len(value["snapshot_hash"]) != 64 or any(char not in "0123456789abcdef" for char in value["snapshot_hash"]):
        return None, ["fixture identity is invalid"]
    discovery = value.get("discovery")
    if not isinstance(discovery, dict) or set(discovery) != {"skill_md_sha256", "challenge_sha256"} or any(not isinstance(item, str) or len(item) != 64 or any(char not in "0123456789abcdef" for char in item) for item in discovery.values()):
        return None, ["fixture discovery contract is invalid"]
    return value, []


def validate_host(value: Any, host: str) -> tuple[dict[str, Any] | None, list[str]]:
    errors: list[str] = []
    expected = {"schema_version", "host", "run_id", "fixture_hash", "snapshot_hash", "status", "model", "effort", "observed_discovery"}
    if not isinstance(value, dict) or set(value) != expected:
        return None, ["host artifact has an unsupported schema"]
    if value["schema_version"] != 3 or value["host"] != host or value["status"] not in STATUS:
        errors.append("host artifact has invalid version, host, or status")
    if any(not isinstance(value[key], str) or not value[key] for key in ("run_id", "fixture_hash", "snapshot_hash")):
        errors.append("host artifact identity is invalid")
    expected_model = "gpt-5.6-luna" if host == "codex" else "haiku"
    if value.get("model") != expected_model or value.get("effort") != "low": errors.append("host artifact model policy is invalid")
    if value.get("status") == "passed" and (not isinstance(value.get("observed_discovery"), dict) or set(value["observed_discovery"]) != {"skill_md_sha256", "challenge_sha256"}):
        errors.append("passed host artifact lacks observed discovery evidence")
    return value, errors


def validate_routing(value: Any, snapshot: dict[str, Any]) -> bool:
    expected = {"schema_version", "snapshot_hash", "classifier_status", "classifier_selected", "selected", "not_evaluated", "strong_routes", "weak_routes"}
    if not isinstance(value, dict) or set(value) != expected or value.get("schema_version") != 1 or value.get("snapshot_hash") != snapshot["snapshot_hash"]:
        return False
    known = set(snapshot.get("route_candidates", {})) | route_selection.CORE_ROLES
    if not all(isinstance(value.get(key), list) and len(value[key]) == len(set(value[key])) and set(value[key]) <= known for key in ("selected", "strong_routes", "weak_routes")) or not isinstance(value.get("not_evaluated"), dict):
        return False
    if value.get("classifier_status") == "completed" and isinstance(value.get("classifier_selected"), list) and set(value["classifier_selected"]) <= known:
        expected_output = route_selection.select_routes(snapshot["route_candidates"], set(value["classifier_selected"]))
    elif value.get("classifier_status") == "failed" and value.get("classifier_selected") is None:
        expected_output = route_selection.select_routes(snapshot["route_candidates"], None)
    else:
        return False
    return all(value[key] == expected_output[key] for key in ("selected", "not_evaluated", "strong_routes", "weak_routes"))


def validate_gates(value: Any, snapshot: dict[str, Any]) -> bool:
    expected = {"schema_version", "snapshot_hash", "results"}
    inventory_items = [item for item in snapshot.get("configured_gates", []) if isinstance(item, dict)]
    inventory = {item.get("gate_id"): item for item in inventory_items}
    fields = {"gate_id", "gate", "config", "scope", "argv", "outcome", "attribution", "reason", "exit_code", "duration_seconds"}
    if not isinstance(value, dict) or set(value) != expected or value.get("schema_version") != 1 or value.get("snapshot_hash") != snapshot["snapshot_hash"] or not isinstance(value.get("results"), list):
        return False
    if len(inventory) != len(inventory_items) or any(not isinstance(gate_id, str) for gate_id in inventory):
        return False
    seen: set[str] = set()
    for item in value["results"]:
        if not isinstance(item, dict) or set(item) != fields or item.get("gate_id") in seen or item.get("gate_id") not in inventory:
            return False
        target = inventory[item["gate_id"]]
        if item.get("gate") != target.get("gate") or item.get("config") != target.get("config") or item.get("argv") != target.get("command_argv") or item.get("scope") != "target-bound" or item.get("outcome") not in {"passed", "failed", "blocked", "not_run"} or item.get("attribution") not in {"diff", "preexisting", "environment", "unknown"} or not isinstance(item.get("reason"), str) or not isinstance(item.get("duration_seconds"), (int, float)) or item.get("exit_code") is not None and not isinstance(item.get("exit_code"), int):
            return False
        seen.add(item["gate_id"])
    return True


def validate_qualification(value: Any, snapshot: dict[str, Any]) -> bool:
    expected = {"schema_version", "snapshot_hash", "status", "valid", "approved_gaps"}
    if not isinstance(value, dict) or set(value) != expected or value.get("schema_version") != 1 or value.get("snapshot_hash") != snapshot["snapshot_hash"] or value.get("valid") is not True or not isinstance(value.get("approved_gaps"), list):
        return False
    complete = snapshot.get("scope_status") == "complete"
    if complete:
        return value.get("status") == "complete" and not value["approved_gaps"]
    expected_gaps = {(item.get("path"), item.get("kind"), item.get("fingerprint")) for item in snapshot.get("scope_gaps", []) if isinstance(item, dict)}
    actual_gaps = {(item.get("path"), item.get("kind"), item.get("fingerprint")) for item in value["approved_gaps"] if isinstance(item, dict)}
    return value.get("status") == "qualified" and len(actual_gaps) == len(value["approved_gaps"]) and actual_gaps == expected_gaps


def validate_pair(codex: Any, claude: Any, fixture: Any, snapshot: Any, component_paths: list[str | None]) -> tuple[dict[str, Any], list[str]]:
    errors: list[str] = []
    codex_value, codex_errors = validate_host(codex, "codex")
    claude_value, claude_errors = validate_host(claude, "claude-code")
    fixture_value, fixture_errors = validate_fixture(fixture)
    errors += codex_errors + claude_errors + fixture_errors
    if not isinstance(snapshot, dict) or snapshot.get("schema_version") != review_snapshot.VERSION or snapshot.get("snapshot_hash") != review_snapshot.canonical_hash(review_snapshot.snapshot_identity(snapshot)):
        errors.append("snapshot is not a canonical v4 artifact")
        snapshot_hash = None
    else:
        snapshot_hash = snapshot["snapshot_hash"]
    if codex_value and claude_value and fixture_value:
        if codex_value["run_id"] != claude_value["run_id"] or codex_value["fixture_hash"] != claude_value["fixture_hash"]:
            errors.append("hosts must share run_id and fixture_hash")
        if snapshot_hash and (codex_value["snapshot_hash"] != snapshot_hash or claude_value["snapshot_hash"] != snapshot_hash):
            errors.append("hosts must bind the canonical snapshot hash")
        if codex_value["run_id"] != fixture_value["run_id"] or codex_value["fixture_hash"] != digest(fixture_value) or codex_value["snapshot_hash"] != fixture_value["snapshot_hash"]:
            errors.append("Codex result does not bind supplied fixture")
        if claude_value["run_id"] != fixture_value["run_id"] or claude_value["fixture_hash"] != digest(fixture_value) or claude_value["snapshot_hash"] != fixture_value["snapshot_hash"]:
            errors.append("Claude result does not bind supplied fixture")
        if codex_value.get("status") == "passed" and codex_value.get("observed_discovery") != fixture_value["discovery"]:
            errors.append("Codex discovery evidence does not match supplied fixture")
        if claude_value.get("status") == "passed" and claude_value.get("observed_discovery") != fixture_value["discovery"]:
            errors.append("Claude discovery evidence does not match supplied fixture")
    component_complete = all(component_paths)
    gate_ready = False
    if component_complete:
        try:
            routing, ledger, gates, qualification = [json.loads(Path(path).read_text(encoding="utf-8")) for path in component_paths]
            if not validate_routing(routing, snapshot):
                errors.append("routing artifact schema is invalid")
            _, ledger_errors = validate_execution_ledger.validate(ledger)
            if ledger_errors or ledger.get("snapshot_hash") != snapshot_hash:
                errors.append("ledger artifact is invalid or target-mismatched")
            if not validate_gates(gates, snapshot):
                errors.append("gate artifact is invalid or target-mismatched")
            else:
                executable_ids = {item["gate_id"] for item in snapshot.get("configured_gates", []) if isinstance(item, dict) and isinstance(item.get("command_argv"), list)}
                gate_ready = executable_ids == {item["gate_id"] for item in gates["results"]} and all(item["outcome"] == "passed" for item in gates["results"])
            if not validate_qualification(qualification, snapshot):
                errors.append("qualification artifact is invalid or target-mismatched")
        except (OSError, ValueError, json.JSONDecodeError):
            errors.append("component artifact cannot be read")
    statuses = [value.get("status") for value in (codex_value, claude_value) if value]
    passed = not errors and component_complete and gate_ready and statuses == ["passed", "passed"]
    if "passed" in statuses and not component_complete:
        errors.append("a host cannot claim passed E2E without all component artifacts")
        passed = False
    return {"valid": not errors, "passed": passed, "snapshot_hash": snapshot_hash, "errors": errors}, errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--codex", required=True)
    parser.add_argument("--claude-code", required=True)
    parser.add_argument("--fixture", required=True)
    parser.add_argument("--snapshot", required=True)
    parser.add_argument("--routing")
    parser.add_argument("--ledger")
    parser.add_argument("--gates")
    parser.add_argument("--qualification")
    parser.add_argument("--output", default="-")
    args = parser.parse_args()
    try:
        output, errors = validate_pair(
            json.loads(Path(args.codex).read_text(encoding="utf-8")), json.loads(Path(args.claude_code).read_text(encoding="utf-8")), json.loads(Path(args.fixture).read_text(encoding="utf-8")),
            json.loads(Path(args.snapshot).read_text(encoding="utf-8")), [args.routing, args.ledger, args.gates, args.qualification],
        )
        encoded = json.dumps(output, indent=2, sort_keys=True) + "\n"
        if args.output == "-":
            sys.stdout.write(encoded)
        else:
            Path(args.output).write_text(encoded, encoding="utf-8")
        return 0 if output["passed"] else 1
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"validate_host_e2e: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

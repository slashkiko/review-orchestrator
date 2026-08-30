#!/usr/bin/env python3
"""Validate an explicit user approval that qualifies every snapshot scope gap."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

import review_snapshot


VERSION = 1
HEX = re.compile(r"[0-9a-f]{64}")
SENSITIVE = re.compile(r"(?:/Users/|/home/|[A-Za-z]:\\\\Users\\\\|@)")


def invalid(snapshot_hash: str | None, error: str) -> dict[str, Any]:
    return {"schema_version": VERSION, "snapshot_hash": snapshot_hash, "status": "blocked", "valid": False, "errors": [error]}


def validate_snapshot(snapshot: Any) -> dict[str, Any]:
    if not isinstance(snapshot, dict) or snapshot.get("schema_version") != review_snapshot.VERSION:
        raise ValueError("snapshot schema is unsupported")
    snapshot_hash = snapshot.get("snapshot_hash")
    if not isinstance(snapshot_hash, str) or not HEX.fullmatch(snapshot_hash):
        raise ValueError("snapshot_hash is invalid")
    if snapshot_hash != review_snapshot.canonical_hash(review_snapshot.snapshot_identity(snapshot)):
        raise ValueError("snapshot document is stale or altered")
    target, root = snapshot.get("target"), snapshot.get("repository_root")
    if not isinstance(root, str) or not Path(root).is_absolute() or not isinstance(target, dict) or target.get("mode") not in {"working", "staged", "range"}:
        raise ValueError("snapshot repository_root or target is invalid")
    binding = snapshot.get("repository_binding")
    if binding is not None and (not isinstance(binding, str) or not HEX.fullmatch(binding)):
        raise ValueError("snapshot repository_binding is invalid")
    if snapshot.get("scope_status") not in {"complete", "blocked"} or not isinstance(snapshot.get("scope_gaps"), list):
        raise ValueError("snapshot scope is invalid")
    gaps = snapshot["scope_gaps"]
    if (snapshot["scope_status"] == "complete") != (not gaps):
        raise ValueError("snapshot complete status must exactly match an empty gap list")
    seen: set[tuple[str, str, str | None]] = set()
    for item in gaps:
        expected = {"path", "kind", "reason"} | ({"fingerprint"} if isinstance(item, dict) and "fingerprint" in item else set())
        if not isinstance(item, dict) or set(item) != expected or not isinstance(item.get("reason"), str) or not item["reason"].strip():
            raise ValueError("snapshot scope gap has an unsupported schema")
        path, kind, fingerprint = item.get("path"), item.get("kind"), item.get("fingerprint")
        if not isinstance(path, str) or not path or path.startswith("/") or ".." in Path(path).parts or not isinstance(kind, str) or not kind:
            raise ValueError("snapshot scope gap path or kind is invalid")
        if fingerprint is not None and (not isinstance(fingerprint, str) or not re.fullmatch(r"[0-9a-f]{12,64}", fingerprint)):
            raise ValueError("snapshot scope gap fingerprint is invalid")
        key = (path, kind, fingerprint)
        if key in seen:
            raise ValueError("snapshot scope gaps contain duplicates")
        seen.add(key)
    return snapshot


def verify_live(snapshot: dict[str, Any]) -> None:
    target = snapshot["target"]
    mode = target["mode"]
    if mode == "range":
        current = review_snapshot.build_snapshot(snapshot["repository_root"], mode, target.get("source_base", target["base"]), target["head"], bool(target.get("merge_base")))
    else:
        current = review_snapshot.build_snapshot(snapshot["repository_root"], mode, target["base"], None, False)
    if current["snapshot_hash"] != snapshot["snapshot_hash"]:
        raise ValueError("live target no longer matches captured snapshot")


def gap_key(item: dict[str, Any]) -> tuple[str, str, str | None]:
    fingerprint = item.get("fingerprint")
    return (item["path"], item["kind"], fingerprint if isinstance(fingerprint, str) else None)


def qualify(snapshot: dict[str, Any], approval: Any) -> dict[str, Any]:
    snapshot_hash = snapshot["snapshot_hash"]
    if snapshot["scope_status"] == "complete":
        if approval not in (None, {"schema_version": VERSION, "snapshot_hash": snapshot_hash, "approved_gaps": [], "reason": "complete_snapshot", "approval_ref": "not_required"}):
            return invalid(snapshot_hash, "a complete snapshot cannot be scope-qualified")
        return {"schema_version": VERSION, "snapshot_hash": snapshot_hash, "status": "complete", "valid": True, "approved_gaps": []}
    expected = {"schema_version", "snapshot_hash", "approved_gaps", "reason", "approval_ref"}
    if not isinstance(approval, dict) or set(approval) != expected:
        return invalid(snapshot_hash, "qualification approval has an unsupported schema")
    if approval["schema_version"] != VERSION or approval["snapshot_hash"] != snapshot_hash:
        return invalid(snapshot_hash, "qualification approval is stale")
    if not isinstance(approval["reason"], str) or not approval["reason"].strip() or SENSITIVE.search(approval["reason"]):
        return invalid(snapshot_hash, "qualification reason must be non-empty and generalized")
    if not isinstance(approval["approval_ref"], str) or not approval["approval_ref"].strip() or SENSITIVE.search(approval["approval_ref"]):
        return invalid(snapshot_hash, "qualification approval_ref is invalid")
    if not isinstance(approval["approved_gaps"], list):
        return invalid(snapshot_hash, "approved_gaps must be an array")
    actual = {gap_key(item) for item in snapshot["scope_gaps"] if isinstance(item, dict) and isinstance(item.get("path"), str) and isinstance(item.get("kind"), str)}
    approved: set[tuple[str, str, str | None]] = set()
    for item in approval["approved_gaps"]:
        if not isinstance(item, dict) or set(item) - {"path", "kind", "fingerprint"} or {"path", "kind"} - set(item):
            return invalid(snapshot_hash, "approved gap has an unsupported schema")
        path, kind = item["path"], item["kind"]
        fingerprint = item.get("fingerprint")
        if not isinstance(path, str) or not path or path.startswith("/") or ".." in Path(path).parts or not isinstance(kind, str):
            return invalid(snapshot_hash, "approved gap has an unsafe path or kind")
        if fingerprint is not None and (not isinstance(fingerprint, str) or not re.fullmatch(r"[0-9a-f]{12,64}", fingerprint)):
            return invalid(snapshot_hash, "approved gap fingerprint is invalid")
        key = (path, kind, fingerprint)
        if key in approved:
            return invalid(snapshot_hash, "approved gaps contain duplicates")
        approved.add(key)
    if approved != actual:
        return invalid(snapshot_hash, "approved gaps do not exactly match current snapshot scope gaps")
    # Do not copy free-form approval strings into the artifact: this output may be shared.
    return {
        "schema_version": VERSION, "snapshot_hash": snapshot_hash, "status": "qualified", "valid": True,
        "approved_gaps": [
            {key: value for key, value in (("path", path), ("kind", kind), ("fingerprint", fp)) if value is not None}
            for path, kind, fp in sorted(approved)
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", required=True)
    parser.add_argument("--approval", help="actual user approval JSON; never synthesize this artifact")
    parser.add_argument("--output", default="-")
    args = parser.parse_args()
    try:
        snapshot = validate_snapshot(json.loads(Path(args.snapshot).read_text(encoding="utf-8")))
        verify_live(snapshot)
        approval = json.loads(Path(args.approval).read_text(encoding="utf-8")) if args.approval else None
        output = qualify(snapshot, approval)
        encoded = json.dumps(output, indent=2, sort_keys=True) + "\n"
        if args.output == "-":
            sys.stdout.write(encoded)
        else:
            Path(args.output).write_text(encoded, encoding="utf-8")
        return 0 if output["valid"] else 1
    except (OSError, ValueError, KeyError, TypeError, AttributeError, json.JSONDecodeError, review_snapshot.SnapshotError) as exc:
        print(f"qualify_scope: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

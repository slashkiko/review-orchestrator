#!/usr/bin/env python3
"""Validate reviewer JSON against an immutable snapshot without leaking raw candidates."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path, PurePosixPath
from typing import Any, Iterable


REVIEWERS = {
    "semantic-core", "simplify", "test-effectiveness", "language-idiom",
    "security", "reliability", "data-integrity", "compatibility", "rollout",
    "observability", "contract-design", "performance", "dependency",
    "accessibility", "docs-dx", "sensitive-data",
}
SEVERITIES = {"critical", "high", "medium", "low"}
CONFIDENCES = {"high", "medium", "low"}
STATUSES = {"completed", "partial", "failed"}
METHODS = {"static", "command", "external-primary-source"}
COMMAND_RESULTS = {"passed", "failed", "not_run"}
LOCATION_SIDES = {"old", "new", "none"}
EVIDENCE_SIDES = {"old", "new"}
NON_LINE_KINDS = {"addition", "deletion", "rename", "copy", "mode", "binary"}

FINDING_FIELDS = {
    "id", "reviewer", "snapshot_hash", "title", "claim", "impact", "severity",
    "confidence", "introduced_by_diff", "location", "evidence", "validation",
}
LOCATION_FIELDS = {"path", "side", "start_line", "end_line", "change_kind"}
EVIDENCE_FIELDS = {"path", "side", "line", "reason"}
UNVERIFIABLE_FIELDS = {"id", "claim", "missing_evidence", "why_it_matters", "retrieval"}
COVERAGE_FIELDS = {"examined", "not_examined", "commands"}
NOT_EXAMINED_FIELDS = {"area", "reason"}
COMMAND_FIELDS = {"command", "scope", "result", "summary"}
SENSITIVE_CANDIDATE_FIELDS = {"candidate_id", "type", "fingerprint"}
RESULT_FIELDS = {"reviewer", "snapshot_hash", "status", "summary", "findings", "unverifiable", "coverage"}

CANDIDATE_PATTERNS = {
    "email": re.compile(r"(?<![\w.+-])[\w.+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}(?![\w.-])"),
    "macos-local-path": re.compile(r"/Users/[^/\s'\"`]+(?:/[^\s'\"`]+)+"),
    "linux-local-path": re.compile(r"/home/[^/\s'\"`]+(?:/[^\s'\"`]+)+"),
    "windows-local-path": re.compile(r"[A-Za-z]:\\Users\\[^\\\s'\"`]+(?:\\[^\s'\"`]+)+"),
    "credential-assignment": re.compile(
        r"(?i)\b(?:api[_-]?key|access[_-]?token|auth[_-]?token|secret|password)\b\s*[:=]\s*['\"]?[^\s,'\"}]{8,}"
    ),
    "bearer-token": re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{12,}"),
    "private-key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "internal-host": re.compile(r"(?i)\b(?:https?://)?[A-Za-z0-9.-]+\.(?:internal|corp|local)(?::\d+)?(?:/[^\s'\"`]*)?"),
    "repository-reference": re.compile(r"(?:git@github\.com:|https://github\.com/)[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:\.git)?"),
}


def safe_relative_path(value: Any) -> bool:
    if not isinstance(value, str) or not value or "\\" in value or re.match(r"^[A-Za-z]:", value):
        return False
    path = PurePosixPath(value)
    return not path.is_absolute() and ".." not in path.parts


def require_string(container: dict[str, Any], key: str, where: str, errors: list[str]) -> None:
    if not isinstance(container.get(key), str) or not container[key].strip():
        errors.append(f"{where}.{key} must be a non-empty string")


def exact_fields(container: dict[str, Any], expected: set[str], where: str, errors: list[str]) -> None:
    missing = sorted(expected - container.keys())
    unexpected = sorted(container.keys() - expected)
    if missing:
        errors.append(f"{where} missing fields: {', '.join(missing)}")
    if unexpected:
        errors.append(f"{where} has {len(unexpected)} unexpected field(s)")


def iter_strings(value: Any, path: str = "result") -> Iterable[tuple[str, str]]:
    if isinstance(value, str):
        yield path, value
    elif isinstance(value, dict):
        for key, nested in value.items():
            yield from iter_strings(nested, f"{path}.{key}")
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            yield from iter_strings(nested, f"{path}[{index}]")


def git_blob(root: Path, spec: str) -> bytes | None:
    completed = subprocess.run(
        ["git", "-C", str(root), "show", spec],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    return completed.stdout if completed.returncode == 0 else None


def immutable_candidate_blob(snapshot: dict[str, Any], path: str) -> bytes | None:
    root = Path(snapshot.get("repository_root", ""))
    target = snapshot.get("target", {})
    if not root.is_dir() or not isinstance(target, dict):
        return None
    mode = target.get("mode")
    if mode == "range" and isinstance(target.get("head"), str):
        return git_blob(root, f"{target['head']}:{path}")
    if mode == "staged":
        return git_blob(root, f":{path}")
    if mode == "working":
        absolute = root / path
        try:
            if absolute.is_symlink():
                return os.readlink(absolute).encode("utf-8", "surrogateescape")
            return absolute.read_bytes() if absolute.is_file() else None
        except OSError:
            return None
    return None


def candidate_raw_values(snapshot: dict[str, Any]) -> tuple[set[str], list[str]]:
    values: set[str] = set()
    errors: list[str] = []
    for candidate in snapshot.get("sensitive_candidates", []):
        if not isinstance(candidate, dict):
            errors.append("a sensitive candidate could not be resolved from the immutable target")
            continue
        path = candidate.get("path")
        line_number = candidate.get("line")
        candidate_type = candidate.get("type")
        fingerprint = candidate.get("fingerprint")
        record = find_record(snapshot, path, "new") if isinstance(path, str) else None
        expected_hash = record.get("new", {}).get("content_sha256") if isinstance(record, dict) else None
        blob = immutable_candidate_blob(snapshot, path) if isinstance(path, str) else None
        if (
            blob is None
            or not isinstance(expected_hash, str)
            or hashlib.sha256(blob).hexdigest() != expected_hash
            or not valid_positive_line(line_number)
            or not isinstance(candidate_type, str)
            or not isinstance(fingerprint, str)
        ):
            errors.append("a sensitive candidate could not be resolved from the immutable target")
            continue
        lines = blob.decode("utf-8", "replace").splitlines()
        if line_number > len(lines) or candidate_type not in CANDIDATE_PATTERNS:
            errors.append("a sensitive candidate could not be resolved from the immutable target")
            continue
        matches = {
            match.group(0)
            for match in CANDIDATE_PATTERNS[candidate_type].finditer(lines[line_number - 1])
            if hashlib.sha256(match.group(0).encode("utf-8")).hexdigest()[:12] == fingerprint
        }
        if len(matches) != 1:
            errors.append("a sensitive candidate could not be resolved from the immutable target")
            continue
        raw = next(iter(matches))
        values.add(raw)
        if candidate_type == "credential-assignment":
            bare = re.split(r"[:=]", raw, maxsplit=1)[-1].strip().strip("'\"")
            if bare:
                values.add(bare)
        elif candidate_type == "bearer-token":
            bare = re.sub(r"(?i)^Bearer\s+", "", raw)
            if bare:
                values.add(bare)
    return values, errors


def candidate_sensitive_paths(snapshot: dict[str, Any], result: Any) -> tuple[list[str], list[str]]:
    raw_values, errors = candidate_raw_values(snapshot)
    paths = {
        path
        for path, value in iter_strings(result)
        if any(raw and raw in value for raw in raw_values)
    }
    return sorted(paths), errors


def snapshot_identity_hash(snapshot: dict[str, Any]) -> str | None:
    try:
        identity = {
            "schema_version": snapshot["schema_version"],
            "target": snapshot["target"],
            "diff_sha256": snapshot["diff_sha256"],
            "files": snapshot["files"],
            "languages": snapshot["languages"],
            "route_candidates": snapshot["route_candidates"],
            "sensitive_candidates": snapshot["sensitive_candidates"],
            "configured_gates": snapshot["configured_gates"],
        }
    except KeyError:
        return None
    encoded = json.dumps(identity, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def find_record(snapshot: dict[str, Any], path: str, side: str) -> dict[str, Any] | None:
    for record in snapshot.get("files", []):
        if not isinstance(record, dict):
            continue
        if side == "new" and record.get("path") == path:
            return record
        old_path = record.get("old_path", record.get("path"))
        if side == "old" and old_path == path:
            return record
        if side == "none" and path in {record.get("path"), old_path}:
            return record
    return None


def immutable_commit_for(snapshot: dict[str, Any], side: str) -> str | None:
    target = snapshot.get("target", {})
    if side == "old":
        return target.get("base")
    if target.get("mode") == "range":
        return target.get("head")
    return target.get("base")


def git_blob_metadata(root: Path, commit: str, path: str) -> dict[str, Any] | None:
    completed = subprocess.run(
        ["git", "-C", str(root), "show", f"{commit}:{path}"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode != 0:
        return None
    binary = b"\0" in completed.stdout[:8192]
    return {
        "exists": True,
        "binary": binary,
        "line_count": None if binary else len(completed.stdout.splitlines()),
    }


def immutable_side_metadata(snapshot: dict[str, Any], path: str, side: str) -> dict[str, Any] | None:
    record = find_record(snapshot, path, side)
    if record is not None:
        metadata = record.get(side)
        return metadata if isinstance(metadata, dict) else None
    commit = immutable_commit_for(snapshot, side)
    root = Path(snapshot.get("repository_root", ""))
    if not isinstance(commit, str) or not root.is_dir():
        return None
    return git_blob_metadata(root, commit, path)


def valid_positive_line(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 1


def overlaps(ranges: list[list[int]], start: int, end: int) -> bool:
    return any(start <= range_end and end >= range_start for range_start, range_end in ranges)


def validate_location(location: Any, snapshot: dict[str, Any], where: str, errors: list[str]) -> None:
    if not isinstance(location, dict):
        errors.append(f"{where} must be an object")
        return
    exact_fields(location, LOCATION_FIELDS, where, errors)
    path = location.get("path")
    side = location.get("side")
    if not safe_relative_path(path):
        errors.append(f"{where}.path must be repository-relative")
    if side not in LOCATION_SIDES:
        errors.append(f"{where}.side is invalid")
        return
    record = find_record(snapshot, path, side)
    if record is None:
        errors.append(f"{where}.path/side is not in the snapshot")
        return

    start = location.get("start_line")
    end = location.get("end_line")
    change_kind = location.get("change_kind")
    if side == "none":
        if start is not None or end is not None:
            errors.append(f"{where} non-line location must use null line bounds")
        if change_kind not in NON_LINE_KINDS or change_kind not in record.get("non_line_changes", []):
            errors.append(f"{where}.change_kind is not recorded for this change")
        return

    if change_kind is not None:
        errors.append(f"{where}.change_kind must be null for a line location")
    if not valid_positive_line(start):
        errors.append(f"{where}.start_line must be a positive integer")
    if not valid_positive_line(end) or (valid_positive_line(start) and end < start):
        errors.append(f"{where}.end_line must be >= start_line")
    if not valid_positive_line(start) or not valid_positive_line(end):
        return
    ranges = record.get("changed_ranges", {}).get(side, [])
    if not ranges or not overlaps(ranges, start, end):
        errors.append(f"{where} does not overlap a changed {side}-side range")
    metadata = record.get(side, {})
    line_count = metadata.get("line_count") if isinstance(metadata, dict) else None
    if metadata.get("binary") if isinstance(metadata, dict) else False:
        errors.append(f"{where} cannot cite a binary side by line")
    elif not isinstance(line_count, int) or end > line_count:
        errors.append(f"{where} exceeds the immutable {side}-side line count")


def validate_evidence(evidence: Any, snapshot: dict[str, Any], where: str, errors: list[str]) -> None:
    if not isinstance(evidence, list) or not evidence:
        errors.append(f"{where} must be a non-empty array")
        return
    for index, item in enumerate(evidence):
        item_where = f"{where}[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{item_where} must be an object")
            continue
        exact_fields(item, EVIDENCE_FIELDS, item_where, errors)
        path = item.get("path")
        side = item.get("side")
        line = item.get("line")
        if not safe_relative_path(path):
            errors.append(f"{item_where}.path must be repository-relative")
        if side not in EVIDENCE_SIDES:
            errors.append(f"{item_where}.side is invalid")
        if not valid_positive_line(line):
            errors.append(f"{item_where}.line must be a positive integer")
        require_string(item, "reason", item_where, errors)
        if not safe_relative_path(path) or side not in EVIDENCE_SIDES or not valid_positive_line(line):
            continue
        metadata = immutable_side_metadata(snapshot, path, side)
        if metadata is None or not metadata.get("exists"):
            errors.append(f"{item_where}.path does not exist in the immutable {side}-side target")
        elif metadata.get("binary"):
            errors.append(f"{item_where} cannot cite binary evidence by line")
        elif not isinstance(metadata.get("line_count"), int) or line > metadata["line_count"]:
            errors.append(f"{item_where}.line exceeds the immutable {side}-side line count")


def validate_sensitive_candidate(
    finding: dict[str, Any], snapshot: dict[str, Any], where: str, errors: list[str]
) -> None:
    metadata = finding.get("sensitive_candidate")
    if finding.get("reviewer") != "sensitive-data":
        if metadata is not None:
            errors.append(f"{where}.sensitive_candidate is allowed only for sensitive-data")
        return
    if not isinstance(metadata, dict):
        errors.append(f"{where}.sensitive_candidate is required for sensitive-data")
        return
    exact_fields(metadata, SENSITIVE_CANDIDATE_FIELDS, f"{where}.sensitive_candidate", errors)
    candidate = next(
        (item for item in snapshot.get("sensitive_candidates", []) if item.get("candidate_id") == metadata.get("candidate_id")),
        None,
    )
    if candidate is None:
        errors.append(f"{where}.sensitive_candidate is not in the snapshot")
        return
    if metadata.get("type") != candidate.get("type") or metadata.get("fingerprint") != candidate.get("fingerprint"):
        errors.append(f"{where}.sensitive_candidate metadata does not match the snapshot")
    location = finding.get("location", {})
    candidate_line = candidate.get("line")
    if (
        location.get("path") != candidate.get("path")
        or location.get("side") != "new"
        or not valid_positive_line(location.get("start_line"))
        or not valid_positive_line(location.get("end_line"))
        or not valid_positive_line(candidate_line)
        or not location["start_line"] <= candidate_line <= location["end_line"]
    ):
        errors.append(f"{where}.location must be a new-side line covering the sensitive candidate")


def validate_finding(finding: Any, index: int, snapshot: dict[str, Any], result_reviewer: str, errors: list[str]) -> None:
    where = f"findings[{index}]"
    if not isinstance(finding, dict):
        errors.append(f"{where} must be an object")
        return
    expected = FINDING_FIELDS | ({"sensitive_candidate"} if result_reviewer == "sensitive-data" else set())
    exact_fields(finding, expected, where, errors)
    for key in ("id", "title", "claim", "impact"):
        require_string(finding, key, where, errors)
    if finding.get("reviewer") != result_reviewer:
        errors.append(f"{where}.reviewer does not match result reviewer")
    if finding.get("snapshot_hash") != snapshot.get("snapshot_hash"):
        errors.append(f"{where}.snapshot_hash does not match snapshot")
    if finding.get("severity") not in SEVERITIES:
        errors.append(f"{where}.severity is invalid")
    if finding.get("confidence") not in CONFIDENCES:
        errors.append(f"{where}.confidence is invalid")
    if finding.get("introduced_by_diff") is not True:
        errors.append(f"{where}.introduced_by_diff must be true")
    validate_location(finding.get("location"), snapshot, f"{where}.location", errors)
    validate_evidence(finding.get("evidence"), snapshot, f"{where}.evidence", errors)
    validation = finding.get("validation")
    if not isinstance(validation, dict):
        errors.append(f"{where}.validation must be an object")
    else:
        exact_fields(validation, {"method", "details"}, f"{where}.validation", errors)
        if validation.get("method") not in METHODS:
            errors.append(f"{where}.validation.method is invalid")
        require_string(validation, "details", f"{where}.validation", errors)
    validate_sensitive_candidate(finding, snapshot, where, errors)


def validate_unverifiable(value: Any, errors: list[str]) -> list[Any]:
    if not isinstance(value, list):
        errors.append("unverifiable must be an array")
        return []
    for index, item in enumerate(value):
        where = f"unverifiable[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{where} must be an object")
            continue
        exact_fields(item, UNVERIFIABLE_FIELDS, where, errors)
        for key in UNVERIFIABLE_FIELDS:
            require_string(item, key, where, errors)
    return value


def validate_coverage(value: Any, errors: list[str]) -> dict[str, Any]:
    if not isinstance(value, dict):
        errors.append("coverage must be an object")
        return {"examined": [], "not_examined": [], "commands": []}
    exact_fields(value, COVERAGE_FIELDS, "coverage", errors)
    examined = value.get("examined")
    if not isinstance(examined, list):
        errors.append("coverage.examined must be an array")
        examined = []
    else:
        for index, item in enumerate(examined):
            if not isinstance(item, str) or not item.strip():
                errors.append(f"coverage.examined[{index}] must be a non-empty string")
    not_examined = value.get("not_examined")
    if not isinstance(not_examined, list):
        errors.append("coverage.not_examined must be an array")
        not_examined = []
    else:
        for index, item in enumerate(not_examined):
            where = f"coverage.not_examined[{index}]"
            if not isinstance(item, dict):
                errors.append(f"{where} must be an object")
                continue
            exact_fields(item, NOT_EXAMINED_FIELDS, where, errors)
            require_string(item, "area", where, errors)
            require_string(item, "reason", where, errors)
    commands = value.get("commands")
    if not isinstance(commands, list):
        errors.append("coverage.commands must be an array")
    else:
        for index, item in enumerate(commands):
            where = f"coverage.commands[{index}]"
            if not isinstance(item, dict):
                errors.append(f"{where} must be an object")
                continue
            exact_fields(item, COMMAND_FIELDS, where, errors)
            for key in ("command", "scope", "summary"):
                require_string(item, key, where, errors)
            if item.get("result") not in COMMAND_RESULTS:
                errors.append(f"{where}.result is invalid")
    return {"examined": examined, "not_examined": not_examined, "commands": commands if isinstance(commands, list) else []}


def validate_status_consistency(
    status: Any, findings: list[Any], unverifiable: list[Any], coverage: dict[str, Any], errors: list[str]
) -> None:
    examined = coverage["examined"]
    not_examined = coverage["not_examined"]
    if status == "completed":
        if not examined:
            errors.append("completed status requires non-empty coverage.examined")
        if not_examined or unverifiable:
            errors.append("completed status cannot contain unevaluated coverage")
    elif status == "partial":
        if not examined or not not_examined:
            errors.append("partial status requires both examined and not_examined coverage")
    elif status == "failed":
        if findings or unverifiable or examined or not not_examined:
            errors.append("failed status requires no findings/unverifiable/examined and non-empty not_examined")


def canonical_finding(finding: dict[str, Any]) -> str:
    comparable = {key: value for key, value in finding.items() if key != "id"}
    return json.dumps(comparable, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def validate(snapshot: dict[str, Any], result: Any) -> tuple[dict[str, Any], list[str]]:
    errors: list[str] = []
    if snapshot.get("schema_version") != 2:
        errors.append("snapshot schema version is unsupported")
    calculated_snapshot_hash = snapshot_identity_hash(snapshot)
    if calculated_snapshot_hash is None or calculated_snapshot_hash != snapshot.get("snapshot_hash"):
        errors.append("snapshot canonical identity is invalid")
    if not isinstance(result, dict):
        errors.append("result must be an object")
        return {"valid": False, "errors": errors, "duplicate_count": 0}, errors

    leak_paths, candidate_errors = candidate_sensitive_paths(snapshot, result)
    errors.extend(candidate_errors)
    if leak_paths:
        errors.extend(f"{path} contains a raw sensitive value; use redacted candidate metadata" for path in leak_paths)
    exact_fields(result, RESULT_FIELDS, "result", errors)

    reviewer = result.get("reviewer")
    if reviewer not in REVIEWERS:
        errors.append("reviewer is invalid")
    if result.get("snapshot_hash") != snapshot.get("snapshot_hash"):
        errors.append("result snapshot_hash does not match snapshot")
    status = result.get("status")
    if status not in STATUSES:
        errors.append("status is invalid")
    require_string(result, "summary", "result", errors)

    findings = result.get("findings")
    if not isinstance(findings, list):
        errors.append("findings must be an array")
        findings = []
    for index, finding in enumerate(findings):
        validate_finding(finding, index, snapshot, reviewer, errors)
    unverifiable = validate_unverifiable(result.get("unverifiable"), errors)
    coverage = validate_coverage(result.get("coverage"), errors)
    validate_status_consistency(status, findings, unverifiable, coverage, errors)

    unique: list[dict[str, Any]] = []
    duplicate_ids: list[str] = []
    seen: set[str] = set()
    for finding in findings:
        if not isinstance(finding, dict):
            continue
        canonical = canonical_finding(finding)
        if canonical in seen:
            duplicate_ids.append(str(finding.get("id", "<missing>")))
            continue
        seen.add(canonical)
        unique.append(finding)

    if errors:
        return {"valid": False, "errors": errors, "duplicate_count": len(duplicate_ids)}, errors
    output = {
        "valid": True,
        "errors": [],
        "duplicate_count": len(duplicate_ids),
        "duplicate_ids": duplicate_ids,
        "result": {**result, "findings": unique},
    }
    return output, []


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", required=True)
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", default="-")
    args = parser.parse_args()
    try:
        snapshot = json.loads(Path(args.snapshot).read_text(encoding="utf-8"))
        result = json.loads(Path(args.input).read_text(encoding="utf-8"))
        output, errors = validate(snapshot, result)
        encoded = json.dumps(output, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
        if args.output == "-":
            sys.stdout.write(encoded)
        else:
            Path(args.output).write_text(encoded, encoding="utf-8")
        return 0 if not errors else 1
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"validate_findings: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

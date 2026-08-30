#!/usr/bin/env python3
"""Run explicitly approved, target-bound mechanical gates once without a shell."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import review_snapshot


VERSION = 1
SOURCES = {"user_exact", "host_skill_allowlist"}
OUTCOMES = {"passed", "failed", "blocked", "not_run"}
ATTRIBUTION = {"diff", "preexisting", "environment", "unknown"}
HEX = re.compile(r"[0-9a-f]{64}")
UNSAFE_ARG = re.compile(r"(?:/Users/|/home/|[A-Za-z]:\\\\Users\\\\|(?i:api[_-]?key|access[_-]?token|auth[_-]?token|secret|password)\s*[:=])")
TRUSTED_DIRS = ("/usr/bin", "/bin", "/usr/sbin", "/sbin", "/usr/local/bin", "/opt/homebrew/bin", "/opt/local/bin")


class GateError(ValueError):
    pass


def exact_fields(value: Any, expected: set[str], label: str) -> None:
    if not isinstance(value, dict) or set(value) != expected:
        raise GateError(f"{label} has an unsupported schema")


def safe_relative(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value or value.startswith("/") or ".." in Path(value).parts:
        raise GateError(f"{label} must be repository-relative")
    return value


def validate_snapshot(snapshot: Any) -> dict[str, Any]:
    if not isinstance(snapshot, dict) or snapshot.get("schema_version") != review_snapshot.VERSION:
        raise GateError("snapshot schema is unsupported")
    snapshot_hash = snapshot.get("snapshot_hash")
    if not isinstance(snapshot_hash, str) or not HEX.fullmatch(snapshot_hash):
        raise GateError("snapshot_hash is invalid")
    if snapshot_hash != review_snapshot.canonical_hash(review_snapshot.snapshot_identity(snapshot)):
        raise GateError("snapshot document is stale or altered")
    root = snapshot.get("repository_root")
    target = snapshot.get("target")
    if not isinstance(root, str) or not Path(root).is_absolute() or not isinstance(target, dict) or target.get("mode") not in {"working", "staged", "range"}:
        raise GateError("snapshot repository_root or target is invalid")
    if target["mode"] in {"working", "staged"} and (set(target) != {"mode", "base", "head"} or not isinstance(target.get("base"), str) or target.get("head") not in {"WORKTREE", "INDEX"}):
        raise GateError("working/staged target schema is invalid")
    if target["mode"] == "range" and (not {"mode", "base", "head", "source_base", "merge_base"} <= set(target) or not all(isinstance(target.get(key), str) for key in ("base", "head", "source_base")) or not isinstance(target.get("merge_base"), bool)):
        raise GateError("range target schema is invalid")
    if not isinstance(snapshot.get("configured_gates"), list):
        raise GateError("snapshot.configured_gates must be an array")
    binding = snapshot.get("repository_binding")
    if binding is not None and (not isinstance(binding, str) or not HEX.fullmatch(binding)):
        raise GateError("repository_binding is invalid")
    for entry in snapshot["configured_gates"]:
        if not isinstance(entry, dict):
            raise GateError("gate inventory entry is invalid")
        safe_relative(entry.get("config"), "gate config")
        if entry.get("cwd") is not None:
            safe_relative(entry["cwd"], "gate cwd")
        if not isinstance(entry.get("gate_id"), str) or not HEX.fullmatch(entry["gate_id"]):
            raise GateError("gate inventory entry has no deterministic gate_id")
    return snapshot


def validate_approval(approval: Any, snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    exact_fields(approval, {"schema_version", "snapshot_hash", "source", "approved"}, "approval")
    if approval["schema_version"] != VERSION or approval["source"] not in SOURCES:
        raise GateError("approval schema or source is invalid")
    if approval["source"] == "host_skill_allowlist":
        # No maintained, independently signed allowlist ships with v1.2.
        raise GateError("host_skill_allowlist is unavailable without a maintained allowlist")
    if approval["snapshot_hash"] != snapshot["snapshot_hash"]:
        raise GateError("approval is for a different snapshot")
    if not isinstance(approval["approved"], list):
        raise GateError("approval.approved must be an array")
    inventory = {entry["gate_id"]: entry for entry in snapshot["configured_gates"]}
    approved: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, item in enumerate(approval["approved"]):
        exact_fields(item, {"gate_id", "argv"}, f"approval.approved[{index}]")
        gate_id, argv = item["gate_id"], item["argv"]
        if not isinstance(gate_id, str) or gate_id in seen:
            raise GateError("approval has duplicate or invalid gate_id")
        seen.add(gate_id)
        if not isinstance(argv, list) or not argv or not all(isinstance(arg, str) and arg for arg in argv):
            raise GateError("approval argv must be a non-empty string array")
        if any(Path(arg).is_absolute() or UNSAFE_ARG.search(arg) for arg in argv):
            raise GateError("approval argv contains a sensitive or local value")
        entry = inventory.get(gate_id)
        if entry is None or entry.get("command_argv") != argv:
            raise GateError("approval is not an exact executable inventory entry")
        # Do not turn a repository-provided absolute executable into authorization.
        if Path(argv[0]).is_absolute():
            raise GateError("absolute executable paths are not permitted")
        approved.append(entry)
    return approved


def validate_resume(path: str | None, snapshot_hash: str, approved: list[dict[str, Any]]) -> None:
    if path is None:
        return
    prior = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(prior, dict) or set(prior) != {"schema_version", "snapshot_hash", "results"} or prior.get("schema_version") != VERSION or prior.get("snapshot_hash") != snapshot_hash or not isinstance(prior.get("results"), list):
        raise GateError("resume ledger is invalid or belongs to another snapshot")
    expected = {"gate_id", "gate", "config", "scope", "argv", "outcome", "attribution", "reason", "exit_code", "duration_seconds"}
    prior_ids: set[str] = set()
    for item in prior["results"]:
        if not isinstance(item, dict) or set(item) != expected or not isinstance(item.get("gate_id"), str) or item["gate_id"] in prior_ids:
            raise GateError("resume ledger results are malformed or duplicate")
        if item.get("outcome") not in OUTCOMES or item.get("attribution") not in ATTRIBUTION:
            raise GateError("resume ledger result has invalid outcome")
        prior_ids.add(item["gate_id"])
    repeated = sorted(entry["gate_id"] for entry in approved if entry["gate_id"] in prior_ids)
    if repeated:
        raise GateError("one-shot gate already has a result in the resume ledger")


def load_executable_map(path: str | None, root: Path) -> dict[str, tuple[Path, str]]:
    if path is None:
        return {}
    map_path = Path(path).resolve()
    if map_path.is_relative_to(root):
        raise GateError("executable map must be main-owned and outside the reviewed repository")
    value = json.loads(map_path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or set(value) != {"schema_version", "executables"} or value.get("schema_version") != 1 or not isinstance(value.get("executables"), list):
        raise GateError("executable map has an unsupported schema")
    result: dict[str, tuple[Path, str]] = {}
    for item in value["executables"]:
        if not isinstance(item, dict) or set(item) != {"name", "path", "sha256"} or not isinstance(item.get("name"), str) or not re.fullmatch(r"[A-Za-z0-9._+-]+", item["name"]) or not isinstance(item.get("path"), str) or not Path(item["path"]).is_absolute() or not isinstance(item.get("sha256"), str) or not HEX.fullmatch(item["sha256"]) or item["name"] in result:
            raise GateError("executable map entry is invalid")
        resolved = Path(item["path"]).resolve()
        if resolved.is_relative_to(root) or not resolved.is_file() or not os.access(resolved, os.X_OK) or review_snapshot.hash_file(resolved) != item["sha256"]:
            raise GateError("executable map entry is unsafe or changed")
        result[item["name"]] = (resolved, item["sha256"])
    return result


def result(entry: dict[str, Any], outcome: str, attribution: str, reason: str, exit_code: int | None, duration: float) -> dict[str, Any]:
    return {
        "gate_id": entry["gate_id"], "gate": entry["gate"], "config": entry["config"],
        "scope": "target-bound", "argv": entry.get("command_argv"), "outcome": outcome,
        "attribution": attribution, "reason": reason, "exit_code": exit_code,
        "duration_seconds": round(duration, 3),
    }


def run(snapshot: dict[str, Any], approved: list[dict[str, Any]], execute: bool, timeout: int, executable_map: dict[str, tuple[Path, str]] | None = None) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    for entry in approved:
        if not execute:
            records.append(result(entry, "not_run", "unknown", "dry_run", None, 0.0))
            continue
        argv = entry["command_argv"]
        started = time.monotonic()
        try:
            trusted = os.pathsep.join(path for path in TRUSTED_DIRS if Path(path).is_dir())
            mapped = (executable_map or {}).get(argv[0])
            if mapped:
                mapped_path, expected_hash = mapped
                if not mapped_path.is_file() or not os.access(mapped_path, os.X_OK) or review_snapshot.hash_file(mapped_path) != expected_hash:
                    raise GateError("approved executable changed before gate execution")
                resolved = str(mapped_path)
            else:
                resolved = shutil.which(argv[0], path=trusted)
            if not resolved:
                raise FileNotFoundError(argv[0])
            executable = Path(resolved).resolve()
            root = Path(snapshot["repository_root"]).resolve()
            if executable.is_relative_to(root):
                raise OSError("executable resolves inside reviewed repository")
            safe_path = str(executable.parent) + os.pathsep + trusted
            process = subprocess.Popen(
                [str(executable), *argv[1:]], cwd=Path(snapshot["repository_root"]) / entry.get("cwd", "."), env={"PATH": safe_path, "LANG": "C", "LC_ALL": "C"}, shell=False,
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            try:
                exit_code = process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, 15)
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, 9)
                    process.wait()
                raise
            elapsed = time.monotonic() - started
            if exit_code == 0:
                records.append(result(entry, "passed", "unknown", "completed", 0, elapsed))
            else:
                records.append(result(entry, "failed", "unknown", "nonzero_exit", exit_code, elapsed))
        except FileNotFoundError:
            records.append(result(entry, "blocked", "environment", "executable_missing", None, time.monotonic() - started))
        except subprocess.TimeoutExpired:
            records.append(result(entry, "blocked", "environment", "timeout", None, time.monotonic() - started))
        except GateError:
            records.append(result(entry, "blocked", "environment", "executable_changed", None, time.monotonic() - started))
        except OSError:
            records.append(result(entry, "blocked", "environment", "startup_failed", None, time.monotonic() - started))
    return {"schema_version": VERSION, "snapshot_hash": snapshot["snapshot_hash"], "results": records}


def journal_path(snapshot: dict[str, Any], gate_id: str) -> Path:
    root = Path(snapshot["repository_root"])
    common = review_snapshot.git(root, "rev-parse", "--git-common-dir").decode().strip()
    common_path = (root / common).resolve() if not Path(common).is_absolute() else Path(common).resolve()
    return common_path / "review-orchestrator-gates" / snapshot["repository_binding"] / snapshot["snapshot_hash"] / f"{gate_id}.json"


def reserve(snapshot: dict[str, Any], gate_id: str) -> Path:
    path = journal_path(snapshot, gate_id); path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise GateError("one-shot gate has existing pending or terminal journal record") from exc
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump({"schema_version": 1, "snapshot_hash": snapshot["snapshot_hash"], "gate_id": gate_id, "state": "pending"}, handle, sort_keys=True)
    return path


def finalize(path: Path, snapshot: dict[str, Any], record: dict[str, Any]) -> None:
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps({"schema_version": 1, "snapshot_hash": snapshot["snapshot_hash"], "gate_id": record["gate_id"], "state": "terminal", "outcome": record["outcome"]}, sort_keys=True), encoding="utf-8")
    os.replace(temp, path)


def verify_live_working(snapshot: dict[str, Any]) -> None:
    if not isinstance(snapshot.get("repository_binding"), str) or len(snapshot["repository_binding"]) != 64:
        raise GateError("v1.2 execution requires a checkout-bound snapshot")
    target = snapshot.get("target", {})
    if target.get("mode") != "working":
        raise GateError("--execute supports only live working snapshots; staged/range execution is refused")
    current = review_snapshot.build_snapshot(snapshot["repository_root"], "working", target.get("base"), None, False)
    if current["snapshot_hash"] != snapshot["snapshot_hash"]:
        raise GateError("live working target no longer matches captured snapshot")


def run_reserved(snapshot: dict[str, Any], approved: list[dict[str, Any]], timeout: int, executable_map: dict[str, tuple[Path, str]]) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    for entry in approved:
        try:
            verify_live_working(snapshot)
            path = reserve(snapshot, entry["gate_id"])
            record = run(snapshot, [entry], True, timeout, executable_map)["results"][0]
            finalize(path, snapshot, record)
        except GateError as exc:
            reason = "already_executed" if "one-shot" in str(exc) else "snapshot_stale" if "snapshot" in str(exc) or "checkout-bound" in str(exc) else "environment_blocked"
            record = result(entry, "blocked", "environment", reason, None, 0.0)
        except review_snapshot.SnapshotError:
            record = result(entry, "blocked", "environment", "snapshot_stale", None, 0.0)
        records.append(record)
    return {"schema_version": VERSION, "snapshot_hash": snapshot["snapshot_hash"], "results": records}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", required=True)
    parser.add_argument("--approval", required=True)
    parser.add_argument("--resume-ledger")
    parser.add_argument("--executable-map", help="main-owned private executable resolution map")
    parser.add_argument("--timeout-seconds", type=int, default=300)
    parser.add_argument("--execute", action="store_true", help="run approved argv; default is dry-run")
    parser.add_argument("--output", default="-")
    args = parser.parse_args()
    try:
        if not 1 <= args.timeout_seconds <= 3600:
            raise GateError("timeout_seconds must be between 1 and 3600")
        snapshot = validate_snapshot(json.loads(Path(args.snapshot).read_text(encoding="utf-8")))
        approved = validate_approval(json.loads(Path(args.approval).read_text(encoding="utf-8")), snapshot)
        validate_resume(args.resume_ledger, snapshot["snapshot_hash"], approved)
        executable_map = load_executable_map(args.executable_map, Path(snapshot["repository_root"]).resolve())
        artifact = run_reserved(snapshot, approved, args.timeout_seconds, executable_map) if args.execute else run(snapshot, approved, False, args.timeout_seconds, executable_map)
        encoded = json.dumps(artifact, indent=2, sort_keys=True) + "\n"
        if args.output == "-":
            sys.stdout.write(encoded)
        else:
            Path(args.output).write_text(encoded, encoding="utf-8")
        return 0
    except (OSError, ValueError, KeyError, TypeError, AttributeError, json.JSONDecodeError, GateError, review_snapshot.SnapshotError) as exc:
        print(f"run_gates: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

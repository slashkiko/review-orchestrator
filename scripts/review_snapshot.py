#!/usr/bin/env python3
"""Create and verify a deterministic, redacted review target snapshot."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
from pathlib import Path, PurePosixPath
from typing import Any, Iterable


VERSION = 2
MAX_SCAN_BYTES = 1_000_000

LANGUAGES = {
    ".c": "c", ".cc": "cpp", ".cpp": "cpp", ".cs": "csharp",
    ".go": "go", ".java": "java", ".js": "javascript", ".jsx": "javascript",
    ".kt": "kotlin", ".php": "php", ".py": "python", ".rb": "ruby",
    ".rs": "rust", ".scala": "scala", ".sh": "shell", ".sql": "sql",
    ".swift": "swift", ".ts": "typescript", ".tsx": "typescript",
    ".vue": "vue", ".svelte": "svelte",
}

MANIFESTS = {
    "package.json", "package-lock.json", "pnpm-lock.yaml", "yarn.lock",
    "go.mod", "go.sum", "cargo.toml", "cargo.lock", "pyproject.toml",
    "poetry.lock", "requirements.txt", "gemfile", "gemfile.lock",
    "pom.xml", "build.gradle", "build.gradle.kts", "composer.json",
}

SENSITIVE_PATTERNS = (
    ("email", re.compile(r"(?<![\w.+-])[\w.+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}(?![\w.-])")),
    ("macos-local-path", re.compile(r"/Users/[^/\s'\"`]+(?:/[^\s'\"`]+)+")),
    ("linux-local-path", re.compile(r"/home/[^/\s'\"`]+(?:/[^\s'\"`]+)+")),
    ("windows-local-path", re.compile(r"[A-Za-z]:\\Users\\[^\\\s'\"`]+(?:\\[^\s'\"`]+)+")),
    ("credential-assignment", re.compile(
        r"(?i)\b(?:api[_-]?key|access[_-]?token|auth[_-]?token|secret|password)\b\s*[:=]\s*['\"]?[^\s,'\"}]{8,}"
    )),
    ("bearer-token", re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{12,}")),
    ("private-key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    ("internal-host", re.compile(r"(?i)\b(?:https?://)?[A-Za-z0-9.-]+\.(?:internal|corp|local)(?::\d+)?(?:/[^\s'\"`]*)?")),
    ("repository-reference", re.compile(r"(?:git@github\.com:|https://github\.com/)[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:\.git)?")),
)

ROUTE_RULES = {
    "language-idiom": re.compile(r"(?i)\b(?:goroutine|context\.|defer|unsafe|clone\(|unwrap\(|promise|async|await|mutex|lock|thread|exception|yield)\b"),
    "security": re.compile(r"(?i)\b(?:auth(?:entication|orization)?|permission|policy|tenant|owner|deserialize|unmarshal|redirect|csrf|cors|cookie|credential|path traversal)\b"),
    "reliability": re.compile(r"(?i)\b(?:retry|timeout|cancel|queue|worker|subscriber|idempoten|backoff|transaction|async|await|cleanup|lease|lock)\b"),
    "data-integrity": re.compile(r"(?i)\b(?:migration|backfill|constraint|unique|upsert|insert|update|delete|precision|decimal|timestamp|timezone|dedup)\b"),
    "compatibility": re.compile(r"(?i)\b(?:public api|openapi|protobuf|proto\b|schema|serialize|version|deprecated|breaking|config(?:uration)? key)\b"),
    "rollout": re.compile(r"(?i)\b(?:feature flag|rollout|rollback|deploy|migration|environment variable|env var|configmap|helm|terraform|kubernetes)\b"),
    "observability": re.compile(r"(?i)\b(?:log(?:ger|ging)?|metric|trace|telemetry|span|alert|monitor|cardinality)\b"),
    "contract-design": re.compile(r"(?i)\b(?:public\s+(?:class|interface|type|struct|func|fn)|interface\b|nullability|lifecycle|ownership)\b"),
    "performance": re.compile(r"(?i)\b(?:select\b|join\b|query|batch|render|cache|paginate|n\+1|allocation|hot path)\b"),
    "accessibility": re.compile(r"(?i)\b(?:aria-|role=|tabindex|focus|keyboard|screen reader|a11y|<button|<input|<label)\b"),
    "docs-dx": re.compile(r"(?i)\b(?:usage|example|migration guide|command line|cli\b|--help|configuration|error message)\b"),
}


class SnapshotError(RuntimeError):
    pass


def git_result(root: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def git(root: Path, *args: str) -> bytes:
    completed = git_result(root, *args)
    if completed.returncode != 0:
        message = completed.stderr.decode("utf-8", "replace").strip()
        raise SnapshotError(f"git {' '.join(args)} failed: {message}")
    return completed.stdout


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_hash(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return sha256(encoded)


def hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def repo_relative_path(value: str) -> str:
    normalized = PurePosixPath(value).as_posix()
    if not normalized or normalized.startswith("../") or normalized.startswith("/") or ".." in PurePosixPath(normalized).parts:
        raise SnapshotError(f"unsafe repository path: {value}")
    return normalized


def parse_name_status(raw: bytes) -> list[dict[str, str]]:
    tokens = [item.decode("utf-8", "surrogateescape") for item in raw.split(b"\0") if item]
    records: list[dict[str, str]] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if "\t" in token:
            status, first_path = token.split("\t", 1)
            index += 1
        else:
            status = token
            index += 1
            if index >= len(tokens):
                raise SnapshotError("malformed git name-status output")
            first_path = tokens[index]
            index += 1
        kind = status[:1]
        if kind in {"R", "C"}:
            if index >= len(tokens):
                raise SnapshotError("malformed rename/copy output")
            second_path = tokens[index]
            index += 1
            records.append({
                "status": status,
                "old_path": repo_relative_path(first_path),
                "path": repo_relative_path(second_path),
            })
        else:
            records.append({"status": status, "path": repo_relative_path(first_path)})
    return records


def patch_path(marker: str) -> str | None:
    marker = marker.split("\t", 1)[0]
    if marker == "/dev/null":
        return None
    if marker.startswith(("a/", "b/")):
        marker = marker[2:]
    return repo_relative_path(marker)


def parse_line_changes(patch: bytes) -> tuple[dict[str, dict[str, list[int]]], list[tuple[str, int, str]]]:
    changes: dict[str, dict[str, list[int]]] = {}
    added: list[tuple[str, int, str]] = []
    old_path: str | None = None
    new_path: str | None = None
    old_line = 0
    new_line = 0
    in_hunk = False

    def record(path: str, side: str, line: int) -> None:
        changes.setdefault(path, {"old": [], "new": []})[side].append(line)

    for line in patch.decode("utf-8", "replace").splitlines():
        if line.startswith("diff --git "):
            old_path = None
            new_path = None
            in_hunk = False
        elif line.startswith("--- "):
            old_path = patch_path(line[4:])
            in_hunk = False
        elif line.startswith("+++ "):
            new_path = patch_path(line[4:])
            in_hunk = False
        elif line.startswith("@@ "):
            match = re.search(r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", line)
            if match:
                old_line = int(match.group(1))
                new_line = int(match.group(3))
                in_hunk = True
        elif in_hunk and line.startswith("-") and not line.startswith("---"):
            if old_path is not None:
                record(old_path, "old", old_line)
            old_line += 1
        elif in_hunk and line.startswith("+") and not line.startswith("+++"):
            if new_path is not None:
                record(new_path, "new", new_line)
                added.append((new_path, new_line, line[1:]))
            new_line += 1
        elif in_hunk and line.startswith(" "):
            old_line += 1
            new_line += 1
        elif in_hunk and line.startswith("\\"):
            continue
        elif in_hunk:
            in_hunk = False
    return changes, added


def compact_ranges(lines: Iterable[int]) -> list[list[int]]:
    ranges: list[list[int]] = []
    for line in sorted(set(lines)):
        if ranges and line == ranges[-1][1] + 1:
            ranges[-1][1] = line
        else:
            ranges.append([line, line])
    return ranges


def role_for_path(path: str) -> list[str]:
    lowered = path.lower()
    name = PurePosixPath(lowered).name
    roles: list[str] = []
    if name in MANIFESTS:
        roles.append("manifest")
    if any(part in lowered for part in ("/test/", "/tests/", "__tests__", "_test.", ".spec.", ".test.")):
        roles.append("test")
    if lowered.startswith(("docs/", "doc/")) or PurePosixPath(lowered).suffix in {".md", ".rst", ".adoc"}:
        roles.append("documentation")
    if "migration" in lowered or PurePosixPath(lowered).suffix in {".sql", ".proto"} or "schema" in lowered:
        roles.append("schema")
    if PurePosixPath(lowered).suffix in {".html", ".css", ".scss", ".jsx", ".tsx", ".vue", ".svelte"}:
        roles.append("ui")
    if name in {"dockerfile", "compose.yaml", "compose.yml"} or any(part in lowered for part in (".github/workflows/", "deploy/", "helm/", "terraform/", "k8s/")):
        roles.append("deployment")
    if name.startswith(".") or PurePosixPath(lowered).suffix in {".yaml", ".yml", ".toml", ".ini", ".env"}:
        roles.append("configuration")
    if any(part in lowered for part in ("vendor/", "generated/", "dist/", "build/")) or name.endswith((".generated.go", ".min.js")):
        roles.append("generated-or-vendor")
    return sorted(set(roles))


def redact_candidates(lines: Iterable[tuple[str, int, str]]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    seen: set[tuple[str, str, int, str]] = set()
    for path, line_number, text in lines:
        for candidate_type, pattern in SENSITIVE_PATTERNS:
            for match in pattern.finditer(text):
                value_fingerprint = sha256(match.group(0).encode("utf-8"))[:12]
                key = (candidate_type, path, line_number, value_fingerprint)
                if key in seen:
                    continue
                seen.add(key)
                candidate_id = sha256(f"{candidate_type}:{path}:{line_number}:{value_fingerprint}".encode())[:16]
                candidates.append({
                    "candidate_id": candidate_id,
                    "type": candidate_type,
                    "path": path,
                    "line": line_number,
                    "fingerprint": value_fingerprint,
                })
    return sorted(candidates, key=lambda item: (item["path"], item["line"], item["type"], item["candidate_id"]))


def route_candidates(files: list[dict[str, Any]], added: list[tuple[str, int, str]], sensitive: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    candidates: dict[str, list[dict[str, Any]]] = {name: [] for name in (*ROUTE_RULES.keys(), "dependency", "sensitive-data")}
    seen: dict[str, set[tuple[str, str]]] = {name: set() for name in candidates}

    def add(route: str, path: str, reason: str) -> None:
        key = (path, reason)
        if key not in seen[route]:
            seen[route].add(key)
            candidates[route].append({"path": path, "reason": reason})

    for item in files:
        path = item["path"]
        roles = item["roles"]
        if "manifest" in roles:
            add("dependency", path, "dependency manifest or lockfile changed")
        if "schema" in roles:
            add("data-integrity", path, "schema or migration candidate changed")
            add("compatibility", path, "schema/protocol candidate changed")
        if "deployment" in roles or "configuration" in roles:
            add("rollout", path, "deployment or configuration candidate changed")
        if "ui" in roles:
            add("accessibility", path, "UI surface changed")
        if "documentation" in roles:
            add("docs-dx", path, "documentation surface changed")
        lowered = path.lower()
        if any(token in lowered for token in ("fixture", "snapshot", "log", "export", "telemetry", "example")):
            add("sensitive-data", path, "sensitive-data-prone artifact changed")

    for path, _, text in added:
        for route, pattern in ROUTE_RULES.items():
            if pattern.search(text):
                add(route, path, "added text matched deterministic route signal")
    for item in sensitive:
        add("sensitive-data", item["path"], f"redacted {item['type']} candidate {item['candidate_id']}")
    return {name: sorted(items, key=lambda item: (item["path"], item["reason"])) for name, items in sorted(candidates.items())}


def configured_gates(root: Path, mode: str, target: dict[str, Any]) -> list[dict[str, str]]:
    checks = {
        "secret-scan": [".gitleaks.toml", ".gitleaks.yaml", ".trufflehog.yaml"],
        "mutation": ["stryker.conf.json", "stryker-config.json", "mutmut_config.py", ".mutmut-config"],
    }
    found: list[dict[str, str]] = []
    for gate, paths in checks.items():
        for path in paths:
            if mode == "range":
                exists = commit_blob(root, target["head"], path) is not None
            elif mode == "staged":
                exists = index_blob(root, path) is not None
            else:
                exists = worktree_blob(root, path) is not None
            if exists:
                found.append({"gate": gate, "config": path, "status": "configured-not-run"})
    return found


def commit_blob(root: Path, commit: str, path: str) -> bytes | None:
    completed = git_result(root, "show", f"{commit}:{path}")
    return completed.stdout if completed.returncode == 0 else None


def index_blob(root: Path, path: str) -> bytes | None:
    completed = git_result(root, "show", f":{path}")
    return completed.stdout if completed.returncode == 0 else None


def worktree_blob(root: Path, path: str) -> bytes | None:
    absolute = root / path
    if absolute.is_symlink():
        return os.readlink(absolute).encode("utf-8", "surrogateescape")
    if not absolute.is_file():
        return None
    return absolute.read_bytes()


def commit_mode(root: Path, commit: str, path: str) -> str | None:
    completed = git_result(root, "ls-tree", "-z", commit, "--", path)
    if completed.returncode != 0 or not completed.stdout:
        return None
    return completed.stdout.split(b" ", 1)[0].decode("ascii", "replace")


def index_mode(root: Path, path: str) -> str | None:
    completed = git_result(root, "ls-files", "-s", "-z", "--", path)
    if completed.returncode != 0 or not completed.stdout:
        return None
    return completed.stdout.split(b" ", 1)[0].decode("ascii", "replace")


def worktree_mode(root: Path, path: str) -> str | None:
    absolute = root / path
    try:
        metadata = absolute.lstat()
    except FileNotFoundError:
        return None
    if stat.S_ISLNK(metadata.st_mode):
        return "120000"
    if stat.S_ISREG(metadata.st_mode):
        return "100755" if metadata.st_mode & stat.S_IXUSR else "100644"
    return None


def side_metadata(path: str, blob: bytes | None, mode: str | None) -> dict[str, Any]:
    binary = blob is not None and b"\0" in blob[:8192]
    return {
        "path": path,
        "exists": blob is not None,
        "mode": mode,
        "size": len(blob) if blob is not None else None,
        "content_sha256": sha256(blob) if blob is not None else None,
        "line_count": None if blob is None or binary else len(blob.splitlines()),
        "binary": binary,
    }


def file_record(
    root: Path,
    record: dict[str, str],
    ranges: dict[str, dict[str, list[int]]],
    mode: str,
    target: dict[str, Any],
) -> dict[str, Any]:
    path = record["path"]
    old_path = record.get("old_path", path)
    old_blob = commit_blob(root, target["base"], old_path)
    old_mode = commit_mode(root, target["base"], old_path)
    if mode == "working":
        new_blob = worktree_blob(root, path)
        new_mode = worktree_mode(root, path)
    elif mode == "staged":
        new_blob = index_blob(root, path)
        new_mode = index_mode(root, path)
    else:
        new_blob = commit_blob(root, target["head"], path)
        new_mode = commit_mode(root, target["head"], path)

    old = side_metadata(old_path, old_blob, old_mode)
    new = side_metadata(path, new_blob, new_mode)
    status_kind = record["status"][:1]
    non_line_changes: list[str] = []
    if status_kind in {"A", "U"}:
        non_line_changes.append("addition")
    if status_kind == "D":
        non_line_changes.append("deletion")
    if status_kind == "R":
        non_line_changes.append("rename")
    if status_kind == "C":
        non_line_changes.append("copy")
    if old["mode"] != new["mode"] and old["exists"] and new["exists"]:
        non_line_changes.append("mode")
    if old["binary"] or new["binary"]:
        non_line_changes.append("binary")
    old_lines = ranges.get(old_path, {}).get("old", [])
    new_lines = ranges.get(path, {}).get("new", [])
    if (
        old["exists"] and new["exists"]
        and old["content_sha256"] != new["content_sha256"]
        and not old_lines and not new_lines
    ):
        # Git attributes can classify a NUL-free blob as binary. A content change
        # with no textual hunks is therefore an explicit non-line binary change.
        non_line_changes.append("binary")

    result: dict[str, Any] = {
        **record,
        "language": LANGUAGES.get(PurePosixPath(path.lower()).suffix),
        "roles": role_for_path(path),
        "changed_ranges": {
            "old": compact_ranges(old_lines),
            "new": compact_ranges(new_lines),
        },
        "non_line_changes": sorted(set(non_line_changes)),
        "old": old,
        "new": new,
    }
    exclusions: list[str] = []
    if "generated-or-vendor" in result["roles"]:
        exclusions.append("generated-or-vendor")
    sizes = [value for value in (old["size"], new["size"]) if value is not None]
    if sizes and max(sizes) > MAX_SCAN_BYTES:
        exclusions.append("large-file")
    result["evidence_exclusions"] = exclusions
    return result


def snapshot_identity(snapshot: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": snapshot["schema_version"],
        "target": snapshot["target"],
        "diff_sha256": snapshot["diff_sha256"],
        "files": snapshot["files"],
        "languages": snapshot["languages"],
        "route_candidates": snapshot["route_candidates"],
        "sensitive_candidates": snapshot["sensitive_candidates"],
        "configured_gates": snapshot["configured_gates"],
    }


def build_snapshot(root_arg: str, mode: str, base: str | None, head: str | None, use_merge_base: bool) -> dict[str, Any]:
    root = Path(git(Path(root_arg).resolve(), "rev-parse", "--show-toplevel").decode().strip()).resolve()
    current_git_head = git(root, "rev-parse", "HEAD").decode().strip()
    target: dict[str, Any] = {"mode": mode}

    if mode in {"working", "staged"}:
        captured_base = git(root, "rev-parse", f"{base or current_git_head}^{{commit}}").decode().strip()
        cached = mode == "staged"
        diff_args = ["-c", "core.quotePath=false", "diff"]
        if cached:
            diff_args.append("--cached")
        diff_args.extend(["--no-ext-diff", "--binary", "--find-renames", captured_base, "--"])
        status_args = ["diff"]
        if cached:
            status_args.append("--cached")
        status_args.extend(["--name-status", "-z", "--find-renames", captured_base, "--"])
        line_args = ["-c", "core.quotePath=false", "diff"]
        if cached:
            line_args.append("--cached")
        line_args.extend(["--no-ext-diff", "--find-renames", "--unified=0", captured_base, "--"])
        target.update({"base": captured_base, "head": "INDEX" if cached else "WORKTREE"})
    else:
        if not base or not head:
            raise SnapshotError("--base and --head are required for range mode")
        source_base = git(root, "rev-parse", f"{base}^{{commit}}").decode().strip()
        resolved_head = git(root, "rev-parse", f"{head}^{{commit}}").decode().strip()
        comparison_base = git(root, "merge-base", source_base, resolved_head).decode().strip() if use_merge_base else source_base
        spec = f"{comparison_base}..{resolved_head}"
        diff_args = ["-c", "core.quotePath=false", "diff", "--no-ext-diff", "--binary", "--find-renames", spec, "--"]
        status_args = ["diff", "--name-status", "-z", "--find-renames", spec, "--"]
        line_args = ["-c", "core.quotePath=false", "diff", "--no-ext-diff", "--find-renames", "--unified=0", spec, "--"]
        target.update({
            "source_base": source_base,
            "base": comparison_base,
            "head": resolved_head,
            "merge_base": use_merge_base,
        })

    patch = git(root, *diff_args)
    identity_material = patch
    line_patch = git(root, *line_args)
    records = parse_name_status(git(root, *status_args))
    ranges, added = parse_line_changes(line_patch)

    if mode == "working":
        untracked_raw = git(root, "ls-files", "--others", "--exclude-standard", "-z")
        for raw_path in untracked_raw.split(b"\0"):
            if not raw_path:
                continue
            path = repo_relative_path(raw_path.decode("utf-8", "surrogateescape"))
            absolute = root / path
            if not absolute.is_file() or absolute.is_symlink():
                continue
            records.append({"status": "U", "path": path})
            identity_material += b"\0UNTRACKED\0" + raw_path + b"\0" + hash_file(absolute).encode()
            if absolute.stat().st_size <= MAX_SCAN_BYTES:
                text = absolute.read_text(encoding="utf-8", errors="replace")
                untracked_lines = [(path, index, value) for index, value in enumerate(text.splitlines(), 1)]
                added.extend(untracked_lines)
                ranges.setdefault(path, {"old": [], "new": []})["new"].extend(index for _, index, _ in untracked_lines)

    records = sorted(records, key=lambda item: (item["path"], item["status"], item.get("old_path", "")))
    files = [file_record(root, record, ranges, mode, target) for record in records]
    sensitive = redact_candidates(added)
    routes = route_candidates(files, added, sensitive)
    gates = configured_gates(root, mode, target)
    snapshot: dict[str, Any] = {
        "schema_version": VERSION,
        "repository_root": str(root),
        "target": target,
        "git_head_at_capture": current_git_head,
        "diff_sha256": sha256(identity_material),
        "files": files,
        "languages": sorted({item["language"] for item in files if item["language"]}),
        "route_candidates": routes,
        "sensitive_candidates": sensitive,
        "configured_gates": gates,
    }
    snapshot["snapshot_hash"] = canonical_hash(snapshot_identity(snapshot))
    return snapshot


def write_json(data: dict[str, Any], output: str) -> None:
    encoded = json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if output == "-":
        sys.stdout.write(encoded)
    else:
        Path(output).write_text(encoded, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=".", help="path inside the Git repository")
    parser.add_argument("--mode", choices=("working", "staged", "range"), default="working")
    parser.add_argument("--base", help="base commit; captured HEAD by default for working/staged")
    parser.add_argument("--head")
    parser.add_argument("--merge-base", action="store_true", help="compare the merge base to head (required for PR semantics)")
    parser.add_argument("--output", default="-")
    parser.add_argument("--verify", metavar="SNAPSHOT", help="recreate the captured target and fail if its canonical identity changed")
    args = parser.parse_args()

    try:
        if args.verify:
            original = json.loads(Path(args.verify).read_text(encoding="utf-8"))
            if original.get("schema_version") != VERSION:
                raise SnapshotError(f"unsupported snapshot schema version: {original.get('schema_version')}")
            recorded_hash = original.get("snapshot_hash")
            document_hash = canonical_hash(snapshot_identity(original))
            if recorded_hash != document_hash:
                write_json({
                    "matched": False,
                    "expected_snapshot_hash": recorded_hash,
                    "actual_snapshot_hash": document_hash,
                    "reason": "snapshot document does not match its canonical identity",
                }, args.output)
                return 3
            target = original["target"]
            mode = target["mode"]
            if mode == "range":
                current = build_snapshot(
                    original["repository_root"], mode, target.get("source_base", target["base"]),
                    target["head"], bool(target.get("merge_base")),
                )
            else:
                current = build_snapshot(original["repository_root"], mode, target["base"], None, False)
            matched = current["snapshot_hash"] == original["snapshot_hash"]
            result = {
                "matched": matched,
                "expected_snapshot_hash": original["snapshot_hash"],
                "actual_snapshot_hash": current["snapshot_hash"],
                "captured_base": target["base"],
            }
            write_json(result, args.output)
            return 0 if matched else 3
        snapshot = build_snapshot(args.repo, args.mode, args.base, args.head, args.merge_base)
        write_json(snapshot, args.output)
        return 0
    except (OSError, KeyError, ValueError, SnapshotError, json.JSONDecodeError) as exc:
        print(f"review_snapshot: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

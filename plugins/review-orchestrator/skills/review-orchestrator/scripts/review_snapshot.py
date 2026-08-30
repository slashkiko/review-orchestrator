#!/usr/bin/env python3
"""Create and verify a deterministic, redacted review target snapshot."""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import tomllib
from pathlib import Path, PurePosixPath
from typing import Any, Iterable


VERSION = 4
MAX_SCAN_BYTES = 1_000_000
STABLE_DIFF_CONFIG = [
    "-c", "core.quotePath=false", "-c", "core.abbrev=40", "-c", "diff.mnemonicPrefix=false",
    "-c", "diff.noprefix=false", "-c", "diff.srcPrefix=a/", "-c", "diff.dstPrefix=b/",
]
STABLE_DIFF_FLAGS = [
    "--no-ext-diff", "--no-textconv", "--no-color", "--full-index", "--find-renames=50%",
    "--diff-algorithm=myers", "--no-indent-heuristic",
]

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

STRONG_PATH_RULES = {
    "security": re.compile(r"(?i)(?:^|/)(?:auth(?:entication|orization)?|permissions?|identity|access-control)(?:/|\.|$)|(?:^|/)middleware/auth(?:/|\.|$)"),
    "data-integrity": re.compile(r"(?i)(?:^|/)(?:migrations?|backfills?)(?:/|$)|(?:^|/)(?:schema|db)/(?:migrations?|backfills?)(?:/|$)"),
    "compatibility": re.compile(r"(?i)(?:^|/)(?:openapi|swagger)(?:\.|/|$)|\.(?:proto|avsc)$|(?:^|/)(?:public[-_]?)?schemas?(?:/|$)"),
    "rollout": re.compile(r"(?i)(?:^|/)(?:deploy(?:ment)?|helm|terraform|k8s|kubernetes|\.github/workflows)(?:/|$)|(?:^|/)(?:docker-compose|compose)\.ya?ml$|(?:^|/)Dockerfile$"),
}

GATE_SCRIPT_NAMES = {
    "build": "build", "check": "check", "format": "format", "lint": "lint",
    "test": "test", "typecheck": "type", "type-check": "type",
    "types": "type", "secret-scan": "secret-scan", "secrets": "secret-scan",
    "mutation": "mutation", "mutate": "mutation",
}
MISE_FILENAMES = ("mise.toml", ".mise.toml")


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


def repository_binding(root: Path) -> str:
    """Opaque checkout binding; never emit the underlying local paths."""
    common = git(root, "rev-parse", "--git-common-dir").decode().strip()
    common_path = (root / common).resolve() if not Path(common).is_absolute() else Path(common).resolve()
    root_stat, common_stat = root.stat(), common_path.stat()
    return sha256(f"{root_stat.st_dev}:{root_stat.st_ino}:{common_stat.st_dev}:{common_stat.st_ino}".encode())


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
    seen: dict[str, set[tuple[str, int | None, str, str]]] = {name: set() for name in candidates}

    def add(
        route: str, path: str, line: int | None, matched_rule: str, source: str,
        strength: str, reason: str,
    ) -> None:
        key = (path, line, matched_rule, source)
        if key not in seen[route]:
            seen[route].add(key)
            candidates[route].append({
                "path": path, "line": line, "matched_rule": matched_rule,
                "source": source, "strength": strength, "reason": reason,
            })

    for item in files:
        path = item["path"]
        roles = item["roles"]
        if "manifest" in roles:
            add("dependency", path, None, "manifest-path", "file-role", "strong", "dependency manifest or lockfile changed")
        for route, pattern in STRONG_PATH_RULES.items():
            if pattern.search(path):
                add(route, path, None, f"{route}-boundary-path", "path-structure", "strong", "structural boundary path changed")
        if "configuration" in roles:
            add("rollout", path, None, "configuration-path", "file-role", "weak", "configuration candidate changed; semantics require classification")
        if "ui" in roles:
            add("accessibility", path, None, "ui-path", "file-role", "strong", "UI surface changed")
        if "documentation" in roles:
            add("docs-dx", path, None, "documentation-path", "file-role", "weak", "documentation surface changed; semantics require classification")
        lowered = path.lower()
        if any(token in lowered for token in ("fixture", "snapshot", "log", "export", "telemetry", "example")):
            add("sensitive-data", path, None, "sensitive-artifact-path", "path-structure", "weak", "sensitive-data-prone artifact changed")

    for path, line, text in added:
        for route, pattern in ROUTE_RULES.items():
            if pattern.search(text):
                add(route, path, line, f"{route}-keyword", "content-keyword", "weak", "added text matched a keyword; semantics require classification")
    for item in sensitive:
        add("sensitive-data", item["path"], item["line"], "redacted-sensitive-candidate", "sensitive-candidate", "strong", f"redacted {item['type']} candidate {item['candidate_id']}")
    return {
        name: sorted(items, key=lambda item: (item["path"], item["line"] is None, item["line"] or 0, item["matched_rule"], item["reason"]))
        for name, items in sorted(candidates.items())
    }


def target_blob(root: Path, mode: str, target: dict[str, Any], path: str) -> bytes | None:
    if mode == "range":
        return commit_blob(root, target["head"], path)
    if mode == "staged":
        return index_blob(root, path)
    return worktree_blob(root, path)


def target_paths(root: Path, mode: str, target: dict[str, Any]) -> list[str]:
    if mode == "range":
        raw = git(root, "ls-tree", "-r", "-z", "--name-only", target["head"])
    elif mode == "staged":
        raw = git(root, "ls-files", "-z")
    else:
        raw = git(root, "ls-files", "-z") + git(root, "ls-files", "--others", "--exclude-standard", "-z")
    return sorted({repo_relative_path(value.decode("utf-8", "surrogateescape")) for value in raw.split(b"\0") if value})


def declared_package_manager(package: dict[str, Any]) -> str | None:
    declared = package.get("packageManager")
    if isinstance(declared, str):
        name = declared.split("@", 1)[0].lower()
        if name in {"npm", "pnpm", "yarn", "bun"}:
            return name
    return None


def package_at(root: Path, mode: str, target: dict[str, Any], path: str) -> dict[str, Any] | None:
    source = target_blob(root, mode, target, path)
    if source is None:
        return None
    try:
        result = json.loads(source.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return result if isinstance(result, dict) else None


def lockfile_manager(root: Path, mode: str, target: dict[str, Any], directory: PurePosixPath) -> str | None:
    prefix = "" if directory.as_posix() == "." else f"{directory}/"
    for manager, lockfile in (("pnpm", "pnpm-lock.yaml"), ("yarn", "yarn.lock"), ("bun", "bun.lockb"), ("npm", "package-lock.json")):
        if target_blob(root, mode, target, prefix + lockfile) is not None:
            return manager
    return None


def workspace_pattern_matches(path: PurePosixPath, pattern: str) -> bool:
    """Match workspace glob segments: * is one segment and ** is zero or more."""
    normalized = PurePosixPath(pattern)
    if normalized.is_absolute() or ".." in normalized.parts or "\\" in pattern:
        return False
    pattern_parts = normalized.parts
    path_parts = path.parts

    def matches(pattern_index: int, path_index: int) -> bool:
        if pattern_index == len(pattern_parts):
            return path_index == len(path_parts)
        part = pattern_parts[pattern_index]
        if part == "**":
            return any(matches(pattern_index + 1, index) for index in range(path_index, len(path_parts) + 1))
        return (
            path_index < len(path_parts)
            and fnmatch.fnmatchcase(path_parts[path_index], part)
            and matches(pattern_index + 1, path_index + 1)
        )

    return matches(0, 0)


def pnpm_workspace_patterns(source: bytes | None) -> list[str]:
    """Read the small packages-list subset without treating YAML as executable input."""
    if source is None:
        return []
    try:
        lines = source.decode("utf-8").splitlines()
    except UnicodeDecodeError:
        return []
    patterns: list[str] = []
    in_packages = False
    for raw in lines:
        stripped = raw.strip()
        if not in_packages:
            if re.match(r"^packages\s*:\s*(?:#.*)?$", stripped):
                in_packages = True
            continue
        if not stripped or stripped.startswith("#"):
            continue
        match = re.match(r"^-\s+(.+?)\s*(?:#.*)?$", stripped)
        if not match:
            # Another YAML mapping key starts a new section.
            if not raw[:1].isspace() or re.match(r"^[A-Za-z0-9_-]+\s*:", stripped):
                break
            continue
        value = match.group(1).strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        if value:
            patterns.append(value)
    return patterns


def matches_workspace_patterns(relative: PurePosixPath, patterns: list[str]) -> bool:
    included = False
    for raw_pattern in patterns:
        negative = raw_pattern.startswith("!")
        pattern = raw_pattern[1:] if negative else raw_pattern
        if workspace_pattern_matches(relative, pattern):
            included = not negative
    return included


def workspace_member(root: Path, mode: str, target: dict[str, Any], ancestor: PurePosixPath, package_path: str, package: dict[str, Any]) -> bool:
    workspaces = package.get("workspaces")
    patterns = workspaces.get("packages") if isinstance(workspaces, dict) else workspaces
    package_directory = PurePosixPath(package_path).parent
    try:
        relative = package_directory.relative_to(ancestor)
    except ValueError:
        return False
    package_patterns = patterns if isinstance(patterns, list) and all(isinstance(pattern, str) for pattern in patterns) else []
    prefix = "" if ancestor.as_posix() == "." else f"{ancestor}/"
    pnpm_patterns = pnpm_workspace_patterns(target_blob(root, mode, target, prefix + "pnpm-workspace.yaml"))
    return matches_workspace_patterns(relative, package_patterns) or matches_workspace_patterns(relative, pnpm_patterns)


def package_manager(root: Path, mode: str, target: dict[str, Any], package_path: str, package: dict[str, Any]) -> str:
    local = declared_package_manager(package)
    if local:
        return local
    local_directory = PurePosixPath(package_path).parent
    local_lockfile = lockfile_manager(root, mode, target, local_directory)
    if local_lockfile:
        return local_lockfile
    ancestor = local_directory.parent
    while True:
        ancestor_path = (ancestor / "package.json").as_posix()
        ancestor_package = package_at(root, mode, target, ancestor_path)
        if ancestor_package and workspace_member(root, mode, target, ancestor, package_path, ancestor_package):
            inherited = declared_package_manager(ancestor_package)
            if inherited:
                return inherited
            inherited_lockfile = lockfile_manager(root, mode, target, ancestor)
            if inherited_lockfile:
                return inherited_lockfile
        if ancestor.as_posix() == ".":
            break
        ancestor = ancestor.parent
    return "npm"


def configured_gates(root: Path, mode: str, target: dict[str, Any]) -> list[dict[str, Any]]:
    checks = {
        "secret-scan": [".gitleaks.toml", ".gitleaks.yaml", ".trufflehog.yaml"],
        "mutation": [
            "stryker.conf.json", "stryker-config.json", "stryker.conf.js", "stryker.conf.cjs",
            "stryker.conf.mjs", "stryker.conf.ts", "mutation.config.json", "mutmut_config.py",
            ".mutmut-config", "mutmut.ini",
        ],
    }
    found: list[dict[str, Any]] = []
    for gate, paths in checks.items():
        for path in paths:
            exists = target_blob(root, mode, target, path) is not None
            if exists:
                found.append({"gate": gate, "config": path, "status": "configured-not-run"})
    for package_path in (path for path in target_paths(root, mode, target) if PurePosixPath(path).name == "package.json"):
        package_blob = target_blob(root, mode, target, package_path)
        if package_blob is None:
            continue
        try:
            package = json.loads(package_blob.decode("utf-8"))
            scripts = package.get("scripts", {})
        except (UnicodeDecodeError, json.JSONDecodeError):
            scripts = {}
            package = {}
        if isinstance(scripts, dict):
            manager = package_manager(root, mode, target, package_path, package if isinstance(package, dict) else {})
            for name in sorted(scripts):
                gate = GATE_SCRIPT_NAMES.get(name.lower().split(":", 1)[0])
                if gate and isinstance(scripts[name], str):
                    found.append({
                        "gate": gate, "config": package_path, "script": name,
                        "cwd": PurePosixPath(package_path).parent.as_posix(),
                        "command_argv": [manager, "run", name], "status": "configured-not-run",
                    })
    for path in MISE_FILENAMES:
        source = target_blob(root, mode, target, path)
        if source is None:
            continue
        try:
            tasks = tomllib.loads(source.decode("utf-8")).get("tasks", {})
        except (UnicodeDecodeError, tomllib.TOMLDecodeError):
            tasks = {}
        if isinstance(tasks, dict):
            for name in sorted(tasks):
                gate = GATE_SCRIPT_NAMES.get(name.lower())
                if gate:
                    found.append({
                        "gate": gate, "config": path, "task": name,
                        "cwd": ".", "command_argv": ["mise", "run", name], "status": "configured-not-run",
                    })
    for item in found:
        # The ID is target-bound through the snapshot identity and binds approval
        # to the exact executable argv rather than a mutable script name alone.
        item["gate_id"] = canonical_hash({
            "gate": item["gate"], "config": item["config"],
            "script": item.get("script"), "task": item.get("task"),
            "cwd": item.get("cwd"),
            "command_argv": item.get("command_argv"),
        })
    return sorted(found, key=lambda item: (item["gate"], item["config"], item.get("script", item.get("task", ""))))


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


def nested_repo_fingerprint(path: Path) -> str:
    """Hash nested state without emitting nested paths, values, or contents."""
    head = git_result(path, "rev-parse", "HEAD")
    status = git_result(path, "status", "--porcelain=v2", "-z", "--untracked-files=all")
    material = b"HEAD\0" + (head.stdout if head.returncode == 0 else b"unborn")
    material += b"\0DIRTY\0" + (b"1" if status.stdout else b"0")
    # Index identity is separate from worktree identity, including unborn repos.
    material += b"\0INDEX\0" + sha256(git_result(path, "ls-files", "-s", "-z").stdout).encode("ascii")
    # Resolve changed tracked paths through Git, then hash only bounded working
    # content. Path bytes remain inside the final one-way fingerprint.
    tracked_paths = {
        item for item in git_result(path, "ls-files", "-z").stdout.split(b"\0") if item
    }
    if head.returncode == 0:
        changed = sorted(item for item in git_result(path, "diff", "--name-only", "-z", "HEAD", "--").stdout.split(b"\0") if item)
    else:
        changed = sorted(tracked_paths)
    tracked_material = bytearray()
    for encoded_path in changed:
        candidate = path / encoded_path.decode("utf-8", "surrogateescape")
        try:
            metadata = candidate.lstat()
        except OSError:
            tracked_material.extend(b"deleted\0" + encoded_path)
            continue
        if stat.S_ISLNK(metadata.st_mode):
            tracked_material.extend(b"symlink\0" + encoded_path + b"\0" + sha256(os.readlink(candidate).encode("utf-8", "surrogateescape")).encode("ascii"))
        elif stat.S_ISREG(metadata.st_mode):
            tracked_material.extend(b"file\0" + encoded_path + b"\0" + hash_file(candidate).encode("ascii"))
        else:
            tracked_material.extend(b"bounded\0" + encoded_path + b"\0" + str(metadata.st_size).encode("ascii"))
    material += b"\0TRACKED\0" + sha256(bytes(tracked_material)).encode("ascii")
    untracked = sorted(item for item in git_result(path, "ls-files", "--others", "--exclude-standard", "-z").stdout.split(b"\0") if item)
    untracked_material = bytearray()
    for encoded_path in untracked:
        candidate = path / encoded_path.decode("utf-8", "surrogateescape")
        try:
            metadata = candidate.lstat()
        except OSError:
            untracked_material.extend(b"missing\0" + sha256(encoded_path).encode("ascii"))
            continue
        if stat.S_ISLNK(metadata.st_mode):
            untracked_material.extend(b"symlink\0" + encoded_path + b"\0" + sha256(os.readlink(candidate).encode("utf-8", "surrogateescape")).encode("ascii"))
            continue
        if not stat.S_ISREG(metadata.st_mode):
            untracked_material.extend(b"special\0" + sha256(encoded_path + str(metadata.st_mode).encode()).encode("ascii"))
            continue
        untracked_material.extend(b"file\0" + encoded_path + b"\0" + hash_file(candidate).encode("ascii"))
    material += b"\0UNTRACKED\0" + sha256(bytes(untracked_material)).encode("ascii")
    return sha256(material)


def scope_gap(path: str, kind: str, reason: str, fingerprint: str | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {"path": path, "kind": kind, "reason": reason}
    if fingerprint is not None:
        result["fingerprint"] = fingerprint
    return result


def working_scope(root: Path) -> tuple[list[dict[str, str]], list[dict[str, Any]], list[tuple[str, int, str]], bytes]:
    """Return includable untracked files and explicit boundaries left outside review."""
    raw = git(root, "status", "--porcelain=v1", "-z", "--untracked-files=all")
    paths = sorted({
        repo_relative_path(item[3:].decode("utf-8", "surrogateescape"))
        for item in raw.split(b"\0") if item.startswith(b"?? ")
    })
    records: list[dict[str, str]] = []
    gaps: list[dict[str, Any]] = []
    added: list[tuple[str, int, str]] = []
    identity = b""
    seen_directories: set[str] = set()
    seen_gaps: set[tuple[str, str]] = set()
    tracked = {
        repo_relative_path(item.decode("utf-8", "surrogateescape"))
        for item in git(root, "ls-files", "-z").split(b"\0") if item
    }
    tracked_directories = {
        parent.as_posix()
        for tracked_path in tracked
        for parent in PurePosixPath(tracked_path).parents
        if parent.as_posix() != "."
    }

    def add_gap(item: dict[str, Any]) -> None:
        key = (item["path"], item["kind"])
        if key not in seen_gaps:
            seen_gaps.add(key)
            gaps.append(item)

    for path in paths:
        absolute = root / path
        try:
            metadata = absolute.lstat()
        except FileNotFoundError:
            # A concurrent filesystem change must make verification stale, not disappear silently.
            add_gap(scope_gap(path, "unreadable-entry", "untracked entry disappeared during capture"))
            continue
        if stat.S_ISDIR(metadata.st_mode):
            if (absolute / ".git").exists():
                fingerprint = nested_repo_fingerprint(absolute)
                add_gap(scope_gap(path.rstrip("/"), "nested-git-repository", "nested repository is a review boundary; contents were not recursively included", fingerprint))
                identity += b"\0NESTED\0" + path.encode("utf-8", "surrogateescape") + b"\0" + fingerprint.encode("ascii")
            else:
                add_gap(scope_gap(path.rstrip("/"), "untracked-directory", "untracked directory boundary is not a full-repository audit"))
            continue
        if stat.S_ISLNK(metadata.st_mode):
            # Hashing link text catches changes while avoiding an emitted target or target contents.
            try:
                target_hash = sha256(os.readlink(absolute).encode("utf-8", "surrogateescape"))
            except OSError:
                target_hash = sha256(b"unreadable")
            add_gap(scope_gap(path, "untracked-symlink", "symlink target contents were not followed", target_hash))
            identity += b"\0SYMLINK\0" + path.encode("utf-8", "surrogateescape") + b"\0" + target_hash.encode("ascii")
            continue
        if not stat.S_ISREG(metadata.st_mode):
            add_gap(scope_gap(path, "special-entry", "non-regular filesystem entry was not read"))
            identity += b"\0SPECIAL\0" + path.encode("utf-8", "surrogateescape") + b"\0" + str(stat.S_IFMT(metadata.st_mode)).encode("ascii")
            continue
        for parent in PurePosixPath(path).parents:
            parent_text = parent.as_posix()
            if parent_text == "." or parent_text in seen_directories:
                continue
            seen_directories.add(parent_text)
            parent_absolute = root / parent_text
            if parent_absolute.is_dir() and not (parent_absolute / ".git").exists():
                add_gap(scope_gap(parent_text, "untracked-directory", "untracked directory boundary contains included regular files but is not independently tracked"))
        records.append({"status": "U", "path": path})
        content_hash = hash_file(absolute)
        identity += b"\0UNTRACKED\0" + path.encode("utf-8", "surrogateescape") + b"\0" + content_hash.encode("ascii")
        if metadata.st_size > MAX_SCAN_BYTES:
            add_gap(scope_gap(path, "scan-size-exceeded", f"untracked regular file exceeds deterministic scan limit of {MAX_SCAN_BYTES} bytes", content_hash))
            continue
        text = absolute.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()
        added.extend((path, index, value) for index, value in enumerate(lines, 1))

    # Git does not surface empty directories or every special entry. This bounded
    # filesystem pass checks ignore rules *before* descending, so ignored trees
    # (for example node_modules) are never scanned.
    pending = [root]
    while pending:
        directory = pending.pop()
        for entry in sorted(os.scandir(directory), key=lambda item: item.name):
            if entry.name == ".git":
                continue
            relative = entry.path[len(str(root)) + 1:].replace(os.sep, "/")
            try:
                metadata = entry.stat(follow_symlinks=False)
            except FileNotFoundError:
                continue
            if stat.S_ISDIR(metadata.st_mode):
                ignored = git_result(root, "check-ignore", "-q", "--", relative + "/").returncode == 0
                if ignored:
                    continue
                if (Path(entry.path) / ".git").exists():
                    continue
                if relative not in tracked_directories:
                    # This is the highest untracked boundary. Do not recurse: Git
                    # already enumerated regular files, while descendants would
                    # only duplicate the same coverage limitation.
                    add_gap(scope_gap(relative, "untracked-directory", "empty or otherwise untracked directory boundary is not a full-repository audit"))
                    continue
                pending.append(Path(entry.path))
                continue
            if relative in tracked or relative in paths:
                continue
            ignored = git_result(root, "check-ignore", "-q", "--", relative).returncode == 0
            if ignored:
                continue
            if stat.S_ISLNK(metadata.st_mode):
                try:
                    target_hash = sha256(os.readlink(entry.path).encode("utf-8", "surrogateescape"))
                except OSError:
                    target_hash = sha256(b"unreadable")
                add_gap(scope_gap(relative, "untracked-symlink", "symlink target contents were not followed", target_hash))
                identity += b"\0SYMLINK\0" + relative.encode("utf-8", "surrogateescape") + b"\0" + target_hash.encode("ascii")
            elif not stat.S_ISREG(metadata.st_mode):
                add_gap(scope_gap(relative, "special-entry", "non-regular filesystem entry was not read"))
                identity += b"\0SPECIAL\0" + relative.encode("utf-8", "surrogateescape") + b"\0" + str(stat.S_IFMT(metadata.st_mode)).encode("ascii")
    return records, sorted(gaps, key=lambda item: (item["path"], item["kind"])), added, identity


def snapshot_identity(snapshot: dict[str, Any]) -> dict[str, Any]:
    identity = {
        "schema_version": snapshot["schema_version"],
        "target": snapshot["target"],
        "diff_sha256": snapshot["diff_sha256"],
        "files": snapshot["files"],
        "languages": snapshot["languages"],
        "route_candidates": snapshot["route_candidates"],
        "sensitive_candidates": snapshot["sensitive_candidates"],
        "configured_gates": snapshot["configured_gates"],
        "scope_status": snapshot["scope_status"],
        "scope_gaps": snapshot["scope_gaps"],
    }
    # v1.1 snapshots remain structurally verifiable but cannot authorize v1.2 execution.
    if "repository_binding" in snapshot:
        identity["repository_binding"] = snapshot["repository_binding"]
    return identity


def build_snapshot(root_arg: str, mode: str, base: str | None, head: str | None, use_merge_base: bool) -> dict[str, Any]:
    root = Path(git(Path(root_arg).resolve(), "rev-parse", "--show-toplevel").decode().strip()).resolve()
    current_git_head = git(root, "rev-parse", "HEAD").decode().strip()
    target: dict[str, Any] = {"mode": mode}

    if mode in {"working", "staged"}:
        captured_base = git(root, "rev-parse", f"{base or current_git_head}^{{commit}}").decode().strip()
        cached = mode == "staged"
        diff_args = [*STABLE_DIFF_CONFIG, "diff"]
        if cached:
            diff_args.append("--cached")
        diff_args.extend([*STABLE_DIFF_FLAGS, "--binary", captured_base, "--"])
        status_args = [*STABLE_DIFF_CONFIG, "diff"]
        if cached:
            status_args.append("--cached")
        status_args.extend([*STABLE_DIFF_FLAGS, "--name-status", "-z", captured_base, "--"])
        line_args = [*STABLE_DIFF_CONFIG, "diff"]
        if cached:
            line_args.append("--cached")
        line_args.extend([*STABLE_DIFF_FLAGS, "--unified=0", captured_base, "--"])
        target.update({"base": captured_base, "head": "INDEX" if cached else "WORKTREE"})
    else:
        if not base or not head:
            raise SnapshotError("--base and --head are required for range mode")
        source_base = git(root, "rev-parse", f"{base}^{{commit}}").decode().strip()
        resolved_head = git(root, "rev-parse", f"{head}^{{commit}}").decode().strip()
        comparison_base = git(root, "merge-base", source_base, resolved_head).decode().strip() if use_merge_base else source_base
        spec = f"{comparison_base}..{resolved_head}"
        diff_args = [*STABLE_DIFF_CONFIG, "diff", *STABLE_DIFF_FLAGS, "--binary", spec, "--"]
        status_args = [*STABLE_DIFF_CONFIG, "diff", *STABLE_DIFF_FLAGS, "--name-status", "-z", spec, "--"]
        line_args = [*STABLE_DIFF_CONFIG, "diff", *STABLE_DIFF_FLAGS, "--unified=0", spec, "--"]
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

    scope_gaps: list[dict[str, Any]] = []
    if mode == "working":
        untracked_records, untracked_gaps, untracked_lines, untracked_identity = working_scope(root)
        records.extend(untracked_records)
        scope_gaps.extend(untracked_gaps)
        identity_material += untracked_identity
        added.extend(untracked_lines)
        for path, index, _ in untracked_lines:
            ranges.setdefault(path, {"old": [], "new": []})["new"].append(index)

    records = sorted(records, key=lambda item: (item["path"], item["status"], item.get("old_path", "")))
    files = [file_record(root, record, ranges, mode, target) for record in records]
    working_gitlink_fingerprints: dict[str, str] = {}
    if mode == "working":
        for item in files:
            if "160000" not in {item["old"].get("mode"), item["new"].get("mode")}:
                continue
            candidate = root / item["path"]
            if candidate.is_dir() and (candidate / ".git").exists():
                fingerprint = nested_repo_fingerprint(candidate)
                working_gitlink_fingerprints[item["path"]] = fingerprint
                identity_material += b"\0GITLINK-WORKTREE\0" + item["path"].encode("utf-8", "surrogateescape") + b"\0" + fingerprint.encode("ascii")
    for item in files:
        if "large-file" in item["evidence_exclusions"]:
            scope_gaps.append(scope_gap(
                item["path"], "scan-size-exceeded",
                f"changed file exceeds deterministic scan limit of {MAX_SCAN_BYTES} bytes",
                item["new"]["content_sha256"] or item["old"]["content_sha256"],
            ))
        modes = {item["old"].get("mode"), item["new"].get("mode")}
        if "120000" in modes:
            scope_gaps.append(scope_gap(
                item["path"], "tracked-symlink",
                "tracked symlink target contents were not followed",
                item["new"].get("content_sha256") or item["old"].get("content_sha256"),
            ))
        if "160000" in modes:
            fingerprint = working_gitlink_fingerprints.get(item["path"])
            scope_gaps.append(scope_gap(
                item["path"], "gitlink",
                "gitlink/submodule contents were not recursively reviewed",
                fingerprint,
            ))
    scope_gaps = sorted({(item["path"], item["kind"]): item for item in scope_gaps}.values(), key=lambda item: (item["path"], item["kind"]))
    sensitive = redact_candidates(added)
    routes = route_candidates(files, added, sensitive)
    gates = configured_gates(root, mode, target)
    snapshot: dict[str, Any] = {
        "schema_version": VERSION,
        "repository_root": str(root),
        "repository_binding": repository_binding(root),
        "target": target,
        "git_head_at_capture": current_git_head,
        "diff_sha256": sha256(identity_material),
        "files": files,
        "languages": sorted({item["language"] for item in files if item["language"]}),
        "route_candidates": routes,
        "sensitive_candidates": sensitive,
        "configured_gates": gates,
        "scope_status": "complete" if not scope_gaps else "blocked",
        "scope_gaps": scope_gaps,
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

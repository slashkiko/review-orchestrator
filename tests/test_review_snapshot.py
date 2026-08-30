from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


SKILL = Path(__file__).resolve().parents[1]
SCRIPT = SKILL / "scripts" / "review_snapshot.py"
EMAIL = "13293648+slashkiko@users.noreply.github.com"


def run(*args: str, cwd: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=cwd, text=True, capture_output=True, check=check)


class ReviewSnapshotTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.workspace = Path(self.tempdir.name)
        self.repo = self.workspace / "repo"
        self.repo.mkdir()
        run("git", "init", "-q", cwd=self.repo)
        (self.repo / "app.py").write_text("def answer():\n    return 1\n", encoding="utf-8")
        (self.repo / "context.txt").write_text("first\nsecond\n", encoding="utf-8")
        run("git", "add", "app.py", "context.txt", cwd=self.repo)
        self.commit("initial")
        self.initial = self.rev()
        self.initial_branch = run("git", "branch", "--show-current", cwd=self.repo).stdout.strip()

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def commit(self, message: str) -> None:
        run(
            "git", "-c", "user.name=Review Test", "-c", f"user.email={EMAIL}",
            "-c", "commit.gpgsign=false", "commit", "-qm", message, cwd=self.repo,
        )

    def rev(self) -> str:
        return run("git", "rev-parse", "HEAD", cwd=self.repo).stdout.strip()

    def create_snapshot(self, name: str, *args: str) -> dict:
        output = self.workspace / name
        run("python3", str(SCRIPT), *args, "--output", str(output), cwd=self.repo)
        return json.loads(output.read_text(encoding="utf-8"))

    def working_snapshot(self, name: str = "snapshot.json") -> dict:
        return self.create_snapshot(name, "--mode", "working")

    def test_working_snapshot_includes_untracked_redacts_and_tracks_both_sides(self) -> None:
        (self.repo / "app.py").write_text("async def answer():\n    return 2\n", encoding="utf-8")
        raw_email = "person@corp.example"
        raw_path = "/Users/alice/private/project"
        (self.repo / "debug.log").write_text(f"owner={raw_email}\npath={raw_path}\n", encoding="utf-8")

        snapshot = self.working_snapshot()

        paths = {item["path"] for item in snapshot["files"]}
        self.assertEqual({"app.py", "debug.log"}, paths)
        app = next(item for item in snapshot["files"] if item["path"] == "app.py")
        self.assertEqual([[1, 2]], app["changed_ranges"]["old"])
        self.assertEqual([[1, 2]], app["changed_ranges"]["new"])
        self.assertTrue(snapshot["route_candidates"]["language-idiom"])
        self.assertTrue(snapshot["route_candidates"]["sensitive-data"])
        encoded_candidates = json.dumps(snapshot["sensitive_candidates"])
        self.assertNotIn(raw_email, encoded_candidates)
        self.assertNotIn(raw_path, encoded_candidates)

    def test_working_scope_gaps_cover_untracked_boundaries_without_leaking_targets(self) -> None:
        ordinary = self.repo / "scratch"
        ordinary.mkdir()
        (ordinary / "note.txt").write_text("included regular file\n", encoding="utf-8")
        nested = self.repo / "nested"
        nested.mkdir()
        run("git", "init", "-q", cwd=nested)
        (nested / "child.txt").write_text("nested content\n", encoding="utf-8")
        run("git", "add", "child.txt", cwd=nested)
        run(
            "git", "-c", "user.name=Review Test", "-c", f"user.email={EMAIL}",
            "-c", "commit.gpgsign=false", "commit", "-qm", "nested", cwd=nested,
        )
        os.symlink("/Users/alice/private-target", self.repo / "outside")
        fifo = self.repo / "event.pipe"
        os.mkfifo(fifo)
        try:
            snapshot = self.working_snapshot()
        finally:
            fifo.unlink()
        gaps = {(item["path"], item["kind"]): item for item in snapshot["scope_gaps"]}
        self.assertEqual("blocked", snapshot["scope_status"])
        self.assertIn(("scratch", "untracked-directory"), gaps)
        self.assertIn(("nested", "nested-git-repository"), gaps)
        self.assertIn(("outside", "untracked-symlink"), gaps)
        self.assertIn(("event.pipe", "special-entry"), gaps)
        self.assertNotIn("/Users/alice/private-target", json.dumps(snapshot))
        self.assertIn("scratch/note.txt", {item["path"] for item in snapshot["files"]})
        self.assertNotIn("nested/child.txt", {item["path"] for item in snapshot["files"]})

    def test_nested_repository_state_fingerprint_makes_verify_stale(self) -> None:
        nested = self.repo / "nested"
        nested.mkdir()
        run("git", "init", "-q", cwd=nested)
        (nested / "child.txt").write_text("one\n", encoding="utf-8")
        run("git", "add", "child.txt", cwd=nested)
        run(
            "git", "-c", "user.name=Review Test", "-c", f"user.email={EMAIL}",
            "-c", "commit.gpgsign=false", "commit", "-qm", "nested", cwd=nested,
        )
        output = self.workspace / "nested.json"
        original = self.create_snapshot("nested.json", "--mode", "working")
        fingerprint = next(item["fingerprint"] for item in original["scope_gaps"] if item["kind"] == "nested-git-repository")
        self.assertEqual(64, len(fingerprint))
        (nested / "child.txt").write_text("dirty\n", encoding="utf-8")
        stale = run("python3", str(SCRIPT), "--verify", str(output), cwd=self.repo, check=False)
        self.assertEqual(3, stale.returncode)
        self.assertFalse(json.loads(stale.stdout)["matched"])

    def test_nested_repository_dirty_content_change_makes_verify_stale(self) -> None:
        nested = self.repo / "nested"
        nested.mkdir()
        run("git", "init", "-q", cwd=nested)
        (nested / "child.txt").write_text("base\n", encoding="utf-8")
        run("git", "add", "child.txt", cwd=nested)
        run("git", "-c", "user.name=Review Test", "-c", f"user.email={EMAIL}", "-c", "commit.gpgsign=false", "commit", "-qm", "nested", cwd=nested)
        (nested / "child.txt").write_text("dirty-one\n", encoding="utf-8")
        output = self.workspace / "nested-dirty.json"
        self.create_snapshot("nested-dirty.json", "--mode", "working")
        (nested / "child.txt").write_text("dirty-two\n", encoding="utf-8")
        stale = run("python3", str(SCRIPT), "--verify", str(output), cwd=self.repo, check=False)
        self.assertEqual(3, stale.returncode)

    def test_empty_and_ignored_directories_are_handled_without_descending_ignored_tree(self) -> None:
        (self.repo / "empty").mkdir()
        (self.repo / ".gitignore").write_text("node_modules/\n", encoding="utf-8")
        ignored = self.repo / "node_modules"
        ignored.mkdir()
        (ignored / "unreadable.txt").write_text("ignored\n", encoding="utf-8")
        os.chmod(ignored, 0)
        try:
            snapshot = self.working_snapshot()
        finally:
            os.chmod(ignored, 0o755)
        gaps = {(item["path"], item["kind"]) for item in snapshot["scope_gaps"]}
        self.assertIn(("empty", "untracked-directory"), gaps)
        self.assertNotIn(("node_modules", "untracked-directory"), gaps)

    def test_scope_directory_fallback_skips_tracked_prefixes_and_descendants(self) -> None:
        source = self.repo / "src"
        source.mkdir()
        (source / "tracked.py").write_text("pass\n", encoding="utf-8")
        run("git", "add", "src/tracked.py", cwd=self.repo)
        self.commit("tracked source directory")
        cache = self.repo / "cache" / "a" / "b"
        cache.mkdir(parents=True)
        gaps = {
            item["path"] for item in self.working_snapshot()["scope_gaps"]
            if item["kind"] == "untracked-directory"
        }
        self.assertIn("cache", gaps)
        self.assertNotIn("cache/a", gaps)
        self.assertNotIn("cache/a/b", gaps)
        self.assertNotIn("src", gaps)

    def test_tracked_symlink_and_gitlink_are_scope_gaps_in_all_target_modes(self) -> None:
        link = self.repo / "link"
        os.symlink("first-target", link)
        run("git", "add", "link", cwd=self.repo)
        self.commit("add link")
        first = self.rev()
        link.unlink()
        os.symlink("second-target", link)
        working = self.working_snapshot("link-working.json")
        self.assertIn("tracked-symlink", {item["kind"] for item in working["scope_gaps"]})
        run("git", "add", "link", cwd=self.repo)
        staged = self.create_snapshot("link-staged.json", "--mode", "staged")
        self.assertIn("tracked-symlink", {item["kind"] for item in staged["scope_gaps"]})
        self.commit("change link")
        ranged = self.create_snapshot("link-range.json", "--mode", "range", "--base", first, "--head", self.rev())
        self.assertIn("tracked-symlink", {item["kind"] for item in ranged["scope_gaps"]})

    def test_gitlink_is_a_scope_gap(self) -> None:
        nested = self.repo / "submodule"
        nested.mkdir()
        run("git", "init", "-q", cwd=nested)
        (nested / "file").write_text("submodule\n", encoding="utf-8")
        run("git", "add", "file", cwd=nested)
        run("git", "-c", "user.name=Review Test", "-c", f"user.email={EMAIL}", "-c", "commit.gpgsign=false", "commit", "-qm", "submodule", cwd=nested)
        child_head = run("git", "rev-parse", "HEAD", cwd=nested).stdout.strip()
        run("git", "update-index", "--add", "--cacheinfo", f"160000,{child_head},submodule", cwd=self.repo)
        snapshot = self.create_snapshot("gitlink.json", "--mode", "staged")
        self.assertIn(("submodule", "gitlink"), {(item["path"], item["kind"]) for item in snapshot["scope_gaps"]})

    def test_snapshot_identity_ignores_core_abbrev_configuration(self) -> None:
        (self.repo / "app.py").write_text("def answer():\n    return 2\n", encoding="utf-8")
        run("git", "config", "core.abbrev", "8", cwd=self.repo)
        abbreviated = self.working_snapshot("abbrev-8.json")
        run("git", "config", "core.abbrev", "40", cwd=self.repo)
        full = self.working_snapshot("abbrev-40.json")
        self.assertEqual(abbreviated["snapshot_hash"], full["snapshot_hash"])

    def test_snapshot_identity_ignores_diff_noprefix_configuration(self) -> None:
        (self.repo / "app.py").write_text("def answer():\n    return 3\n", encoding="utf-8")
        run("git", "config", "diff.noprefix", "true", cwd=self.repo)
        no_prefix = self.working_snapshot("noprefix-true.json")
        run("git", "config", "diff.noprefix", "false", cwd=self.repo)
        prefixed = self.working_snapshot("noprefix-false.json")
        self.assertEqual(no_prefix["snapshot_hash"], prefixed["snapshot_hash"])

    def test_unborn_nested_staged_content_and_untracked_symlink_changes_are_stale(self) -> None:
        nested = self.repo / "nested"
        nested.mkdir()
        run("git", "init", "-q", cwd=nested)
        (nested / "staged.txt").write_text("one\n", encoding="utf-8")
        run("git", "add", "staged.txt", cwd=nested)
        os.symlink("first-link", nested / "outside")
        output = self.workspace / "unborn-nested.json"
        self.create_snapshot("unborn-nested.json", "--mode", "working")
        (nested / "staged.txt").write_text("two\n", encoding="utf-8")
        run("git", "add", "staged.txt", cwd=nested)
        (nested / "outside").unlink()
        os.symlink("other-link", nested / "outside")
        stale = run("python3", str(SCRIPT), "--verify", str(output), cwd=self.repo, check=False)
        self.assertEqual(3, stale.returncode)

    def test_nested_oversized_tracked_same_size_change_is_stale(self) -> None:
        nested = self.repo / "nested"
        nested.mkdir()
        run("git", "init", "-q", cwd=nested)
        payload_size = 8 * 1024 * 1024 + 1
        (nested / "large.bin").write_bytes(b"a" * payload_size)
        run("git", "add", "large.bin", cwd=nested)
        run("git", "-c", "user.name=Review Test", "-c", f"user.email={EMAIL}", "-c", "commit.gpgsign=false", "commit", "-qm", "nested", cwd=nested)
        (nested / "large.bin").write_bytes(b"b" * payload_size)
        output = self.workspace / "large-nested.json"
        self.create_snapshot("large-nested.json", "--mode", "working")
        (nested / "large.bin").write_bytes(b"c" * payload_size)
        stale = run("python3", str(SCRIPT), "--verify", str(output), cwd=self.repo, check=False)
        self.assertEqual(3, stale.returncode)

    def test_nested_all_untracked_content_changes_are_stale_beyond_old_limits(self) -> None:
        nested = self.repo / "nested"
        nested.mkdir()
        run("git", "init", "-q", cwd=nested)
        (nested / "base").write_text("base\n", encoding="utf-8")
        run("git", "add", "base", cwd=nested)
        run("git", "-c", "user.name=Review Test", "-c", f"user.email={EMAIL}", "-c", "commit.gpgsign=false", "commit", "-qm", "nested", cwd=nested)
        (nested / "large-untracked.bin").write_bytes(b"a" * (9 * 1024 * 1024))
        for index in range(257):
            (nested / f"many-{index:03}.txt").write_text("a\n", encoding="utf-8")
        output = self.workspace / "nested-untracked.json"
        self.create_snapshot("nested-untracked.json", "--mode", "working")
        (nested / "large-untracked.bin").write_bytes(b"b" * (9 * 1024 * 1024))
        (nested / "many-256.txt").write_text("b\n", encoding="utf-8")
        stale = run("python3", str(SCRIPT), "--verify", str(output), cwd=self.repo, check=False)
        self.assertEqual(3, stale.returncode)

    def test_nested_index_only_change_is_stale_with_unchanged_worktree(self) -> None:
        nested = self.repo / "nested"
        nested.mkdir()
        run("git", "init", "-q", cwd=nested)
        (nested / "tracked.txt").write_text("base\n", encoding="utf-8")
        run("git", "add", "tracked.txt", cwd=nested)
        run("git", "-c", "user.name=Review Test", "-c", f"user.email={EMAIL}", "-c", "commit.gpgsign=false", "commit", "-qm", "nested", cwd=nested)
        (nested / "tracked.txt").write_text("staged-one\n", encoding="utf-8")
        run("git", "add", "tracked.txt", cwd=nested)
        (nested / "tracked.txt").write_text("base\n", encoding="utf-8")
        output = self.workspace / "nested-index.json"
        self.create_snapshot("nested-index.json", "--mode", "working")
        (nested / "tracked.txt").write_text("staged-two\n", encoding="utf-8")
        run("git", "add", "tracked.txt", cwd=nested)
        (nested / "tracked.txt").write_text("base\n", encoding="utf-8")
        stale = run("python3", str(SCRIPT), "--verify", str(output), cwd=self.repo, check=False)
        self.assertEqual(3, stale.returncode)

    def test_dirty_worktree_gitlink_fingerprint_makes_verify_stale(self) -> None:
        nested = self.repo / "submodule"
        nested.mkdir()
        run("git", "init", "-q", cwd=nested)
        (nested / "file").write_text("base\n", encoding="utf-8")
        run("git", "add", "file", cwd=nested)
        run("git", "-c", "user.name=Review Test", "-c", f"user.email={EMAIL}", "-c", "commit.gpgsign=false", "commit", "-qm", "submodule", cwd=nested)
        child_head = run("git", "rev-parse", "HEAD", cwd=nested).stdout.strip()
        run("git", "update-index", "--add", "--cacheinfo", f"160000,{child_head},submodule", cwd=self.repo)
        self.commit("add gitlink")
        (nested / "file").write_text("dirty-one\n", encoding="utf-8")
        output = self.workspace / "dirty-gitlink.json"
        self.create_snapshot("dirty-gitlink.json", "--mode", "working")
        (nested / "file").write_text("dirty-two\n", encoding="utf-8")
        stale = run("python3", str(SCRIPT), "--verify", str(output), cwd=self.repo, check=False)
        self.assertEqual(3, stale.returncode)

    def test_package_and_mise_gate_inventory_uses_target_boundary(self) -> None:
        (self.repo / "package.json").write_text(
            '{"scripts":{"test":"vitest","lint":"eslint .","ignored":"echo nope"}}', encoding="utf-8"
        )
        (self.repo / "mise.toml").write_text("[tasks]\ncheck = 'python -m unittest'\n", encoding="utf-8")
        snapshot = self.working_snapshot()
        inventory = {(item["gate"], item["config"], item.get("script", item.get("task"))) for item in snapshot["configured_gates"]}
        self.assertIn(("test", "package.json", "test"), inventory)
        self.assertIn(("lint", "package.json", "lint"), inventory)
        self.assertIn(("check", "mise.toml", "check"), inventory)
        self.assertTrue(all(item["status"] == "configured-not-run" for item in snapshot["configured_gates"]))

    def test_package_gate_inventory_reads_range_and_staged_targets_not_worktree(self) -> None:
        package = self.repo / "package.json"
        package.write_text('{"scripts":{"test":"node test"}}', encoding="utf-8")
        run("git", "add", "package.json", cwd=self.repo)
        self.commit("add package test")
        head = self.rev()
        package.write_text('{"scripts":{"lint":"eslint ."}}', encoding="utf-8")
        run("git", "add", "package.json", cwd=self.repo)
        staged = self.create_snapshot("package-staged.json", "--mode", "staged")
        ranged = self.create_snapshot("package-range.json", "--mode", "range", "--base", self.initial, "--head", head)
        self.assertIn(("lint", "package.json"), {(item["gate"], item["config"]) for item in staged["configured_gates"]})
        self.assertIn(("test", "package.json"), {(item["gate"], item["config"]) for item in ranged["configured_gates"]})
        self.assertNotIn(("lint", "package.json"), {(item["gate"], item["config"]) for item in ranged["configured_gates"]})

    def test_nested_package_prefix_scripts_and_package_manager_are_inventoried(self) -> None:
        package_dir = self.repo / "packages" / "web"
        package_dir.mkdir(parents=True)
        (package_dir / "package.json").write_text(
            '{"packageManager":"pnpm@9.0.0","scripts":{"test:unit":"vitest","lint:ci":"eslint ."}}', encoding="utf-8"
        )
        (package_dir / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n", encoding="utf-8")
        entries = self.working_snapshot()["configured_gates"]
        by_script = {item.get("script"): item for item in entries if item.get("config") == "packages/web/package.json"}
        self.assertEqual("test", by_script["test:unit"]["gate"])
        self.assertEqual(["pnpm", "run", "test:unit"], by_script["test:unit"]["command_argv"])
        self.assertEqual("lint", by_script["lint:ci"]["gate"])

    def test_nested_package_inherits_root_workspace_package_manager(self) -> None:
        (self.repo / "package.json").write_text('{"packageManager":"pnpm@9.0.0","workspaces":["packages/*"]}', encoding="utf-8")
        (self.repo / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n", encoding="utf-8")
        package_dir = self.repo / "packages" / "worker"
        package_dir.mkdir(parents=True)
        (package_dir / "package.json").write_text('{"scripts":{"test:unit":"vitest"}}', encoding="utf-8")
        entries = self.working_snapshot()["configured_gates"]
        entry = next(item for item in entries if item.get("config") == "packages/worker/package.json")
        self.assertEqual(["pnpm", "run", "test:unit"], entry["command_argv"])

    def test_local_lockfile_wins_over_workspace_ancestor_manager(self) -> None:
        (self.repo / "package.json").write_text('{"packageManager":"pnpm@9.0.0","workspaces":["packages/*","examples/*"]}', encoding="utf-8")
        (self.repo / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n", encoding="utf-8")
        member = self.repo / "packages" / "member"
        member.mkdir(parents=True)
        (member / "package.json").write_text('{"scripts":{"test":"vitest"}}', encoding="utf-8")
        example = self.repo / "examples" / "npm-app"
        example.mkdir(parents=True)
        (example / "package.json").write_text('{"scripts":{"test":"node test"}}', encoding="utf-8")
        (example / "package-lock.json").write_text('{"lockfileVersion":3}', encoding="utf-8")
        entries = self.working_snapshot()["configured_gates"]
        managers = {item["config"]: item["command_argv"][0] for item in entries if item.get("script") == "test"}
        self.assertEqual("pnpm", managers["packages/member/package.json"])
        self.assertEqual("npm", managers["examples/npm-app/package.json"])

    def test_workspace_glob_is_segment_aware_for_star_and_double_star(self) -> None:
        package_dir = self.repo / "packages" / "team" / "app"
        package_dir.mkdir(parents=True)
        (package_dir / "package.json").write_text('{"scripts":{"test":"node test"}}', encoding="utf-8")
        (self.repo / "package.json").write_text('{"packageManager":"pnpm@9","workspaces":["packages/*"]}', encoding="utf-8")
        first = self.working_snapshot("one-segment.json")["configured_gates"]
        first_entry = next(item for item in first if item.get("config") == "packages/team/app/package.json")
        self.assertEqual("npm", first_entry["command_argv"][0])
        (self.repo / "package.json").write_text('{"packageManager":"pnpm@9","workspaces":["packages/**","!packages/excluded/**"]}', encoding="utf-8")
        excluded_dir = self.repo / "packages" / "excluded" / "app"
        excluded_dir.mkdir(parents=True)
        (excluded_dir / "package.json").write_text('{"scripts":{"test":"node test"}}', encoding="utf-8")
        second = self.working_snapshot("many-segment.json")["configured_gates"]
        second_entry = next(item for item in second if item.get("config") == "packages/team/app/package.json")
        excluded_entry = next(item for item in second if item.get("config") == "packages/excluded/app/package.json")
        self.assertEqual("pnpm", second_entry["command_argv"][0])
        self.assertEqual("npm", excluded_entry["command_argv"][0])

    def test_pnpm_workspace_yaml_membership_inherits_root_manager(self) -> None:
        (self.repo / "package.json").write_text('{"packageManager":"pnpm@9.0.0"}', encoding="utf-8")
        (self.repo / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n", encoding="utf-8")
        (self.repo / "pnpm-workspace.yaml").write_text("packages:\n  - 'packages/*'\ncatalog:\n  react: 19\n", encoding="utf-8")
        package_dir = self.repo / "packages" / "worker"
        package_dir.mkdir(parents=True)
        (package_dir / "package.json").write_text('{"scripts":{"test":"vitest"}}', encoding="utf-8")
        entries = self.working_snapshot()["configured_gates"]
        entry = next(item for item in entries if item.get("config") == "packages/worker/package.json")
        self.assertEqual(["pnpm", "run", "test"], entry["command_argv"])

    def test_keyword_only_yaml_is_weak_while_structural_boundaries_are_strong(self) -> None:
        (self.repo / "notes.yaml").write_text("message: async auth rollout\n", encoding="utf-8")
        (self.repo / "auth" / "middleware").mkdir(parents=True)
        (self.repo / "auth" / "middleware" / "check.py").write_text("pass\n", encoding="utf-8")
        (self.repo / "migrations").mkdir()
        (self.repo / "migrations" / "001.sql").write_text("select 1;\n", encoding="utf-8")
        (self.repo / "public" / "schemas").mkdir(parents=True)
        (self.repo / "public" / "schemas" / "api.proto").write_text("syntax = 'proto3';\n", encoding="utf-8")
        (self.repo / "deploy").mkdir()
        (self.repo / "deploy" / "app.yaml").write_text("kind: Deployment\n", encoding="utf-8")
        routes = self.working_snapshot()["route_candidates"]
        weak_yaml = [item for values in routes.values() for item in values if item["path"] == "notes.yaml"]
        self.assertTrue(weak_yaml)
        self.assertTrue(all(item["strength"] == "weak" for item in weak_yaml))
        self.assertTrue(any(item["strength"] == "strong" for item in routes["security"] if item["path"] == "auth/middleware/check.py"))
        self.assertTrue(any(item["strength"] == "strong" for item in routes["data-integrity"] if item["path"] == "migrations/001.sql"))
        self.assertTrue(any(item["strength"] == "strong" for item in routes["compatibility"] if item["path"] == "public/schemas/api.proto"))
        self.assertTrue(any(item["strength"] == "strong" for item in routes["rollout"] if item["path"] == "deploy/app.yaml"))

    def test_snapshot_identity_includes_mode_and_target_metadata(self) -> None:
        (self.repo / "app.py").write_text("def answer():\n    return 4\n", encoding="utf-8")
        run("git", "add", "app.py", cwd=self.repo)
        staged = self.create_snapshot("staged.json", "--mode", "staged")
        working = self.working_snapshot("working.json")
        self.assertEqual(staged["diff_sha256"], working["diff_sha256"])
        self.assertNotEqual(staged["snapshot_hash"], working["snapshot_hash"])
        self.assertEqual("INDEX", staged["target"]["head"])
        self.assertEqual("WORKTREE", working["target"]["head"])

    def test_verify_uses_captured_base_after_head_advances(self) -> None:
        (self.repo / "app.py").write_text("def answer():\n    return 2\n", encoding="utf-8")
        output = self.workspace / "captured.json"
        original = self.create_snapshot("captured.json", "--mode", "working")
        run("git", "add", "app.py", cwd=self.repo)
        self.commit("advance head with reviewed content")
        self.assertNotEqual(original["target"]["base"], self.rev())

        verified = run("python3", str(SCRIPT), "--verify", str(output), cwd=self.repo)
        self.assertEqual(0, verified.returncode)
        payload = json.loads(verified.stdout)
        self.assertTrue(payload["matched"])
        self.assertEqual(original["target"]["base"], payload["captured_base"])

    def test_verify_detects_stale_worktree(self) -> None:
        (self.repo / "app.py").write_text("def answer():\n    return 2\n", encoding="utf-8")
        output = self.workspace / "snapshot.json"
        self.create_snapshot("snapshot.json", "--mode", "working")
        (self.repo / "app.py").write_text("def answer():\n    return 3\n", encoding="utf-8")
        stale = run("python3", str(SCRIPT), "--verify", str(output), cwd=self.repo, check=False)
        self.assertEqual(3, stale.returncode)
        self.assertFalse(json.loads(stale.stdout)["matched"])

    def test_verify_rejects_tampered_snapshot_metadata(self) -> None:
        (self.repo / "app.py").write_text("def answer():\n    return 2\n", encoding="utf-8")
        output = self.workspace / "tampered.json"
        snapshot = self.create_snapshot("tampered.json", "--mode", "working")
        snapshot["files"][0]["new"]["line_count"] = 999
        output.write_text(json.dumps(snapshot), encoding="utf-8")
        completed = run("python3", str(SCRIPT), "--verify", str(output), cwd=self.repo, check=False)
        self.assertEqual(3, completed.returncode)
        payload = json.loads(completed.stdout)
        self.assertFalse(payload["matched"])
        self.assertIn("canonical identity", payload["reason"])

    def test_same_state_has_same_canonical_identity(self) -> None:
        (self.repo / "app.py").write_text("def answer():\n    return 4\n", encoding="utf-8")
        first = self.working_snapshot("first.json")
        second = self.working_snapshot("second.json")
        self.assertEqual(first["snapshot_hash"], second["snapshot_hash"])
        self.assertEqual(first["files"], second["files"])

    def test_range_configured_gates_are_identical_across_different_checkouts(self) -> None:
        checkout = self.workspace / "checkout"
        run("git", "clone", "-q", str(self.repo), str(checkout), cwd=self.workspace)
        (self.repo / ".gitleaks.toml").write_text("[allowlist]\n", encoding="utf-8")

        first = self.create_snapshot(
            "range-first.json", "--repo", str(self.repo), "--mode", "range",
            "--base", self.initial, "--head", self.initial,
        )
        second = self.create_snapshot(
            "range-second.json", "--repo", str(checkout), "--mode", "range",
            "--base", self.initial, "--head", self.initial,
        )

        self.assertEqual([], first["configured_gates"])
        self.assertEqual(first["configured_gates"], second["configured_gates"])
        self.assertNotEqual(first["snapshot_hash"], second["snapshot_hash"])

    def test_configured_gates_use_index_for_staged_and_worktree_for_working(self) -> None:
        config = self.repo / ".gitleaks.toml"
        config.write_text("[allowlist]\n", encoding="utf-8")
        run("git", "add", ".gitleaks.toml", cwd=self.repo)
        config.unlink()

        staged = self.create_snapshot("gate-staged.json", "--mode", "staged")
        working = self.create_snapshot("gate-working.json", "--mode", "working")

        self.assertEqual(1, len(staged["configured_gates"]))
        self.assertEqual(".gitleaks.toml", staged["configured_gates"][0]["config"])
        self.assertEqual("secret-scan", staged["configured_gates"][0]["gate"])
        self.assertEqual("configured-not-run", staged["configured_gates"][0]["status"])
        self.assertRegex(staged["configured_gates"][0]["gate_id"], r"^[0-9a-f]{64}$")
        self.assertEqual([], working["configured_gates"])

    def test_range_hashes_committed_head_not_current_worktree(self) -> None:
        committed = "def answer():\n    return 2\n"
        (self.repo / "app.py").write_text(committed, encoding="utf-8")
        run("git", "add", "app.py", cwd=self.repo)
        self.commit("second")
        head = self.rev()
        (self.repo / "app.py").write_text("def answer():\n    return 99\n", encoding="utf-8")

        snapshot = self.create_snapshot(
            "range.json", "--mode", "range", "--base", self.initial, "--head", head,
        )
        app = next(item for item in snapshot["files"] if item["path"] == "app.py")
        self.assertEqual(hashlib.sha256(committed.encode()).hexdigest(), app["new"]["content_sha256"])

    def test_staged_hashes_index_not_unstaged_worktree(self) -> None:
        staged_content = "def answer():\n    return 5\n"
        (self.repo / "app.py").write_text(staged_content, encoding="utf-8")
        run("git", "add", "app.py", cwd=self.repo)
        (self.repo / "app.py").write_text("def answer():\n    return 6\nextra = True\n", encoding="utf-8")

        snapshot = self.create_snapshot("staged.json", "--mode", "staged")
        app = next(item for item in snapshot["files"] if item["path"] == "app.py")
        self.assertEqual(hashlib.sha256(staged_content.encode()).hexdigest(), app["new"]["content_sha256"])
        self.assertEqual(2, app["new"]["line_count"])

    def test_pr_merge_base_excludes_base_only_commits_on_divergent_branch(self) -> None:
        run("git", "switch", "-c", "feature", cwd=self.repo)
        (self.repo / "app.py").write_text("def answer():\n    return 7\n", encoding="utf-8")
        run("git", "add", "app.py", cwd=self.repo)
        self.commit("feature change")
        feature_head = self.rev()

        run("git", "switch", self.initial_branch, cwd=self.repo)
        (self.repo / "base-only.txt").write_text("base only\n", encoding="utf-8")
        run("git", "add", "base-only.txt", cwd=self.repo)
        self.commit("base branch change")
        base_tip = self.rev()

        snapshot = self.create_snapshot(
            "pr.json", "--mode", "range", "--base", base_tip, "--head", feature_head, "--merge-base",
        )
        self.assertEqual(self.initial, snapshot["target"]["base"])
        self.assertEqual(base_tip, snapshot["target"]["source_base"])
        self.assertEqual({"app.py"}, {item["path"] for item in snapshot["files"]})

    def test_deletion_binary_mode_and_rename_have_explicit_change_metadata(self) -> None:
        (self.repo / "binary.bin").write_bytes(b"one\0two")
        (self.repo / ".gitattributes").write_text("attr.dat binary\n", encoding="utf-8")
        (self.repo / "attr.dat").write_text("plain one\n", encoding="utf-8")
        (self.repo / "script.sh").write_text("#!/bin/sh\necho ok\n", encoding="utf-8")
        run("git", "add", ".gitattributes", "attr.dat", "binary.bin", "script.sh", cwd=self.repo)
        self.commit("add non-line fixtures")

        (self.repo / "context.txt").unlink()
        (self.repo / "binary.bin").write_bytes(b"three\0four")
        (self.repo / "attr.dat").write_text("plain two\n", encoding="utf-8")
        os.chmod(self.repo / "script.sh", 0o755)
        run("git", "mv", "app.py", "renamed.py", cwd=self.repo)
        snapshot = self.working_snapshot()
        by_path = {item["path"]: item for item in snapshot["files"]}

        self.assertEqual([[1, 2]], by_path["context.txt"]["changed_ranges"]["old"])
        self.assertEqual([], by_path["context.txt"]["changed_ranges"]["new"])
        self.assertIn("deletion", by_path["context.txt"]["non_line_changes"])
        self.assertIn("binary", by_path["binary.bin"]["non_line_changes"])
        self.assertEqual([], by_path["binary.bin"]["changed_ranges"]["new"])
        self.assertIn("binary", by_path["attr.dat"]["non_line_changes"])
        self.assertEqual([], by_path["attr.dat"]["changed_ranges"]["new"])
        self.assertIn("mode", by_path["script.sh"]["non_line_changes"])
        self.assertIn("rename", by_path["renamed.py"]["non_line_changes"])
        self.assertEqual("app.py", by_path["renamed.py"]["old_path"])


if __name__ == "__main__":
    unittest.main()

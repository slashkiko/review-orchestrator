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
        self.assertEqual(first["snapshot_hash"], second["snapshot_hash"])

    def test_configured_gates_use_index_for_staged_and_worktree_for_working(self) -> None:
        config = self.repo / ".gitleaks.toml"
        config.write_text("[allowlist]\n", encoding="utf-8")
        run("git", "add", ".gitleaks.toml", cwd=self.repo)
        config.unlink()

        staged = self.create_snapshot("gate-staged.json", "--mode", "staged")
        working = self.create_snapshot("gate-working.json", "--mode", "working")

        self.assertEqual(
            [{"config": ".gitleaks.toml", "gate": "secret-scan", "status": "configured-not-run"}],
            staged["configured_gates"],
        )
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

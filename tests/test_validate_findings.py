from __future__ import annotations

import copy
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


SKILL = Path(__file__).resolve().parents[1]
SNAPSHOT_SCRIPT = SKILL / "scripts" / "review_snapshot.py"
VALIDATE_SCRIPT = SKILL / "scripts" / "validate_findings.py"
EMAIL = "13293648+slashkiko@users.noreply.github.com"


def run(*args: str, cwd: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=cwd, text=True, capture_output=True, check=check)


class ValidateFindingsTest(unittest.TestCase):
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
        (self.repo / "app.py").write_text("def answer():\n    return 2\n", encoding="utf-8")
        self.snapshot = self.create_snapshot("working.json", "--mode", "working")
        self.finding = self.make_finding(self.snapshot)

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
        run("python3", str(SNAPSHOT_SCRIPT), *args, "--output", str(output), cwd=self.repo)
        return json.loads(output.read_text(encoding="utf-8"))

    def make_finding(self, snapshot: dict, reviewer: str = "semantic-core") -> dict:
        return {
            "id": "F-1",
            "reviewer": reviewer,
            "snapshot_hash": snapshot["snapshot_hash"],
            "title": "Preserve the changed value",
            "claim": "The new value is discarded before it is observed.",
            "impact": "Callers continue to receive the old value.",
            "severity": "medium",
            "confidence": "high",
            "introduced_by_diff": True,
            "location": {
                "path": "app.py", "side": "new", "start_line": 2,
                "end_line": 2, "change_kind": None,
            },
            "evidence": [
                {"path": "app.py", "side": "new", "line": 2, "reason": "The changed return is observable here."},
            ],
            "validation": {"method": "static", "details": "Traced the changed return to its caller."},
        }

    def base_result(self, snapshot: dict | None = None, reviewer: str = "semantic-core") -> dict:
        snapshot = snapshot or self.snapshot
        finding = self.make_finding(snapshot, reviewer)
        return {
            "reviewer": reviewer,
            "snapshot_hash": snapshot["snapshot_hash"],
            "status": "completed",
            "summary": "One supported issue.",
            "findings": [finding],
            "unverifiable": [],
            "coverage": {"examined": ["app.py"], "not_examined": [], "commands": []},
        }

    def sensitive_snapshot(self) -> dict:
        (self.repo / "secrets.log").write_text(
            "api_key=abcdefgh12345678\nAuthorization: Bearer zyxwvutsrqpon9876\n",
            encoding="utf-8",
        )
        return self.create_snapshot("candidate-specific.json", "--mode", "working")

    def free_text_variants(self, snapshot: dict, value: str, include_paths: bool = False) -> list[dict]:
        variants: list[dict] = []
        result = self.base_result(snapshot)
        result["summary"] = value
        variants.append(result)
        for field in ("title", "claim", "impact", "id"):
            result = self.base_result(snapshot)
            result["findings"][0][field] = value
            variants.append(result)
        result = self.base_result(snapshot)
        result["findings"][0]["evidence"][0]["reason"] = value
        variants.append(result)
        result = self.base_result(snapshot)
        result["findings"][0]["validation"]["details"] = value
        variants.append(result)
        if include_paths:
            result = self.base_result(snapshot)
            result["findings"][0]["location"]["path"] = value
            variants.append(result)
            result = self.base_result(snapshot)
            result["findings"][0]["evidence"][0]["path"] = value
            variants.append(result)
        result = self.base_result(snapshot)
        result["coverage"]["examined"] = [value]
        variants.append(result)
        for field in ("command", "scope", "summary"):
            result = self.base_result(snapshot)
            command = {"command": "check", "scope": "diff", "result": "passed", "summary": "Completed."}
            command[field] = value
            result["coverage"]["commands"] = [command]
            variants.append(result)
        for field in ("id", "claim", "missing_evidence", "why_it_matters", "retrieval"):
            partial = {
                "reviewer": "semantic-core", "snapshot_hash": snapshot["snapshot_hash"],
                "status": "partial", "summary": "Partial review.", "findings": [],
                "unverifiable": [{
                    "id": "U-1", "claim": "A claim is unknown.",
                    "missing_evidence": "The schema was unavailable.",
                    "why_it_matters": "It affects validation.", "retrieval": "Use read-only metadata.",
                }],
                "coverage": {
                    "examined": ["app.py"],
                    "not_examined": [{"area": "external", "reason": "No access."}],
                    "commands": [],
                },
            }
            partial["unverifiable"][0][field] = value
            variants.append(partial)
        for field in ("area", "reason"):
            partial = {
                "reviewer": "semantic-core", "snapshot_hash": snapshot["snapshot_hash"],
                "status": "partial", "summary": "Partial review.", "findings": [],
                "unverifiable": [{
                    "id": "U-1", "claim": "A claim is unknown.",
                    "missing_evidence": "The schema was unavailable.",
                    "why_it_matters": "It affects validation.", "retrieval": "Use read-only metadata.",
                }],
                "coverage": {
                    "examined": ["app.py"],
                    "not_examined": [{"area": "external", "reason": "No access."}],
                    "commands": [],
                },
            }
            partial["coverage"]["not_examined"][0][field] = value
            variants.append(partial)
        return variants

    def invoke(self, result: dict, snapshot: dict | None = None) -> subprocess.CompletedProcess[str]:
        snapshot = snapshot or self.snapshot
        snapshot_path = self.workspace / "input-snapshot.json"
        result_path = self.workspace / "result.json"
        snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")
        result_path.write_text(json.dumps(result), encoding="utf-8")
        return subprocess.run(
            ["python3", str(VALIDATE_SCRIPT), "--snapshot", str(snapshot_path), "--input", str(result_path)],
            text=True, capture_output=True, check=False,
        )

    def assert_valid(self, result: dict, snapshot: dict | None = None) -> dict:
        completed = self.invoke(result, snapshot)
        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertTrue(payload["valid"])
        return payload

    def assert_invalid(self, result: dict, snapshot: dict | None = None) -> dict:
        completed = self.invoke(result, snapshot)
        self.assertEqual(1, completed.returncode, completed.stdout + completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertFalse(payload["valid"])
        self.assertNotIn("result", payload)
        return payload

    def test_valid_result_and_deduplicates_ignoring_local_id(self) -> None:
        result = self.base_result()
        duplicate = copy.deepcopy(result["findings"][0])
        duplicate["id"] = "F-2"
        result["findings"].append(duplicate)
        output = self.assert_valid(result)
        self.assertEqual(["F-2"], output["duplicate_ids"])
        self.assertEqual(1, len(output["result"]["findings"]))

    def test_rejects_stale_hash_and_non_changed_location(self) -> None:
        result = self.base_result()
        result["snapshot_hash"] = "b" * 64
        result["findings"][0]["location"]["path"] = "other.py"
        output = self.assert_invalid(result)
        self.assertTrue(any("snapshot_hash" in error for error in output["errors"]))
        self.assertTrue(any("not in the snapshot" in error for error in output["errors"]))

    def test_staged_evidence_uses_index_and_base_not_different_worktree(self) -> None:
        run("git", "add", "app.py", cwd=self.repo)
        staged = self.create_snapshot("staged.json", "--mode", "staged")
        (self.repo / "app.py").write_text("\n".join(f"line {index}" for index in range(1, 11)) + "\n", encoding="utf-8")
        (self.repo / "context.txt").unlink()
        result = self.base_result(staged)
        result["findings"][0]["evidence"].append(
            {"path": "context.txt", "side": "new", "line": 2, "reason": "Unchanged context exists in the captured index."}
        )
        self.assert_valid(result, staged)

        result["findings"][0]["evidence"][0]["line"] = 3
        output = self.assert_invalid(result, staged)
        self.assertTrue(any("immutable new-side line count" in error for error in output["errors"]))

    def test_range_evidence_uses_head_commit_not_different_worktree(self) -> None:
        run("git", "add", "app.py", cwd=self.repo)
        self.commit("head change")
        head = self.rev()
        snapshot = self.create_snapshot("range.json", "--mode", "range", "--base", self.initial, "--head", head)
        (self.repo / "app.py").write_text("\n".join(f"line {index}" for index in range(1, 11)) + "\n", encoding="utf-8")
        (self.repo / "context.txt").unlink()
        result = self.base_result(snapshot)
        result["findings"][0]["evidence"].append(
            {"path": "context.txt", "side": "new", "line": 2, "reason": "Context exists in the immutable head commit."}
        )
        self.assert_valid(result, snapshot)

    def test_accepts_old_side_deletion_and_non_line_mode_locations(self) -> None:
        (self.repo / "context.txt").unlink()
        deletion = self.create_snapshot("deletion.json", "--mode", "working")
        result = self.base_result(deletion)
        result["findings"][0]["location"] = {
            "path": "context.txt", "side": "old", "start_line": 1,
            "end_line": 2, "change_kind": None,
        }
        result["findings"][0]["evidence"] = [
            {"path": "context.txt", "side": "old", "line": 2, "reason": "The deleted behavior was present here."}
        ]
        result["coverage"]["examined"] = ["context.txt"]
        self.assert_valid(result, deletion)

        os.chmod(self.repo / "app.py", 0o755)
        mode_snapshot = self.create_snapshot("mode.json", "--mode", "working")
        mode_result = self.base_result(mode_snapshot)
        mode_result["findings"][0]["location"] = {
            "path": "app.py", "side": "none", "start_line": None,
            "end_line": None, "change_kind": "mode",
        }
        self.assert_valid(mode_result, mode_snapshot)

    def test_enforces_unverifiable_coverage_and_command_schema(self) -> None:
        malformed = self.base_result()
        malformed["extra"] = "unexpected"
        malformed["unverifiable"] = ["missing context"]
        malformed["coverage"]["commands"] = [{"command": "tests", "result": "unknown"}]
        output = self.assert_invalid(malformed)
        self.assertTrue(any("unverifiable[0]" in error for error in output["errors"]))
        self.assertTrue(any("coverage.commands[0]" in error for error in output["errors"]))

    def test_rejects_tampered_snapshot_identity(self) -> None:
        tampered = copy.deepcopy(self.snapshot)
        tampered["files"][0]["new"]["line_count"] = 999
        output = self.assert_invalid(self.base_result(), tampered)
        self.assertTrue(any("snapshot canonical identity" in error for error in output["errors"]))

    def test_partial_and_failed_status_consistency(self) -> None:
        partial = self.base_result()
        partial.update({
            "status": "partial",
            "findings": [],
            "unverifiable": [{
                "id": "U-1", "claim": "A contract could not be checked.",
                "missing_evidence": "The external schema was unavailable.",
                "why_it_matters": "The changed field may be rejected.",
                "retrieval": "Read the versioned schema with existing read-only access.",
            }],
            "coverage": {
                "examined": ["app.py"],
                "not_examined": [{"area": "external schema", "reason": "No read access was available."}],
                "commands": [{"command": "schema check", "scope": "external schema", "result": "not_run", "summary": "No configured command."}],
            },
        })
        self.assert_valid(partial)
        broken_partial = copy.deepcopy(partial)
        broken_partial["coverage"]["not_examined"] = []
        self.assert_invalid(broken_partial)

        failed = {
            "reviewer": "semantic-core",
            "snapshot_hash": self.snapshot["snapshot_hash"],
            "status": "failed",
            "summary": "The reviewer task failed before evaluation.",
            "findings": [],
            "unverifiable": [],
            "coverage": {
                "examined": [],
                "not_examined": [{"area": "semantic review", "reason": "The reviewer task timed out."}],
                "commands": [],
            },
        }
        self.assert_valid(failed)
        broken_failed = copy.deepcopy(failed)
        broken_failed["coverage"]["examined"] = ["app.py"]
        self.assert_invalid(broken_failed)

    def test_rejects_exact_candidate_values_and_bare_tokens_without_republishing_them(self) -> None:
        snapshot = self.sensitive_snapshot()
        raw = "abcdefgh12345678"
        for variant in self.free_text_variants(snapshot, raw, include_paths=True):
            completed = self.invoke(variant, snapshot)
            self.assertEqual(1, completed.returncode)
            self.assertNotIn(raw, completed.stdout)
            self.assertNotIn("\"result\"", completed.stdout)

        bearer = self.base_result(snapshot)
        bearer["summary"] = "zyxwvutsrqpon9876"
        completed = self.invoke(bearer, snapshot)
        self.assertEqual(1, completed.returncode)
        self.assertNotIn("zyxwvutsrqpon9876", completed.stdout)

        unexpected_key = self.base_result(snapshot)
        unexpected_key[raw] = "unexpected"
        completed = self.invoke(unexpected_key, snapshot)
        self.assertEqual(1, completed.returncode)
        self.assertNotIn(raw, completed.stdout)

    def test_all_free_text_fields_allow_unrelated_public_urls_and_dummy_emails(self) -> None:
        snapshot = self.sensitive_snapshot()
        for unrelated in ("https://github.com/public/example", "user@example.com"):
            for variant in self.free_text_variants(snapshot, unrelated):
                self.assert_valid(variant, snapshot)

    def test_candidate_values_are_resolved_from_staged_index_not_worktree(self) -> None:
        staged_secret = "stagedsecret12345"
        worktree_secret = "worktreesecret12345"
        (self.repo / "secrets.log").write_text(f"api_key={staged_secret}\n", encoding="utf-8")
        run("git", "add", "app.py", "secrets.log", cwd=self.repo)
        snapshot = self.create_snapshot("staged-sensitive.json", "--mode", "staged")
        (self.repo / "secrets.log").write_text(f"api_key={worktree_secret}\n", encoding="utf-8")

        leaking = self.base_result(snapshot)
        leaking["summary"] = staged_secret
        completed = self.invoke(leaking, snapshot)
        self.assertEqual(1, completed.returncode)
        self.assertNotIn(staged_secret, completed.stdout)

        unrelated = self.base_result(snapshot)
        unrelated["summary"] = worktree_secret
        self.assert_valid(unrelated, snapshot)

    def test_sensitive_finding_requires_snapshot_candidate_metadata(self) -> None:
        raw = "person@corp.example"
        (self.repo / "debug.log").write_text(f"owner={raw}\n", encoding="utf-8")
        snapshot = self.create_snapshot("sensitive.json", "--mode", "working")
        candidate = next(item for item in snapshot["sensitive_candidates"] if item["type"] == "email")
        finding = self.make_finding(snapshot, "sensitive-data")
        finding.update({
            "location": {
                "path": candidate["path"], "side": "new", "start_line": candidate["line"],
                "end_line": candidate["line"], "change_kind": None,
            },
            "evidence": [{
                "path": candidate["path"], "side": "new", "line": candidate["line"],
                "reason": "The redacted candidate crosses a log boundary.",
            }],
            "sensitive_candidate": {
                "candidate_id": candidate["candidate_id"],
                "type": candidate["type"],
                "fingerprint": candidate["fingerprint"],
            },
        })
        result = {
            "reviewer": "sensitive-data", "snapshot_hash": snapshot["snapshot_hash"],
            "status": "completed", "summary": "One redacted candidate is exposed.",
            "findings": [finding], "unverifiable": [],
            "coverage": {"examined": ["debug.log"], "not_examined": [], "commands": []},
        }
        output = self.assert_valid(result, snapshot)
        self.assertNotIn(raw, json.dumps(output))

        missing = copy.deepcopy(result)
        del missing["findings"][0]["sensitive_candidate"]
        self.assert_invalid(missing, snapshot)
        non_line = copy.deepcopy(result)
        non_line["findings"][0]["location"] = {
            "path": candidate["path"], "side": "none", "start_line": None,
            "end_line": None, "change_kind": "addition",
        }
        output = self.assert_invalid(non_line, snapshot)
        self.assertTrue(any("new-side line" in error for error in output["errors"]))
        leaking = copy.deepcopy(result)
        leaking["findings"][0]["claim"] = raw
        completed = self.invoke(leaking, snapshot)
        self.assertEqual(1, completed.returncode)
        self.assertNotIn(raw, completed.stdout)


if __name__ == "__main__":
    unittest.main()

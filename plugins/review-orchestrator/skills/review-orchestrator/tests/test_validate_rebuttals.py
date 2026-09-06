from __future__ import annotations

import copy
import json
import subprocess
import tempfile
import unittest
from pathlib import Path


SKILL = Path(__file__).resolve().parents[1]
SNAPSHOT_SCRIPT = SKILL / "scripts" / "review_snapshot.py"
VALIDATE_SCRIPT = SKILL / "scripts" / "validate_rebuttals.py"
EMAIL = "13293648+slashkiko@users.noreply.github.com"


def run(*args: str, cwd: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=cwd, text=True, capture_output=True, check=check)


class ValidateRebuttalsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.workspace = Path(self.tempdir.name)
        self.repo = self.workspace / "repo"
        self.repo.mkdir()
        run("git", "init", "-q", cwd=self.repo)
        (self.repo / "app.py").write_text("def answer():\n    return 1\n", encoding="utf-8")
        run("git", "add", "app.py", cwd=self.repo)
        run(
            "git", "-c", "user.name=Review Test", "-c", f"user.email={EMAIL}",
            "-c", "commit.gpgsign=false", "commit", "-qm", "initial", cwd=self.repo,
        )
        (self.repo / "app.py").write_text("def answer():\n    return 2\n", encoding="utf-8")
        output = self.workspace / "working.json"
        run("python3", str(SNAPSHOT_SCRIPT), "--mode", "working", "--output", str(output), cwd=self.repo)
        self.snapshot_path = output
        self.snapshot = json.loads(output.read_text(encoding="utf-8"))

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def upheld(self, finding_id: str = "F-1", reviewer: str = "semantic-core") -> dict:
        return {
            "rebuttal_of": {"reviewer": reviewer, "finding_id": finding_id},
            "snapshot_hash": self.snapshot["snapshot_hash"],
            "verdict": "upheld",
            "rationale": "The cited line carries the changed return the claim depends on.",
            "narrowed_condition": None,
            "missing_evidence": None,
            "counter_evidence": [],
        }

    def refuted(self) -> dict:
        rebuttal = self.upheld()
        rebuttal["verdict"] = "refuted"
        rebuttal["rationale"] = "The precondition is unreachable; no caller observes the value."
        rebuttal["counter_evidence"] = [
            {"path": "app.py", "side": "new", "line": 1, "reason": "The function has no caller in the target."},
        ]
        return rebuttal

    def invoke(self, document: object) -> subprocess.CompletedProcess[str]:
        source = self.workspace / "rebuttals.json"
        source.write_text(json.dumps(document), encoding="utf-8")
        return run(
            "python3", str(VALIDATE_SCRIPT), "--snapshot", str(self.snapshot_path),
            "--input", str(source), cwd=self.repo, check=False,
        )

    def test_accepts_upheld_and_refuted_verdicts_and_counts_them(self) -> None:
        completed = self.invoke([self.upheld(), self.refuted() | {"rebuttal_of": {"reviewer": "simplify", "finding_id": "F-2"}}])
        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
        output = json.loads(completed.stdout)
        self.assertTrue(output["valid"])
        self.assertEqual(2, output["rebutted"])
        self.assertEqual(1, output["verdicts"]["upheld"])
        self.assertEqual(1, output["verdicts"]["refuted"])

    def test_rejects_refuted_verdict_without_counter_evidence(self) -> None:
        rebuttal = self.refuted()
        rebuttal["counter_evidence"] = []
        completed = self.invoke([rebuttal])
        self.assertEqual(1, completed.returncode)
        self.assertTrue(any("counter_evidence" in error for error in json.loads(completed.stdout)["errors"]))

    def test_rejects_counter_evidence_outside_the_immutable_target(self) -> None:
        rebuttal = self.refuted()
        rebuttal["counter_evidence"][0]["path"] = "absent.py"
        completed = self.invoke([rebuttal])
        self.assertEqual(1, completed.returncode)
        self.assertTrue(any("does not exist" in error for error in json.loads(completed.stdout)["errors"]))

    def test_rejects_counter_evidence_on_an_upheld_verdict(self) -> None:
        rebuttal = self.upheld()
        rebuttal["counter_evidence"] = [
            {"path": "app.py", "side": "new", "line": 2, "reason": "Unused."},
        ]
        completed = self.invoke([rebuttal])
        self.assertEqual(1, completed.returncode)
        self.assertTrue(any("must be empty" in error for error in json.loads(completed.stdout)["errors"]))

    def test_requires_the_field_that_makes_each_verdict_checkable(self) -> None:
        weakened = self.refuted()
        weakened["verdict"] = "weakened"
        completed = self.invoke([weakened])
        self.assertEqual(1, completed.returncode)
        self.assertTrue(any("narrowed_condition" in error for error in json.loads(completed.stdout)["errors"]))

        unverifiable = self.upheld()
        unverifiable["verdict"] = "unverifiable"
        completed = self.invoke([unverifiable])
        self.assertEqual(1, completed.returncode)
        self.assertTrue(any("missing_evidence" in error for error in json.loads(completed.stdout)["errors"]))

    def test_rejects_stale_hash_unknown_reviewer_and_repeated_finding(self) -> None:
        stale = self.upheld()
        stale["snapshot_hash"] = "0" * 64
        completed = self.invoke([stale])
        self.assertEqual(1, completed.returncode)
        self.assertTrue(any("snapshot_hash" in error for error in json.loads(completed.stdout)["errors"]))

        unknown = self.upheld()
        unknown["rebuttal_of"]["reviewer"] = "not-a-reviewer"
        completed = self.invoke([unknown])
        self.assertEqual(1, completed.returncode)
        self.assertTrue(any("reviewer is invalid" in error for error in json.loads(completed.stdout)["errors"]))

        completed = self.invoke([self.upheld(), copy.deepcopy(self.upheld())])
        self.assertEqual(1, completed.returncode)
        self.assertTrue(any("already rebutted" in error for error in json.loads(completed.stdout)["errors"]))


if __name__ == "__main__":
    unittest.main()

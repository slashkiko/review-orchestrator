from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "validate_execution_ledger.py"


class ExecutionLedgerTest(unittest.TestCase):
    def invoke(self, ledger: dict) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "ledger.json"
            source.write_text(json.dumps(ledger), encoding="utf-8")
            return subprocess.run(["python3", str(SCRIPT), "--input", str(source)], text=True, capture_output=True, check=False)

    def ledger(self) -> dict:
        return {
            "schema_version": 1,
            "snapshot_hash": "a" * 64,
            "selected_roles": ["semantic-core", "simplify", "test-effectiveness", "security"],
            "entries": [
                {
                    "role": "semantic-core",
                    "requested": {"tier": "balanced", "model": "model", "effort": "medium"},
                    "actual": {"exposure": "reported", "model": "model", "effort": "medium"},
                    "host_task_id": "task-1", "attempt": 1, "retry_or_escalation_reason": None,
                    "terminal_status": "completed", "timeout_seconds": 900, "schema_validation": "passed",
                },
                {
                    "role": "simplify",
                    "requested": {"tier": "balanced", "model": "model", "effort": "medium"},
                    "actual": {"exposure": "reported", "model": "model", "effort": "medium"},
                    "host_task_id": "task-2", "attempt": 1, "retry_or_escalation_reason": None,
                    "terminal_status": "completed", "timeout_seconds": 900, "schema_validation": "passed",
                },
                {
                    "role": "test-effectiveness",
                    "requested": {"tier": "balanced", "model": "model", "effort": "medium"},
                    "actual": {"exposure": "reported", "model": "model", "effort": "medium"},
                    "host_task_id": "task-3", "attempt": 1, "retry_or_escalation_reason": None,
                    "terminal_status": "completed", "timeout_seconds": 900, "schema_validation": "passed",
                },
                {
                    "role": "security",
                    "requested": {"tier": "deep", "model": None, "effort": "high"},
                    "actual": {"exposure": "not_exposed", "model": None, "effort": None},
                    "host_task_id": "task-4", "attempt": 1, "retry_or_escalation_reason": None,
                    "terminal_status": "timed_out", "timeout_seconds": 900, "schema_validation": "not_run",
                },
            ],
        }

    def test_valid_ledger_and_not_exposed_actual_configuration(self) -> None:
        completed = self.invoke(self.ledger())
        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertEqual("complete", json.loads(completed.stdout)["coverage"])

    def test_missing_selected_role_is_incomplete(self) -> None:
        ledger = self.ledger()
        ledger["entries"].pop()
        completed = self.invoke(ledger)
        self.assertEqual(1, completed.returncode)
        output = json.loads(completed.stdout)
        self.assertEqual("incomplete", output["coverage"])
        self.assertEqual(["security"], output["missing_roles"])

    def test_rejects_invalid_required_enum(self) -> None:
        ledger = self.ledger()
        ledger["entries"][0]["terminal_status"] = "running"
        completed = self.invoke(ledger)
        self.assertEqual(1, completed.returncode)
        self.assertTrue(any("terminal_status" in error for error in json.loads(completed.stdout)["errors"]))

    def test_requires_core_roles_and_contiguous_unique_attempts(self) -> None:
        ledger = self.ledger()
        ledger["selected_roles"].remove("simplify")
        ledger["entries"].append({**ledger["entries"][0], "host_task_id": "task-1", "attempt": 3})
        completed = self.invoke(ledger)
        self.assertEqual(1, completed.returncode)
        errors = json.loads(completed.stdout)["errors"]
        self.assertTrue(any("core role" in error for error in errors))
        self.assertTrue(any("host_task_id" in error for error in errors))
        self.assertTrue(any("attempts" in error for error in errors))

    def test_rejects_empty_selection_invalid_hash_and_nonterminal_schema_result(self) -> None:
        ledger = self.ledger()
        ledger["selected_roles"] = []
        ledger["snapshot_hash"] = "not-a-hash"
        ledger["entries"][3]["schema_validation"] = "passed"
        completed = self.invoke(ledger)
        self.assertEqual(1, completed.returncode)
        errors = json.loads(completed.stdout)["errors"]
        self.assertTrue(any("snapshot_hash" in error for error in errors))
        self.assertTrue(any("core role" in error for error in errors))
        self.assertTrue(any("non-completed" in error for error in errors))

    def test_rejects_unselected_role_missing_reported_model_and_unexplained_retry(self) -> None:
        ledger = self.ledger()
        ledger["entries"][0]["actual"]["model"] = None
        retry = {**ledger["entries"][0], "host_task_id": "retry-task", "attempt": 2, "retry_or_escalation_reason": None}
        ledger["entries"].append(retry)
        ledger["entries"].append({**ledger["entries"][0], "role": "validator", "host_task_id": "validator-task"})
        completed = self.invoke(ledger)
        self.assertEqual(1, completed.returncode)
        errors = json.loads(completed.stdout)["errors"]
        self.assertTrue(any("actual.model" in error for error in errors))
        self.assertTrue(any("attempt >1" in error for error in errors))
        self.assertTrue(any("unselected role" in error for error in errors))


if __name__ == "__main__":
    unittest.main()

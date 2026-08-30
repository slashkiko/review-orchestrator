from __future__ import annotations

import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "route_selection.py"
SPEC = importlib.util.spec_from_file_location("route_selection", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class RouteSelectionTest(unittest.TestCase):
    def test_classifier_failure_adds_only_weak_high_impact_without_capping_strong_routes(self) -> None:
        candidates = {
            "security": [{"strength": "weak"}], "docs-dx": [{"strength": "weak"}],
            "rollout": [{"strength": "strong"}], "dependency": [{"strength": "strong"}],
        }
        selection = MODULE.select_routes(candidates, None)
        self.assertTrue({"semantic-core", "simplify", "test-effectiveness", "security", "rollout", "dependency"}.issubset(selection["selected"]))
        self.assertEqual({"docs-dx": "routing_classifier_failed"}, selection["not_evaluated"])
        self.assertGreater(len(selection["selected"]), 5)  # Strong routes do not consume a global cap.

    def test_cli_records_completed_classifier_and_failure_selection(self) -> None:
        snapshot = {"route_candidates": {"security": [{"strength": "weak"}], "dependency": [{"strength": "strong"}], "docs-dx": [{"strength": "weak"}]}}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            snapshot_path = root / "snapshot.json"
            classifier_path = root / "classifier.json"
            snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")
            classifier_path.write_text(json.dumps({"status": "completed", "selected": ["docs-dx"]}), encoding="utf-8")
            completed = subprocess.run(["python3", str(SCRIPT), "--snapshot", str(snapshot_path), "--classifier-result", str(classifier_path)], text=True, capture_output=True, check=False)
            self.assertEqual(0, completed.returncode, completed.stderr)
            self.assertIn("docs-dx", json.loads(completed.stdout)["selected"])
            failed = subprocess.run(["python3", str(SCRIPT), "--snapshot", str(snapshot_path), "--classifier-failed"], text=True, capture_output=True, check=False)
            self.assertEqual(0, failed.returncode, failed.stderr)
            output = json.loads(failed.stdout)
            self.assertIn("security", output["selected"])
            self.assertEqual("routing_classifier_failed", output["not_evaluated"]["docs-dx"])


if __name__ == "__main__":
    unittest.main()

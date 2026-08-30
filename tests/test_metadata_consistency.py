from __future__ import annotations

import json
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_NAME = "review-orchestrator"
PLUGIN_ROOT = REPO_ROOT / "plugins" / PLUGIN_NAME


def load_json(path: Path) -> dict[str, object]:
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise TypeError(f"expected a JSON object: {path.relative_to(REPO_ROOT)}")
    return value


class MetadataConsistencyTests(unittest.TestCase):
    def test_host_manifests_share_release_identity(self) -> None:
        codex = load_json(PLUGIN_ROOT / ".codex-plugin" / "plugin.json")
        claude = load_json(PLUGIN_ROOT / ".claude-plugin" / "plugin.json")

        for field in ("name", "version", "description", "license"):
            with self.subTest(field=field):
                self.assertEqual(codex[field], claude[field])

    def test_marketplaces_point_to_the_same_plugin(self) -> None:
        codex = load_json(REPO_ROOT / ".agents" / "plugins" / "marketplace.json")
        claude = load_json(REPO_ROOT / ".claude-plugin" / "marketplace.json")

        codex_entry = codex["plugins"][0]
        claude_entry = claude["plugins"][0]

        self.assertEqual(codex["name"], claude["name"])
        self.assertEqual(codex_entry["name"], PLUGIN_NAME)
        self.assertEqual(claude_entry["name"], PLUGIN_NAME)
        self.assertEqual(claude_entry["license"], "Apache-2.0")
        self.assertEqual(codex_entry["source"]["path"], f"./plugins/{PLUGIN_NAME}")
        self.assertEqual(claude_entry["source"], f"./plugins/{PLUGIN_NAME}")


if __name__ == "__main__":
    unittest.main()

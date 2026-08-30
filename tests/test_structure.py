from __future__ import annotations

import re
import stat
import unittest
from pathlib import Path


SKILL = Path(__file__).resolve().parents[1]


class StructureTest(unittest.TestCase):
    def test_all_local_markdown_links_resolve(self) -> None:
        missing: list[str] = []
        for source in SKILL.rglob("*.md"):
            content = source.read_text(encoding="utf-8")
            for target in re.findall(r"\[[^]]*\]\(([^)]+)\)", content):
                if target.startswith(("http://", "https://", "#")):
                    continue
                path = target.split("#", 1)[0]
                if path and not (source.parent / path).resolve().exists():
                    missing.append(f"{source.relative_to(SKILL)} -> {target}")
        self.assertEqual([], missing)

    def test_reviewer_catalog_is_complete(self) -> None:
        reviewers = {path.stem for path in (SKILL / "references" / "reviewers").glob("*.md")}
        always = {"semantic-core", "simplify", "test-effectiveness"}
        conditional = {
            "language-idiom", "security", "reliability", "data-integrity",
            "compatibility", "rollout", "observability", "contract-design",
            "performance", "dependency", "accessibility", "docs-dx", "sensitive-data",
        }
        self.assertEqual(always | conditional, reviewers)

    def test_both_host_adapters_are_packaged(self) -> None:
        adapters = SKILL / "references" / "hosts"
        self.assertTrue((adapters / "codex.md").is_file())
        self.assertTrue((adapters / "claude-code.md").is_file())

    def test_documented_direct_scripts_are_executable(self) -> None:
        for name in (
            "review_snapshot.py", "route_selection.py", "validate_findings.py",
            "validate_execution_ledger.py", "run_gates.py", "qualify_scope.py",
            "evaluate_routing_corpus.py", "run_host_smoke.py", "validate_host_e2e.py",
        ):
            mode = (SKILL / "scripts" / name).stat().st_mode
            self.assertTrue(mode & stat.S_IXUSR, name)


if __name__ == "__main__":
    unittest.main()

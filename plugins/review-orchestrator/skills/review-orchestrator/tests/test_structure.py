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
        always = {"semantic-core", "simplify", "convention", "test-effectiveness", "comment-integrity"}
        conditional = {
            "language-idiom", "security", "reliability", "data-integrity",
            "compatibility", "rollout", "observability", "contract-design",
            "performance", "dependency", "accessibility", "docs-dx", "sensitive-data",
            "ci-workflow", "deprecation", "localization", "cost",
        }
        self.assertEqual(always | conditional, reviewers)

    def test_both_host_adapters_are_packaged(self) -> None:
        adapters = SKILL / "references" / "hosts"
        self.assertTrue((adapters / "codex.md").is_file())
        self.assertTrue((adapters / "claude-code.md").is_file())

    def test_review_run_owner_is_context_based_and_single(self) -> None:
        skill = (SKILL / "SKILL.md").read_text(encoding="utf-8")
        ownership = (SKILL / "references" / "ownership.md").read_text(encoding="utf-8")
        policy = (SKILL / "references" / "execution-policy.md").read_text(encoding="utf-8")
        ledger = (SKILL / "references" / "execution-ledger.md").read_text(encoding="utf-8")

        self.assertIn("delegation-capable nested lead", skill)
        self.assertIn("exactly one context owns", ownership)
        self.assertIn("Ownership is stable for the run", ownership)
        self.assertIn("One review-run owner", policy)
        self.assertIn("One owner writes the entire ledger", ledger)
        self.assertNotIn("Keep the orchestrator in the main context", skill)
        self.assertNotIn("The main session owns", policy)

    def test_host_adapters_allow_capable_nested_owners_without_worker_delegation(self) -> None:
        adapters = SKILL / "references" / "hosts"
        codex = (adapters / "codex.md").read_text(encoding="utf-8")
        claude = (adapters / "claude-code.md").read_text(encoding="utf-8")
        ownership = (SKILL / "references" / "ownership.md").read_text(encoding="utf-8")
        claude_worker = (SKILL.parents[1] / "agents" / "review-worker.md").read_text(encoding="utf-8")
        worker_frontmatter = claude_worker.split("---", 2)[1]
        tools_match = re.search(r"(?m)^tools:\s*([^\n]*)(\n(?:[ \t]+[^\n]*\n?)*)?", worker_frontmatter)

        self.assertIn("delegation-capable nested lead", codex)
        self.assertIn("delegation-capable nested lead", claude)
        self.assertIn("Current Claude Code supports nested subagents", claude)
        self.assertIn("Do not return a `review_request`", claude)
        self.assertIn("whether `Agent` is present", claude)
        self.assertIn("do not guess a numeric current depth", claude)
        self.assertIn("Those workers never spawn another worker", ownership)
        self.assertIn("`review-orchestrator:review-worker`", claude)
        self.assertIsNotNone(tools_match)
        worker_tools = " ".join(tools_match.groups(default=""))
        self.assertNotRegex(worker_tools, r"\b(?:Agent|SendMessage)\b")
        self.assertIn("Never spawn or message another agent", claude_worker)

    def test_stale_snapshot_remains_fail_closed_under_one_owner(self) -> None:
        ownership = (SKILL / "references" / "ownership.md").read_text(encoding="utf-8")
        aggregation = (SKILL / "references" / "aggregation.md").read_text(encoding="utf-8")

        self.assertIn("same owner re-verifies the immutable snapshot", ownership)
        self.assertIn("A mismatch stops aggregation", ownership)
        self.assertIn("same review-run owner that created the snapshot", aggregation)
        self.assertIn("If the snapshot is stale, stop aggregation", aggregation)

    def test_documented_direct_scripts_are_executable(self) -> None:
        for name in (
            "review_snapshot.py", "route_selection.py", "validate_findings.py",
            "validate_execution_ledger.py", "run_gates.py", "qualify_scope.py",
            "evaluate_routing_corpus.py", "run_host_smoke.py", "validate_host_e2e.py",
            "validate_rebuttals.py",
        ):
            mode = (SKILL / "scripts" / name).stat().st_mode
            self.assertTrue(mode & stat.S_IXUSR, name)


if __name__ == "__main__":
    unittest.main()

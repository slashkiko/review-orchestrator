from __future__ import annotations

import importlib.util
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path


SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL / "scripts"))
SNAPSHOT_SCRIPT = SKILL / "scripts" / "review_snapshot.py"
GATES = SKILL / "scripts" / "run_gates.py"
QUALIFY = SKILL / "scripts" / "qualify_scope.py"
CORPUS = SKILL / "scripts" / "evaluate_routing_corpus.py"
HOST = SKILL / "scripts" / "validate_host_e2e.py"
SMOKE = SKILL / "scripts" / "run_host_smoke.py"
SPEC = importlib.util.spec_from_file_location("review_snapshot", SNAPSHOT_SCRIPT)
assert SPEC and SPEC.loader
SNAPSHOT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SNAPSHOT)
GATE_SPEC = importlib.util.spec_from_file_location("run_gates", GATES)
QUALIFY_SPEC = importlib.util.spec_from_file_location("qualify_scope", QUALIFY)
assert GATE_SPEC and GATE_SPEC.loader and QUALIFY_SPEC and QUALIFY_SPEC.loader
GATE_MODULE = importlib.util.module_from_spec(GATE_SPEC); GATE_SPEC.loader.exec_module(GATE_MODULE)
QUALIFY_MODULE = importlib.util.module_from_spec(QUALIFY_SPEC); QUALIFY_SPEC.loader.exec_module(QUALIFY_MODULE)
HOST_SPEC = importlib.util.spec_from_file_location("validate_host_e2e", HOST)
assert HOST_SPEC and HOST_SPEC.loader
HOST_MODULE = importlib.util.module_from_spec(HOST_SPEC); HOST_SPEC.loader.exec_module(HOST_MODULE)


class V12GateCliRegressionTest(unittest.TestCase):
    def git(self, root: Path, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", "-C", str(root), *args],
            text=True,
            capture_output=True,
            check=True,
        )

    def make_repo(self, workspace: Path, scripts: dict[str, str]) -> Path:
        repo = workspace / "repo"
        package = repo / "packages" / "nested"
        package.mkdir(parents=True)
        self.git(repo, "init", "-q")
        (package / "package.json").write_text(
            json.dumps({"scripts": scripts}),
            encoding="utf-8",
        )
        self.git(repo, "add", "packages/nested/package.json")
        self.git(
            repo,
            "-c", "user.name=Review Test",
            "-c", "user.email=13293648+slashkiko@users.noreply.github.com",
            "-c", "commit.gpgsign=false",
            "commit", "-qm", "fixture",
        )
        return repo

    def capture(self, workspace: Path, repo: Path) -> tuple[Path, dict]:
        path = workspace / "snapshot.json"
        completed = subprocess.run(
            ["python3", str(SNAPSHOT_SCRIPT), "--repo", str(repo), "--mode", "working", "--output", str(path)],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(0, completed.returncode, completed.stderr)
        return path, json.loads(path.read_text(encoding="utf-8"))

    def executable_map(self, workspace: Path, source: str) -> Path:
        executable = workspace / "npm-fixture"
        executable.write_text("#!/usr/bin/env python3\n" + source, encoding="utf-8")
        executable.chmod(0o755)
        mapping = workspace / "executables.json"
        mapping.write_text(json.dumps({
            "schema_version": 1,
            "executables": [{
                "name": "npm",
                "path": str(executable),
                "sha256": hashlib.sha256(executable.read_bytes()).hexdigest(),
            }],
        }), encoding="utf-8")
        return mapping

    def approval(self, workspace: Path, snapshot: dict, gates: list[dict]) -> Path:
        path = workspace / "approval.json"
        path.write_text(json.dumps({
            "schema_version": 1,
            "snapshot_hash": snapshot["snapshot_hash"],
            "source": "user_exact",
            "approved": [
                {"gate_id": gate["gate_id"], "argv": gate["command_argv"]}
                for gate in gates
            ],
        }), encoding="utf-8")
        return path

    def execute(self, snapshot: Path, approval: Path, executable_map: Path) -> tuple[subprocess.CompletedProcess[str], dict]:
        completed = subprocess.run(
            [
                "python3", str(GATES),
                "--snapshot", str(snapshot),
                "--approval", str(approval),
                "--executable-map", str(executable_map),
                "--timeout-seconds", "5",
                "--execute",
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        value = json.loads(completed.stdout) if completed.stdout else {}
        return completed, value

    def test_nested_gate_runs_in_package_cwd_and_persistent_journal_blocks_repeat(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            repo = self.make_repo(workspace, {"test": "fixture"})
            snapshot_path, snapshot = self.capture(workspace, repo)
            gate = snapshot["configured_gates"][0]
            marker = workspace / "cwd.log"
            executable_map = self.executable_map(
                workspace,
                "import os\nfrom pathlib import Path\n"
                f"with Path({str(marker)!r}).open('a', encoding='utf-8') as handle:\n"
                "    handle.write(os.getcwd() + '\\n')\n",
            )
            approval = self.approval(workspace, snapshot, [gate])

            first, first_value = self.execute(snapshot_path, approval, executable_map)
            self.assertEqual(0, first.returncode, first.stderr)
            self.assertEqual("passed", first_value["results"][0]["outcome"])
            self.assertEqual(
                [str((repo / "packages" / "nested").resolve())],
                marker.read_text(encoding="utf-8").splitlines(),
            )

            second, second_value = self.execute(snapshot_path, approval, executable_map)
            self.assertEqual(0, second.returncode, second.stderr)
            self.assertEqual("blocked", second_value["results"][0]["outcome"])
            self.assertEqual("already_executed", second_value["results"][0]["reason"])
            self.assertEqual(1, len(marker.read_text(encoding="utf-8").splitlines()))

    def test_snapshot_root_tampered_to_identical_clone_is_blocked_before_execution(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            repo = self.make_repo(workspace, {"test": "fixture"})
            _, snapshot = self.capture(workspace, repo)
            clone = workspace / "clone"
            subprocess.run(
                ["git", "clone", "-q", str(repo), str(clone)],
                text=True,
                capture_output=True,
                check=True,
            )
            snapshot["repository_root"] = str(clone)
            tampered = workspace / "tampered-snapshot.json"
            tampered.write_text(json.dumps(snapshot), encoding="utf-8")
            marker = workspace / "clone-marker"
            executable_map = self.executable_map(
                workspace,
                f"from pathlib import Path\nPath({str(marker)!r}).write_text('ran', encoding='utf-8')\n",
            )
            approval = self.approval(workspace, snapshot, [snapshot["configured_gates"][0]])

            completed, value = self.execute(tampered, approval, executable_map)

            self.assertEqual(0, completed.returncode, completed.stderr)
            self.assertEqual("blocked", value["results"][0]["outcome"])
            self.assertEqual("snapshot_stale", value["results"][0]["reason"])
            self.assertFalse(marker.exists())

    def test_first_gate_target_change_makes_second_gate_stale(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            repo = self.make_repo(workspace, {"test:first": "fixture", "lint:second": "fixture"})
            snapshot_path, snapshot = self.capture(workspace, repo)
            gates = {gate["script"]: gate for gate in snapshot["configured_gates"]}
            second_marker = workspace / "second-marker"
            executable_map = self.executable_map(
                workspace,
                "import sys\nfrom pathlib import Path\n"
                "if sys.argv[-1] == 'test:first':\n"
                "    Path('target-change.txt').write_text('changed', encoding='utf-8')\n"
                "elif sys.argv[-1] == 'lint:second':\n"
                f"    Path({str(second_marker)!r}).write_text('ran', encoding='utf-8')\n",
            )
            approval = self.approval(workspace, snapshot, [gates["test:first"], gates["lint:second"]])

            completed, value = self.execute(snapshot_path, approval, executable_map)

            self.assertEqual(0, completed.returncode, completed.stderr)
            self.assertEqual(["passed", "blocked"], [item["outcome"] for item in value["results"]])
            self.assertEqual("snapshot_stale", value["results"][1]["reason"])
            self.assertTrue((repo / "packages" / "nested" / "target-change.txt").is_file())
            self.assertFalse(second_marker.exists())


class V12ControlsTest(unittest.TestCase):
    def snapshot(self, root: Path, gap: dict | None = None, argv: list[str] | None = None) -> tuple[dict, dict]:
        entry = {"gate": "test", "config": "package.json", "script": "test", "command_argv": argv or ["python3", "-c", "pass"], "status": "configured-not-run"}
        entry["gate_id"] = SNAPSHOT.canonical_hash({"gate": entry["gate"], "config": entry["config"], "script": entry["script"], "task": None, "command_argv": entry["command_argv"]})
        value = {
            "schema_version": 4, "repository_root": str(root), "repository_binding": "d" * 64, "target": {"mode": "working", "base": "a" * 40, "head": "WORKTREE"},
            "git_head_at_capture": "a" * 40, "diff_sha256": "b" * 64, "files": [], "languages": [],
            "route_candidates": {}, "sensitive_candidates": [], "configured_gates": [entry],
            "scope_status": "blocked" if gap else "complete", "scope_gaps": [gap] if gap else [],
        }
        value["snapshot_hash"] = SNAPSHOT.canonical_hash(SNAPSHOT.snapshot_identity(value))
        return value, entry

    def invoke(self, script: Path, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(["python3", str(script), *args], text=True, capture_output=True, check=False)

    def test_gate_runner_refuses_unapproved_stale_and_duplicate_and_does_not_leak_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            snapshot, entry = self.snapshot(root, argv=["python3", "-c", "import os; print(os.environ.get('HOME', ''), file=__import__('sys').stderr)"])
            source = root / "snapshot.json"; source.write_text(json.dumps(snapshot))
            approval = {"schema_version": 1, "snapshot_hash": snapshot["snapshot_hash"], "source": "user_exact", "approved": [{"gate_id": entry["gate_id"], "argv": entry["command_argv"]}]}
            approved = root / "approval.json"; approved.write_text(json.dumps(approval))
            dry = self.invoke(GATES, "--snapshot", str(source), "--approval", str(approved))
            self.assertEqual(0, dry.returncode, dry.stderr)
            self.assertEqual("not_run", json.loads(dry.stdout)["results"][0]["outcome"])
            run = GATE_MODULE.run(snapshot, [entry], True, 5)
            self.assertEqual("passed", run["results"][0]["outcome"])
            self.assertNotIn(str(Path.home()), json.dumps(run))
            approval["approved"].append(approval["approved"][0])
            approved.write_text(json.dumps(approval))
            self.assertEqual(2, self.invoke(GATES, "--snapshot", str(source), "--approval", str(approved)).returncode)
            approval["approved"] = [{"gate_id": entry["gate_id"], "argv": ["python3", "-c", "x; echo pwned"]}]
            approved.write_text(json.dumps(approval))
            rejected = self.invoke(GATES, "--snapshot", str(source), "--approval", str(approved))
            self.assertEqual(2, rejected.returncode)
            self.assertNotIn("pwned", rejected.stdout)
            approval["snapshot_hash"] = "0" * 64; approval["approved"] = []
            approved.write_text(json.dumps(approval))
            self.assertEqual(2, self.invoke(GATES, "--snapshot", str(source), "--approval", str(approved)).returncode)
            approval["snapshot_hash"] = snapshot["snapshot_hash"]
            approval["approved"] = [{"gate_id": "0" * 64, "argv": entry["command_argv"]}]
            approved.write_text(json.dumps(approval))
            self.assertEqual(2, self.invoke(GATES, "--snapshot", str(source), "--approval", str(approved)).returncode)
            approval["source"] = "host_skill_allowlist"; approval["approved"] = []
            approved.write_text(json.dumps(approval))
            self.assertEqual(2, self.invoke(GATES, "--snapshot", str(source), "--approval", str(approved)).returncode)

    def test_gate_runner_pass_fail_timeout_missing_and_resume_one_shot(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for argv, outcome in [(["python3", "-c", "pass"], "passed"), (["python3", "-c", "import sys; assert sys.argv[1] == 'literal;echo pwned'", "literal;echo pwned"], "passed"), (["python3", "-c", "raise SystemExit(4)"], "failed"), (["missing-review-gate"], "blocked"), (["python3", "-c", "import time; time.sleep(2)"], "blocked")]:
                snapshot, entry = self.snapshot(root, argv=argv)
                source = root / "snapshot.json"; source.write_text(json.dumps(snapshot))
                approval = {"schema_version": 1, "snapshot_hash": snapshot["snapshot_hash"], "source": "user_exact", "approved": [{"gate_id": entry["gate_id"], "argv": argv}]}
                approved = root / "approval.json"; approved.write_text(json.dumps(approval))
                output = GATE_MODULE.run(snapshot, [entry], True, 1 if outcome == "blocked" and argv[0] == "python3" else 5)
                self.assertEqual(outcome, output["results"][0]["outcome"])
                ledger = root / "ledger.json"; ledger.write_text(json.dumps(output))
                self.assertEqual(2, self.invoke(GATES, "--snapshot", str(source), "--approval", str(approved), "--resume-ledger", str(ledger)).returncode)
                ledger.write_text(json.dumps({"schema_version": 1, "snapshot_hash": snapshot["snapshot_hash"], "results": [{"gate_id": entry["gate_id"]}]}))
                self.assertEqual(2, self.invoke(GATES, "--snapshot", str(source), "--approval", str(approved), "--resume-ledger", str(ledger)).returncode)

    def test_scope_qualification_requires_exact_current_gaps(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            gap = {"path": "nested", "kind": "nested-git-repository", "reason": "boundary", "fingerprint": "a" * 12}
            snapshot, _ = self.snapshot(root, gap=gap)
            source = root / "snapshot.json"; source.write_text(json.dumps(snapshot))
            approved_gap = {"path": "nested", "kind": "nested-git-repository", "fingerprint": "a" * 12}
            approval = {"schema_version": 1, "snapshot_hash": snapshot["snapshot_hash"], "approved_gaps": [approved_gap], "reason": "nested component intentionally excluded", "approval_ref": "user message 2026-08-30"}
            approved = root / "scope.json"; approved.write_text(json.dumps(approval))
            complete = QUALIFY_MODULE.qualify(snapshot, approval)
            self.assertEqual("qualified", complete["status"])
            approval["approved_gaps"] = []
            approved.write_text(json.dumps(approval))
            partial = QUALIFY_MODULE.qualify(snapshot, approval)
            self.assertEqual("blocked", partial["status"])

    def test_routing_corpus_and_host_artifact_schema(self) -> None:
        measured = self.invoke(CORPUS, "--corpus", str(SKILL / "fixtures" / "routing-corpus.json"))
        self.assertEqual(0, measured.returncode, measured.stderr)
        metrics = json.loads(measured.stdout)
        self.assertTrue(metrics["passed"])
        self.assertEqual(1.0, metrics["high_risk_recall"]["value"])
        fixture_value = {
            "schema_version": 3,
            "run_id": "run-1",
            "snapshot_hash": "a" * 64,
            "discovery": {
                "skill_md_sha256": hashlib.sha256((SKILL / "SKILL.md").read_bytes()).hexdigest(),
                "challenge_sha256": "b" * 64,
            },
            "nested_owner": {
                "owner_challenge_sha256": "c" * 64,
                "worker_challenge_sha256": "d" * 64,
            },
        }
        with tempfile.TemporaryDirectory() as directory:
            fixture = Path(directory) / "fixture.json"; fixture.write_text(json.dumps(fixture_value))
            smoke = self.invoke(SMOKE, "--host", "codex", "--fixture", str(fixture), "--repo", str(SKILL))
        self.assertEqual(0, smoke.returncode, smoke.stderr)
        dry_run = json.loads(smoke.stdout)
        self.assertEqual("not_run", dry_run["status"])
        self.assertEqual(5, dry_run["schema_version"])
        smoke_module = __import__("run_host_smoke")
        argv = smoke_module.build_argv("codex", "/usr/bin/codex", SKILL, Path("/tmp/schema.json"), Path("/tmp/out.json"), fixture_value)
        self.assertEqual(["/usr/bin/codex", "app-server", "--stdio"], argv)
        self.assertNotIn("-m", argv)
        self.assertIn("Do not spawn the worker from this parent context", smoke_module.prompt("codex", fixture_value))
        claude_argv = smoke_module.build_argv("claude-code", "/usr/bin/claude", SKILL, Path("/tmp/schema.json"), Path("/tmp/out.json"), fixture_value)
        self.assertEqual(["/usr/bin/claude", "--print"], claude_argv[:2])
        self.assertNotIn("--model", claude_argv)
        self.assertNotIn("--effort", claude_argv)
        self.assertIn("--plugin-dir", claude_argv)
        self.assertIn("stream-json", claude_argv)
        self.assertIn("--forward-subagent-text", claude_argv)
        self.assertEqual("--", claude_argv[-2])
        self.assertEqual("Agent,Read,Bash", claude_argv[claude_argv.index("--tools") + 1])
        self.assertEqual("Bash(shasum -a 256 SKILL.md)", claude_argv[claude_argv.index("--allowedTools") + 1])
        owner_name, worker_name = smoke_module.agent_names(fixture_value)
        agent_definitions = json.loads(claude_argv[claude_argv.index("--agents") + 1])
        self.assertEqual(["Agent"], agent_definitions[owner_name]["tools"])
        self.assertEqual([], agent_definitions[worker_name]["tools"])
        self.assertIn(fixture_value["nested_owner"]["worker_challenge_sha256"], agent_definitions[worker_name]["prompt"])
        self.assertNotIn(fixture_value["nested_owner"]["worker_challenge_sha256"], claude_argv[-1])
        passed = json.dumps({
            "observed_discovery": fixture_value["discovery"],
            "observed_nested_owner": smoke_module.nested_success(fixture_value),
        })
        self.assertIsNotNone(smoke_module.parse_observed(passed, fixture_value))
        fail_closed = json.dumps({
            "observed_discovery": fixture_value["discovery"],
            "observed_nested_owner": {
                "status": "not_evaluated",
                "owner_challenge_sha256": "",
                "worker_challenge_sha256": "",
                "worker_spawned_by": "none",
                "worker_spawned_descendants": False,
            },
        })
        self.assertIsNone(smoke_module.parse_observed(fail_closed, fixture_value))
        self.assertIsNone(smoke_module.parse_observed('{"observed_discovery":{"skill_md_sha256":"x"}}', fixture_value))
        codex_events = "\n".join(json.dumps(event) for event in (
            {"type": "response_item", "payload": {"type": "function_call", "name": "spawn_agent", "namespace": "collaboration", "call_id": "spawn-1", "arguments": json.dumps({"task_name": owner_name})}},
            {"type": "response_item", "payload": {"type": "function_call_output", "call_id": "spawn-1", "output": json.dumps({"task_name": f"/root/{owner_name}"})}},
            {"type": "response_item", "payload": {"type": "function_call", "name": "list_agents", "namespace": "collaboration", "call_id": "list-1", "arguments": "{}"}},
            {"type": "response_item", "payload": {"type": "function_call_output", "call_id": "list-1", "output": json.dumps({"agents": [
                {"agent_name": "/root", "agent_status": "running"},
                {"agent_name": f"/root/{owner_name}", "agent_status": {"completed": "owner"}},
                {"agent_name": f"/root/{owner_name}/{worker_name}", "agent_status": {"completed": "worker"}},
            ]})}},
        ))
        self.assertTrue(smoke_module.verify_codex_trace(codex_events, fixture_value))
        failed_spawn = codex_events.replace(json.dumps({"task_name": f"/root/{owner_name}"}).replace('"', '\\"'), "collab spawn failed: no rollout found")
        self.assertFalse(smoke_module.verify_codex_trace(failed_spawn, fixture_value))
        self.assertFalse(smoke_module.verify_codex_trace(codex_events.replace('"namespace": "collaboration"', '"namespace": "untrusted"'), fixture_value))
        direct_worker_events = codex_events.replace(f"/root/{owner_name}/{worker_name}", f"/root/{worker_name}")
        self.assertFalse(smoke_module.verify_codex_trace(direct_worker_events, fixture_value))
        incomplete_worker_events = codex_events.replace('\\"completed\\": \\"worker\\"', '\\"completed\\": false')
        self.assertFalse(smoke_module.verify_codex_trace(incomplete_worker_events, fixture_value))
        public_codex_events = "\n".join(json.dumps(event) for event in (
            {"type": "item.completed", "item": {"id": "spawn", "type": "collab_tool_call", "tool": "spawn_agent", "status": "completed", "agents_states": {}}},
            {"type": "item.completed", "item": {"id": "list", "type": "collab_tool_call", "tool": "list_agents", "status": "completed", "agents_states": {
                "/root": {"status": "running"},
                f"/root/{owner_name}": {"status": "completed"},
                f"/root/{owner_name}/{worker_name}": {"status": "completed"},
            }}},
        ))
        self.assertTrue(smoke_module.verify_codex_trace(public_codex_events, fixture_value))
        claude_events = json.dumps({
            "type": "assistant",
            "message": {"content": [{"type": "tool_use", "id": "owner-call", "name": "Agent", "input": {"subagent_type": owner_name}}]},
        })
        self.assertTrue(smoke_module.verify_claude_trace(claude_events, fixture_value))
        direct_claude = claude_events.replace(owner_name, worker_name)
        self.assertFalse(smoke_module.verify_claude_trace(direct_claude, fixture_value))
        with mock.patch("run_host_smoke.subprocess.run", return_value=subprocess.CompletedProcess([], 1)):
            self.assertFalse(smoke_module.host_ready("claude-code", "/usr/bin/claude"))

    def test_e2e_rejects_not_run_and_arbitrary_equal_fixture_hash(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            snapshot, _ = self.snapshot(Path(directory))
            fixture = {
                "schema_version": 3,
                "run_id": "run-1",
                "snapshot_hash": snapshot["snapshot_hash"],
                "discovery": {"skill_md_sha256": "a" * 64, "challenge_sha256": "b" * 64},
                "nested_owner": {"owner_challenge_sha256": "c" * 64, "worker_challenge_sha256": "d" * 64},
            }
            base = {"schema_version": 5, "run_id": "run-1", "fixture_hash": HOST_MODULE.digest(fixture), "snapshot_hash": snapshot["snapshot_hash"], "status": "not_run", "model": "default", "effort": "default", "observed_discovery": None, "observed_nested_owner": None, "delegation_trace": None}
            codex, claude = {**base, "host": "codex"}, {**base, "host": "claude-code"}
            output, _ = HOST_MODULE.validate_pair(codex, claude, fixture, snapshot, [None] * 4)
            self.assertFalse(output["passed"])
            codex["fixture_hash"] = claude["fixture_hash"] = "c" * 64
            output, errors = HOST_MODULE.validate_pair(codex, claude, fixture, snapshot, [None] * 4)
            self.assertFalse(output["valid"])
            self.assertTrue(any("fixture" in error for error in errors))
            nested = {"status": "passed", **fixture["nested_owner"], "worker_spawned_by": "nested_owner", "worker_spawned_descendants": False}
            codex.update(fixture_hash=HOST_MODULE.digest(fixture), status="passed", observed_discovery={"skill_md_sha256": "c" * 64, "challenge_sha256": "d" * 64}, observed_nested_owner=nested, delegation_trace={"verified": True, "method": "codex_task_tree"})
            claude.update(fixture_hash=HOST_MODULE.digest(fixture), status="passed", observed_discovery=fixture["discovery"], observed_nested_owner=nested, delegation_trace={"verified": True, "method": "claude_hidden_worker_challenge"})
            output, errors = HOST_MODULE.validate_pair(codex, claude, fixture, snapshot, [None] * 4)
            self.assertFalse(output["valid"])
            self.assertTrue(any("Codex discovery evidence" in error for error in errors))

            codex["observed_discovery"] = fixture["discovery"]
            codex["observed_nested_owner"] = {**nested, "worker_spawned_by": "parent"}
            output, errors = HOST_MODULE.validate_pair(codex, claude, fixture, snapshot, [None] * 4)
            self.assertFalse(output["valid"])
            self.assertTrue(any("nested-owner" in error for error in errors))

            codex["observed_nested_owner"] = nested
            codex["delegation_trace"] = None
            output, errors = HOST_MODULE.validate_pair(codex, claude, fixture, snapshot, [None] * 4)
            self.assertFalse(output["valid"])
            self.assertTrue(any("delegation trace" in error for error in errors))

    def test_e2e_component_validators_reject_malformed_gates_and_scope_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            snapshot, entry = self.snapshot(Path(directory))
            malformed = {"schema_version": 1, "snapshot_hash": snapshot["snapshot_hash"], "results": [{"gate_id": entry["gate_id"]}]}
            self.assertFalse(HOST_MODULE.validate_gates(malformed, snapshot))
            inconsistent = {"schema_version": 1, "snapshot_hash": snapshot["snapshot_hash"], "status": "qualified", "valid": True, "approved_gaps": []}
            self.assertFalse(HOST_MODULE.validate_qualification(inconsistent, snapshot))

    def test_gate_cli_rejects_malformed_target_without_traceback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            snapshot, entry = self.snapshot(root)
            snapshot["target"] = []
            snapshot["snapshot_hash"] = SNAPSHOT.canonical_hash(SNAPSHOT.snapshot_identity(snapshot))
            source = root / "snapshot.json"; source.write_text(json.dumps(snapshot))
            approval = {"schema_version": 1, "snapshot_hash": snapshot["snapshot_hash"], "source": "user_exact", "approved": []}
            approved = root / "approval.json"; approved.write_text(json.dumps(approval))
            result = self.invoke(GATES, "--snapshot", str(source), "--approval", str(approved))
            self.assertEqual(2, result.returncode)
            self.assertNotIn("Traceback", result.stderr)

    def test_executable_map_rejects_changed_private_executable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); executable = root / "gatefake"
            executable.write_text("#!/bin/sh\nexit 0\n"); executable.chmod(0o755)
            valid_hash = hashlib.sha256(executable.read_bytes()).hexdigest()
            mapping = {"schema_version": 1, "executables": [{"name": "gatefake", "path": str(executable), "sha256": "0" * 64}]}
            source = root / "map.json"; source.write_text(json.dumps(mapping))
            with self.assertRaises(GATE_MODULE.GateError):
                GATE_MODULE.load_executable_map(str(source), root / "repo")
            mapping["executables"][0]["path"] = "relative/gatefake"
            source.write_text(json.dumps(mapping))
            with self.assertRaises(GATE_MODULE.GateError):
                GATE_MODULE.load_executable_map(str(source), root / "repo")
            mapping["executables"][0].update(path=str(executable), sha256=valid_hash)
            source.write_text(json.dumps(mapping))
            loaded = GATE_MODULE.load_executable_map(str(source), root / "repo")
            executable.write_text("#!/bin/sh\nexit 9\n")
            snapshot, entry = self.snapshot(root / "repo", argv=["gatefake"])
            output = GATE_MODULE.run(snapshot, [entry], True, 5, loaded)
            self.assertEqual("blocked", output["results"][0]["outcome"])
            self.assertEqual("executable_changed", output["results"][0]["reason"])
            self.assertNotIn(str(executable), json.dumps(output))
            inside_repo = root / "repo" / "map.json"
            inside_repo.parent.mkdir()
            inside_repo.write_text(json.dumps(mapping))
            with self.assertRaises(GATE_MODULE.GateError):
                GATE_MODULE.load_executable_map(str(inside_repo), root / "repo")


if __name__ == "__main__":
    unittest.main()

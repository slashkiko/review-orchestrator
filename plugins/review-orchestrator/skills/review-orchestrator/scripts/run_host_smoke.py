#!/usr/bin/env python3
"""Fixed read-only host adapters for cross-host discovery and nested-owner smoke tests."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from codex_host_transport import run_codex_host


TRUSTED_DIRS = (
    "/usr/bin",
    "/bin",
    "/usr/sbin",
    "/sbin",
    "/usr/local/bin",
    "/opt/homebrew/bin",
    "/opt/local/bin",
)
HASH_FIELDS = {"skill_md_sha256", "challenge_sha256"}
NESTED_FIELDS = {"owner_challenge_sha256", "worker_challenge_sha256"}


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def valid_hash(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(char in "0123456789abcdef" for char in value)
    )


def trusted_path() -> str:
    return os.pathsep.join(path for path in TRUSTED_DIRS if Path(path).is_dir())


def host_environment() -> dict[str, str]:
    environment = {"PATH": trusted_path(), "LANG": "C", "LC_ALL": "C"}
    # macOS keychain lookup depends on the inherited login-session identity.
    # Preserve location/identity values, without forwarding arbitrary tool config.
    for key in (
        "HOME", "USER", "LOGNAME", "TMPDIR", "SECURITYSESSIONID", "XPC_FLAGS",
        "XPC_SERVICE_NAME", "__CF_USER_TEXT_ENCODING", "LaunchInstanceID",
        "CODEX_HOME", "CLAUDE_CONFIG_DIR", "XDG_CONFIG_HOME", "XDG_DATA_HOME",
    ):
        if key in os.environ:
            environment[key] = os.environ[key]
    return environment


def resolve_host(host: str) -> str | None:
    name = "codex" if host == "codex" else "claude"
    value = shutil.which(name, path=trusted_path())
    return value if value and Path(value).name == name else None


def host_ready(host: str, executable: str) -> bool:
    if host != "claude-code":
        return True
    try:
        completed = subprocess.run(
            [executable, "auth", "status"],
            env=host_environment(),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
            check=False,
        )
        return completed.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def load_fixture(path: str) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    expected = {"schema_version", "run_id", "snapshot_hash", "discovery", "nested_owner"}
    if not isinstance(value, dict) or set(value) != expected or value.get("schema_version") != 3:
        raise ValueError("unsupported fixture")
    discovery = value.get("discovery")
    nested = value.get("nested_owner")
    if (
        not isinstance(value.get("run_id"), str)
        or not value["run_id"]
        or not valid_hash(value.get("snapshot_hash"))
        or not isinstance(discovery, dict)
        or set(discovery) != HASH_FIELDS
        or not all(valid_hash(item) for item in discovery.values())
        or not isinstance(nested, dict)
        or set(nested) != NESTED_FIELDS
        or not all(valid_hash(item) for item in nested.values())
    ):
        raise ValueError("invalid fixture")
    return value


def nested_success(fixture: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": "passed",
        "owner_challenge_sha256": fixture["nested_owner"]["owner_challenge_sha256"],
        "worker_challenge_sha256": fixture["nested_owner"]["worker_challenge_sha256"],
        "worker_spawned_by": "nested_owner",
        "worker_spawned_descendants": False,
    }


def agent_names(fixture: dict[str, Any]) -> tuple[str, str]:
    return (
        "owner" + fixture["nested_owner"]["owner_challenge_sha256"][:8],
        "worker" + fixture["nested_owner"]["worker_challenge_sha256"][:8],
    )


def trace_success(host: str) -> dict[str, Any]:
    method = "codex_task_tree" if host == "codex" else "claude_hidden_worker_challenge"
    return {"verified": True, "method": method}


def schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["observed_discovery", "observed_nested_owner"],
        "properties": {
            "observed_discovery": {
                "type": "object",
                "additionalProperties": False,
                "required": sorted(HASH_FIELDS),
                "properties": {key: {"type": "string"} for key in HASH_FIELDS},
            },
            "observed_nested_owner": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "status",
                    "owner_challenge_sha256",
                    "worker_challenge_sha256",
                    "worker_spawned_by",
                    "worker_spawned_descendants",
                ],
                "properties": {
                    "status": {"type": "string", "enum": ["passed", "not_evaluated"]},
                    "owner_challenge_sha256": {"type": "string"},
                    "worker_challenge_sha256": {"type": "string"},
                    "worker_spawned_by": {"type": "string"},
                    "worker_spawned_descendants": {"type": "boolean"},
                },
            },
        },
    }


def prompt(host: str, fixture: dict[str, Any]) -> str:
    owner_name, worker_name = agent_names(fixture)
    if host == "claude-code":
        worker_instruction = f"Dispatch only the `{owner_name}` Agent. Its hidden definition owns the probe and dispatches `{worker_name}`."
        worker_challenge = "The direct-worker challenge is intentionally absent from this prompt. Do not spawn the worker directly or guess its response."
        trace_instruction = "The harness verifies the root Agent call and a worker challenge hidden in the worker definition."
    else:
        worker_instruction = f"Spawn one nested lead with task name `{owner_name}`. It must spawn one direct worker with task name `{worker_name}` and explicitly forbid that worker from delegating."
        worker_challenge = f'Direct-worker challenge to pass only through the nested owner: {fixture["nested_owner"]["worker_challenge_sha256"]}'
        trace_instruction = "After both agents complete, call list_agents so the harness can verify the actual owner/worker task tree."
    return f"""Run a read-only review-orchestrator host topology smoke, not a code review.

The current context is only the parent harness. It must:
1. Read SKILL.md and use only `shasum -a 256 SKILL.md` to calculate its SHA-256.
2. {worker_instruction}
3. Do not spawn the worker from this parent context. The nested lead is the sole owner of the delegation probe.
4. Return only the JSON required by the supplied schema.

The nested lead must first verify that its subagent-delegation tool is exposed. If it is absent, it must not create review-run state or fabricate success; return status `not_evaluated` with empty challenge strings and `worker_spawned_by` set to `none`. The worker must return its challenge without spawning descendants. The nested owner must return both challenges to this parent only after its direct worker completes. {trace_instruction}

Return `observed_discovery` with the calculated SKILL.md hash and discovery challenge. Return `observed_nested_owner` with status `passed`, both exact challenges, `worker_spawned_by` set to `nested_owner`, and `worker_spawned_descendants` set to false only if that topology completed.

Discovery challenge: {fixture["discovery"]["challenge_sha256"]}
Nested-owner challenge: {fixture["nested_owner"]["owner_challenge_sha256"]}
{worker_challenge}"""


def claude_agents(fixture: dict[str, Any]) -> dict[str, Any]:
    owner_name, worker_name = agent_names(fixture)
    return {
        owner_name: {
            "description": "Nested owner for the read-only delegation topology smoke.",
            "prompt": (
                f"You own one delegation probe. Confirm Agent is exposed, then dispatch exactly one `{worker_name}` Agent without passing it any challenge value. "
                f"Wait for it and return owner challenge {fixture['nested_owner']['owner_challenge_sha256']} plus the worker's exact response. "
                "Never invoke a skill, read files, edit, or dispatch any other Agent."
            ),
            "tools": ["Agent"],
        },
        worker_name: {
            "description": "Non-delegating leaf for the read-only delegation topology smoke.",
            "prompt": (
                f"Return exactly this worker challenge to your parent: {fixture['nested_owner']['worker_challenge_sha256']}. "
                "Do not invoke tools or spawn descendants."
            ),
            "tools": [],
        },
    }


def build_argv(
    host: str,
    executable: str,
    repo: Path,
    schema_path: Path,
    output_path: Path,
    fixture: dict[str, Any],
) -> list[str]:
    if host == "codex":
        return [executable, "app-server", "--stdio"]
    plugin_root = repo.parents[1]
    return [
        executable,
        "--print",
        "--max-budget-usd",
        "0.25",
        "--output-format",
        "stream-json",
        "--verbose",
        "--forward-subagent-text",
        "--json-schema",
        json.dumps(schema(), sort_keys=True),
        "--permission-mode",
        "plan",
        "--no-session-persistence",
        "--plugin-dir",
        str(plugin_root),
        "--agents",
        json.dumps(claude_agents(fixture), sort_keys=True),
        "--tools",
        "Agent,Read,Bash",
        "--allowedTools",
        "Bash(shasum -a 256 SKILL.md)",
        "--disallowedTools",
        "Edit,Write",
        "--",
        prompt(host, fixture),
    ]


def normalized(
    host: str,
    fixture: dict[str, Any],
    status: str,
    observed_discovery: dict[str, str] | None = None,
    observed_nested_owner: dict[str, Any] | None = None,
    delegation_trace: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": 5,
        "host": host,
        "run_id": fixture["run_id"],
        "fixture_hash": digest(fixture),
        "snapshot_hash": fixture["snapshot_hash"],
        "status": status,
        "model": "default",
        "effort": "default",
        "observed_discovery": observed_discovery,
        "observed_nested_owner": observed_nested_owner,
        "delegation_trace": delegation_trace,
    }


def json_events(raw: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for line in raw.splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            events.append(value)
    return events


def parse_observed(raw: str, fixture: dict[str, Any]) -> tuple[dict[str, str], dict[str, Any]] | None:
    try:
        try:
            candidates: list[Any] = [json.loads(raw)]
        except json.JSONDecodeError:
            candidates = json_events(raw)
        for candidate in reversed(candidates):
            value = candidate
            if isinstance(value, dict) and isinstance(value.get("result"), str):
                try:
                    value = json.loads(value["result"])
                except json.JSONDecodeError:
                    pass
            if isinstance(value, dict) and isinstance(value.get("structured_output"), dict):
                value = value["structured_output"]
            discovery = value.get("observed_discovery") if isinstance(value, dict) else None
            nested = value.get("observed_nested_owner") if isinstance(value, dict) else None
            if discovery == fixture["discovery"] and nested == nested_success(fixture):
                return discovery, nested
        return None
    except (TypeError, ValueError, json.JSONDecodeError):
        return None


def function_calls(events: list[dict[str, Any]], name: str) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    for event in events:
        payload = event.get("payload", event)
        if not isinstance(payload, dict):
            continue
        if payload.get("type") == "function_call" and payload.get("name") == name and payload.get("namespace") == "collaboration":
            calls.append(payload)
    return calls


def parse_arguments(call: dict[str, Any]) -> dict[str, Any] | None:
    arguments = call.get("arguments")
    if isinstance(arguments, dict):
        return arguments
    if isinstance(arguments, str):
        try:
            value = json.loads(arguments)
            return value if isinstance(value, dict) else None
        except json.JSONDecodeError:
            return None
    return None


def verify_codex_trace(raw: str, fixture: dict[str, Any]) -> bool:
    events = json_events(raw)
    # Raw notifications can be replayed. Reject conflicting call IDs instead of
    # letting the last copy replace evidence from an earlier result.
    unique: dict[tuple[str, str], dict[str, Any]] = {}
    for event in events:
        payload = event.get("payload", event)
        if not isinstance(payload, dict) or payload.get("type") not in ("function_call", "function_call_output"):
            continue
        key = (payload["type"], payload.get("call_id", ""))
        if not key[1] or key in unique and unique[key] != payload:
            return False
        unique[key] = payload
    if unique:
        events = list(unique.values())
    owner_name, worker_name = agent_names(fixture)
    spawn_calls = function_calls(events, "spawn_agent")
    agents: list[dict[str, Any]] = []
    if spawn_calls:
        spawn_arguments = parse_arguments(spawn_calls[0]) if len(spawn_calls) == 1 else None
        if not isinstance(spawn_arguments, dict) or spawn_arguments.get("task_name") != owner_name:
            return False
        spawn_id = spawn_calls[0].get("call_id")
        spawn_outputs = [event.get("payload", event) for event in events
                         if event.get("payload", event).get("type") == "function_call_output"
                         and event.get("payload", event).get("call_id") == spawn_id]
        if len(spawn_outputs) != 1:
            return False
        try:
            spawned = json.loads(spawn_outputs[0].get("output", ""))
        except (ValueError, TypeError):
            return False
        if not isinstance(spawned, dict) or spawned.get("task_name") != f"/root/{owner_name}":
            return False
        list_calls = function_calls(events, "list_agents")
        if not list_calls:
            return False
        call_id = list_calls[-1].get("call_id")
        outputs: list[Any] = []
        for event in events:
            payload = event.get("payload", event)
            if isinstance(payload, dict) and payload.get("type") == "function_call_output" and payload.get("call_id") == call_id:
                output = payload.get("output")
                try:
                    outputs.append(json.loads(output) if isinstance(output, str) else output)
                except json.JSONDecodeError:
                    return False
        if outputs and isinstance(outputs[-1], dict) and isinstance(outputs[-1].get("agents"), list):
            agents = [item for item in outputs[-1]["agents"] if isinstance(item, dict)]
    else:
        collab_items = [
            event.get("item") for event in events
            if event.get("type") == "item.completed"
            and isinstance(event.get("item"), dict)
            and event["item"].get("type") == "collab_tool_call"
            and event["item"].get("status") == "completed"
        ]
        spawns = [item for item in collab_items if item.get("tool") == "spawn_agent"]
        lists = [item for item in collab_items if item.get("tool") == "list_agents"]
        if len(spawns) != 1 or not lists:
            return False
        states = lists[-1].get("agents_states")
        if isinstance(states, dict):
            for agent_path, state in states.items():
                reported_path = state.get("agent_path", agent_path) if isinstance(state, dict) else agent_path
                agents.append({"agent_name": reported_path, "agent_status": state})
        elif isinstance(states, list):
            agents = [item for item in states if isinstance(item, dict)]
    if not agents:
        return False
    owner_suffix = f"/root/{owner_name}"
    owners = [item for item in agents if isinstance(item.get("agent_name"), str) and item["agent_name"] == owner_suffix]
    if len(owners) != 1 or not agent_completed(owners[0].get("agent_status")):
        return False
    owner_path = owners[0]["agent_name"]
    worker_path = f"{owner_path}/{worker_name}"
    descendants = [item for item in agents if isinstance(item.get("agent_name"), str) and item["agent_name"].startswith(owner_path + "/")]
    if len(descendants) != 1 or descendants[0].get("agent_name") != worker_path:
        return False
    return agent_completed(descendants[0].get("agent_status"))


def agent_completed(status: Any) -> bool:
    return status == "completed" or isinstance(status, dict) and (
        isinstance(status.get("completed"), str) or status.get("status") == "completed"
    )


def claude_tool_uses(event: dict[str, Any]) -> list[dict[str, Any]]:
    message = event.get("message")
    if not isinstance(message, dict) or not isinstance(message.get("content"), list):
        return []
    return [item for item in message["content"] if isinstance(item, dict) and item.get("type") == "tool_use"]


def verify_claude_trace(raw: str, fixture: dict[str, Any]) -> bool:
    owner_name, _ = agent_names(fixture)
    root_agent_uses: list[dict[str, Any]] = []
    for event in json_events(raw):
        if event.get("parent_tool_use_id") not in (None, ""):
            continue
        root_agent_uses.extend(item for item in claude_tool_uses(event) if item.get("name") == "Agent")
    return (
        len(root_agent_uses) == 1
        and isinstance(root_agent_uses[0].get("input"), dict)
        and root_agent_uses[0]["input"].get("subagent_type") == owner_name
    )


def verify_trace(host: str, raw: str, fixture: dict[str, Any]) -> bool:
    return verify_codex_trace(raw, fixture) if host == "codex" else verify_claude_trace(raw, fixture)


def run_host_process(argv: list[str], repo: Path, environment: dict[str, str], output: Any, timeout: int, error_output: Any = subprocess.DEVNULL) -> subprocess.CompletedProcess:
    # The CLI can spawn worker processes. Bound the whole process group, not
    # just the direct child, so a timed-out smoke cannot leave workers running.
    with subprocess.Popen(
        argv, cwd=repo, env=environment, stdin=subprocess.DEVNULL,
        stdout=output, stderr=error_output, start_new_session=True,
    ) as process:
        try:
            code = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
            raise
    return subprocess.CompletedProcess(argv, code)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", choices=("codex", "claude-code"), required=True)
    parser.add_argument("--fixture", required=True)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--timeout-seconds", type=int, default=180)
    parser.add_argument("--output", default="-")
    args = parser.parse_args()
    try:
        fixture = load_fixture(args.fixture)
        repo = Path(args.repo).resolve()
        manifest = repo / "SKILL.md"
        if not manifest.is_file() or file_hash(manifest) != fixture["discovery"]["skill_md_sha256"]:
            raise ValueError("manifest discovery contract failed")
        artifact = normalized(args.host, fixture, "not_run")
        code = 0
        if args.execute:
            executable = resolve_host(args.host)
            if not executable or not host_ready(args.host, executable):
                artifact["status"] = "unavailable"
                code = 1
            else:
                with tempfile.TemporaryDirectory(prefix="review-host-smoke-") as directory:
                    root = Path(directory)
                    schema_path = root / "schema.json"
                    response = root / "response.json"
                    schema_path.write_text(json.dumps(schema()), encoding="utf-8")
                    try:
                        argv = build_argv(args.host, executable, repo, schema_path, response, fixture)
                        environment = host_environment()
                        if args.host == "claude-code":
                            raw = root / "claude-output.json"
                            with raw.open("wb") as handle:
                                completed = run_host_process(
                                    argv, repo, environment, handle, args.timeout_seconds,
                                )
                            raw_text = raw.read_text(encoding="utf-8", errors="replace")
                            response_text = raw_text
                        else:
                            raw = root / "codex-events.jsonl"
                            with raw.open("wb") as handle:
                                completed, response_text = run_codex_host(
                                    argv, repo, environment, handle, args.timeout_seconds,
                                    prompt(args.host, fixture), schema(),
                                )
                            raw_text = raw.read_text(encoding="utf-8", errors="replace")
                        observed = parse_observed(response_text, fixture)
                        trace_verified = verify_trace(args.host, raw_text, fixture)
                        if completed.returncode == 0 and observed and trace_verified:
                            artifact = normalized(args.host, fixture, "passed", *observed, trace_success(args.host))
                        else:
                            artifact["status"] = "failed"
                            code = 1
                    except subprocess.TimeoutExpired:
                        artifact["status"] = "unavailable"
                        code = 1
        text = json.dumps(artifact, indent=2, sort_keys=True) + "\n"
        if args.output == "-":
            sys.stdout.write(text)
        else:
            Path(args.output).write_text(text, encoding="utf-8")
        return code
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"run_host_smoke: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

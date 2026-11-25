"""Capture root-thread tool evidence through Codex's local app-server protocol."""

from __future__ import annotations

import json
import os
import selectors
import signal
import subprocess
import time
from pathlib import Path
from typing import Any


def run_codex_host(
    argv: list[str], repo: Path, environment: dict[str, str], output: Any,
    timeout: int, prompt: str, schema: dict[str, Any],
    error_output: Any = subprocess.DEVNULL,
) -> tuple[subprocess.CompletedProcess, str]:
    """Keep history for forked agents; accept evidence only from this root turn.

    Codex exec JSONL omits some collaboration tools. Raw app-server events retain
    call IDs and outputs. Persistent thread history is required by fork_turns=all;
    the synthetic session stays in the host history, without changing settings.
    """
    deadline = time.monotonic() + timeout
    with subprocess.Popen(
        argv, cwd=repo, env=environment, stdin=subprocess.PIPE,
        stdout=subprocess.PIPE, stderr=error_output, start_new_session=True,
    ) as process, selectors.DefaultSelector() as selector:
        assert process.stdin is not None and process.stdout is not None
        selector.register(process.stdout, selectors.EVENT_READ)
        buffer = b""
        pending: list[dict[str, Any]] = []

        def send(method: str, params: dict[str, Any], request_id: int | None = None) -> None:
            value: dict[str, Any] = {"method": method, "params": params}
            if request_id is not None:
                value["id"] = request_id
            process.stdin.write((json.dumps(value) + "\n").encode())
            process.stdin.flush()

        def receive() -> dict[str, Any]:
            nonlocal buffer
            if time.monotonic() >= deadline:
                raise subprocess.TimeoutExpired(argv, timeout)
            while not pending:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise subprocess.TimeoutExpired(argv, timeout)
                if not selector.select(remaining):
                    raise subprocess.TimeoutExpired(argv, timeout)
                block = os.read(process.stdout.fileno(), 65536)
                if not block:
                    raise ValueError("Codex app-server closed before turn completion")
                buffer += block
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    if line:
                        value = json.loads(line)
                        if not isinstance(value, dict):
                            raise ValueError("invalid Codex app-server event")
                        pending.append(value)
            event = pending.pop(0)
            if "method" in event and "id" in event:
                # Never approve an interactive request on behalf of the user.
                process.stdin.write((json.dumps({
                    "id": event["id"], "error": {
                        "code": -32601, "message": "Smoke probe cannot handle interactive requests",
                    },
                }) + "\n").encode())
                process.stdin.flush()
            return event

        def response(request_id: int) -> dict[str, Any]:
            deferred: list[dict[str, Any]] = []
            while True:
                event = receive()
                if event.get("id") == request_id:
                    pending[:0] = deferred
                    if "error" in event:
                        raise ValueError("Codex app-server rejected the smoke request")
                    result = event.get("result")
                    if not isinstance(result, dict):
                        raise ValueError("invalid Codex app-server response")
                    return result
                deferred.append(event)

        try:
            send("initialize", {
                "clientInfo": {"name": "review_orchestrator_smoke", "version": "2.0.0"},
                "capabilities": {"experimentalApi": True},
            }, 1)
            response(1)
            send("initialized", {})
            send("thread/start", {
                "cwd": str(repo), "sandbox": "read-only", "approvalPolicy": "never",
                "ephemeral": False, "experimentalRawEvents": True,
            }, 2)
            thread_id = response(2)["thread"]["id"]
            send("turn/start", {
                "threadId": thread_id, "input": [{"type": "text", "text": prompt}],
                "outputSchema": schema,
            }, 3)
            # Preserve notifications that arrive before the turn acknowledgement.
            turn_id = response(3)["turn"]["id"]
            final = ""
            while True:
                event = receive()
                params = event.get("params", {})
                if params.get("threadId") != thread_id:
                    continue
                if event.get("method") == "turn/completed":
                    turn = params.get("turn", {})
                    if turn.get("id") != turn_id:
                        continue
                    code = 0 if turn.get("status") == "completed" else 1
                    return subprocess.CompletedProcess(argv, code), final
                if params.get("turnId") != turn_id:
                    continue
                if event.get("method") == "rawResponseItem/completed":
                    item = params.get("item", {})
                    if item.get("type") in ("function_call", "function_call_output"):
                        output.write((json.dumps({"type": "response_item", "payload": item}) + "\n").encode())
                        output.flush()
                elif event.get("method") == "item/completed":
                    item = params.get("item", {})
                    if item.get("type") == "agentMessage" and item.get("phase") == "final_answer":
                        final = item.get("text", "")
        finally:
            # The process group is private to this probe, including on protocol errors.
            process.poll()  # Reap an exited server before signalling its process group.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()

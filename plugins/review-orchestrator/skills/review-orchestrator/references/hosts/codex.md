# Codex host adapter

The Codex context that invokes this skill becomes the review-run owner when its collaboration tools can spawn all required direct workers. This includes a root/main agent and a delegation-capable nested lead such as a workstream lead. Do not move orchestration to root/main merely because the invoking owner is nested.

- Discover the current concurrency capacity instead of assuming a fixed slot count.
- Confirm that the owner can spawn children before resolving the target or creating the snapshot. Spawn as many independent reviewer tasks as free slots allow. Queue remaining envelopes unchanged for later waves.
- Select the model and reasoning effort explicitly when the runtime supports it, using [../model-policy.md](../model-policy.md). If available model identifiers differ, choose the smallest equivalent and record it.
- Wait for terminal messages without forwarding reviewer findings to still-running or later-wave initial reviewers.
- Repository `AGENTS.md` files remain applicable evidence/instructions according to Codex precedence. Include relevant task constraints explicitly because a subagent may not share all transient main-context discoveries.
- Do not use user-owned Codex threads for internal reviewers; use the host collaboration subagents. This does not mean starting the CLI with `--ephemeral`: context-sharing subagents may need a persisted parent rollout.
- Spawn every reviewer, rebuttal, routing classifier, and validator directly from the owner. Explicitly tell each worker not to spawn subagents or invoke the orchestrator.
- The owner records each selected role, requested/actual model and effort (or `not_exposed`), host task ID, attempt, timeout, terminal status, retry/escalation reason, and schema-validation result in the shared [execution ledger](../execution-ledger.md). Do not ask reviewers to report these values.

If delegation is unavailable in the invoking context, report that independent-review execution is not evaluated. Do not impersonate multiple reviewers sequentially, transfer a partially initialized run, or call either behavior equivalent.

For a real smoke, use the shared [cross-host E2E contract](../host-e2e.md). This adapter supplies Codex-specific CLI/agent invocation only; snapshot, routing, ledger, gate, and qualification schemas remain shared. Mark an unavailable Codex CLI `unavailable` rather than storing raw output.

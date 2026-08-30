# Codex host adapter

Keep orchestration in the root/main agent. Use the available collaboration subagent mechanism to spawn one task per selected reviewer and later one validator task.

- Discover the current concurrency capacity instead of assuming a fixed slot count.
- Spawn as many independent reviewer tasks as free slots allow. Queue remaining envelopes unchanged for later waves.
- Select the model and reasoning effort explicitly when the runtime supports it, using [../model-policy.md](../model-policy.md). If available model identifiers differ, choose the smallest equivalent and record it.
- Wait for terminal messages without forwarding reviewer findings to still-running or later-wave initial reviewers.
- Repository `AGENTS.md` files remain applicable evidence/instructions according to Codex precedence. Include relevant task constraints explicitly because a subagent may not share all transient main-context discoveries.
- Do not use user-owned Codex threads for internal reviewers; use ephemeral subagents.
- The main agent records each selected role, requested/actual model and effort (or `not_exposed`), host task ID, attempt, timeout, terminal status, retry/escalation reason, and schema-validation result in the shared [execution ledger](../execution-ledger.md). Do not ask reviewers to report these values.

If delegation is unavailable, report that independent-review execution is not evaluated. Do not impersonate multiple reviewers sequentially in the main context and call it equivalent.

# Claude Code host adapter

Keep orchestration in the main Claude Code context and use the Agent/subagent facility for one task per selected reviewer and later one validator task. Claude subagents must not be asked to spawn other agents.

- Discover available concurrency; dispatch independent tasks concurrently up to that limit and preserve later envelopes unchanged across waves.
- Map `fast`, `balanced`, and `deep` using [../model-policy.md](../model-policy.md). Omit an effort field when the chosen model/runtime does not support it and record that omission.
- Give each Agent the complete reviewer envelope because subagent context is isolated. Explicitly include applicable repository `CLAUDE.md`, `AGENTS.md`, and task constraints not guaranteed to preload.
- Do not pass previous findings into later initial-review waves.
- Wait for all reviewer tasks before creating the validator Agent.
- The main context records each Agent's requested/actual model and effort (or `not_exposed`), host task ID, attempts, timeout, terminal status, retry/escalation reason, and schema-validation result in the shared [execution ledger](../execution-ledger.md). Reviewers do not self-report this data.

Codex-only `agents/openai.yaml` is inert metadata for Claude Code; the portable behavior is defined by `SKILL.md` and `references/`. If the installed Claude version rejects unknown ancillary files, discovery through the directory symlink must still target `SKILL.md`; do not fork the shared instructions.

If the Agent facility cannot run, report the review as not evaluated rather than simulating independent contexts in the main session.

For a real smoke, use the shared [cross-host E2E contract](../host-e2e.md). This adapter supplies Claude Code-specific CLI/Agent invocation only; snapshot, routing, ledger, gate, and qualification schemas remain shared. Mark an unavailable Claude CLI `unavailable` rather than storing raw output.

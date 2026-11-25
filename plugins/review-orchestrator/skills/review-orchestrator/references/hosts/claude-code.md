# Claude Code host adapter

The Claude Code context that invokes this skill becomes the review-run owner when the `Agent` tool is exposed in that context. [Current Claude Code supports nested subagents](https://code.claude.com/docs/en/sub-agents#let-subagents-spawn-their-own-subagents), so the owner may be the main context or a delegation-capable nested lead. Do not return a `review_request` to main merely because the owner is a subagent.

- Before resolving the target or creating the snapshot, check whether `Agent` is present in the invoking context's available tools. Claude Code withholds `Agent` at the configured depth limit, and a subagent definition may also omit or deny it. Tool exposure is the in-context capability signal; do not guess a numeric current depth or configured maximum. A temporarily full concurrency limit only delays a wave and does not disqualify an otherwise capable owner. Dispatch independent tasks concurrently up to the available limit and preserve later envelopes unchanged across waves.
- Map `fast`, `balanced`, and `deep` using [../model-policy.md](../model-policy.md). Omit an effort field when the chosen model/runtime does not support it and record that omission.
- Give each Agent the complete reviewer envelope because subagent context is isolated. Explicitly include applicable repository `CLAUDE.md`, `AGENTS.md`, and task constraints not guaranteed to preload.
- Do not pass previous findings into later initial-review waves.
- The owner directly creates every reviewer, rebuttal, routing-classifier, and validator Agent using the plugin's `review-orchestrator:review-worker` type. Its tool allowlist omits `Agent`, and each task envelope must also forbid further delegation.
- Request foreground nested workers and wait for every worker to finish before the owner returns; in print/SDK sessions, background workers that outlive their owner report to main instead. Wait for all reviewer and rebuttal tasks before creating the validator Agent.
- The owner records each Agent's requested/actual model and effort (or `not_exposed`), host task ID, attempts, timeout, terminal status, retry/escalation reason, and schema-validation result in the shared [execution ledger](../execution-ledger.md). Reviewers do not self-report this data.

Codex-only `agents/openai.yaml` is inert metadata for Claude Code; the portable behavior is defined by `SKILL.md` and `references/`. If the installed Claude version rejects unknown ancillary files, discovery through the directory symlink must still target `SKILL.md`; do not fork the shared instructions.

If `Agent` is absent in the invoking context, report the review as not evaluated before creating any run state rather than simulating independent contexts, returning orchestration artifacts to main, or transferring a partially initialized run.

For a real smoke, use the shared [cross-host E2E contract](../host-e2e.md). This adapter supplies Claude Code-specific CLI/Agent invocation only; snapshot, routing, ledger, gate, and qualification schemas remain shared. Mark an unavailable Claude CLI `unavailable` rather than storing raw output.

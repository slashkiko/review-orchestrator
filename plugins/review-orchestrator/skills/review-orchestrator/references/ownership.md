# Review-run ownership

The **review-run owner** is the orchestration context that starts a review run after confirming that it can delegate every required worker on the current host. The owner may be a root/main context or a delegation-capable nested lead. Its position in the agent tree does not determine ownership.

A run starts when target resolution or snapshot creation begins. From that point through the final report, exactly one context owns:

- target resolution, snapshot creation, change mapping, and routing;
- reviewer, rebuttal, routing-classifier, and validator scheduling;
- result and execution-ledger validation;
- aggregation, coverage accounting, and the final stale-snapshot verification.

Ownership is stable for the run. Do not split those responsibilities between a parent and child, transfer a partially built run, or merge ledgers from separate orchestrators. Every reviewer, rebuttal, routing classifier, and validator is dispatched by the owner for that run. Those workers never spawn another worker or invoke this skill as a new orchestrator.

Before starting a run, use the host adapter's concrete capability signal to confirm that the invoking context can create a direct worker. For Claude Code, that signal is whether `Agent` is exposed; the host withholds it at the configured depth limit. If the context cannot delegate, do not create a snapshot, route reviewers, or begin a ledger there. Report independent-review execution as `not_evaluated`; do not simulate perspectives sequentially or pass partially owned artifacts to another context.

If delegation becomes unavailable after the run starts, the owner records every undispatched or unfinished role as `not_evaluated`, reports incomplete coverage, and keeps ownership. It must not hand the live run to another context.

Immediately before aggregation, the same owner re-verifies the immutable snapshot. A mismatch stops aggregation and permits only a stale result that requires a new run.

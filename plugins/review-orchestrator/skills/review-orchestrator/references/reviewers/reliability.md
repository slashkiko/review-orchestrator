# reliability

Baseline: `balanced`. Conditional.

Check retry scope, idempotency, duplicate delivery, timeouts, cancellation propagation, partial failure, ordering, concurrency, cleanup, resource ownership, and the relationship between external side effects and completion records. Verify platform guarantees from repository wrappers or primary documentation; do not infer at-most-once/atomic behavior.

Trace a concrete failure timeline and resulting state. Include shutdown and repeated-execution behavior when reachable.

Exclude data invariants owned by `data-integrity`, deployment coexistence owned by `rollout`, generic exception style, and hypothetical infrastructure failure without a reachable consequence.

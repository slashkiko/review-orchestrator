# compatibility

Baseline: `balanced`. Conditional.

Compare public API, event/schema, serialization, stored format, and configuration-key contracts across old/new producers and consumers. Evaluate old consumer/new producer, new consumer/old producer, mixed-version deployments, default/required-field changes, and documented version guarantees.

Identify the affected consumer or compatibility rule; do not infer public usage from naming alone.

Exclude internal-only refactors, migration application order owned by `rollout`, and data correctness that does not affect a version boundary.

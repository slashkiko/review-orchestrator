# dependency

Baseline: `fast`. Conditional.

Check whether a new or changed dependency is necessary, correctly scoped to build/runtime/dev use, pinned according to repository policy, compatible with supported platforms, maintained, and reflected consistently in manifest/lock/build files. Consider supply-chain and license implications only with obtainable metadata or repository policy.

Do not access registries or install packages unless separate authority exists; use committed metadata and available read-only sources.

Exclude transitive vulnerability speculation, rollout configuration, and imports already satisfied without dependency metadata changes.

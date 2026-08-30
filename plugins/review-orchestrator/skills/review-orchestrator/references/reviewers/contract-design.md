# contract-design

Baseline: `balanced`. Conditional.

Review public types, interfaces, core models, and lifecycle APIs for representable invalid states, ambiguous ownership, nullability/default meaning, temporal coupling, error semantics, and whether callers can use the contract correctly without private knowledge. Compare with existing public conventions and actual call sites.

Report concrete misuse enabled by the new contract or a materially inconsistent public shape, not aesthetic API taste.

Exclude private helper signatures, general simplification, version compatibility, and documentation omissions owned by `docs-dx`.

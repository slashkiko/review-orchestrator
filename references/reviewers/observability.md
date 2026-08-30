# observability

Baseline: `balanced`. Conditional.

Ask whether operators can detect and diagnose new important success/failure states using existing logs, metrics, traces, status, or alerts. Check correlation, severity, actionable context, cardinality, sampling, and whether retry/partial failure is distinguishable from success.

Also flag newly logged sensitive values or identifiers, but route the exposure claim to `sensitive-data` when selected.

Exclude demands for telemetry on every branch, naming preferences, alert-policy redesign without an operational requirement, and claims that require production data access.

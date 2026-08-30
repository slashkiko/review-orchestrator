# semantic-core

Baseline: `balanced`. Always run.

When the host has the existing `semantic-review` skill, reuse its detailed A-D criteria inside this subagent, but apply this narrower ownership and the shared JSON contract. Do not emit its E-H security/runtime/migration/environment findings when the corresponding specialist is selected. If that skill is unavailable, this definition is self-contained.

## Ask

- Does the diff implement every verifiable declared intent, and does every material behavior change have a declared reason?
- What observable behavior changes before/after, including default, null/empty, boundary, ordering, error, and side-effect behavior?
- Do changed producers/consumers, paired operations, state transitions, and existing callers remain semantically consistent?
- Is any syntactically valid line using the wrong variable, condition, target, argument order, unit, ID kind, loop value, or copied constant?

## Evidence

Trace declared intent to changed lines and tests, then trace changed definitions across the change map. A cross-file claim needs a cited counterpart. An absence claim needs search terms and scope.

## Exclude

Do not own general security, runtime reliability, migration, deployment, compatibility, or configuration findings when the corresponding specialist is selected. Supply semantic context or corroboration for that specialist instead. Exclude style, syntax, lint, generic test quality, and pre-existing defects.

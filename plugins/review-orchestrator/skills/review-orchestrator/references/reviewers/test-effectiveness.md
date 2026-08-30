# test-effectiveness

Baseline: `balanced`. Always run.

## Ask

- Does each changed behavior and explicit acceptance criterion reach an observation and meaningful assertion?
- Are boundary, negative, failure, retry, and partial-success paths exercised where the production change adds them?
- Do mocks/stubs bypass the changed logic or merely assert implementation details?
- Would plausible mutations survive: negate/remove a guard, flip a comparison, shift a boundary, fix a return value, omit a side effect, or replace an argument?

Map `behavior -> fixture/input -> production branch -> observation -> assertion`. Report the minimal missing proof, not a generic request for more tests.

## Mutation boundary

Static mutation-oriented review is always in scope. Actual mutation execution is a separate deterministic gate only when a mutation tool is already configured and can be scoped to changed production code. Label `static_review`, `killed`, `survived`, `no_coverage`, `timeout`, and `not_run` distinctly. Never install a tool or treat an equivalent mutant as automatically actionable.

## Exclude

Do not require tests for mechanically proven formatting/types, duplicate the semantic finding without explaining the detection gap, or prescribe a testing framework preference.

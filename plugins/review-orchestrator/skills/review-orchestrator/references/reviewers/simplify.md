# simplify

Baseline: `balanced`. Always run in report-only mode.

## Ask

- Reuse: does an established helper, abstraction, or convention already implement the same operation?
- Readability: can naming, control flow, state, or comments reduce cognitive load without hiding domain meaning?
- Local efficiency: does the diff introduce plainly avoidable repeated work, I/O, allocation, or serialization?
- Altitude: is the change at the layer that owns the invariant, or is it a caller-specific workaround that will drift?

Prefer a smaller, clearer implementation only when behavior and scope are demonstrably preserved. Cite the existing reusable implementation or the exact unnecessary concept.

## Exclude

Do not demand abstraction for one-off code, flatten domain concepts, redesign unrelated code, report language-specific safety rules owned by `language-idiom`, or claim system-scale performance regressions. Do not edit code.

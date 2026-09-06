# deprecation

Baseline: `fast`. Conditional.

Review whether a change that supersedes something finishes the replacement, either in the same diff or under a recorded plan.

## Ask

- Does the superseded path, flag, field, column, endpoint, constant, or configuration key still exist, and is it still reachable?
- Did every caller move, or does the old and the new implementation now both run?
- Do tests, fixtures, and documentation still exercise the shape that was replaced?
- Did a removal leave behind a caller, a migration, a persisted record, or a configured value that still names it?

## Evidence

Cite the surviving definition together with the reference that still reaches it, or the removed definition together with the reference that still points at it. Record the search terms and scope behind a claim that nothing else references the old shape. When the repository documents a deprecation period, treat the still-live path as intended and report only a missing marker or a missing removal record.

## Exclude

Do not report a compatibility window the repository deliberately states, version-boundary breakage owned by `compatibility`, deployment-order coexistence owned by `rollout`, general cleanup owned by `simplify`, or pre-existing dead code the diff does not touch.

# Validation, aggregation, and coverage

## Mechanical validation

Run `scripts/validate_findings.py --snapshot <snapshot> --input <result.json>`. It verifies required fields, enum values, snapshot hash, old/new or non-line locations, evidence paths and line bounds against captured blobs/index/commits, structured unverifiable/coverage/command records, status consistency, sensitive candidate metadata, and exact duplicates. Invalid output is fail-closed: it returns errors without republishing the raw reviewer result. One same-tier retry may repair invalid JSON/schema. A second failure becomes a coverage gap.

## Rebuttal verdicts

Before the validator runs, every mechanically valid finding is challenged by its own rebuttal subagent and the verdicts are checked with `scripts/validate_rebuttals.py --snapshot <snapshot> --input <verdicts.json>`. It verifies the snapshot hash, the target reviewer, the field each verdict requires, and supporting evidence and counter-evidence against the captured blobs, and rejects a repeated target. Invalid output is fail-closed exactly as a reviewer result is. The role and its verdicts are defined in [rebuttal.md](rebuttal.md).

## Validator subagent

After all initial reviewers and their rebuttals terminate, give a separate validator subagent the immutable packet, the mechanically valid findings, and each finding's verdict. Ask it to:

1. verify that the diff introduced or exposed the issue;
2. trace the claimed condition to observable impact;
3. reject claims whose evidence only restates the diff, relies on preference, or assumes unavailable facts;
4. merge findings with the same root cause while preserving corroborating evidence and reviewer provenance;
5. keep materially conflicting supported conclusions under `unresolved` rather than choosing silently;
6. reconcile each finding with its rebuttal verdict, keeping a supported disagreement under `unresolved` instead of preferring either side;
7. request one-tier re-review only under the model-policy escalation conditions.

The validator does not decide whether a proposed patch is safe. That requires a separately authorized fix and fix-validation workflow.

## Prior finding decisions

When the calling implementation workflow supplies prior finding decisions, give that history only to the validator, after discovery and rebuttal. Keep it out of initial reviewer and rebuttal packets. Preserve each prior run reference, snapshot hash, reviewer-local finding ID, claim, and decision with its evidence.

Match repeated issues by cause, precondition, and impact, not by title or a reused local ID. Compare current evidence with the earlier rejection or remediation rationale. Reopen a rejected claim only when new evidence or a changed precondition defeats that rationale; an earlier rejection is not permanently valid. An unchanged supported rationale must not turn into a required fix merely because another reviewer repeats the claim.

Report every supplied prior issue's disposition and links to current corroborating findings, or name the missing evidence under `unverifiable`. A finding absent from the new discovery output is not thereby fixed. This review may assess whether the current snapshot supports a claim, but the calling workflow still owns verification of the fix and its effects.

## Final order

Return:

1. validated findings, highest severity first, each carrying its rebuttal verdict;
2. refuted and weakened findings with the counter-evidence that defeated or narrowed them;
3. unresolved conflicts;
4. unverifiable items that name obtainable missing evidence;
5. coverage.

Coverage must list target and final snapshot hash; reviewed and skipped perspectives with reasons; findings left `not_rebutted` and why; task failures/timeouts; requested and actual model/effort; escalation reasons and before/after IDs; examined and excluded paths; unavailable evidence; commands with scope/outcome/attribution/reason; dynamic checks not run; and stale status.

A clean conclusion requires complete selected-role coverage and valid results, no supported findings, no unresolved conflicts, and no unverifiable items. This includes unverifiable rebuttal verdicts and prior issues; do not waive an open question as non-blocking to issue a clean conclusion. An empty supported-finding list alone is insufficient. A clean review result is not approval of a fix or completion of the calling implementation workflow.

Never collapse these states:

- `passed`: a named command actually succeeded;
- `no_finding`: a reviewer completed its stated scope without a supported issue or an `unverifiable` item;
- `open_questions`: a reviewer completed its stated scope but left `unverifiable` items, with or without findings;
- `not_evaluated`: skipped, failed, timed out, lacked evidence, or was outside available authority.

`validate_findings.py` reports a valid result's `state` as `no_finding`, `open_questions`, `findings`, `partial`, or `failed`; use it rather than re-deriving the state from the result.

If the snapshot is stale, do not issue a clean verdict. If any reviewer is `open_questions`, list its unverifiable items with the conclusion and do not state the review as clean. If any selected reviewer is `not_evaluated`, qualify the conclusion to its actual coverage.

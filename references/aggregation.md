# Validation, aggregation, and coverage

## Mechanical validation

Run `scripts/validate_findings.py --snapshot <snapshot> --input <result.json>`. It verifies required fields, enum values, snapshot hash, old/new or non-line locations, evidence paths and line bounds against captured blobs/index/commits, structured unverifiable/coverage/command records, status consistency, sensitive candidate metadata, and exact duplicates. Invalid output is fail-closed: it returns errors without republishing the raw reviewer result. One same-tier retry may repair invalid JSON/schema. A second failure becomes a coverage gap.

## Validator subagent

After all initial reviewers terminate, give a separate validator subagent the immutable packet and mechanically valid findings. Ask it to:

1. verify that the diff introduced or exposed the issue;
2. trace the claimed condition to observable impact;
3. reject claims whose evidence only restates the diff, relies on preference, or assumes unavailable facts;
4. merge findings with the same root cause while preserving corroborating evidence and reviewer provenance;
5. keep materially conflicting supported conclusions under `unresolved` rather than choosing silently;
6. request one-tier re-review only under the model-policy escalation conditions.

The validator does not decide whether a proposed patch is safe. That requires a separately authorized fix and fix-validation workflow.

## Final order

Return:

1. validated findings, highest severity first;
2. unresolved conflicts;
3. unverifiable items that name obtainable missing evidence;
4. coverage.

Coverage must list target and final snapshot hash; reviewed and skipped perspectives with reasons; task failures/timeouts; requested and actual model/effort; escalation reasons and before/after IDs; examined and excluded paths; unavailable evidence; commands with scope/result; dynamic checks not run; and stale status.

Never collapse these states:

- `passed`: a named command actually succeeded;
- `no_finding`: a reviewer completed its stated scope without a supported issue;
- `not_evaluated`: skipped, failed, timed out, lacked evidence, or was outside available authority.

If the snapshot is stale, do not issue a clean verdict. If any selected reviewer is `not_evaluated`, qualify the conclusion to its actual coverage.

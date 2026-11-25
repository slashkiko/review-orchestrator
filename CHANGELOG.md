# Changelog

## Unreleased (2.0.0)

### Breaking changes

- Rebuttal output must include `supporting_evidence`. `upheld` and `weakened`
  require citations establishing the claim; absence of counter-evidence is not
  support. Regenerate older rebuttal output instead of filling this field
  without reassessing the claim.
- A delegation-capable nested lead can own a review run. The context that starts
  it owns snapshotting, workers, the execution ledger, and aggregation through
  completion. It must not transfer a live run to the parent context.
- Host smoke fixtures use schema v3 and host artifacts use schema v5, including
  nested-owner evidence and verified delegation traces. Regenerate older smoke
  artifacts; they cannot prove the new topology. Smoke adapters inherit the
  host's model and effort defaults and record that requested policy.

### Review behavior

- Give prior finding decisions only to the final validator, after independent
  discovery and rebuttal. Reopen a rejected claim only when new evidence or a
  changed precondition defeats the earlier rationale.
- Require complete coverage and no unresolved or unverifiable items for a clean
  conclusion. `open_questions` remains non-clean, including when there are no
  supported findings. Do not repeat an unchanged snapshot solely to obtain
  consecutive clean results.
- Add a non-delegating Claude review worker and a cross-host nested-owner smoke.
  Timeout terminates the CLI process group so worker processes cannot outlive
  the smoke deadline within that group.

### Fixes

- Fixed snapshot line ranges after a removed line that starts with `-- ` or an
  added line that starts with `++ `, which the diff shows like a file header.
  Later hunks on that side were recorded under a path taken from that line.
- Let `completed` reviewer results carry `unverifiable` questions that were
  examined but not settled, and added an `open_questions` state so such a
  review is never reported as clean.

## v1.4.0 - 2026-09-07

- Added the always-on `convention` reviewer, which owns departures from documented
  repository rules and from patterns established by sibling implementations.
- Added the always-on `comment-integrity` reviewer, which owns a changed comment that
  contradicts the code, count, or location it names.
- Required a cited documented rule or at least two sibling implementations before a
  convention claim counts as a finding, so style opinions remain rejected preferences.
- Added four conditional reviewers: `ci-workflow` for trigger privilege, action
  provenance, and untrusted input reaching a CI shell; `deprecation` for a superseded
  path the change leaves reachable; `localization` for translatability and
  locale-dependent formatting; and `cost` for metered third-party consumption.
- Routed `.github/workflows` to `ci-workflow` alongside `rollout`, translation catalogs
  to `localization`, and a deleted or renamed path to a weak `deprecation` candidate.
- Added the `rebuttal` auxiliary role. One subagent per accepted finding tries to break
  it and returns `upheld`, `weakened`, `refuted`, or `unverifiable`; the validator then
  reconciles each finding with its verdict instead of adjudicating alone.
- Added `scripts/validate_rebuttals.py`, which checks a verdict against the immutable
  snapshot and rejects a `refuted` or `weakened` verdict that cites no counter-evidence.
- Gave each rebuttal its own ledger role key, `rebuttal:<token>`, so the per-role attempt
  sequence stays readable when many rebuttals run at once.

## v1.3.0 - 2026-08-30

- Packaged the shared Skill as an independently installable Codex and Claude
  Code Plugin.
- Added public repository documentation, Apache-2.0 licensing, and CI metadata.
- Preserved one host-neutral Skill source for both agent hosts.

## v1.2 - 2026-08-30

- Added checkout-bound, explicitly approved, one-shot mechanical gate execution.
- Added exact scope-gap qualification without mutating the captured snapshot.
- Added deterministic routing corpus metrics and strict cross-host contract validation.
- Added fixed read-only Codex and Claude Code discovery/runtime smoke adapters.

Validation:

- All 70 local tests passed.
- Deterministic routing corpus passed with high-risk recall `1.0` and conditional precision `0.857`.
- Independent execution-safety and cross-host contract reviewers approved the final implementation.
- Codex discovery/runtime smoke passed with Luna at low effort.
- Claude Code discovery/runtime smoke was `unavailable` because the local CLI was not authenticated. v1.2 therefore does not claim a passed cross-host runtime smoke.

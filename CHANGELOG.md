# Changelog

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

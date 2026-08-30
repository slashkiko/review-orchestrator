# Changelog

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

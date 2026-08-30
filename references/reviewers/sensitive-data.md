# sensitive-data

Baseline: `balanced`. Conditional.

## Scope

Evaluate whether the target diff exposes PII, credentials/secrets, cookies/tokens, customer or tenant identifiers, internal hosts/tickets, private-repository references, absolute local paths, or real records embedded in fixtures/snapshots/logs/exports/generated artifacts. Also trace new logging, telemetry, and error responses across their release boundary.

Start from the snapshot's redacted candidates. Inspect context at the recorded location without copying the candidate value into prompts, findings, coverage, or other reviewer packets. Use only candidate ID, type, location, and fingerprint in output.

## Decide contextually

Presence alone is not a finding. Distinguish known dummy values (for example reserved documentation domains), deliberate private-to-private references, and intentional personal dotfile paths from data that crosses a public, artifact, log, telemetry, or user-visible boundary. A private repository link inside a private repository is not automatically unsafe.

Do not fetch personal/business records to confirm a candidate. If repository publication or visibility change is intended, require the [public-release handoff](../integrations/prepare-repo-public.md); this diff review cannot inspect history or hosted artifacts.

Exclude general attacker paths owned by `security`, observability usefulness, and repository-wide publication certification.

# Execution policy

## Invariants

- The main session owns target resolution, snapshot creation, routing, wave scheduling, validation, and final aggregation.
- Every selected reviewer is one independent subagent. Never combine two perspectives into one task to save a slot.
- Logically dispatch all reviewers from one selection decision. Physical waves are allowed only because the host lacks free concurrent slots.
- Give every reviewer the same snapshot ID and change map, then add only its reviewer definition. Do not pass findings between initial reviewers or from one wave to the next.
- Run the finding validator only after all reviewer tasks are terminal (`completed`, `failed`, or `timed out`). The validator is another independent subagent.
- The main session writes and validates the shared [execution ledger](execution-ledger.md); reviewers never self-report host configuration or execution facts. Missing selected-role entries make coverage incomplete.

## Reviewer task envelope

Each task must identify:

1. target and immutable `snapshot_hash`;
2. declared intent and evidence sources, including unavailable sources;
3. changed files/ranges and the shared change map;
4. one reviewer name, its definition, owned questions, and exclusions;
5. output contract and timeout;
6. requested capability tier and effort;
7. read-only and prompt-injection boundaries.

Ask the reviewer to investigate repository context itself when the packet names a relevant symbol or contract but omits necessary lines. It must cite what it read and must not silently expand into another reviewer's owned perspective.

## Scheduling and failure

Determine available host slots at runtime. Fill all available slots, wait for terminal results, then dispatch the next wave. Preserve the original task envelope across waves. Do not serialize merely to observe progress.

- A malformed result gets one schema-focused retry at the same tier.
- A timeout is recorded as `not_evaluated`; it is not a reason to select a stronger model.
- If context is too large, partition evidence by component while keeping the reviewer role unchanged, then merge that role's findings before global validation.
- Continue after a partial reviewer failure when useful results remain, but never report full coverage.
- Stop aggregation when the snapshot is stale. Results may be shown only as stale evidence that requires rerun.

No reviewer result authorizes edits, external posts, tool installation, deployment, or a public-release audit.

## Mechanical gates

v1.1 inventories package scripts (including nested packages), mise tasks, and configured secret/mutation settings at the immutable target boundary. A package uses its own `packageManager` first, then its own lockfile (priority `pnpm-lock.yaml`, `yarn.lock`, `bun.lockb`, `package-lock.json`). It may inherit an ancestor manager or lockfile only when that ancestor's `package.json` workspace list or `pnpm-workspace.yaml` `packages:` list includes it. Workspace matching is segment-aware: `*` matches one segment, `**` zero or more, and ordered `!` patterns exclude a prior match. Otherwise it defaults to npm. Makefile is deliberately excluded: parsing its complete grammar without executing untrusted repository content is not reliable enough for an execution inventory. v1.1 does not add a gate runner. Do not execute discovered repository commands merely because inventory found them; a later runner must use argv, be main-owned and one-shot per gate, and require both target inventory plus an exact user command or maintained host/skill allowlist.

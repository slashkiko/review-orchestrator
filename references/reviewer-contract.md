# Reviewer and finding contract

## Reviewer result

Return one JSON object and no prose outside it:

```json
{
  "reviewer": "semantic-core",
  "snapshot_hash": "sha256 hex",
  "status": "completed",
  "summary": "short result",
  "findings": [],
  "unverifiable": [],
  "coverage": {
    "examined": ["path or symbol"],
    "not_examined": [{"area": "contract", "reason": "why it was not evaluated"}],
    "commands": [{"command": "...", "scope": "changed package", "result": "passed|failed|not_run", "summary": "redacted result"}]
  }
}
```

`status` is `completed`, `partial`, or `failed`. `completed` requires examined coverage and no unevaluated items. `partial` requires both examined and not-examined coverage. `failed` has no findings, unverifiable items, or examined coverage and must name the unevaluated area. An empty `findings` array means no supported finding only for the areas in `coverage.examined`.

Each `unverifiable` item has non-empty `id`, `claim`, `missing_evidence`, `why_it_matters`, and `retrieval` fields. Do not use an unstructured string.

## Finding schema

```json
{
  "id": "temporary reviewer-local ID",
  "reviewer": "semantic-core",
  "snapshot_hash": "sha256 hex",
  "title": "imperative and specific",
  "claim": "what is wrong and under which conditions",
  "impact": "observable consequence",
  "severity": "critical|high|medium|low",
  "confidence": "high|medium|low",
  "introduced_by_diff": true,
  "location": {"path": "repo/relative", "side": "new", "start_line": 10, "end_line": 12, "change_kind": null},
  "evidence": [
    {"path": "repo/relative", "side": "new", "line": 10, "reason": "fact supporting the claim"}
  ],
  "validation": {"method": "static|command|external-primary-source", "details": "what was checked"}
}
```

All fields are required. A line location uses `side: old|new`, positive line bounds, and `change_kind: null`; it must overlap that side's captured changed range. A non-line location uses `side: none`, null line bounds, and one captured `change_kind`: `addition`, `deletion`, `rename`, `copy`, `mode`, or `binary`. Evidence uses `side: old|new` and is checked against the immutable target blob/index/commit rather than the current worktree. Evidence must support causality, not merely repeat the changed line. Cite external material by stable document/version/section without copying a raw sensitive URL or record.

`sensitive-data` findings additionally require:

```json
"sensitive_candidate": {
  "candidate_id": "redacted snapshot candidate ID",
  "type": "candidate type",
  "fingerprint": "redacted fingerprint"
}
```

The three values must match one snapshot candidate, and the finding location must be a `side: new` line location covering its exact path and line; a non-line location never satisfies candidate coverage. No free-text field—including summary, coverage, commands, unverifiable entries, evidence, or validation details—may repeat the exact raw candidate value. For credential assignments and Bearer headers, the derived bare secret/token is protected too. Validation resolves these values from the immutable snapshot target and does not reject unrelated public URLs or documented dummy emails merely because they match a general pattern. Invalid output is rejected without echoing the original result.

## Quality rules

- Report only issues introduced or made materially reachable by the target diff.
- State preconditions and observable impact. Do not report preferences, speculative future requirements, or mechanically detectable syntax/format/type failures as LLM findings.
- Use the narrowest relevant reviewer owner. If the issue crosses domains, identify the primary cause and let aggregation merge corroboration.
- `confidence: low` may describe an `unverifiable` item but should not be presented as a defect unless evidence still establishes the claim.
- Sensitive-data findings contain type, location, and redacted fingerprint/candidate ID. Never repeat the detected value.
- Fix suggestions are optional context, not validated remediations.

`unverifiable` entries must name the exact missing evidence, why it matters, and how it could be obtained without expanding authority.

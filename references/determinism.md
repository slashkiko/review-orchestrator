# Deterministic, hybrid, and LLM boundaries

Do not ask a model to rediscover a fact in the deterministic column. Do not present an LLM conclusion as a command result.

| Boundary | Processing | Output |
| --- | --- | --- |
| Deterministic | target/base/head resolution, changed/untracked files, diff hash, old/new line ranges, non-line changes, old/new blob/mode hashes, language/file-role and route candidates | canonical snapshot JSON; identity covers mode, captured commits, diff, target blobs/metadata, routes, candidates, and configured gates |
| Deterministic | added-line candidate extraction for credentials, email, internal/private URL, and absolute local path; configured gate discovery from range head, staged index, or working tree according to target mode | redacted candidate ID/type/location/fingerprint; never extracted value |
| Deterministic | already-configured format/parse/build/type/lint/test/secret/mutation command execution | exact command, scope, exit status, captured result summary; `not_run` is distinct |
| Deterministic | finding schema, enum/hash/location/evidence checks, exact duplicate removal, task/timeout status, stale verification | validated JSON and coverage facts |
| Hybrid | change map | mechanical symbol/path candidates first; LLM expands implicit contracts, paired operations, and downstream meaning |
| Hybrid | reviewer routing | path/file/keyword candidates first; a fast classifier decides only genuinely ambiguous relevance |
| LLM | semantic, simplification, test-effectiveness, and specialist reviews | causal and contextual claims under one reviewer contract |
| Hybrid | aggregation | mechanical validity first; validator subagent decides shared cause, reachability, impact, confidence, and material conflict |
| Hybrid | coverage | execution facts are mechanical; LLM may summarize residual risk without changing those facts |

`validate_findings.py` resolves each candidate's exact raw match from the immutable target and rejects only that value (plus a credential assignment's or Bearer header's derived bare token) when it is copied into reviewer output. It does not apply broad secret/PII patterns to unrelated output text. `review_snapshot.py` does not select reviewers or claim impact. `validate_findings.py` does not determine whether a claim is true or whether a fix is safe. Those limits are part of their contract, not implementation gaps.

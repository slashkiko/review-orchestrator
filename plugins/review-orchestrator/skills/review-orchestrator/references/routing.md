# Reviewer routing

Routing is hybrid: deterministic candidates carry `path`, optional `line`, `matched_rule`, `source`, `strength`, and reason. Record every selected reviewer and every skipped reviewer with its reason. Multiple conditional reviewers may run.

## Always select

| Reviewer | Definition | Ownership |
| --- | --- | --- |
| `semantic-core` | [reviewers/semantic-core.md](reviewers/semantic-core.md) | declared intent, behavior, end-to-end meaning, diff-exposed semantic mistakes |
| `simplify` | [reviewers/simplify.md](reviewers/simplify.md) | reuse, readability, local efficiency, abstraction altitude |
| `test-effectiveness` | [reviewers/test-effectiveness.md](reviewers/test-effectiveness.md) | whether tests can detect the changed behavior, including mutation-oriented static analysis |

## Conditional routes

| Reviewer | Select when the change meaningfully touches | Do not select solely for |
| --- | --- | --- |
| [language-idiom](reviewers/language-idiom.md) | language-specific concurrency, resource, type, exception, ownership, or runtime idioms beyond configured lint | syntax, formatting, ordinary readability |
| [security](reviewers/security.md) | authentication/authorization, trust boundaries, external input, files/network, deserialization, credential use | a token-like literal alone (route sensitive-data) |
| [reliability](reviewers/reliability.md) | async/queue/retry/timeout/cancellation, external I/O, resource lifecycle, partial failure | ordinary local exceptions with no lifecycle effect |
| [data-integrity](reviewers/data-integrity.md) | persistence writes, constraints, backfills, partial updates, deduplication, precision, time semantics | read-only presentation transformations |
| [compatibility](reviewers/compatibility.md) | public API/event/schema, persisted format, configuration key, versioned protocol | private implementation-only signature changes |
| [rollout](reviewers/rollout.md) | migration, feature flag, environment variable, deploy manifest, phased release or rollback behavior | dependency manifest alone without rollout effect |
| [observability](reviewers/observability.md) | services/jobs/external integration or an operationally important failure path | incidental debug output with no production path |
| [contract-design](reviewers/contract-design.md) | public types/interfaces, core data model, ownership/nullability/lifecycle contract | local variable or private helper shape |
| [performance](reviewers/performance.md) | database query, batch/hot path/render loop, allocation/I/O volume, algorithmic scale | tiny local waste owned by simplify |
| [dependency](reviewers/dependency.md) | dependency/build manifest or lockfile changes | imports satisfied by an existing dependency |
| [accessibility](reviewers/accessibility.md) | user interface, HTML/component semantics, input or navigation flow | non-interactive styling with no accessibility effect |
| [docs-dx](reviewers/docs-dx.md) | public API/CLI/configuration/error/usage or migration experience | purely internal implementation detail |
| [sensitive-data](reviewers/sensitive-data.md) | docs/fixtures/snapshots/logs/exports/config/generated output/telemetry/error response, or redacted absolute-path/email/credential/internal/private-URL candidates | a known dummy value with no release/logging boundary after contextual confirmation |

`manifest` is deliberately not a sufficient route by itself for both dependency and rollout: select dependency for package/build supply changes, rollout for deployment/configuration order. Similarly, `language-idiom` and `simplify` may both be selected, but language-idiom excludes general readability and local cleanup.

Structural auth boundaries, migration/backfill paths, public schemas/protocols, deployment manifests, dependency manifests, UI surfaces, and redacted sensitive-data candidates are `strong`. Keyword matches in YAML, documentation, comments, string bodies, and other text are always `weak`, even when they say `async`, `auth`, or `rollout`; they do not select a reviewer by themselves.

Use the fast route classifier once for the complete weak-candidate set, not once per route. It returns selected reviewer names and evidence locations, not findings. Feed the immutable snapshot plus either its completed result or failure state to `scripts/route_selection.py`; its JSON is the deterministic selection record. If it fails, select all strong routes and the redacted sensitive-data route as usual, then fail open only for weak `security`, `data-integrity`, `reliability`, and `rollout` candidates, with at most four **additional weak** conditional reviewers. Strong routes and the three core reviewers do not consume that fallback budget. Mark every other weak-only candidate `not_evaluated:routing_classifier_failed`; do not retry the classifier or add a later routing wave. This is a classifier-failure policy, not a reason to alter model tier: retain [model policy](model-policy.md) until labeled fixture calibration supports a change.

If publication or visibility change is intended, also read [integrations/prepare-repo-public.md](integrations/prepare-repo-public.md). This is a handoff requirement, not a fourteenth conditional reviewer.

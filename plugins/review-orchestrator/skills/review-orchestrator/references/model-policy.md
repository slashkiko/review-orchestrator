# Model and effort policy

The shared policy names capability tiers. The host adapter resolves them to models available at execution time and records the requested and actual model/effort.

| Tier | Baseline roles | Intended capability |
| --- | --- | --- |
| `fast` | `language-idiom`, `dependency`, `accessibility`, `docs-dx`, ambiguous route classifier | Narrow, evidence-local classification and review |
| `balanced` | `semantic-core`, `simplify`, `test-effectiveness`, `reliability`, `compatibility`, `observability`, `contract-design`, `performance`, `sensitive-data`, validator without major conflict | Cross-file causal reasoning |
| `deep` | high-risk `security`, `data-integrity`/migration, `rollout`; rebuttal of a major finding or material conflict | High-stakes, multi-contract reasoning |

Start each role at its baseline. If the host cannot select a requested model or effort, use the smallest available substitute likely to meet the tier and record the substitution; never pretend the requested configuration ran.

## Escalation

Escalate only the affected role by one tier when at least one condition holds:

- potential impact is high but confidence remains low despite available evidence;
- the role reports `unverifiable` although the packet identifies obtainable evidence;
- two supported findings materially conflict on a high-impact outcome;
- a maintained role fixture demonstrates that the baseline misses its acceptance threshold.

Do not escalate because there are no findings, context is large, output was malformed once, or a task timed out. Partition large context, retry malformed schema once at the same tier, and report timeout in coverage.

## Host mappings

- Codex initial mapping: `fast` = Luna/low, `balanced` = Terra/medium, `deep` = Sol/high. Use currently available equivalents when aliases change.
- Claude Code initial mapping: `fast` = Haiku with effort omitted, `balanced` = Sonnet/medium, `deep` = Opus/high. Omit unsupported effort fields.

Calibrate per role against representative fixtures by lowering tier or effort one step at a time. Retain the lowest configuration that preserves accepted recall, precision, evidence quality, and schema compliance. Do not infer calibration from a single real review.

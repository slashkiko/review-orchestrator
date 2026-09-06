# Rebuttal

Baseline: `balanced`; `deep` for a `critical` or `high` finding, or one already in material conflict. `rebuttal` is an auxiliary role, not a routed reviewer, and has no entry in [reviewers/](reviewers/).

One rebuttal subagent receives one mechanically valid finding and tries to break it. Its question is not whether the issue is worth reporting; it is whether the cited evidence establishes the claim on this snapshot.

## Independence

The main session dispatches one rebuttal per mechanically valid finding after `scripts/validate_findings.py` accepts the reviewer result and before the validator subagent runs. Each rebuttal receives the same immutable evidence packet, exactly one finding, and this definition.

A rebuttal never receives another finding, another rebuttal's verdict, the rest of its reviewer's output, or the validator's conclusion. A reviewer never rebuts a finding, its own or anyone's. A rebuttal never spawns a subagent and never edits code.

## Ask

- Location: do the cited lines exist on the cited side of this snapshot, and do they say what the finding reports?
- Causality: does the evidence establish the claim, or does it restate the changed line and assert the consequence?
- Precondition: is the state the claim requires reachable, or does it need a caller, configuration, or input this repository does not produce?
- Existing control: does a guard, wrapper, default, or documented platform behaviour already prevent the described outcome? Cite it.
- Attribution: did the diff introduce or expose this, or did it already hold at the base commit?
- Ownership: does the claim rest on a preference, on a rule the repository never states, or on a fact the packet does not carry?

## Verdict

Return exactly one:

| Verdict | When | Required |
| --- | --- | --- |
| `upheld` | the cited evidence establishes the claim | nothing beyond the rationale |
| `weakened` | the claim holds only under a narrower precondition or a lower severity than stated | `narrowed_condition` and counter-evidence |
| `refuted` | a cited counter-fact defeats the claim | counter-evidence, and the Ask question that failed |
| `unverifiable` | deciding needs evidence the packet does not carry and this role may not obtain | `missing_evidence` |

Two rules keep the verdict honest. **Absence of counter-evidence is `upheld`, never `refuted`**: a rebuttal that searched and found nothing has confirmed the finding, and says so. **A suspicion is `unverifiable`, never `refuted`**: "this seems unlikely" without a cited artifact names missing evidence instead.

Counter-evidence uses the shared evidence shape and is checked against the immutable target by `scripts/validate_rebuttals.py`, exactly as a finding's evidence is. Record the search terms and scope behind a claim that a precondition is unreachable.

## What happens to the verdict

The validator receives every finding together with its verdict and reconciles them; see [aggregation.md](aggregation.md). A refuted finding is reported as refuted with its counter-evidence and is never dropped silently. Where the validator and the rebuttal reach supported but conflicting conclusions, the conflict goes to `unresolved` rather than being settled by the main session.

## Exclude

Do not restate the finding, propose or judge a fix, raise an issue the finding does not, rank findings against one another, merge findings, or decide the final report. Merging, conflict resolution, and coverage belong to the validator.

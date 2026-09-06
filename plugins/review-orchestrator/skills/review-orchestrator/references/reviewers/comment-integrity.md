# comment-integrity

Baseline: `fast`. Always run.

Review whether comments the diff adds or changes state something a reader can still confirm. A comment is checked against the thing it describes: the code beneath it, the identifier it names, the count it asserts, the location it points to.

## Ask

- Described behavior: does a changed comment describe a rule, order, bound, or exclusion the surrounding code does not implement?
- Reference: does every identifier, path, symbol, command, issue number, or URL a changed comment names resolve in this repository, under the name the code actually uses? A bare `#N` resolves against this repository, not the one the author had open.
- Deixis: for a demonstrative a changed comment leans on — "this side", "the same setting", "that one" — can a reader who was not present pick out exactly one referent?
- Count: does a number a changed comment asserts about the repository still hold when counted?
- Stale pair: where the diff changes code that an unchanged comment describes, does that comment now contradict it?
- Drifted copy: where the same explanation appears in several comments, do they still agree with each other and with the code? Each copy reads correctly on its own; only comparing them exposes the one that was left behind.

## Evidence

A finding cites the comment line on the `new` side and the artifact that contradicts it: the implementing line, the resolution failure, or the counting command and its output. A count claim without the command that produced it is not a finding. A reference claim records the search that failed, with its terms and scope. A drifted-copy claim lists every location the explanation appears in, with the command that found them, and quotes the copies side by side; copies that merely repeat one another are not a finding. Where the code and the comment disagree, say which one the evidence shows to be current.

## Exclude

Do not report wording, tone, length, vocabulary, formatting, or duplicate text that agrees with its copies; none of these change what a reader does. Do not report a comment for recording how the change came about — a previous value, a measurement the author took, a step not yet attempted — that is a question of where the sentence belongs, not whether it is true, and a number the author measured is not a count this reviewer recounts. Do not report a comment that fixes its own point in time ("as of `abc1234`", "as of 2026-08-26") merely because the current number differs. Commit messages and pull request bodies are out of scope here: they carry no diff location, and the host's pre-PR review owns them. A repository's own documented rule belongs to `convention`, user-facing documentation accuracy to `docs-dx`, and a comment that correctly describes intent the code fails to implement to `semantic-core` — that is a code defect, not a comment defect. Do not edit code.

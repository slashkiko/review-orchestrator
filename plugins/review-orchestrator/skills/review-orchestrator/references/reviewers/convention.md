# convention

Baseline: `balanced`. Always run.

Review whether the change follows the conventions its own repository already establishes, limited to rules that configured tooling does not decide.

## Ask

- Documented rule: does the change contradict a repository instruction, style guide, ADR, or contributing document that states a naming, comment, structure, or procedure rule?
- Peer pattern: do sibling implementations in the same layer, module, or role share a required step, ordering, wrapper, annotation, or error/log convention that this change omits or reverses?
- Naming and comments: do introduced identifiers, files, and comments follow the scheme their neighbours actually use, including a doc comment the changed surface requires?
- Placement: does new code sit where the existing structure already puts that responsibility?

## Evidence

A finding cites either the exact documented rule with its path and line, or at least two sibling implementations that establish the pattern. One neighbour is a coincidence, not a convention. An omission claim records the search terms and scope used to establish that the diff lacks the counterpart its peers have. Prefer the repository's own words over general community style, and check whether the cited pattern is current rather than one the repository is migrating away from.

## Exclude

Do not report what a configured formatter, linter, or type checker already decides, a rule the repository neither states nor practices, or an extrapolation from a single example. Reuse of an existing helper belongs to `simplify`, language-specific hazards to `language-idiom`, whether operators can detect a failure to `observability`, and user-facing documentation accuracy to `docs-dx`. Do not edit code.

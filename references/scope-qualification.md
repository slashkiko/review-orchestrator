# Scope qualification

Use `scripts/qualify_scope.py` only with an actual user approval artifact, never one synthesized by the main agent. It binds a snapshot hash to every exact gap path/kind/fingerprint (or path/kind where the snapshot has no fingerprint), a non-empty generalized reason, and an approval reference.

The snapshot remains immutable and is recreated before qualification. `complete` is valid only for an empty, well-formed gap list; `blocked` is valid only for a non-empty list. All and only current gaps approved becomes `qualified`; partial, stale, duplicate, malformed, unmatched, or unsafe approval remains `blocked` and invalid. The output intentionally omits free-form approval text. `qualified` permits “no findings within qualified scope,” but never “full repository” or “full coverage.”

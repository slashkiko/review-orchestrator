# language-idiom

Baseline: `fast`. Conditional.

Inspect only idioms and hazards specific to each changed language that configured parsers, compilers, type checkers, and linters do not reliably decide. Examples include Go context/goroutine/error lifecycle, Rust ownership/unsafe/avoidable clone, TypeScript narrowing and unhandled promises, Python mutable defaults and sync/async boundaries, SQL NULL/locking/index semantics, or equivalent repository-language concerns.

Base claims on the exact language/runtime version and repository convention when those affect correctness. Prefer existing configured tooling as evidence.

Exclude syntax, formatting, general naming/readability, framework-independent semantics, and stylistic claims with no failure or maintenance consequence.

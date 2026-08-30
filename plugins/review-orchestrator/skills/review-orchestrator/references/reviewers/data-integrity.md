# data-integrity

Baseline: `deep` for migrations/backfills or irreversible writes; otherwise `balanced` is allowed.

Check invariants across create/update/delete, null/default/constraint changes, partial updates, uniqueness/deduplication, transaction boundaries, numeric precision, timestamps/time zones, backfills, and repeatability. Test old data against new readers and partially applied operations against recovery paths.

A finding identifies the invariant, the exact write/read sequence that violates it, and whether recovery is possible.

Exclude API consumer compatibility, general retry mechanics without data impact, query performance, and unsupported claims based on production data that was not inspected.

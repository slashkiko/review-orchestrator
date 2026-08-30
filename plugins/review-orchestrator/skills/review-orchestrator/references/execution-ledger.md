# Execution ledger

The main orchestrator, never a reviewer, records one entry for each attempted selected role in a host-neutral ledger and validates it with `scripts/validate_execution_ledger.py`. The ledger is an audit record, not reviewer self-report.

```json
{
  "schema_version": 1,
  "snapshot_hash": "sha256 hex",
  "selected_roles": ["semantic-core"],
  "entries": [{
    "role": "semantic-core",
    "requested": {"tier": "balanced", "model": "gpt-5.6-terra", "effort": "medium"},
    "actual": {"exposure": "reported", "model": "gpt-5.6-terra", "effort": "medium"},
    "host_task_id": "host task identifier",
    "attempt": 1,
    "retry_or_escalation_reason": null,
    "terminal_status": "completed",
    "timeout_seconds": 900,
    "schema_validation": "passed"
  }]
}
```

`requested.tier` is `fast`, `balanced`, or `deep`. Actual configuration is either reported or explicitly `{ "exposure": "not_exposed", "model": null, "effort": null }`; do not infer it. Terminal status is `completed`, `failed`, `timed_out`, `cancelled`, or `not_started`; schema validation is `passed`, `failed`, or `not_run`.

Every selected role needs at least one entry, every entry role must be selected, and `semantic-core`, `simplify`, and `test-effectiveness` are mandatory selected roles. Known auxiliaries (`validator`, `routing-classifier`) are valid only when selected. `snapshot_hash` is lowercase 64-character hex; attempts are contiguous from 1 per role, attempts after 1 name a retry/escalation reason, and host task IDs are unique. Completed tasks record schema validation `passed|failed`; all non-completed terminal states record `not_run`. A reported actual configuration includes a model (effort may be null when unsupported). A missing role, invalid entry, or failed ledger validation means execution coverage is `incomplete`; it cannot be summarized as a clean review. Only a maintained fixture can justify tier/effort changes; a timeout or one real review cannot.

# cost

Baseline: `fast`. Conditional.

Review the metered consumption the change commits to: billed third-party calls, model tokens, network egress, stored and retained bytes, and provider quota or rate-limit headroom.

Ask what one request and one scheduled run consume, how that scales with the traffic or data volume the repository already handles, whether a retry, fan-out, loop, or backfill multiplies it, and what happens when the quota is exhausted rather than merely approached.

A finding names the consuming call site and the multiplier or growth rate. Use committed pricing, quota configuration, or limits the repository documents; when none are available, report the unverifiable quantity instead of estimating a price.

Exclude compute efficiency owned by `performance`, dependency footprint owned by `dependency`, infrastructure sizing the diff does not change, and speculative bills with no evidence of scale.

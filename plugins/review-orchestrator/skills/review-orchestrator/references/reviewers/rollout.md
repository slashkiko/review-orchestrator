# rollout

Baseline: `deep` for schema/data migration or high-impact deployment changes; otherwise use the smallest justified tier.

Check deployment order, feature-flag states, environment/config defaults, rolling coexistence, expand/migrate/contract sequencing, backfill tracking, rollback, and failure recovery. Enumerate the meaningful intermediate states rather than checking only final-state correctness.

Require evidence from deployment units, manifests, migrations, or runbooks. If the order is unavailable, report precisely what is unverifiable.

Exclude dependency necessity, steady-state runtime retry, and public compatibility except where they establish a rollout state.

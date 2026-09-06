# ci-workflow

Baseline: `balanced`. Conditional.

Review continuous-integration and automation definitions as a privileged execution surface: which trigger runs them, what token and secrets that trigger exposes, whose code they execute, and what untrusted text reaches a shell.

Check trigger and privilege pairing, especially a trigger that runs on outside contributions together with a writable token, a repository secret, or a checkout of the contributed revision. Check the privilege actually granted against least privilege, third-party action and container provenance and pinning against repository policy, interpolation of event-controlled text into a script body, secret and artifact exposure through logs, caches, and uploads, and runner and concurrency assumptions.

A finding names the trigger, the privilege or secret it exposes, and the path an outside contributor takes to reach it. Use the repository's own pinning and permission policy when one exists; otherwise name the platform default the definition relies on.

Exclude application-code trust boundaries owned by `security`, deployment ordering and rollback owned by `rollout`, dependency necessity owned by `dependency`, and build preferences with no privilege or provenance consequence. Do not run a workflow.

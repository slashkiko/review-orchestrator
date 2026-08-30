# Public-release handoff

Trigger this handoff when the user intends to make a repository public, open-source it, publish a curated repository artifact, or asks whether the whole repository is safe to publish.

The current diff review may still report sensitive data newly introduced by the target, but it cannot certify publication safety. Git history, existing files outside the diff, Actions logs/artifacts, issues/PRs, repository settings, licensing, private-repository references, and other GitHub-hosted content require a repository-wide public-release audit such as `prepare-repo-public`.

Do not invoke that audit merely because a candidate was found. Report the required handoff and obtain separate authorization for its broader reads or any remediation. Never change repository visibility, rewrite history, delete hosted content, or publish from this skill.

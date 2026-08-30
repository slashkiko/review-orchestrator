# review-orchestrator

`review-orchestrator` runs an explicitly requested multi-perspective review of
one immutable code-change snapshot. It routes the snapshot to independent
specialist agents, validates their evidence, and reports findings with explicit
coverage and unresolved conflicts.

It supports pull requests, commit ranges, staged changes, and working-tree
changes. It does not modify code, post comments, or replace a repository-wide
security or public-release audit.

## Install

### Codex

```shell
codex plugin marketplace add slashkiko/review-orchestrator --ref main
codex plugin add review-orchestrator@review-orchestrator
```

To update:

```shell
codex plugin marketplace upgrade review-orchestrator
codex plugin add review-orchestrator@review-orchestrator
```

### Claude Code

```shell
claude plugin marketplace add slashkiko/review-orchestrator
claude plugin install review-orchestrator@review-orchestrator
```

To update:

```shell
claude plugin marketplace update review-orchestrator
claude plugin update review-orchestrator@review-orchestrator
```

Both hosts install stable copies into host-owned locations. The repository is
the release source, not mutable runtime state.

## Usage

Ask for multiple independent review perspectives or explicitly invoke
`review-orchestrator`. A generic request for a single code review does not
trigger the orchestration workflow.

## Layout

```text
.agents/plugins/marketplace.json
.claude-plugin/marketplace.json
plugins/
  review-orchestrator/
    .codex-plugin/plugin.json
    .claude-plugin/plugin.json
    skills/
      review-orchestrator/
        SKILL.md
        agents/
        fixtures/
        references/
        scripts/
        tests/
```

## Validate

```shell
python3 -m unittest discover -s tests -p 'test_*.py'
python3 -m unittest discover \
  -s plugins/review-orchestrator/skills/review-orchestrator/tests \
  -p 'test_*.py'
```

See `CONTRIBUTING.md` for the complete local gate and `SECURITY.md` for private
vulnerability reporting.

## License

Apache License 2.0. See `LICENSE`.

# Contributing

Keep the host-neutral review contract in the shared Skill. Codex and Claude
metadata should remain thin adapters around the same files.

Before submitting a change, run:

```shell
python3 -m unittest discover -s tests -p 'test_*.py'
python3 -m unittest discover \
  -s plugins/review-orchestrator/skills/review-orchestrator/tests \
  -p 'test_*.py'
```

Maintainers should also run the current Codex plugin validator when it is
available locally. Repository CI remains portable and does not depend on a
personal filesystem path.

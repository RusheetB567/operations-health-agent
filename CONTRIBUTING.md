# Contributing

Use focused changes that solve an operational problem and include evidence. Existing repository commit and publication preferences remain under the owner's control.

## Local verification

```powershell
.\.venv\Scripts\python -m unittest discover -s tests -v
.\.venv\Scripts\python tools/demo_local.py
.\.venv\Scripts\python tools/check_docs.py
.\.venv\Scripts\python tools/verify_regressions.py
git diff --check
```

Tests use loopback servers and temporary directories. They should not require credentials, public endpoints, fixed application ports or user data. Add regression cases for observable failures; avoid tests that merely repeat implementation details.

The defect-injection tool changes temporary copies only. Its three scenarios measure sensitivity to specific known failures, not exhaustive mutation coverage.

## Review boundaries

Keep implementation, substantial regression coverage and documentation/demo changes reviewable. Do not split changes solely to inflate counts. Exclude generated reports, local databases, virtual environments, caches and personal configurations. Check tracked generated files explicitly because ignore rules are not retroactive.

Describe the problem, resulting behaviour, tests run and remaining limits. Do not claim remote CI, Linux execution, TLS integration coverage or real-application verification without evidence.

See [architecture](docs/ARCHITECTURE.md) before changing report or persistence contracts.

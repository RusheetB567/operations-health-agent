# Service catalogue monitoring

Check the components of an application together instead of assuming a running backend means the whole application works.

```powershell
.\.venv\Scripts\python service_monitor.py services.example.json --check
.\.venv\Scripts\python service_monitor.py services.example.json --workers 4 --output reports/services.json
.\.venv\Scripts\python service_monitor.py services.example.json --group application
```

The example contains illustrative local frontend, API and database endpoints. Replace them with services you operate. Those example services are not installed or started by this tool, so checks can correctly return warnings when they are absent.

## Catalogue contract

The root contains exactly `version: 1` and a `services` array of 1–100 entries. Duplicate JSON keys, unknown properties and duplicate service names are rejected before any checks run.

| Field | Meaning |
| --- | --- |
| name | Unique service identifier, 1–64 letters, digits, dots, underscores or hyphens; starts with letter or digit |
| group | Optional application or infrastructure group; defaults to `default`; same format as name |
| type | `http` or `tcp` |
| target | HTTP(S) URL or TCP `HOST:PORT`; IPv6 uses `[::1]:5432` |
| timeout | Per-check timeout, greater than zero and at most 60 seconds; defaults to 3 |
| expected_status | HTTP-only integer from 100 to 599; defaults to 200 |

HTTP targets cannot contain credentials, query strings or fragments. Use dedicated read-only readiness endpoints. HTTP redirects are not followed and HTTPS certificates are verified using Python defaults. TCP success proves only that a connection opened.

## Results and failure behaviour

The JSON report includes named results in catalogue order, detailed diagnostic outcomes, per-group counts and a combined summary. One failed service makes the overall result `warning`. Exit codes are `0` for all healthy, `1` for one or more warnings, and `2` for invalid configuration or input/output failure.

Use `--check` to validate without network requests or report writes. `--group` selects one group and rejects an unknown group. Worker count is 1–16, default 4. Worker exceptions become sanitized internal-error results and do not cancel other services. Reports use the existing atomic replacement writer.

Each check has its own timeout; checks queued behind workers have not started their timeout yet. Total runtime therefore depends on catalogue size, worker count and process startup/cleanup. There is no whole-catalogue deadline. Output retains endpoint addresses and should be treated as operational data. There is no continuous scheduling, automatic restart, service discovery or authenticated browser testing.

## Delivery layers

- **2.1 — Implementation:** `run_profile.py`, `local-profile.example.json`, `service_monitor.py`, `services.example.json`.
- **2.2 — Verification:** `tests/test_profiles.py`, `tests/test_profile_validation.py`, `tests/test_service_monitor.py`.
- **2.3 — Documentation:** this file, profile-related changes in `OPERATIONS.md`, and an updated Day Two report.

Keep the log analyser and its tests for their separate work package. Keep generated reports out of these commits. No staging, commits or pushes are performed by this feature.

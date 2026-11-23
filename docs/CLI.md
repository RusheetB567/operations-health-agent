# Command reference

Run commands from the repository root using your virtual environment's Python interpreter. `--help` is authoritative for argument syntax.

| Tool | Purpose | Key options |
| --- | --- | --- |
| `system_health.py` | Host snapshot or bounded sampling | `--samples`, `--consecutive`, `--disk`, resource `--*-threshold`, `--tcp`, `--http`, `--network-timeout`, `--output` |
| `run_profile.py PROFILE` | Reusable host-monitor options | `--check` validates without running |
| `service_monitor.py CATALOGUE` | Named HTTP/TCP stack checks | `--check`, `--group`, `--workers`, `--output` |
| `log_analyzer.py LOG` | JSONL severity summary | Positional log file |
| `tools/demo_local.py` | Temporary local demonstration | No arguments |
| `tools/check_docs.py` | Check local Markdown file links | No arguments |
| `tools/verify_regressions.py` | Detect three injected defects in temporary copies | No arguments |

## Exit-code contract

| Command | 0 | 1 | 2 |
| --- | --- | --- | --- |
| Host/profile run | Healthy final state | Active resource alert or failed dependency | Operational/configuration failure |
| Service catalogue | All selected services healthy | Any selected service failed | Invalid configuration or I/O failure |
| Validation-only | Valid configuration | Not used | Invalid configuration |
| History query | Query succeeded, including stored warnings | Not used | Query failed |
| Log analysis | No errors, critical records or malformed/oversized lines | Any of those conditions found | Input unreadable |
| Local demo | Demo passed | Not used | Demo failed |
| Docs/regression tooling | Checks passed | Check failed | Unhandled environment failure may use a different nonzero exit |

Check PowerShell `$LASTEXITCODE` immediately after a command. For Python callers, inspect `subprocess.CompletedProcess.returncode`.

## Examples

```powershell
.\.venv\Scripts\python system_health.py --history-db reports/history.sqlite3 --max-reports 1000
.\.venv\Scripts\python system_health.py --history-db reports/history.sqlite3 --show-history 10
.\.venv\Scripts\python service_monitor.py services.example.json --group application --workers 2
.\.venv\Scripts\python log_analyzer.py reports/application.jsonl
```

`--http-status` on the host monitor applies to every configured HTTP target. A service catalogue instead supports `expected_status` per HTTP service. `--network-timeout` on the host monitor defaults to 3 seconds; catalogue entries have their own `timeout`.

See [catalogue schema](../SERVICE-CATALOGUE.md) for field validation and [quickstart](QUICKSTART.md) for installation.

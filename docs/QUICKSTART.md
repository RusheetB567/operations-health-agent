# Quickstart

Start in the repository root. Python 3.11 or newer is required.

## Install

Windows PowerShell:

```powershell
py -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
```

Linux shell (commands prepared; not locally verified):

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

The commands below use the Windows interpreter path. On Linux substitute `.venv/bin/python`.

## Try the self-contained demo

```powershell
.\.venv\Scripts\python tools/demo_local.py
```

It starts a temporary loopback HTTP server, checks healthy/outage/recovery states, runs a monitoring profile, reads persisted history, and summarises a synthetic log. It removes its temporary data and stops the server on exit. It does not start your real applications or contact public endpoints. Expect final `status: passed`; the demonstration intentionally includes warning outcomes.

## Collect host metrics

```powershell
.\.venv\Scripts\python system_health.py --samples 3 --consecutive 2 --output reports/host.json
```

Exit 1 can be a valid resource alert. Inspect the JSON rather than treating every nonzero exit as a program crash.

## Reuse a profile

```powershell
.\.venv\Scripts\python run_profile.py local-profile.example.json --check
.\.venv\Scripts\python run_profile.py local-profile.example.json
```

Paths in profiles resolve from the current working directory. Review configured targets and output destinations before running shared configurations.

## Check an application stack

```powershell
.\.venv\Scripts\python service_monitor.py services.example.json --check
.\.venv\Scripts\python service_monitor.py services.example.json --workers 4 --output reports/services.json
```

The example contains illustrative ports; it does not install those services. Adapt it to your running frontend, API and database. Missing services correctly produce warning status. Use dedicated read-only health URLs.

Next: [CLI reference](CLI.md), [report formats](REPORTS.md), and [troubleshooting](RUNBOOK.md).

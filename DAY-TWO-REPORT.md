# Day Two — Repeatable Monitoring Profiles

Completed: 23 November 2026. This completes the monitoring-profile work started on 15 November.

Focus: make the same host and dependency checks easy to repeat without rebuilding a long command.

Delivered: JSON profiles, an example configuration, strict type/range/endpoint validation, duplicate-option rejection, and a validation-only --check command that does not run monitoring.

Verification: 40 automated tests passed locally on Windows. The example passed validation and a live three-sample run produced a healthy report. Linux and remote CI remain unverified.

Try from the project directory:

```powershell
.\.venv\Scripts\python run_profile.py local-profile.example.json --check
.\.venv\Scripts\python run_profile.py local-profile.example.json
```

Paths are relative to the current working directory. Review real diagnostic targets and output paths before running a personal profile. This does not install a background service.

All changes remain local for review; nothing was staged, committed or pushed in this session.

## Expanded service monitoring delivery

The implementation now includes named HTTP/TCP services, strict versioned catalogue validation, independent per-service expected status and timeout, application groups, group filtering, bounded parallel checks, failure isolation, deterministic result order and atomic combined-report output. See SERVICE-CATALOGUE.md for the updated 2.1/2.2/2.3 file boundaries.

Verification: 47 automated tests passed on Windows, including an end-to-end catalogue check against real local HTTP and TCP services with a saved combined report. Linux and remote CI remain pending. These additions remain unstaged and uncommitted.

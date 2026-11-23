# Day One — Operations Health Agent

**Date:** 14 November 2026 · **Focus:** reliable local monitoring and service diagnostics

## Objective

Build a practical tool that helps operators distinguish host resource pressure, dependency failures and application readiness problems, while preserving useful evidence for investigation.

## Delivered

- **Host monitoring:** CPU, memory, disk utilisation and uptime in versioned JSON reports with UTC timestamps.
- **Actionable alerts:** configurable thresholds, consecutive-breach detection, recovery hysteresis, and timestamped opening/recovery events.
- **Network diagnostics:** optional DNS and TCP checks with time budgets and distinct failure results.
- **HTTP readiness:** expected-status checks for frontends and APIs, redirect detection, and default HTTPS certificate verification.
- **Reliable persistence:** temporary-file replacement, bounded retries for Windows file contention, and cleanup after failed report writes.
- **Local history:** SQLite report storage, configurable record retention, and read-only history queries.
- **Engineering foundations:** automated tests, Windows/Linux CI configuration, operating documentation, and ignore rules for generated files.

## Lessons applied

Earlier project reviews highlighted stopped preview servers, incomplete service startup, address-dependent behaviour and partial-save risks. These informed separate frontend/API checks, explicit local-address testing, sanitized HTTP errors, and a regression proving that failed retention rolls back a new history record.

No account data or application-specific authentication code was copied into this project.

## Verification

**29 automated tests passed locally on Windows**, using Python 3.13.15 and psutil 7.2.2. Checks included real loopback TCP and HTTP servers, simulated failures, alert recovery, concurrent report writers, and database rollback.

Live runs verified resource collection, report persistence, failed-dependency reporting, and SQLite save/read behaviour. A sustained memory-pressure alert was captured during local monitoring.

## Current limits

Linux CI has not yet run. Checks against earlier applications were not rerun. HTTP status checks do not establish successful login or validate page content. History stores each invocation's final report and alert transitions, rather than every sample; retention limits record count, not database file size. Alert state resets between invocations.

## Next priorities

Verify remote CI, add application-specific readiness endpoints where needed, and review generated files already tracked by Git before broader publication. Evaluate OpenTelemetry interoperability before extending the collector architecture.

See [OPERATIONS.md](OPERATIONS.md) for setup, usage and detailed behaviour.

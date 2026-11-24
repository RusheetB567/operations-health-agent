# Day 3.1 — Privacy-Safe Incident Log Triage

Date: 24 November 2026.

## Focus

Move beyond knowing that an application is unhealthy: identify recurring error patterns within an incident time window without copying raw log messages or credentials into diagnostic summaries.

## Implemented

- A new multi-file JSONL triage command, leaving the simple existing log analyser compatible.
- Inclusive timezone-aware windows normalised to UTC.
- Severity counts and fixed heuristic categories for timeout, connection, database, authentication and capacity issues.
- Per-run recurring-error fingerprints, counts and observed first/last timestamps.
- Ephemeral HMAC keys: raw/normalised messages and the grouping key are not persisted.
- Bounded physical-line and distinct-pattern budgets, plus visible truncation/drop counts.
- Duplicate-key, invalid UTF-8/Unicode, malformed JSON and oversized-record handling.
- Atomic JSON output, input-overwrite protection and sanitised command errors.

## Verification

19 new tests passed; the full local Windows suite passed 162 tests. All three targeted injected-defect checks passed. Full and windowed synthetic CLI runs were verified: seven total records, five inside the selected window, three error groups and no seeded credential in exported summaries. The largest groups were two timeout errors and two database-lock errors.

## Manual commit scope

- triage_logs.py
- tests/test_log_triage.py
- examples/incident-logs.jsonl
- docs/LOG-TRIAGE.md
- README.md
- DAY-3.1-REPORT.md

Suggested message: Day - 3.1: add bounded privacy-safe incident log triage

The pending Day 2.9 auditor files are separate. No staging, commit or push was performed by the assistant.

## Limits and next increment

Grouping and categorisation are heuristic, not proof of root cause. Fingerprints intentionally differ across invocations. This handles finite UTF-8 JSONL files, not live streams or multiline plaintext. There is no whole-run timeout or cross-system event correlation. Linux and remote CI remain unverified.

A useful next increment is an incident timeline linking coarse log categories to service observation windows, with explicit uncertainty rather than automatic root-cause claims.

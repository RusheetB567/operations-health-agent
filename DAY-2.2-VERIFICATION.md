# Day 2.2 — Profile and Service Regression Tests

Completed: 23 November 2026.

## Focus

Verify operational behaviour under invalid configuration, dependency failure and report-write failure. This increment adds tests and removes one duplicate test definition; it introduces no new production features.

## Added coverage

- Invalid catalogue roots, unsupported versions and duplicate JSON keys stop before monitoring.
- Oversized catalogues and missing inputs return controlled errors.
- Validation-only mode neither contacts services nor overwrites reports.
- Group filtering checks only selected targets.
- Per-service timeout and expected HTTP status reach the diagnostic worker.
- Failed checks produce warning exit status.
- Report-write failures produce sanitized error output.
- Saved JSON matches the JSON returned on stdout.
- Real CLI processes return appropriate exit codes without tracebacks.
- Profile validation does not create its configured output file.

The existing local HTTP/TCP end-to-end check is preserved. One duplicate method definition was removed because Python silently replaces an earlier method with the same name.

## Results

All 57 tests passed locally on Windows. Ten new regression tests were added. Linux and remote CI remain unverified.

## Files for your manual test commit

- tests/test_profiles.py
- tests/test_profile_validation.py
- tests/test_service_monitor.py
- tests/test_service_regressions.py

Suggested message: test(monitoring): cover profile and catalogue operational failures

This report can be included in the documentation layer (2.3). Production runner files belong to 2.1. Day 3 log-analysis files and generated reports remain separate. Nothing was staged, committed or pushed by the assistant.

## Expanded reliability package

Added a reusable loopback-only failure fixture and six end-to-end tests. These execute real CLI subprocesses and exercise outage/recovery, stalled response deadlines, redirects without following, abrupt disconnection, validation without side effects, and failed output replacement without loss of existing data.

The optional tools/verify_regressions.py script makes temporary copies and injects three known defects: failed checks incorrectly return success, duplicate names are accepted, and HTTP readiness comparison is inverted. All three defects were detected by failing assertions. The working source is never mutated by the script. This is a targeted sensitivity check, not an exhaustive mutation score.

A separate reliability workflow is prepared for Windows and Ubuntu on Python 3.13, including manual dispatch and a job timeout. It has not run remotely. The latest local suite passed 63 tests, and all three sensitivity checks passed. TLS certificate integration coverage is still pending; no TLS verification settings were weakened.

### Suggested reviewable contributions

1. Local failure lab and end-to-end coverage: tests/fault_lab.py and tests/test_service_end_to_end.py.
2. Regression sensitivity tool: tools/verify_regressions.py.
3. Reliability CI: .github/workflows/fault-verification.yml.
4. Verification evidence: this report.

These are meaningful separate review units. No staging, commits, pushes, merges or commit-date changes were performed. Existing earlier Day 2.2 test changes remain for your review as well.

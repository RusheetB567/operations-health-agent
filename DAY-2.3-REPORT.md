# Day 2.3 — Documentation and Reproducible Demonstration

Completed: 23 November 2026.

## Focus

Make the monitoring system understandable, runnable and reviewable by someone who did not follow its development. Replace the minimal landing page with a practical product overview and provide a demonstration requiring no external application setup.

## Delivered

- Rewritten README covering purpose, capabilities, commands, limits and guide navigation.
- Windows installation instructions and prepared Linux equivalents.
- Architecture diagram and component/persistence boundaries.
- CLI and exit-code reference for each tool.
- Report-format guide covering host reports, named service results and log summaries.
- Troubleshooting runbook and recovery workflow.
- Contributor verification instructions and release-review checklist.
- Self-contained local demo using temporary data and a dynamically allocated loopback port.
- Demo regression test and local documentation-link checker.
- Prepared documentation/demo CI workflow.

## Demonstrated workflow

The demo checks a temporary application while healthy, during a controlled HTTP 503 outage, and after recovery. It then validates and runs a host profile, reads its SQLite report, and analyses a synthetic log while excluding a seeded sensitive value. Temporary files are removed and the local server is stopped.

Run: `.\.venv\Scripts\python tools/demo_local.py`.

## Verification

- 64 automated tests passed locally on Windows.
- The standalone demo completed all five steps successfully.
- All three deliberate defects in isolated temporary copies were detected.
- Documentation checks passed with no broken local file links.
- CLI help and example validation commands were checked locally.

Remote CI, Linux execution and TLS integration coverage remain unverified. The documentation checker verifies local file targets, not web links, heading anchors or the semantic correctness of prose.

## Review scope

README.md; CONTRIBUTING.md; docs/QUICKSTART.md; docs/ARCHITECTURE.md; docs/CLI.md; docs/REPORTS.md; docs/RUNBOOK.md; docs/RELEASE-REVIEW.md; tools/demo_local.py; tools/check_docs.py; tests/test_demo.py; .github/workflows/docs-verification.yml; this report.

Suggested review units: documentation/navigation; runnable demonstration and regression test; automated documentation/CI verification. The owner decides how to commit. No staging, commit, push, merge, deployment or release was performed by the assistant.

# Day 2.5 — Dashboard Analytics Expansion

Date: 23 November 2026. Prepared on the existing DEV checkout for manual review and commit.

## Delivered

- A dedicated analytics engine calculating observed health shares, group counts, transport and HTTP-code distributions.
- Probe-duration minimum, maximum, mean, nearest-rank P50/P95, missing-value counts and configurable slow-check counts.
- A substantially expanded offline HTML report with seven summary cards, group table, diagnostic table, top-five probe-duration meters, diagnostic buckets, section navigation and print layout.
- Group and warning filters plus health/name/duration sorting at generation time.
- Optional CSV and machine-readable JSON statistics exports.
- Endpoint hiding for HTML and CSV, HTML escaping, spreadsheet-formula mitigation and input/output path protection.
- A six-service synthetic fixture and a detailed usage/statistical reference.

## Measured verification

- 19 new tests; 99 tests passed in the full local Windows suite.
- Synthetic preview: six services, four healthy, two warning, three groups.
- Observed healthy share 66.67%; P50 24 ms; P95 3000 ms; two slow probes at a 1000 ms threshold.
- Full HTML/CSV/JSON export and filtered application-warning export completed successfully.
- Exported HTML/CSV omitted the fixture endpoints when hiding was enabled.

## Review files

1. render_dashboard.py
2. report_analytics.py
3. report_csv.py
4. tests/test_report_analytics.py
5. tests/test_report_exports.py
6. examples/service-snapshot.json
7. docs/OFFLINE-DASHBOARD.md
8. README.md
9. DAY-2.5-ANALYTICS.md

Suggested manual commit message: Day - 2.5: expand offline dashboard analytics and safe exports

No files were staged, committed or pushed by the assistant. Existing published history and branch selection were preserved.

## Limits

Metrics represent one selected snapshot, not uptime or historical latency. Export files are individually atomic, not a multi-file transaction. Endpoint hiding leaves names/groups visible. HTML is static and has no interactive in-browser filtering. Remote CI, Linux execution and visual browser/accessibility audits remain unverified.

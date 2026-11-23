# Offline dashboard, analytics and exports

Generate a service-health dashboard without a server, JavaScript, external assets or network requests. The renderer reads an existing service report; it does not run probes.

## Try the complete synthetic example

```powershell
.\.venv\Scripts\python render_dashboard.py examples/service-snapshot.json --output reports/dashboard-preview.html --csv-output reports/dashboard-preview.csv --analytics-output reports/dashboard-analytics.json --redact-targets --sort duration --slow-ms 1000
```

Open reports/dashboard-preview.html in a browser. The six-service fixture contains four healthy services and two warnings across three groups. Its expected snapshot healthy share is 66.67%, P50 probe duration is 24 ms, P95 is 3,000 ms, and two probes meet the 1,000 ms slow threshold. These are synthetic demonstration values.

## Dashboard sections

- Overview: service counts, healthy share, P50/P95 duration and slow-check count.
- Application groups: total, healthy, warning and healthy percentage per group.
- Service diagnostics: sortable-at-generation table with explicit health and diagnostic outcomes.
- Probe duration analysis: valid/missing timing counts, mean, top-five slowest checks and accessible meter bars.
- Diagnostic outcomes: fixed buckets for ready, reachable, timeout, refusal and other supported results.
- Optional previous-snapshot comparison, preserving incident semantics.

The page provides section navigation, row/column table headings, responsive horizontal tables, warning markers and a print stylesheet. It is a static document; changing filters or sorting requires running the command again.

## Options

| Option | Purpose |
| --- | --- |
| --output FILE | Required HTML destination |
| --csv-output FILE | Optional CSV of selected service rows |
| --analytics-output FILE | Optional machine-readable JSON statistics |
| --group NAME | Include only one exact group |
| --warnings-only | Include only warning services |
| --sort health | Warnings first, then group and name; default |
| --sort name | Service-name order |
| --sort duration | Largest measured probe duration first; missing values last |
| --slow-ms NUMBER | Positive finite slow-check threshold; default 1000 |
| --redact-targets | Hide endpoint addresses in HTML and CSV |
| --previous FILE | Compare a previous service report |

Example: `.\.venv\Scripts\python render_dashboard.py examples/service-snapshot.json --output reports/application-warnings.html --group application --warnings-only`.

Filters apply before statistics and export. No matching rows returns exit 2 and writes no output. Group filtering applies to both snapshots when a baseline is supplied, and each must contain that group. Warning-only filtering is incompatible with comparison because removing recovered services would misrepresent incident transitions.

## Statistical meaning

All numbers describe the selected services in one snapshot. They are not historical uptime, service availability SLAs or an application's response-time distribution. Probe duration includes diagnostic and subprocess overhead, and failed probes can have recorded durations.

P50/P95 use the nearest-rank method: sort valid observations and select the ceiling of count times percentile. One observation produces the same P50/P95. Missing, negative, boolean, nonnumeric and non-finite durations are excluded, not converted to zero. An empty valid timing set displays Unavailable. A measured zero is valid. Slow count includes values at or above the threshold.

The JSON summary also contains transport counts, numeric HTTP-code counts and the top five measured services. It excludes targets but retains service names and groups. Summary counts are calculated from service rows rather than trusting an input summary block.

## Privacy, integrity and safety

Dynamic HTML text is escaped. The content policy forbids scripts and remote assets. Endpoints are plain text. Endpoint hiding does not anonymise service names, groups, timestamps or the input JSON. Review all output before sharing.

CSV uses standard quoting and prefixes formula-like text fields with an apostrophe, including leading whitespace followed by formula markers. This mitigates common spreadsheet formula injection; it is not a guarantee across every spreadsheet importer.

Output destinations must be distinct and cannot overwrite either input report. Each file uses atomic replacement independently. A later write failure can leave earlier successful outputs; there is no multi-file transaction.

Exit 0 means rendering/export succeeded, even if the snapshot contains warnings. Exit 2 means invalid configuration, input or output failure. Keep generated outputs under ignored reports. No automatic commits, uploads, remediation or background refresh occur.

## Verification

19 new automated tests cover statistics, timing edge cases, filtering, ordering, input preservation, endpoint hiding, HTML escaping, CSV quoting/formula mitigation and output-path safeguards. The complete 99-test suite passed locally on Windows. Synthetic full and filtered CLI exports were checked. Linux CI and visual browser/accessibility audits remain unverified.

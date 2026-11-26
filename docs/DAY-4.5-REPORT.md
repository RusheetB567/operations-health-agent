# Day 4.5 — Incident report export

SignalDesk now generates incident handoff reports from the incident workspace, with Markdown and JSON formats and a preview before downloading.

- Include incident state, owner, service address, failure count, resolution and recorded activity.
- Include up to 100 retained check observations overlapping the incident window, including the recovery check. Reports state their retention limits and flag truncation.
- Exclude investigation notes by default. Including notes requires an explicit checkbox selection; opening another incident resets that choice.
- Export only selected diagnostic fields, without copying arbitrary log/probe fields into the report.
- Preview content as literal text. Markdown notes are indented to prevent user-entered headings, links or HTML from becoming report structure.
- Download the previewed snapshot rather than regenerating potentially changed content at download time.

## Try it

Launch `Start-SignalDesk.cmd` and open **Incidents**. Select **Investigate**, choose Markdown or JSON under **Export incident report**, optionally include investigation notes, and select **Preview report**. Review the content, then select **Download report**. The export includes the local service address and ownership labels; review it before sharing. Nothing is uploaded or sent automatically.

The report uses a consistent database snapshot and leaves incidents, notes and check history unchanged. Owner labels are not authenticated identities, and observations do not establish root cause. Missing/pruned evidence cannot be reconstructed. Older incidents may have fewer retained observations than their lifetime failure count.

## Verification

All 343 repository tests passed. Five new integration tests cover recovery evidence, note omission, diagnostic-field filtering, literal Markdown, input/token validation and evidence truncation. The browser preview displayed the expected incident details and retained observations with notes excluded. The download control produced no browser errors, but the in-app browser's file-save outcome could not be confirmed; file download needs a check in the user's normal browser.

No staging, commits or pushes were performed.

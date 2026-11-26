# Day 4.6 — Verified local report saving

The final Day 4 increment closes the report-saving gap from Day 4.5. Incident previews can now be saved directly into `reports/incident-exports`, independently of browser download support.

- Save the exact UTF-8 bytes of the previewed Markdown or JSON snapshot, even if the incident changes afterward.
- Display the saved relative path, byte count and SHA-256 checksum.
- Write atomically to a unique filename. Saving the same preview twice returns the same result; fresh previews preserve earlier files.
- Keep at most eight previews in memory for 15 minutes. Expired or evicted previews require regeneration.
- Reject client-supplied file paths/content and output-folder redirects outside the repository. Saved reports remain covered by the existing `reports/` ignore rule.

## Try it

Launch `Start-SignalDesk.cmd`. Open **Incidents**, select **Investigate**, choose a format and select **Preview report**, then **Save local copy**. The saved path appears below the controls. The normal browser download option remains available, but its in-app file-save outcome was not confirmed; this local-save path was verified end to end.

## Verification

Four new tests cover exact content/checksum, snapshot preservation, repeat-save behaviour, validation/token protection, expiry and bounded preview storage. Browser verification saved a real 1,351-byte Markdown report; filesystem verification checked its SHA-256 checksum and Git ignore status. See the Day 4 wrap-up for the complete delivered workflow. No staging, commits or pushes were performed.

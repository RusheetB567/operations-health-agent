# Day 5.6 — Reliability handoff snapshots

28 November 2026

The final Day 5 increment adds a portable reliability-review snapshot. Operators can preview Markdown or JSON for all services or the selected review category, then save the exact preview locally.

Snapshots include saved objectives, sampled availability/latency assessments, evidence counts, assessment reasons and active incident ownership. Endpoint fields and investigation notes are excluded. Reports identify evidence and retention limits rather than claim continuous uptime or root cause.

## Try it

Launch `Start-SignalDesk.cmd`, open **Reliability**, select a review category and choose **Export this review**. Choose a format, select **Preview snapshot**, then **Save local snapshot**. The file is written under `reports/reliability-exports`, and the dialog shows its path, byte count and SHA-256 checksum.

The existing bounded preview cache and atomic-save mechanism are reused. Previews expire after 15 minutes, with eight retained across incident/reliability exports. Saving the same preview is idempotent; a fresh preview creates a separate file. Objective changes after preview do not alter the saved snapshot. Generated files remain ignored by Git. Nothing is uploaded or sent automatically.

## Verification

Four new integration tests cover category filtering, report contents, exact snapshot saving/checksums, privacy, database preservation, validation and empty workspaces. The existing incident-export tests also pass after preview-cache reuse. Browser and filesystem checks verified a 5,102-byte JSON snapshot with a matching checksum and confirmed Git ignore coverage.

No staging, commits or pushes were performed. See [the completed Day 5 wrap-up](DAY-FIVE-WRAP-UP.md) for the full delivery and final validation results.

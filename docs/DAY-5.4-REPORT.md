# Day 5.4 — Reliability review

28 November 2026

The Reliability page now includes a review panel that connects objective assessments to evidence and active incident ownership.

## Delivered

- Separate saved-target misses, missing evidence/settings, paused/maintenance work and services within saved targets.
- Treat unsaved availability defaults as suggestions instead of committed goals.
- Distinguish latency target misses from incomplete timing coverage or insufficient successful samples.
- Show active incident counts and ownership labels, with links to the incident workspace.
- Link each service directly to reliability evidence and objective editing.
- Filter review categories without changing services, objectives, schedules or incidents.

## Try it

Launch `Start-SignalDesk.cmd`, open **Reliability**, and use the **Show** filter in **Reliability review**. Select **View evidence** to inspect observations, **Review objective** to edit the target, or an incident link to continue investigation.

Each service receives exactly one review category. Paused and maintenance services are deferred while retaining their reason details. A saved target miss takes precedence over missing evidence for another objective. Services with unsaved availability objectives or incomplete required evidence remain in the evidence/settings category unless another saved target is demonstrably missed.

The review is read-only guidance from retained sampled checks. Meeting objectives does not close an incident. Deferral is not recovery, and objective misses are not root-cause findings. Active incident labels are local ownership text, not authenticated identities; investigation notes are not included in the review response.

## Validation

Five new integration tests cover unsaved defaults, target boundaries/category counts, latency misses versus missing timings, paused/maintenance deferral and read-only incident ownership links. Browser checks verified category filters, observation drill-down and navigation to the linked unresolved incident. Nothing was staged, committed or pushed.

# Day 5.2 — Reliability evidence and trends

28 November 2026

The Reliability page now includes a per-service **View history** workspace. It connects objective assessments to the observations behind them.

- Display twelve equal time buckets across the configured objective window, with healthy-check percentages and sample counts. Empty buckets remain labelled gaps.
- Show the latest consecutive warning count and P95 probe duration from valid, nonnegative finite measurements.
- Compare two equally sized groups of recent observations when there are at least six samples and the objective's configured minimum is met. Odd counts omit the oldest extra observation.
- Label descriptive trends as improving, declining or unchanged without claiming a forecast or continuous uptime.
- List the latest 50 matching observations, with timestamps, manual/scheduled triggers, health, probe results and durations. Calculations use up to 200 retained observations.
- Preserve the current objective window, service configuration and maintenance-cycle boundaries. Reading history does not mutate the database or launch probes.

## Try it

Launch `Start-SignalDesk.cmd`, open **Reliability**, then select **View history** for a service. Inspect gaps, warning streaks and individual probe results. Close and reopen the dialog to refresh it after new checks.

Six new regression tests cover missing/empty history, bucket counts and gaps, declining/improving trends, minimum/odd sample counts, timing validation, field filtering, read-only behaviour and configuration/maintenance scope. Browser verification inspected an actual retained worker warning, its HTTP 503 result, measured duration and insufficient-data trend state.

The previously interrupted attempt made no edits. This session completed and verified the implementation. No staging, commits or pushes were performed.

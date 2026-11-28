# Day 5 wrap-up — Reliability with evidence

Day 5 added service reliability objectives and the history needed to understand them.

Operators can now save a healthy-check target, lookback window and minimum observation count for each service. The Reliability page separates meeting target, below target and insufficient evidence, and shows sampled health and remaining failure allowance.

The history workspace adds twelve time buckets, visible evidence gaps, warning streaks, valid probe-duration percentiles and recent observation details. Equal-sized sample comparisons describe improvement or decline only after enough observations exist.

## What runs in the background

The local Python server reads retained completed observations from SQLite. Objective calculations do not send network probes. New checks still come from manual actions or the explicitly enabled scheduler. The Reliability summary refreshes every ten seconds while visible; history dialogs show a snapshot and refresh when reopened.

Configuration revisions and maintenance cycles keep unrelated observations separate. Pausing preserves existing observations. Retention remains 200 runs, so long windows may have incomplete or uneven coverage. These metrics describe sampled checks rather than continuous uptime, request-level availability or a contractual SLA.

## Review and launch

Double-click `Start-SignalDesk.cmd`, open **Reliability**, set an objective and inspect **View history**. See [the initial Day 5 report](DAY-FIVE-REPORT.md) for objective calculations and [Day 5.2](DAY-5.2-REPORT.md) for trend and history behaviour.

Final verification includes 361 repository tests, including 69 console integration tests, plus browser inspection of the working history interface. The SQLite concurrency regression tests remain included. Remote CI has not been run on these uncommitted changes.

Day 5 is ready for the repository owner's review. Nothing was staged, committed or pushed.

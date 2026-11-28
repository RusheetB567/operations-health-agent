# Day 5.5 — Windows CI ordering fix

28 November 2026

## Why the checks failed

The history fixtures generated timestamps in a tight loop. Windows Python 3.11/3.12 runner clocks produced equal timestamps for several observations. History then used random run IDs as a tie-breaker. That shuffled the intended sequence, changing consecutive-warning counts and even reversing the apparent trend.

The logs for push runs #60, #61 and #62 and pull-request run #63 show the same failures in history streak/trend tests. For example, the [Windows 3.12 PR job](https://github.com/RusheetB567/operations-health-agent/actions/runs/46093338809/job/140819068257) reported one consecutive warning instead of three, and an improving trend instead of declining. Earlier successful local Python 3.13 runs did not reliably expose the timestamp ties.

Cancelled matrix jobs were a separate effect: GitHub's default matrix fail-fast behaviour cancelled unfinished jobs once another job failed. Both push and pull-request triggers ran for the branch, producing multiple results/notifications. Old failed-run notifications remain historical records after a fix.

## Changes

- Break equal timestamps using SQLite run insertion order instead of random IDs. Apply deterministic ordering to latest observations, reliability history, run lists, retained-run pruning and exported check evidence.
- Give synthetic reliability fixtures explicit one-second spacing rather than relying on clock resolution.
- Add equal-timestamp regressions for streaks, trends, latest state and restart persistence. The regression was also checked against the old UUID ordering and correctly rejected it.
- Set `fail-fast: false` so every Windows/Linux and Python matrix job can finish independently. Add a ten-minute job limit to bound stalled runs.
- Preserve every test and the existing six-job OS/Python matrix; no failures are skipped or ignored.

## Verification

All 373 tests passed locally on Windows with Python 3.11.16, 3.12.14 and 3.13.15. The additional runtimes were installed in an isolated workspace folder, not added as repository dependencies. Documentation links and diff checks passed. Remote Ubuntu and hosted-runner validation remain for the fresh GitHub workflow after the owner pushes the fix.

## Publishing

The fix is left uncommitted for the owner. Commit and push it to DEV to trigger fresh checks on the PR. Existing failed runs do not become successful retroactively. No staging, commits, pushes, merges or remote reruns were performed by Codex.

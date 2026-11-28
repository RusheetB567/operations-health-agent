# Day 5 — Service reliability objectives

27 November 2026

SignalDesk now has a Reliability page for setting service objectives and evaluating sampled check history. This extends the console from responding to individual incidents to understanding whether repeated observations meet an explicit target.

## Delivered

- Save a healthy-check target, lookback window and minimum sample count for each service.
- See observed healthy percentage, healthy/total checks and remaining failure allowance.
- Distinguish meeting target, below target and insufficient evidence.
- Label unsaved defaults as suggestions rather than configured objectives.
- Refresh assessments manually or every ten seconds while the Reliability page is visible.
- Persist objective settings in the local SQLite database without replacing existing history.

## How to use it

Launch `Start-SignalDesk.cmd`, then open **Reliability**. Select **Set objective** for a service, enter a target from 50–100%, choose a lookback of 1–168 hours and require 5–200 observations. Save the objective, collect checks and refresh the view.

For example, four healthy checks out of five meet an 80% target. At 99%, the same sample is below target. If the minimum is ten observations, five checks produce an insufficient-data assessment regardless of their healthy percentage.

Failure allowance is `observations × (1 − target / 100)`. Remaining allowance subtracts observed warnings. It can be fractional or negative; it does not guarantee that another failure is permissible.

## Scope

This is sampled-check reliability, not continuous uptime, request-level availability or a contractual SLA. Manual checks and unequal sampling can bias results. The page evaluates retained completed observations within the selected time window for the current service configuration and maintenance cycle. Configuration changes and a new maintenance cycle begin a fresh evidence set. Pausing preserves observations. History retention remains 200 runs, so a long window does not guarantee full coverage.

## Verification

Six new tests cover insufficient evidence, exact target boundaries, failure allowances, a 100% target, invalid values/request protection, persistence, lookback filtering, configuration revisions, paused services and maintenance cycles. Browser testing found and corrected a route-ordering issue, then confirmed saving a 95%/48-hour objective with a five-sample minimum and retaining it after reload.

The earlier SQLite concurrency fix and its regression tests remain included. No staging, commits or pushes were performed; remote CI validation still requires publishing the changes.

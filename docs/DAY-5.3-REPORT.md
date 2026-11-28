# Day 5.3 — Separate latency objectives

28 November 2026

SignalDesk now supports an optional latency goal per service, assessed separately from sampled availability.

## Delivered

- Enable or disable latency assessment without changing the availability target.
- Set a threshold of 1–60,000 milliseconds and require 50–100% of successful probes to finish within it.
- Reuse the service's existing lookback window and minimum observation count.
- Display the latency target, observed percentage and successful-check timing coverage beside availability.
- Persist settings locally and apply existing configuration/maintenance-cycle boundaries.
- Expose P95 duration of valid successful probes in the reliability API, separate from the all-probe P95 in history.

Failed probes never count as latency successes or as the latency denominator; availability continues to assess those failures. Successful observations with invalid/missing timings are explicitly counted, and the latency assessment remains insufficient until coverage is complete and the sample minimum is met. Observed percentages may still be displayed as partial evidence.

## Try it

Launch `Start-SignalDesk.cmd`, open **Reliability**, and choose **Latency goal** for a service. Enable assessment, enter a threshold and target, then save. The latency column appears beside the availability assessment. Disable the goal using the same form when it is no longer needed.

For example, four of five successful probes within 500 ms meet an 80% latency goal. A separate failed probe does not improve or worsen that conditional latency percentage; it lowers availability. Probe durations include process overhead and are not end-user request-latency measurements.

## Validation

Five new tests cover inclusive threshold boundaries, fast-failure exclusion, absent/invalid timing coverage, persistence, disabling, maintenance boundaries, strict input validation and token protection. Browser verification saved a 90%/750-ms goal, confirmed the insufficient-data result for a service with no successful samples, and checked persistence after reload.

No staging, commits or pushes were performed.

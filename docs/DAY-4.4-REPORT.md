# Day 4.4 — Compare saved check runs

SignalDesk's Check history now includes a baseline/current run comparison. Operators can see which observations changed before and after an investigation or repair.

- Classify new failures, recoveries, ongoing failures and services that stayed healthy.
- Show services added to or absent from a run without claiming they were added to or removed from the catalogue. Partial checks, paused services and maintenance can change run membership.
- Treat configuration revisions and maintenance cycles as separate comparison boundaries rather than apparent recoveries.
- Match stable service IDs: deleting and recreating the same service name does not join unrelated observations.
- Display before/after health and probe-duration differences where both observations are comparable. Positive differences mean the later probe took longer; they are not performance guarantees.
- Reject identical, reversed, unfinished, missing or incomplete run selections with clear errors.

## Try it

Launch `Start-SignalDesk.cmd`, open **Check history**, choose an older **Baseline run** and a newer **Current run**, then select **Compare runs**. Use the local lab's failure and recovery runs for a complete example. The selectors offer completed runs from the latest 30 displayed runs; existing retention keeps up to 200 runs. Comparison reads saved observations and does not launch new probes or modify incidents.

The existing snapshot comparison logic is reused for comparable health transitions, with console service identity, configuration revisions and maintenance metadata providing additional safeguards. No new dependencies or database schema changes are required.

## Verification

Eight new integration tests exercise health transitions, partial checks, configuration changes, maintenance boundaries, reused names, invalid selections, timing values and incomplete metadata. Browser tests confirmed one recovered service and two still healthy services in an actual saved lab comparison, plus correct added/absent labels for partial runs. All 338 repository tests passed, including 46 console integration tests. Nothing was staged, committed or pushed.

# Day 4.3 — Maintenance windows

SignalDesk now supports planned maintenance for individual local services. Operators can provide a reason and a duration of 1–1,440 minutes, see the active window, and end it early.

## What changed

- Manual and scheduled checks exclude services in active maintenance.
- Expiry automatically restores check eligibility; the next manual or scheduled check records the new observation.
- Maintenance does not change the service's enabled setting. A paused service stays paused afterward.
- Existing incidents remain open until a fresh check confirms recovery.
- Observations captured before a maintenance cycle cannot claim current health or open/resolve incidents after that cycle. Already running probes may finish, and their run reports remain available.
- Health counts and probe-duration statistics exclude maintenance services. The enabled-service card reports the number in maintenance separately.
- Services includes a maintenance history with reasons, planned end times and active/ended/expired states. Windows survive console restarts, although scheduled checks still require a fresh start.

## Try it

Launch `Start-SignalDesk.cmd`, open **Services**, and choose **Maintenance** for the lab worker. Enter a reason and a duration, then select **Start maintenance**. Its individual Check button becomes disabled. Run combined checks: only services outside maintenance should appear. Select **End now** in the maintenance history and check the worker again to obtain a fresh observation.

## Validation and limits

Eight new integration tests cover validation and request protection, partial/all-service exclusion, scheduled resumption, early ending, expiry, persistence, paused-service behaviour, stale in-flight results and incident recovery. Browser testing confirmed a worker window, a run with only the other two services, early ending and a fresh warning after checks resumed.

Windows start immediately; future or recurring maintenance is not included. Removing a service removes its maintenance records. History displays up to 250 windows; creating a window prunes completed/expired history to the latest 200 while retaining active windows. Reasons are local plaintext and should not contain credentials or personal data. No commits or pushes were made.

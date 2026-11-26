# Day 4.2 — Controlled scheduled checks

SignalDesk can now run service checks on a configurable interval while the local console is running.

## Delivered

- Start, stop and update scheduled checks from Overview, with intervals from 10 to 3,600 seconds.
- See the next check time, current scheduling state and the result of the last scheduling attempt.
- Identify manual and scheduled runs in Check history.
- Use the existing probe, history and incident pipeline: scheduled failures open or update incidents, and healthy observations record recovery.
- Skip an interval when another check is running instead of building a backlog. Paused services remain excluded.
- Save the interval locally while leaving scheduling stopped after every console restart.
- Extend older run-history databases without replacing their records. Previous runs are labelled manual.

## Try it

Launch `Start-SignalDesk.cmd`. Start the local lab or add an enabled loopback service. On Overview, choose **10** seconds under **Scheduled checks**, then select **Start schedule**. The first check runs after that interval. Open **Check history** to find its **scheduled** trigger, then select **Stop** on Overview when finished.

Stopping prevents future scheduled checks; an already running check finishes and saves its result. Updating an interval resets the next due time. The scheduler runs in the console process, so it continues when the browser tab is closed, but stops when the console terminal exits. It does not install an operating-system task or background service. Missed intervals during a long run or device sleep are skipped.

## Verification

New tests cover interval validation and request protection, real scheduled probes, waiting until due, missed intervals, overlap rejection, stopping, paused services, saved interval/restart behaviour, legacy database migration, and incident failure/recovery. Browser verification confirmed that a 10-second timer created a completed run with the scheduled trigger and that the stop control disabled further scheduling.

The migration test also now explicitly closes its SQLite setup connection so Windows can clean up the temporary database. The app remains local-only. No Git staging, commits or pushes were performed.

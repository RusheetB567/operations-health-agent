# Day 4 wrap-up — SignalDesk

Day 4 turned Operations Health Agent from a collection of diagnostic commands into a working local browser workspace.

| Increment | Delivered behaviour |
| --- | --- |
| 4 | Dashboard, service management, real HTTP/TCP checks, run history, log triage and evidence verification |
| 4.1 | Incident creation, acknowledgement, ownership, investigation notes and recovery tracking |
| 4.2 | Controlled scheduled checks with start/stop controls, interval selection and overlap prevention |
| 4.3 | Maintenance windows with expiry, early ending, history and protection against stale observations |
| 4.4 | Saved-run comparisons covering failures, recovery, configuration/maintenance boundaries and partial checks |
| 4.5 | Previewable Markdown/JSON incident reports with optional notes and retained evidence |
| 4.6 | Verified local report saving with exact preview content, atomic writes and checksums |

## How it works

The browser talks to the local Python server. The server uses the existing diagnostic probes and stores settings, observations and incident activity in SQLite under `reports/console`. Checks run manually or on an explicitly started schedule. Failed observations open/update incidents; fresh healthy observations record recovery. Maintenance excludes services temporarily without pretending an outage was fixed.

Log triage retains summaries rather than raw messages. Investigation notes and saved handoff reports are local plaintext; review them before sharing. Reports are generated from retained evidence and do not prove root cause or reconstruct expired history.

## Start and review

1. Double-click `Start-SignalDesk.cmd`; leave its terminal running.
2. Start the local lab to observe a controlled failure and recovery.
3. Review Services, Incidents, Check history, Log triage and Evidence library.
4. Preview an incident report and select **Save local copy** to create a file under `reports/incident-exports`.
5. Stop schedules in Overview when finished; Ctrl+C in the terminal stops the console.

The app remains bound to localhost and accepts loopback targets. It has no authenticated remote collectors, multi-user accounts, cloud hosting, automatic repair or installed operating-system scheduler. Scheduled checks start stopped after every console restart. Maintenance windows retain their expiry across restarts.

## Verification and repository state

The final repository suite contains 347 tests, including 55 console integration tests. Browser checks across Day 4 exercised failure/recovery, incident ownership, scheduling, maintenance exclusion/resumption, run comparisons, evidence verification, log triage and report preview. The final local-save flow was checked in the browser and on disk. In-app browser file downloading remains unconfirmed; local report saving provides a verified alternative.

Changes are left for the repository owner to review, stage, commit and push. Day 4 work is wrapped up; no further feature work was started.

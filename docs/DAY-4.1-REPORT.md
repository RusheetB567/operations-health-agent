# Day 4.1 — Incident ownership and recovery

SignalDesk now turns failed service checks into incidents that can be investigated in the browser.

- A warning opens one incident for the current service configuration. Repeated failures update its counter instead of creating duplicate incidents.
- Operators can acknowledge an incident, assign an owner and save investigation notes in a persistent activity history.
- A successful check resolves the incident as recovered. A later failure opens a new incident.
- Editing a service configuration or removing a service closes its incident with that specific reason. Pausing a service leaves its incident active.
- Results from configurations edited or removed while a check was running cannot open misleading incidents.
- Version checks prevent an outdated browser form from overwriting a newer update.

## Try it

Launch `Start-SignalDesk.cmd`. Start the local lab, or select **Simulate failure** if it is already healthy. Open **Incidents**, select **Investigate**, enter an owner and a note, then select **Acknowledge**. Return to **Overview** and select **Recover lab worker**. In **Incidents**, choose **All incidents** to inspect the resolved record and its preserved notes.

Incident detection starts with checks completed after this update; old reports are not retroactively converted. Ownership labels are local text, not authenticated identities. Notes are saved locally and should not contain credentials or personal data. Checks still run only when requested.

The existing SQLite database is extended automatically without replacing services, runs or triage summaries. The console retains 200 resolved incidents plus active incidents, displays the latest 50 activity entries per incident, and caps activity storage at 200 entries while reserving room for resolution.

Validation covers failure, repeated warnings, acknowledgement, reassignment, recovery, recurrence, persistence, stale edits/results, configuration changes, paused/removed services, retention and activity limits. Browser testing exercised the complete failure-to-recovery workflow with a saved owner and investigation note. No Git staging, commits or pushes were performed.

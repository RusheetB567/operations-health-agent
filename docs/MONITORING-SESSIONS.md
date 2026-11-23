# Finite monitoring sessions

Repeat an application catalogue and preserve transitions across observations:

```powershell
.\.venv\Scripts\python watch_services.py services.example.json --cycles 3 --interval 5 --output-dir reports/sessions
```

The example catalogue uses illustrative ports. Adapt it to services you operate, or use the self-contained session demo described below. The command never starts your applications or installs a background service.

## Controls

| Option | Meaning |
| --- | --- |
| --cycles | Required number of finite observations, default 3, range 1–100 |
| --interval | Delay after a completed cycle, default 5 seconds, range 0.1–3600 |
| --workers | Service-check concurrency, default 4, range 1–16 |
| --group | Optional exact catalogue group |
| --output-dir | Parent for a unique session directory; default reports/sessions |

The interval is a delay between runs, not a fixed-rate schedule. Probe time and artifact writes add to total duration. No interval is added after the final cycle. Configuration is validated before creating a session; catalogues are reloaded by each cycle, allowing configuration changes to be recorded.

## Evidence layout

Each `session-*` directory contains an atomically replaced `session.json` and a `bundles` directory with a distinct complete diagnostic bundle for every successful cycle. Those bundles include checksums and an offline dashboard. The next cycle uses the last completed report as its comparison baseline.

The journal records requested/completed cycles, warning-cycle count, final observed health, timestamps, cycle durations, bundle paths and incident events. It is checkpointed after every cycle. Events distinguish initial warnings, new openings, recoveries, additions, removals and reconfigurations. An ongoing warning is not repeatedly labelled as a new incident.

## Exit status and recovery

- 0: completed with no warning cycles.
- 1: completed, but at least one cycle warned, even if final health recovered.
- 2: configuration, cycle or persistence failure.
- 130: interrupted with Ctrl+C, with progress saved when storage is available.

Operational failures stop the session and preserve prior completed evidence. A failed cycle may leave an incomplete bundle directory. Abrupt termination or power loss can leave the journal in `running`; there is no automatic resume or claim of exactly-once execution. Previously saved bundles remain inspectable.

No storage quota or automatic deletion is implemented. Session histories contain operational details. Use ignored local directories and appropriate file permissions. File-write failures can prevent a final checkpoint. This is finite local observation, not historical uptime/SLA measurement.

## Verification

Dedicated tests cover bounded cycle counts, interval placement, incident opening/recovery, deduplication, catalogue changes, failed-cycle checkpoints, interruption, validation, exit codes and real CLI runs against a loopback server. The real-process test verifies each generated bundle's checksums.

## Self-contained demonstration

```powershell
.\.venv\Scripts\python tools/demo_session.py
```

The demo starts an ephemeral loopback server that returns healthy, outage and recovery responses across three cycles. It verifies those transitions, stops the server, and retains evidence under reports/session-demo. The demo returns 0 when the scenario behaves as expected, even though its underlying session intentionally contains one warning cycle. It requires no public endpoint or credentials.

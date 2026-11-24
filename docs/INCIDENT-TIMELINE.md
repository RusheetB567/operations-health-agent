# Incident evidence timeline

Place service observations and coarse log-pattern spans alongside each other:

```powershell
.\.venv\Scripts\python triage_logs.py examples/incident-logs.jsonl --output reports/triage.json
.\.venv\Scripts\python incident_timeline.py examples/session-timeline.json reports/triage.json --window-seconds 30 --output reports/timeline.json --html-output reports/timeline.html
```

The synthetic log triage and timeline intentionally return warning exit 1. Both commands still produce usable evidence. For real investigation, substitute a monitoring session's session.json and a summary produced by triage_logs.py. No probes, network requests or raw-log processing occur in the timeline command.

## Interpretation

Each timed service event gets a symmetric UTC window, default plus/minus 60 seconds. A log pattern is displayed if its first/last observed span intersects that window, including boundaries. The command does not possess individual log-event timestamps from the summary, so an intersecting span is not proof that any of the pattern's individual occurrences fell inside the window. Counts describe the full pattern, never a calculated per-window event count.

The log source is not mapped to specific services. Matching evidence can be relevant to a different application, and clocks can be skewed. This is temporal alignment, not correlation strength, root-cause attribution or proof of causality. Broad spans can create misleading apparent proximity; use original logs locally for deeper investigation.

Added, removed and reconfigured service events remain distinct from openings/recoveries. Untimed service events and untimed patterns are retained/countable without fabricated overlap. Timeline entries are sorted by observed UTC timestamp, with untimed events last.

## Coverage and safety

The output carries malformed/oversized/untimed/dropped-message counts, truncation flags, match-cap flags and windows extending outside an explicitly selected log window. No matching span is not proof that no related log exists. Empty or incomplete inputs can leave coverage uncertain.

Raw log messages, arbitrary metadata, source paths and endpoint addresses are not copied. Output still contains service labels, timestamps, fixed categories and per-run log fingerprints, which can be sensitive. Fingerprints belong to one triage invocation and should not be linked across independent runs.

Input metadata is bounded to 4 MiB per file, 1000 service events and 1000 log patterns. Duplicate JSON keys, invalid schemas, counts, categories and reversed spans are rejected. --window-seconds accepts 0–3600; --max-matches accepts 1–50, default 10 per service observation. Excess matching patterns are counted but not all displayed.

Output destinations must be distinct and must preserve both inputs. Each file is atomically written separately; failure of a later HTML write can leave a successful JSON output. The offline HTML uses escaping and a restrictive policy with no scripts or remote assets.

Exit 0 means no reported error/opening or coverage warning; 1 means investigation-worthy observations or limited coverage; 2 means invalid configuration, input or persistence failure. No authentication testing, remediation, upload or automatic Git action occurs.

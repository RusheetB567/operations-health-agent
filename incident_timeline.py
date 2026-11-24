"""Align service observations with coarse log-pattern spans; never infer cause."""
import argparse
import html
import json
import re
import sys
from datetime import timedelta
from pathlib import Path

from run_profile import unique_object
from system_health import write_report
from triage_logs import timestamp

EVENTS = {"initial_warning", "opened", "recovered", "added", "removed", "reconfigured"}
CATEGORIES = {"timeout", "connection", "database", "authentication", "capacity", "other"}
CAUTION = "Temporal overlap only. Pattern first/last timestamps do not prove individual log events occurred near this service observation, that logs belong to this service, or that one caused the other."


def load_evidence(path):
    with Path(path).open("rb") as stream:
        data = stream.read(4194305)
    if len(data) > 4194304:
        raise ValueError("input exceeds 4 MiB")
    result = json.loads(data.decode("utf-8"), object_pairs_hook=unique_object)
    if not isinstance(result, dict) or type(result.get("schema_version")) is not int or result["schema_version"] != 1:
        raise ValueError("unsupported evidence schema")
    return result


def nonnegative(value):
    if type(value) is not int or not 0 <= value <= 1000000:
        raise ValueError("invalid count")
    return value


def align(session, logs, window_seconds=60, max_matches=10):
    if type(window_seconds) is not int or not 0 <= window_seconds <= 3600:
        raise ValueError("window must be 0–3600 seconds")
    if type(max_matches) is not int or not 1 <= max_matches <= 50:
        raise ValueError("max_matches must be 1–50")
    for report in (session, logs):
        if not isinstance(report, dict) or type(report.get("schema_version")) is not int or report["schema_version"] != 1:
            raise ValueError("unsupported evidence schema")
    events, patterns = session.get("events"), logs.get("patterns")
    if not isinstance(events, list) or len(events) > 1000 or not isinstance(patterns, list) or len(patterns) > 1000:
        raise ValueError("input exceeds 1000 events or patterns")
    counts, levels = logs.get("counts"), logs.get("levels")
    if not isinstance(counts, dict) or not isinstance(levels, dict) or type(logs.get("truncated")) is not bool:
        raise ValueError("not a log triage summary")
    selected = nonnegative(counts.get("selected_records"))
    log_window = logs.get("window", {})
    if not isinstance(log_window, dict):
        raise ValueError("invalid log window")
    log_start = timestamp(log_window["since"]) if log_window.get("since") is not None else None
    log_end = timestamp(log_window["until"]) if log_window.get("until") is not None else None
    if log_start and log_end and log_start > log_end:
        raise ValueError("reversed log window")
    quality = {key: nonnegative(counts.get(key, 0)) for key in (
        "malformed_lines", "oversized_lines", "untimed_records", "ungrouped_errors", "unusable_error_messages")}
    errors = nonnegative(levels.get("ERROR", 0)) + nonnegative(levels.get("CRITICAL", 0))
    if errors > selected:
        raise ValueError("error counts exceed selected records")
    anchored, untimed, seen = [], 0, set()
    pattern_observations = 0
    for item in patterns:
        if not isinstance(item, dict):
            raise ValueError("invalid pattern")
        token = item.get("fingerprint")
        if not isinstance(token, str) or not re.fullmatch(r"[0-9a-f]{24}", token) or token in seen:
            raise ValueError("invalid/duplicate per-run fingerprint")
        seen.add(token)
        category, count = item.get("category"), nonnegative(item.get("count"))
        if not isinstance(category, str) or category not in CATEGORIES or count < 1:
            raise ValueError("invalid pattern category or count")
        pattern_observations += count
        first, last = item.get("first_seen"), item.get("last_seen")
        if first is None and last is None:
            untimed += 1
            continue
        first, last = timestamp(first), timestamp(last)
        if first > last:
            raise ValueError("reversed pattern span")
        anchored.append({"fingerprint": token, "category": category, "count": count,
                         "first": first, "last": last})
    if pattern_observations > errors:
        raise ValueError("grouped counts exceed error records")
    anchored.sort(key=lambda item: (item["first"], item["fingerprint"]))
    rows = []
    for index, item in enumerate(events):
        if not isinstance(item, dict) or item.get("event") not in EVENTS:
            raise ValueError("invalid service event")
        name = item.get("service")
        if not isinstance(name, str) or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,63}", name):
            raise ValueError("invalid service label")
        cycle = item.get("cycle")
        if type(cycle) is not int or not 1 <= cycle <= 100:
            raise ValueError("invalid cycle")
        raw_time = item.get("timestamp")
        observed = timestamp(raw_time) if raw_time is not None else None
        start = observed - timedelta(seconds=window_seconds) if observed else None
        end = observed + timedelta(seconds=window_seconds) if observed else None
        outside_coverage = bool(observed and ((log_start and start < log_start) or (log_end and end > log_end)))
        candidates = [pattern for pattern in anchored if observed is not None and pattern["first"] <= end and pattern["last"] >= start]
        matches = [{"fingerprint": pattern["fingerprint"], "category": pattern["category"],
                    "total_pattern_observations": pattern["count"], "first_seen": pattern["first"].isoformat(),
                    "last_seen": pattern["last"].isoformat(), "basis": "pattern_range_overlap_not_exact_event_match"}
                   for pattern in candidates[:max_matches]]
        rows.append({"service": name, "event": item["event"], "cycle": cycle,
                     "timestamp": observed.isoformat() if observed else None,
                     "window_start": start.isoformat() if start else None, "window_end": end.isoformat() if end else None,
                     "alignment": "unanchored_service_event" if observed is None else (
                         "pattern_span_overlap" if candidates else "no_pattern_span_overlap"),
                     "overlapping_patterns": len(candidates), "matches_limited": len(candidates) > max_matches,
                     "window_extends_beyond_selected_log_window": outside_coverage,
                     "matches": matches, "input_order": index})
    rows.sort(key=lambda item: (item["timestamp"] is None, item["timestamp"] or "", item["input_order"]))
    for row in rows:
        del row["input_order"]
    limits = not rows or selected == 0 or logs["truncated"] or any(quality.values()) or untimed > 0 or any(row["matches_limited"] or row["timestamp"] is None or row["window_extends_beyond_selected_log_window"] for row in rows)
    warning = errors > 0 or any(row["event"] in ("opened", "initial_warning") for row in rows) or limits
    return {"schema_version": 1, "status": "warning" if warning else "healthy", "window_seconds": window_seconds,
            "summary": {"service_events": len(rows), "events_with_span_overlap": sum(bool(row["matches"]) for row in rows),
                        "selected_log_records": selected, "error_records": errors, "anchored_patterns": len(anchored),
                        "unanchored_patterns": untimed},
            "quality": {**quality, "logs_truncated": logs["truncated"], "coverage_limited": bool(limits)},
            "timeline": rows, "interpretation": CAUTION,
            "privacy": "service labels, UTC timestamps, fixed categories and per-run fingerprints only; no raw logs, endpoint targets or source paths"}


def render_timeline(report):
    escape = lambda value: html.escape(str(value), quote=True)
    rows = []
    for event in report["timeline"]:
        matches = '; '.join(f'{item["category"]} ({item["total_pattern_observations"]} across full pattern span)' for item in event["matches"]) or 'No displayed matches'
        rows.append('<tr>' + ''.join(f'<td>{escape(value)}</td>' for value in (
            event["timestamp"] or "Untimed", event["service"], event["event"], event["cycle"],
            event["alignment"], matches)) + '</tr>')
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'">
<title>Incident evidence timeline</title><style>body{{font:16px/1.5 system-ui;background:#101827;color:#e5edf7;margin:2rem}}main{{max-width:1200px;margin:auto}}.scroll{{overflow:auto}}table{{border-collapse:collapse;width:100%}}th,td{{padding:.7rem;border-bottom:1px solid #56677e;text-align:left}}.notice{{padding:1rem;border:1px solid #ffc069}}@media print{{body{{background:white;color:black}}}}</style></head>
<body><main><h1>Incident evidence timeline</h1><p class="notice">{escape(report["interpretation"])}</p>
<p>Service observations: {report["summary"]["service_events"]}. Events with overlapping pattern spans: {report["summary"]["events_with_span_overlap"]}. Coverage limited: {escape(report["quality"]["coverage_limited"])}.</p>
<div class="scroll"><table><caption>Observed service changes and coarse log-pattern evidence</caption><thead><tr>
<th scope="col">UTC time</th><th scope="col">Service</th><th scope="col">Observation</th><th scope="col">Cycle</th><th scope="col">Alignment</th><th scope="col">Pattern evidence</th>
</tr></thead><tbody>{''.join(rows)}</tbody></table></div><p>Static local evidence. No network requests, scripts or remote assets. Service labels and times may still be sensitive.</p></main></body></html>'''


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("session", type=Path)
    parser.add_argument("triage", type=Path)
    parser.add_argument("--window-seconds", type=int, default=60)
    parser.add_argument("--max-matches", type=int, default=10)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--html-output", type=Path)
    args = parser.parse_args(argv)
    try:
        sources = {args.session.resolve(), args.triage.resolve()}
        destinations = [path.resolve() for path in (args.output, args.html_output) if path]
        if len(set(destinations)) != len(destinations) or any(path in sources for path in destinations):
            raise ValueError("outputs must be distinct and preserve inputs")
        report = align(load_evidence(args.session), load_evidence(args.triage), args.window_seconds, args.max_matches)
        payload = json.dumps(report, indent=2) + "\n"
        page = render_timeline(report) if args.html_output else None
        if args.output:
            write_report(args.output, payload)
        if args.html_output:
            write_report(args.html_output, page)
        print(payload, end="")
        return 1 if report["status"] == "warning" else 0
    except (OSError, ValueError, TypeError, OverflowError, RecursionError):
        print(json.dumps({"status": "error", "error": "timeline failed; check evidence schemas windows limits and output paths"}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())

"""Offline service analytics dashboard and optional CSV/JSON summary export."""
import argparse
import html
import json
import math
import sys
from pathlib import Path

from incident_compare import compare_reports, load_report, validate_report
from report_analytics import duration, order_services, select_report, statistics
from report_csv import export_csv
from system_health import write_report


def escape(value):
    return html.escape(str(value), quote=True)


def number(value, suffix=""):
    return "Unavailable" if value is None else f"{escape(value)}{suffix}"


def render(report, previous=None, redact_targets=False, sort="health", slow_ms=1000):
    validate_report(report)
    stats = statistics(report, slow_ms)
    times = stats["probe_duration"]
    cards = [("Services", stats["total"]), ("Healthy", stats["healthy"]), ("Warnings", stats["warning"]),
             ("Snapshot healthy", f'{stats["healthy_percent"]}%'), ("P50 probe", number(times["p50_ms"], " ms")),
             ("P95 probe", number(times["p95_ms"], " ms")), ("Slow checks", times["slow_count"])]
    card_html = ''.join(f'<div class="card">{escape(label)}<strong>{value}</strong></div>' for label, value in cards)
    group_rows = ''.join('<tr>' + ''.join(f'<td>{escape(value)}</td>' for value in (
        name, group["total"], group["healthy"], group["warning"], f'{group["healthy_percent"]}%')) + '</tr>'
        for name, group in stats["groups"].items())
    rows = []
    for item in order_services(report["services"], sort):
        detail = item["detail"]
        target = "[endpoint hidden]" if redact_targets else detail.get("url", f'{detail.get("host", "—")}:{detail.get("port", "—")}')
        measured = duration(item)
        row = f'<tr class="{item["status"]}"><th scope="row">{escape(item["name"])}</th>'
        row += ''.join(f'<td>{escape(value)}</td>' for value in (item["group"], item["type"], item["status"],
            detail.get("status", "unknown"), target, detail.get("http_status", "—")))
        row += f'<td>{number(measured, " ms")}{" · slow" if measured is not None and measured >= slow_ms else ""}</td></tr>'
        rows.append(row)
    maximum = times["max_ms"] or 1
    bars = ''.join(f'<li><span>{escape(item["name"])}</span><meter min="0" max="{maximum}" value="{item["duration_ms"]}">{item["duration_ms"]}</meter><span>{item["duration_ms"]} ms</span></li>'
                   for item in stats["slowest"])
    diagnostics = ''.join(f'<li>{escape(name)}: <strong>{count}</strong></li>' for name, count in stats["diagnostics"].items())
    transitions = ""
    if previous is not None:
        delta = compare_reports(previous, report)
        transitions = '<section id="changes"><h2>Changes since previous snapshot</h2><ul>' + ''.join(
            f'<li>{escape(key.replace("_", " "))}: {escape(json.dumps(value))}</li>'
            for key, value in delta["changes"].items() if value) + '</ul></section>'
    return f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'">
<title>Service health snapshot</title><style>
:root{{color-scheme:dark}}body{{font:16px/1.55 system-ui,sans-serif;background:#101827;color:#e5edf7;margin:0;padding:2rem}}
main{{max-width:1320px;margin:auto}}h1{{margin-bottom:.25rem}}a{{color:#a8d5ff}}.muted{{color:#b6c6dc}}
nav{{display:flex;gap:1rem;flex-wrap:wrap;margin:1rem 0}}.cards{{display:flex;flex-wrap:wrap;gap:1rem;margin:1.5rem 0}}
.card{{background:#1c2a40;border:1px solid #4b607d;border-radius:12px;padding:1rem;min-width:130px}}.card strong{{display:block;font-size:1.7rem}}
.scroll{{overflow:auto}}table{{border-collapse:collapse;width:100%;background:#18253a}}th,td{{padding:.75rem;text-align:left;border-bottom:1px solid #4b607d;overflow-wrap:anywhere}}
caption{{text-align:left;padding:.5rem 0}}thead th{{background:#22344f}}.warning th[scope=row]{{border-left:4px solid #ffc069}}
section{{margin-top:2rem}}li{{overflow-wrap:anywhere}}.durations li{{display:flex;align-items:center;gap:1rem;flex-wrap:wrap;margin:.75rem 0}}meter{{width:200px;max-width:100%}}
@media(max-width:600px){{body{{padding:1rem}}.card{{flex:1}}}}@media print{{:root{{color-scheme:light}}body{{background:white;color:black}}table,.card,thead th{{background:white}}.muted,a{{color:#333}}nav{{display:none}}}}
</style></head><body><main><h1>Service health snapshot</h1>
<p class="muted">Observed: {escape(report.get("timestamp", "not provided"))}. Static evidence; regenerate to update.</p>
<p>Endpoints {"hidden" if redact_targets else "visible"}; service names and groups remain visible.</p>
<nav aria-label="Report sections"><a href="#overview">Overview</a><a href="#groups">Groups</a><a href="#services">Services</a><a href="#duration">Probe durations</a></nav>
<section id="overview" aria-label="Overview"><div class="cards">{card_html}</div>
<p>These percentages describe selected services in one snapshot, not uptime or an availability SLA.</p></section>
<section id="groups"><h2>Application groups</h2><div class="scroll"><table><caption>Health by group</caption><thead><tr>
<th scope="col">Group</th><th scope="col">Services</th><th scope="col">Healthy</th><th scope="col">Warnings</th><th scope="col">Healthy share</th>
</tr></thead><tbody>{group_rows}</tbody></table></div></section>
<section id="services"><h2>Service diagnostics</h2><div class="scroll"><table><caption>Named service diagnostic results · sorted by {escape(sort)}</caption><thead><tr>
<th scope="col">Service</th><th scope="col">Group</th><th scope="col">Type</th><th scope="col">Health</th><th scope="col">Diagnostic</th><th scope="col">Target</th><th scope="col">HTTP</th><th scope="col">Probe duration</th>
</tr></thead><tbody>{''.join(rows)}</tbody></table></div></section>
<section id="duration"><h2>Probe duration analysis</h2><p>Valid timings: {times["valid"]}. Missing or invalid: {times["missing_or_invalid"]}. Mean: {number(times["mean_ms"], " ms")}. Slow threshold: {slow_ms} ms.</p>
<ul class="durations">{bars or '<li>No valid timing observations.</li>'}</ul><p>Top five measured checks. Timings include probe overhead; P50/P95 use nearest-rank observations from this snapshot, not a historical latency distribution.</p></section>
<section><h2>Diagnostic outcomes</h2><ul>{diagnostics}</ul></section>{transitions}
<section><h2>Interpretation</h2><p>TCP reachability and HTTP status do not prove working login or correct page content. No scripts or remote assets are included. Review names, groups, addresses and timestamps before sharing.</p></section>
</main></body></html>'''


def positive_ms(value):
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError("slow threshold must be finite and positive")
    return number


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("--previous", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--csv-output", type=Path)
    parser.add_argument("--analytics-output", type=Path)
    parser.add_argument("--group")
    parser.add_argument("--warnings-only", action="store_true")
    parser.add_argument("--redact-targets", action="store_true")
    parser.add_argument("--sort", choices=("health", "name", "duration"), default="health")
    parser.add_argument("--slow-ms", type=positive_ms, default=1000)
    args = parser.parse_args(argv)
    try:
        if args.previous and args.warnings_only:
            raise ValueError("warning-only selection cannot establish recoveries")
        outputs = [path for path in (args.output, args.csv_output, args.analytics_output) if path]
        sources = {path.resolve() for path in (args.report, args.previous) if path}
        resolved = [path.resolve() for path in outputs]
        if len(set(resolved)) != len(resolved) or any(path in sources for path in resolved):
            raise ValueError("output paths must be distinct and preserve inputs")
        report = select_report(load_report(args.report), args.group, args.warnings_only)
        previous = select_report(load_report(args.previous), args.group) if args.previous else None
        page = render(report, previous, args.redact_targets, args.sort, args.slow_ms)
        csv_data = export_csv(report, args.redact_targets, args.sort) if args.csv_output else None
        analytics = json.dumps(statistics(report, args.slow_ms), indent=2) if args.analytics_output else None
        write_report(args.output, page)
        if args.csv_output:
            write_report(args.csv_output, csv_data)
        if args.analytics_output:
            write_report(args.analytics_output, analytics + "\n")
        print(json.dumps({"status": "rendered", "output": str(args.output), "selected_services": len(report["services"])}))
        return 0
    except (OSError, ValueError, RecursionError):
        print(json.dumps({"status": "error", "error": "could not render service report; check schema filters and output paths"}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())

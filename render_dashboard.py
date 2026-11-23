"""Render a service report as a standalone offline HTML document."""
import argparse
import html
import json
import sys
from pathlib import Path

from incident_compare import compare_reports, load_report, validate_report
from system_health import write_report


def escape(value):
    return html.escape(str(value), quote=True)


def render(report, previous=None):
    validate_report(report)
    services = report["services"]
    healthy = sum(item["status"] == "healthy" for item in services)
    rows = []
    for item in services:
        detail = item["detail"]
        target = detail.get("url", f'{detail.get("host", "—")}:{detail.get("port", "—")}')
        rows.append("<tr>" + "".join(f"<td>{escape(value)}</td>" for value in (
            item["name"], item["group"], item["type"], item["status"], detail.get("status", "unknown"),
            target, detail.get("http_status", "—"), detail.get("duration_ms", "—"))) + "</tr>")
    transitions = ""
    if previous is not None:
        delta = compare_reports(previous, report)
        transitions = '<section><h2>Changes since previous snapshot</h2><ul>' + "".join(
            f"<li>{escape(key.replace('_', ' '))}: {escape(json.dumps(value))}</li>"
            for key, value in delta["changes"].items() if value) + "</ul></section>"
    return f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'">
<title>Service health snapshot</title><style>
body{{font:16px/1.5 system-ui,sans-serif;background:#101827;color:#e5edf7;margin:0;padding:2rem}}
main{{max-width:1200px;margin:auto}}h1{{margin-bottom:.25rem}}.muted{{color:#b6c6dc}}
.cards{{display:flex;flex-wrap:wrap;gap:1rem;margin:1.5rem 0}}.card{{background:#1c2a40;border:1px solid #4b607d;border-radius:12px;padding:1rem;min-width:140px}}
.card strong{{display:block;font-size:2rem}}.scroll{{overflow:auto}}table{{border-collapse:collapse;width:100%;background:#18253a}}
th,td{{padding:.75rem;text-align:left;border-bottom:1px solid #4b607d;overflow-wrap:anywhere}}caption{{text-align:left;padding:.5rem 0}}th{{background:#22344f}}
section{{margin-top:2rem}}li{{overflow-wrap:anywhere}}@media print{{body{{background:white;color:black}}table,th{{background:white}}.muted{{color:#333}}}}
</style></head><body><main><h1>Service health snapshot</h1>
<p class="muted">Observed: {escape(report.get("timestamp", "not provided"))}. Static evidence; refresh by generating another report.</p>
<div class="cards"><div class="card">Services<strong>{len(services)}</strong></div>
<div class="card">Healthy<strong>{healthy}</strong></div><div class="card">Warnings<strong>{len(services)-healthy}</strong></div></div>
<div class="scroll"><table><caption>Named service diagnostic results</caption><thead><tr>
<th scope="col">Service</th><th scope="col">Group</th><th scope="col">Type</th><th scope="col">Health</th>
<th scope="col">Diagnostic</th><th scope="col">Target</th><th scope="col">HTTP</th><th scope="col">Milliseconds</th>
</tr></thead><tbody>{''.join(rows)}</tbody></table></div>{transitions}
<section><h2>Interpretation</h2><p>TCP reachability and HTTP status are observations, not proof of a working login or correct application content. This document contains no scripts or remote assets. Host and target details may be sensitive; review before sharing.</p></section>
</main></body></html>'''


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("--previous", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        page = render(load_report(args.report), load_report(args.previous) if args.previous else None)
        write_report(args.output, page)
        print(json.dumps({"status": "rendered", "output": str(args.output)}))
        return 0
    except (OSError, ValueError, RecursionError):
        print(json.dumps({"status": "error", "error": "could not render service report; check schema and paths"}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())

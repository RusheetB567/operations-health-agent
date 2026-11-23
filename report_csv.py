"""CSV service export with formula-injection mitigation for text fields."""
import csv
import io

from incident_compare import validate_report
from report_analytics import duration, order_services


def safe_cell(value):
    text = str(value)
    if text and (text[0] in "=+-@\t\r\n" or text.lstrip().startswith(("=", "+", "-", "@"))):
        return "'" + text
    return text


def export_csv(report, redact_targets=False, sort="health"):
    validate_report(report)
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow(["service", "group", "transport", "health", "diagnostic", "target", "http_status", "probe_duration_ms"])
    for item in order_services(report["services"], sort):
        detail = item["detail"]
        target = detail.get("url", f'{detail.get("host", "")}:{detail.get("port", "")}')
        target = "[endpoint hidden]" if redact_targets else target
        writer.writerow([safe_cell(value) for value in (
            item["name"], item["group"], item["type"], item["status"], detail.get("status", "unknown"),
            target, detail.get("http_status", ""), duration(item) if duration(item) is not None else "")])
    return stream.getvalue()

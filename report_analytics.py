"""Snapshot statistics, not historical availability or application response SLAs."""
import math
from collections import Counter

from incident_compare import validate_report


def duration(item):
    value = item["detail"].get("duration_ms")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        return float(value) if math.isfinite(value) and value >= 0 else None
    except OverflowError:
        return None


def select_report(report, group=None, warnings_only=False):
    validate_report(report)
    selected = [item for item in report["services"]
                if (group is None or item["group"] == group)
                and (not warnings_only or item["status"] == "warning")]
    if not selected:
        raise ValueError("no services match the selected filters")
    return {**report, "services": selected}


def order_services(services, mode="health"):
    if mode == "health":
        return sorted(services, key=lambda item: (item["status"] != "warning", item["group"], item["name"]))
    if mode == "name":
        return sorted(services, key=lambda item: item["name"])
    if mode == "duration":
        return sorted(services, key=lambda item: (duration(item) is None, -(duration(item) or 0), item["name"]))
    raise ValueError("unknown sort mode")


def statistics(report, slow_ms=1000):
    validate_report(report)
    if not math.isfinite(slow_ms) or slow_ms <= 0:
        raise ValueError("slow threshold must be positive and finite")
    services = report["services"]
    healthy = sum(item["status"] == "healthy" for item in services)
    observations = sorted(value for item in services if (value := duration(item)) is not None)
    groups = {}
    diagnostics = Counter()
    transports = Counter()
    http_codes = Counter()
    for item in services:
        group = groups.setdefault(item["group"], {"total": 0, "healthy": 0, "warning": 0})
        group["total"] += 1
        group[item["status"]] += 1
        transports[item["type"]] += 1
        status = item["detail"].get("status", "unknown")
        # Diagnostic buckets are fixed so arbitrary report values aren't copied.
        known = {"ready", "reachable", "unexpected_status", "connection_error", "timeout", "error",
                 "dns_error", "refused", "unreachable", "internal_error"}
        diagnostics[status if isinstance(status, str) and status in known else "unknown"] += 1
        code = item["detail"].get("http_status")
        if type(code) is int and 100 <= code <= 599:
            http_codes[str(code)] += 1
    for group in groups.values():
        group["healthy_percent"] = round(group["healthy"] / group["total"] * 100, 2)
    def percentile(percent):
        return round(observations[max(0, math.ceil(len(observations) * percent) - 1)], 2) if observations else None
    slowest = [{"name": item["name"], "group": item["group"], "duration_ms": duration(item), "status": item["status"]}
               for item in order_services(services, "duration") if duration(item) is not None][:5]
    return {"schema_version": 1, "total": len(services), "healthy": healthy, "warning": len(services) - healthy,
            "healthy_percent": round(healthy / len(services) * 100, 2),
            "warning_percent": round((len(services) - healthy) / len(services) * 100, 2),
            "groups": dict(sorted(groups.items())), "diagnostics": dict(sorted(diagnostics.items())),
            "transports": dict(sorted(transports.items())), "http_codes": dict(sorted(http_codes.items())),
            "probe_duration": {"valid": len(observations), "missing_or_invalid": len(services) - len(observations),
                               "min_ms": min(observations) if observations else None,
                               "max_ms": max(observations) if observations else None,
                               "p50_ms": percentile(0.5), "p95_ms": percentile(0.95),
                               "mean_ms": round(sum(value / len(observations) for value in observations), 2) if observations else None,
                               "slow_threshold_ms": slow_ms,
                               "slow_count": sum(value >= slow_ms for value in observations)},
            "slowest": slowest}

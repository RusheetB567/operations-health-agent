"""Explainable offline review recommendations; never perform remediation."""
import argparse
import html
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import portable_pack as portable
from run_profile import unique_object
from system_health import write_report
from triage_logs import time_argument, timestamp

KINDS = {"error_records_at_least", "category_records_at_least", "service_events_at_least", "coverage_limited", "age_minutes_at_least"}
CATEGORIES = {"timeout", "connection", "database", "authentication", "capacity", "other"}


def label(value):
    portable.safe_name(value)
    if len(value) > 64:
        raise ValueError("policy labels must fit 64 characters")
    return value


def validate_policy(policy):
    if (not isinstance(policy, dict) or set(policy) != {"version", "name", "rules"}
            or type(policy["version"]) is not int or policy["version"] != 1):
        raise ValueError("invalid policy envelope")
    label(policy["name"])
    if not isinstance(policy["rules"], list) or not 1 <= len(policy["rules"]) <= 25:
        raise ValueError("policy requires 1–25 rules")
    seen = set()
    for rule in policy["rules"]:
        if not isinstance(rule, dict):
            raise ValueError("invalid policy rule")
        identity = label(rule.get("id"))
        if identity in seen:
            raise ValueError("duplicate rule ID")
        seen.add(identity)
        kind = rule.get("type")
        if not isinstance(kind, str) or kind not in KINDS or rule.get("severity") not in ("review", "block"):
            raise ValueError("unsupported rule or severity")
        expected = {"id", "type", "severity"}
        if kind != "coverage_limited":
            expected.add("threshold")
            maximum = 525600 if kind == "age_minutes_at_least" else 1000000
            if type(rule.get("threshold")) is not int or not 1 <= rule["threshold"] <= maximum:
                raise ValueError("invalid rule threshold")
        if kind == "category_records_at_least":
            expected.add("category")
            if not isinstance(rule.get("category"), str) or rule["category"] not in CATEGORIES:
                raise ValueError("invalid diagnostic category")
        if set(rule) != expected:
            raise ValueError("unknown or missing rule properties")
    return policy


def load_policy(path):
    with Path(path).open("rb") as stream:
        raw = portable.read_bounded(stream, 65536)
    return validate_policy(json.loads(raw.decode("utf-8"), object_pairs_hook=unique_object))


def count(value, maximum=1000000):
    if type(value) is not int or not 0 <= value <= maximum:
        raise ValueError("invalid evidence count")
    return value


def facts_from_pack(path):
    blobs, _ = portable.source_files(path, portable.Limits())
    manifest = portable.metadata(blobs["manifest.json"], portable.Limits())
    timeline = json.loads(blobs[manifest["files"]["report"]].decode("utf-8"), object_pairs_hook=unique_object)
    logs = json.loads(blobs[manifest["files"]["log_summary"]].decode("utf-8"), object_pairs_hook=unique_object)
    for artifact in (timeline, logs):
        if not isinstance(artifact, dict) or type(artifact.get("schema_version")) is not int or artifact["schema_version"] != 1:
            raise ValueError("unsupported evidence schema")
    summary = timeline.get("summary")
    if not isinstance(summary, dict) or manifest.get("summary") != summary:
        raise ValueError("inconsistent evidence summary")
    errors = count(summary.get("error_records"))
    events = count(summary.get("service_events"), 1000)
    selected = count(summary.get("selected_log_records"))
    categories = logs.get("categories")
    if errors > selected or not isinstance(categories, dict) or set(categories) - CATEGORIES:
        raise ValueError("invalid evidence category/counts")
    categories = {name: count(value) for name, value in categories.items()}
    if sum(categories.values()) > errors:
        raise ValueError("categories exceed error records")
    quality = timeline.get("quality")
    coverage = quality.get("coverage_limited") if isinstance(quality, dict) else None
    if coverage is not None and type(coverage) is not bool:
        raise ValueError("invalid coverage flag")
    return {"pack_id": portable.checksum(blobs["manifest.json"]),
            "created_at": timestamp(manifest.get("created_at")).isoformat(timespec="microseconds"),
            "error_records": errors, "service_events": events, "categories": categories, "coverage_limited": coverage}


def evaluate(facts, policy, at=None):
    validate_policy(policy)
    at = at or datetime.now(timezone.utc)
    if at.tzinfo is None or at.utcoffset() is None:
        raise ValueError("evaluation reference requires a timezone")
    at = at.astimezone(timezone.utc)
    age = (at - timestamp(facts["created_at"])).total_seconds() / 60
    guards = ["pack_creation_is_after_reference_time"] if age < 0 else []
    checks = []
    for rule in policy["rules"]:
        kind = rule["type"]
        if kind == "error_records_at_least":
            observed = facts["error_records"]
        elif kind == "service_events_at_least":
            observed = facts["service_events"]
        elif kind == "category_records_at_least":
            observed = facts["categories"].get(rule["category"], 0)
        elif kind == "coverage_limited":
            observed = facts["coverage_limited"]
        else:
            observed = age
        state = "unknown" if observed is None else "matched" if (
            observed is True if kind == "coverage_limited" else observed >= rule["threshold"]) else "unmatched"
        if state == "unknown" and "unknown_rule_fact" not in guards:
            guards.append("unknown_rule_fact")
        checks.append({**rule, "observed": observed, "state": state})
    decision = "block" if any(item["state"] == "matched" and item["severity"] == "block" for item in checks) else (
        "review" if guards or any(item["state"] == "matched" for item in checks) else "pass")
    return {"schema_version": 1, "report_type": "evidence-policy-review", "decision": decision,
            "pack_id": facts["pack_id"], "policy": policy["name"],
            "policy_sha256": portable.checksum(json.dumps(policy, sort_keys=True, separators=(",", ":")).encode()),
            "evaluated_at": at.isoformat(timespec="microseconds"), "pack_created_at": facts["created_at"],
            "guards": guards, "checks": checks,
            "interpretation": "Offline review recommendation only; no service, publication, file access or remediation was automatically blocked or changed."}


def render_review(report):
    escape = lambda value: html.escape(str(value), quote=True)
    rows = ''.join('<tr>' + ''.join(f'<td>{escape(value)}</td>' for value in (
        rule["id"], rule["type"], rule.get("category", "—"), rule["observed"] if rule["observed"] is not None else "Unknown",
        rule.get("threshold", "true"), rule["severity"], rule["state"])) + '</tr>' for rule in report["checks"])
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'">
<title>Evidence review recommendation</title><style>body{{font:16px/1.5 system-ui;background:#101827;color:#e5edf7;margin:2rem}}table{{border-collapse:collapse}}th,td{{padding:.7rem;border:1px solid #53677f}}.scroll{{overflow:auto}}@media print{{body{{background:white;color:black}}}}</style></head>
<body><main><h1>Recommendation: {escape(report["decision"])}</h1><p>{escape(report["interpretation"])}</p>
<p>Policy: {escape(report["policy"])}. Evaluated UTC: {escape(report["evaluated_at"])}.</p><p>Uncertainty guards: {escape(', '.join(report["guards"]) or 'None')}.</p>
<div class="scroll"><table><caption>Rule-by-rule evidence review</caption><thead><tr><th scope="col">Rule</th><th scope="col">Condition</th><th scope="col">Category</th><th scope="col">Observed</th><th scope="col">Threshold</th><th scope="col">Severity</th><th scope="col">Result</th></tr></thead><tbody>{rows}</tbody></table></div></main></body></html>'''


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pack", type=Path)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--at", type=time_argument, help="Explicit timezone-aware reference for reproducible retrospective reviews")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--html-output", type=Path)
    args = parser.parse_args(argv)
    try:
        outputs = [path.resolve() for path in (args.output, args.html_output) if path]
        if len(set(outputs)) != len(outputs) or any(path.is_relative_to(args.pack.resolve()) or path == args.policy.resolve() for path in outputs):
            raise ValueError("outputs must preserve policy and evidence")
        report = evaluate(facts_from_pack(args.pack), load_policy(args.policy), args.at)
        page = render_review(report) if args.html_output else None
        if args.output:
            write_report(args.output, json.dumps(report, indent=2) + "\n")
        if args.html_output:
            write_report(args.html_output, page)
        print(json.dumps(report, indent=2))
        return {"pass": 0, "review": 1, "block": 3}[report["decision"]]
    except (OSError, ValueError, TypeError, KeyError, OverflowError, RecursionError):
        print(json.dumps({"status": "error", "error": "evidence review failed; check policy schema hashes reference time and output paths"}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())

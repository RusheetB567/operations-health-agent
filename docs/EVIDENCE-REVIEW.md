# Offline evidence review policies

Evaluate an investigation pack against declarative thresholds:

```powershell
.\.venv\Scripts\python review_evidence.py reports/investigations/run-investigation-EXAMPLE --policy examples/evidence-review-policy.json --output reports/review.json --html-output reports/review.html
```

Replace the pack path with real evidence. The command verifies source artifact hashes first, then evaluates fixed rule types. It does not execute policy scripts, contact services, send alerts, change access controls, block a deployment or alter evidence.

## Policy format

The JSON root contains version 1, a short name and 1–25 rules. Each rule needs a unique short id, type and severity (`review` or `block`). Unknown properties, duplicate JSON keys/IDs and wrong types are rejected. Policy input is capped at 64 KiB.

| Type | Comparison |
| --- | --- |
| error_records_at_least | Selected ERROR/CRITICAL count >= integer threshold |
| category_records_at_least | Fixed category count >= threshold; requires category |
| service_events_at_least | Number of recorded service transitions >= threshold |
| coverage_limited | True quality flag; no threshold property |
| age_minutes_at_least | Pack age relative to reference >= integer minute threshold |

Counts are report observations, not deduplicated incidents across systems. Categories are heuristic text matches. No rule establishes causality. Count thresholds accept 1–1000000; age thresholds accept 1–525600 minutes. Missing categories mean zero. An absent coverage flag is unknown rather than false.

## Recommendations and safeguards

An unmatched policy recommends pass. A matched review rule recommends review; any matched block rule recommends block. Block is a label for a human decision, not an action enforced by this tool. Unknown required facts or a pack created after the reference time force at least review, preventing silent pass. A matched block rule still takes precedence.

Each output records the observed value, threshold, severity and matched/unmatched/unknown state for every rule. The report links to a manifest-derived pack ID and canonical policy digest without copying source paths, raw log messages or arbitrary metadata. Labels, counts, timestamps and categories remain sensitive.

## Reproducible reference time

Use --at with an explicit timezone-aware ISO timestamp for a retrospective review. Without it, current UTC is used. The report records that reference time. This option makes evaluation repeatable; it does not prove clock correctness or make old evidence current. A negative age is visible through a safeguard rather than silently clamped.

JSON and HTML destinations must be distinct, outside the source pack and different from the policy input. Each output is independently atomic; a later failure can leave an earlier output in place. HTML is static, escaped, offline and script-free.

Exit 0: pass recommendation. Exit 1: review recommendation. Exit 3: block recommendation. Exit 2: invalid policy, inconsistent/unavailable evidence or output failure. A recommendation is not an integrity signature or compliance certification. Protect evidence and policy files separately; there is no policy registry, authentication layer or automated remediation.

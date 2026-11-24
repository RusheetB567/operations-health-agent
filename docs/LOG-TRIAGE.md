# Privacy-safe application log triage

```powershell
.\.venv\Scripts\python triage_logs.py examples/incident-logs.jsonl --output reports/log-triage.json
.\.venv\Scripts\python triage_logs.py examples/incident-logs.jsonl --since 2026-11-24T10:01:00Z --until 2026-11-24T10:03:00Z
```

Use UTF-8 JSONL: one object per line. Recognised fields are `level`, `timestamp` and `message`; other fields are ignored. Supply multiple file paths to aggregate a known set of logs. Files are read as supplied; repeated paths count twice. There is no folder discovery, remote ingestion or live tailing.

## Investigation features

- Inclusive time windows, normalised to UTC. Input/filter timestamps require an explicit timezone.
- Severity counts and fixed heuristic categories: timeout, connection, database, authentication, capacity and other.
- Repeated ERROR/CRITICAL message patterns, with count and earliest/latest observed timestamp.
- Malformed, duplicate-key, invalid-encoding, oversized and unusable-message counts.
- Line budget across all files and a bounded number of distinct patterns.

Numeric IDs, emails, IPv4 addresses and UUID-like tokens are normalised for grouping. The report never includes raw or normalised messages. Fingerprints use HMAC with a fresh random key that is not saved, so they cannot be directly correlated between runs. This grouping is heuristic and can merge different errors or separate similar ones. Categories describe text matches, not verified root causes.

## Processing limits

`--max-lines` defaults to 100000, accepts 1–1000000, and counts physical lines including blanks. `--max-patterns` defaults to 1000 and accepts 1–10000. New patterns exceeding that cap increment `ungrouped_errors`; already-known patterns continue to accumulate. Oversized physical lines above 65536 bytes are drained in bounded chunks. Runtime depends on input size and there is no time limit.

With a time filter, untimed/invalid-timestamp records are excluded and counted, making incomplete coverage visible. Without filters they are included, with no observed timestamps. Malformed records are counted even if their unknown time might have fallen outside the window.

## Privacy and exit status

The summary excludes raw messages, arbitrary record values and input filenames. It still reveals error counts, timestamps, broad categories and per-run grouping. This is not a claim of complete anonymity; protect reports according to their operational sensitivity. Input logs are not modified. An output path that resolves to an input file is rejected.

Exit 0 means no selected ERROR/CRITICAL records and no relevant processing warnings. Exit 1 indicates errors, truncation, malformed/oversized records, dropped patterns or unusable error messages; untimed records also warn when filtering. WARNING records alone do not make the process return 1. Exit 2 means invalid configuration or a file/persistence failure. Results are atomically written when `--output` is supplied.

The existing lightweight `log_analyzer.py` remains available. This new command adds incident investigation features without changing its interface.

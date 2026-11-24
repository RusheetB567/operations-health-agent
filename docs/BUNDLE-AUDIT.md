# Read-only diagnostic bundle audit

Audit complete and incomplete local `run-*` directories without changing the evidence:

```powershell
.\.venv\Scripts\python audit_bundles.py reports/runs --output reports/bundle-audit.json
```

For a monitoring session, pass its bundle directory rather than the sessions parent:

```powershell
.\.venv\Scripts\python audit_bundles.py reports/session-demo/session-EXAMPLE/bundles
```

Replace the illustrative session name with a real one. The auditor does not recurse into arbitrary session directories, launch probes or contact services.

## Findings

The audit checks required manifest roles, declared files, checksum coverage, SHA-256 matches, missing artifacts, unlisted files, old bundles without checksums, incomplete runs and latest-pointer validity. Old unverifiable evidence is flagged rather than silently treated as intact.

The output includes verified/warning bundle counts, inspected artifact bytes, per-bundle issues and latest-pointer issues. Integrity verification is independent of health: a bundle can faithfully record a failed service and still pass its integrity audit.

Artifact names must be simple basenames. Duplicate metadata keys, malformed/oversized metadata and paths outside the audited bundle are rejected or flagged. Symlink/junction bundle escapes are not followed. The optional output must be outside the audited directory so the auditor cannot overwrite inspected evidence.

## Exit status and limits

- 0: every selected bundle and latest pointer verified.
- 1: damaged, missing, partial, legacy, empty or otherwise unverifiable evidence.
- 2: invalid root, limit or output destination, or failure to save the audit output.

`--limit` defaults to 100 and accepts 1–1000. Exceeding it stops the operation rather than presenting a partial scan as complete. Only direct `run-*` entries are considered. Scan ordering is by directory name, not creation time. Scan time depends on artifact sizes; there is no whole-scan timeout or storage quota.

Run audits when collection is idle: concurrent writes can produce transient findings. SHA-256 detects accidental changes relative to the recorded manifest; it is not a signature and cannot prove authenticity if an attacker changes both artifacts and manifest. Metadata reads are bounded to 1 MiB. Artifact hashing streams in chunks.

No deletion, repair, automatic quarantine, retention cleanup or upload is performed. Review findings locally and preserve evidence before manual recovery actions.

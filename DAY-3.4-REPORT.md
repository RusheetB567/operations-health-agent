# Day 3.4 — Portable Archives and Verifiable Handoff

Date: 24 November 2026. Expanded local review package; no staging, commits or pushes by the assistant.

## Implemented archive transport

- Export, verify-without-extraction and staged import for the five-artifact investigation pack plus original manifest.
- Transport index with sizes/digests, deterministic ordering/timestamps and verification before publication.
- Bounds on compressed size, ZIP directory metadata, expanded size, individual files, entry count and compression ratios.
- Rejection of escaping/reserved paths, duplicate/case-colliding names, symlinks, special/directory/encrypted entries, split ZIPs and ZIP64.
- Existing-evidence protection and temporary-file/staging cleanup after ordinary failures.

## Added handoff controls

- Read-only inventory with member roles, sizes, file digests and archive digest.
- Optional separately supplied expected SHA-256 during inspection; required during receipt-based receive.
- Expected-hash mismatch rejection before decompression.
- Import from the exact checked private byte snapshot, protecting against a changed original archive between verification and import.
- External import receipts covering six imported files, without recording local filesystem paths or artifact contents.
- Later read-only receipt verification for changed/missing files and complete coverage.
- Explicit imported_receipt_failed outcome if verified import succeeds but receipt publication fails; imported evidence is preserved.
- Collection guards against duplicate test methods/classes silently replacing regressions.
- Prepared Windows/Linux CI coverage for transport, handoff and collection checks.

## Verification

51 feature/infrastructure tests passed: 32 archive cases, 17 handoff cases and two collection guards. The full 248-test suite passed on an isolated main baseline containing 3.3 plus these changes. All three targeted defect-injection checks and local documentation links passed.

A real synthetic 3.3 pack was exported, verified, imported and compared with its original manifest. A subsequent inventory/receive/receipt-verification smoke flow matched all six imported file records. The smoke flow calculated its expected hash locally for consistency testing; it did not establish independent sender authenticity.

Tests exercise real CLI processes, tampering, malicious metadata/paths, resource policies, reproducibility, read-only inspection, expected hashes, checked-snapshot reuse despite source changes, external receipts, missing/modified files, source preservation and explicit partial completion.

## Files for manual review/commit

1. portable_pack.py
2. archive_handoff.py
3. tests/test_portable_pack.py
4. tests/test_archive_handoff.py
5. tests/test_test_collection.py
6. docs/PORTABLE-PACKS.md
7. docs/ARCHIVE-HANDOFF.md
8. .github/workflows/portable-verification.yml
9. DAY-3.4-REPORT.md

Suggested message: Day - 3.4: add bounded archive transport and verified receipt handoff

Generated previews, inventories and receipts remain under ignored reports. Existing branch selection and published history were preserved. DEV was behind the 3.3 main baseline, so full-system checks used an isolated main export; create fresh source investigation packs on a branch containing 3.3.

## Limits

Archives, receipts and hashes are unsigned and unencrypted. Expected hashes must come from an independently trusted source to add trust beyond local consistency. No malware scan or universal hostile-content sandbox is provided. Receipts need separate protection/authentication. Privacy depends on reviewing pack contents; exporting does not redact arbitrary file contents.

Resource limits can reject legitimate evidence. There is no CPU deadline. New-file publication requires hard-link support, which passed on local Windows NTFS. Concurrent imports to the same destination are unsupported. Filesystem-wide atomicity and recovery from power loss are not guaranteed. A successful import can remain after receipt failure, explicitly reported with exit 2. Abrupt termination can leave temporary data.

Linux/remote CI, independent security review and browser/accessibility review remain unverified.

# Archive handoff and external receipts

The portable ZIP index checks internal consistency. A separately obtained expected archive hash adds a different check: whether the bytes received match the bytes you expected before decompression/import.

## Inspect without importing

```powershell
.\.venv\Scripts\python archive_handoff.py inspect reports/incident.zip --output reports/incident-inventory.json
```

The inventory reports compressed/expanded sizes, archive digest, member roles, sizes and hashes. It does not import artifacts. A temporary private ZIP snapshot is used for verification and removed afterward. File contents and source paths are not copied into the inventory. Artifact names and digests remain visible.

An optional --expected-sha256 value must be a 64-character hexadecimal SHA-256 digest. A mismatch stops processing before ZIP decompression. Without an expected hash, the inventory does not claim one was checked.

## Receive against an expected hash

Obtain the expected archive digest independently from a channel you trust, then substitute its actual hexadecimal value:

```powershell
.\.venv\Scripts\python archive_handoff.py receive reports/incident.zip --expected-sha256 EXPECTED_64_HEX_DIGEST --destination reports/received/run-investigation-copy --receipt reports/receipts/incident-receipt.json
```

The literal placeholder is invalid and must be replaced. Computing a hash from the same untrusted download only tests local consistency; it does not independently establish sender identity or authenticity. SHA-256 is not a signature, and an untrusted sender can supply a matching hash for malicious data.

The receiver validates the expected digest against a bounded byte snapshot, then verifies and imports that exact snapshot. Replacing the original archive between hash checking and import does not change the imported bytes. All existing archive path, size and format policies still apply.

The destination and receipt must both be new. The receipt must be outside the imported pack and cannot overwrite the source archive. It records the archive digest, match result, UTC receipt time and sizes/hashes for the six imported files. It does not record source/destination filesystem paths or raw artifact contents. Keeping it outside the pack preserves the original pack's audit compatibility.

## Verify the imported files later

```powershell
.\.venv\Scripts\python archive_handoff.py verify-receipt reports/receipts/incident-receipt.json --destination reports/received/run-investigation-copy
```

Verification is read-only. It compares the imported manifest and all declared artifacts with the receipt, rejects reduced coverage or escaping paths, and reports changed/missing files. The original archive is not required. This does not validate the receipt's own authenticity: protect or independently authenticate the receipt if it is used as trusted evidence.

## Failure semantics

Inventory/receipt outputs use new-file publication and never overwrite existing evidence. This requires the same hard-link-capable filesystem policy as portable export.

Import and receipt publication are not one atomic transaction. If import succeeds but receipt creation fails, the command returns exit 2 with status imported_receipt_failed, destination information and receipt_saved false. It preserves the verified imported pack and does not delete or roll it back. Inspect the result before retrying; the existing destination cannot simply be reused.

Exit 0 means the requested inventory/receipt operation succeeded. Exit 1 means integrity comparison reported warning findings. Exit 2 means a format, expected-hash, destination or persistence failure, including the explicitly reported partial receipt case.

Archives and receipts are unencrypted and unsigned. These tools do not perform malware scans, network authentication, uploads, automated Git changes or protection against all hostile-format implementation flaws. Review sensitivity before sharing.

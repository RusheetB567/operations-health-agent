# Portable investigation archives

Transport a completed investigation pack without including unlisted files or local source paths. This is local export/import; nothing is uploaded or committed automatically.

## Commands

Replace the example directory names with actual pack results:

```powershell
.\.venv\Scripts\python portable_pack.py export reports/investigations/run-investigation-EXAMPLE --output reports/incident.zip
.\.venv\Scripts\python portable_pack.py verify reports/incident.zip
.\.venv\Scripts\python portable_pack.py import reports/incident.zip --destination reports/imported/run-investigation-copy
.\.venv\Scripts\python artifact_integrity.py reports/imported/run-investigation-copy
```

This feature requires the [3.3 investigation-pack format](INVESTIGATION-PACKS.md) on the branch used to create new source packs. The portable tool itself uses existing manifest/checksum conventions. Host snapshots and arbitrary ZIP files are not accepted as investigation archives.

## Export

The exporter verifies each declared artifact against the original investigation manifest before copying it. Only the five declared artifacts and manifest are included. Extra files beside a pack, such as a raw log, are deliberately omitted.

An archive-index.json records sizes and digests for all six transported files. The ZIP therefore contains seven entries. Names are flat basenames: no directories, absolute paths or relative path navigation. No original filesystem paths or modification times are added. File ordering and ZIP timestamps are fixed, making identical source packs byte-reproducible under the same runtime/compression implementation.

The finished ZIP is verified before publication. It must be outside the source pack, and an existing archive is never overwritten. Publication uses a same-directory hard link and therefore requires a filesystem supporting hard links, such as the tested Windows NTFS volume. Unsupported filesystems return an error and the temporary file is removed. There is no automatic replacement flag.

## Verification before extraction

The verifier checks ZIP directory metadata before constructing its entry objects, then validates names, sizes, compression ratios, entry types, index coverage and manifest coverage. Duplicate names and case collisions are rejected for Windows/Linux portability. Reserved Windows device names, symlink/special entries, directory entries, encrypted entries, split archives and ZIP64 are unsupported.

Successful ZIP decompression/CRC checking alone is insufficient: the index must match all transported files, and original manifest digests must match every artifact. A payload edited into an otherwise valid ZIP is reported as a warning. Structural or size-policy failures are errors.

## Import

All archive content is verified in bounded memory before the destination is created. Validated flat filenames are written explicitly; the implementation does not call extract or extractall. Files are checked again after writing into a temporary staging directory beside the destination. The staging directory is then renamed into place.

The destination must not already exist. Existing directories and files are preserved. Concurrent import into the same destination is unsupported; use distinct destination names. A changed/invalid archive produces no imported destination. Staging is cleaned after ordinary failures. Abrupt termination or power loss can leave temporary data: this is not a crash-proof transaction.

The transport index is not copied into the imported original pack. Its five artifacts and manifest retain their original contents and can be verified with artifact_integrity.py or audited by the existing bundle auditor when stored beneath an appropriate run-* directory.

## Default resource policy

| Boundary | Limit |
| --- | --- |
| ZIP entries | 16 |
| Expanded bytes including transport metadata | 32 MiB |
| Individual expanded entry | 8 MiB |
| Individual parsed JSON metadata | 1 MiB |
| Central-directory metadata | 64 KiB, also constrained by metadata limit |
| Compression ratio for entries over 64 KiB | 200:1 |

The compressed file is also bounded before parsing. Files are read in chunks and archive payloads retained only within the expanded-size policy. These limits can reject a legitimate large or highly compressible pack. There is no CPU deadline, encryption, malware scanning, signature verification or guarantee against every ZIP implementation vulnerability. Treat the tool as a constrained evidence transporter, not an untrusted-content sandbox.

## Privacy and exit codes

Archives are not encrypted. Labels, timestamps and diagnostic categories inside a source pack remain visible. Review before sharing. Checksums detect changes relative to the included metadata, not authenticity: an attacker who rewrites artifacts and both manifests can produce internally consistent data.

Exit 0 means export/import succeeded or an archive verified. Exit 1 means a structurally accepted archive has digest/size mismatches. Exit 2 means the operation failed format, resource, integrity, I/O or destination checks. Invalid archives are never imported.

Tests cover real CLI round-trips, same-runtime reproducibility, tampering, unsafe paths, case collisions, duplicate entries, symlink flags, encrypted flags, split metadata, compression/size limits, source preservation and failure cleanup. Windows verification is local; Linux and remote CI remain pending.

## Review and handoff extensions

Use [archive handoff](ARCHIVE-HANDOFF.md) to inspect a ZIP without importing, require an expected SHA-256 obtained separately, receive the exact checked byte snapshot, and retain an external receipt for later imported-file verification. These are additional consistency controls, not digital signatures or a content-redaction system.

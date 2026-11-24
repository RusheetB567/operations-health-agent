# Local evidence catalogue

Index completed investigation packs without storing raw log bodies or complete artifact contents in the database:

```powershell
.\.venv\Scripts\python evidence_catalogue.py add reports/investigations/run-investigation-EXAMPLE --db reports/evidence.sqlite3
.\.venv\Scripts\python evidence_catalogue.py search --db reports/evidence.sqlite3 --category timeout --service api --html-output reports/catalogue.html
.\.venv\Scripts\python evidence_catalogue.py stats --db reports/evidence.sqlite3
.\.venv\Scripts\python evidence_catalogue.py recheck --db reports/evidence.sqlite3
```

Replace the example directory with a real 3.3 pack. Verification of all source artifact hashes and whitelisted metadata finishes before indexing. The SQLite database must be outside that pack.

## Identity and storage

The pack ID is the SHA-256 of the original manifest bytes. Indexing the same pack again is idempotent. Identical copies at different locations share an identity but keep separate location/check states. Reindexing a changed path creates a new identity and preserves older indexed metadata; an older record may have zero remaining registered locations.

The database stores creation/index/check timestamps, recorded health, reported counts, service labels, fixed categories, expected file hashes/sizes and local pack paths. It does not copy raw logs, notes, HTML bodies or arbitrary metadata. Paths are stored locally but omitted from search output unless --show-paths is explicitly requested. The HTML report always omits paths.

## Search and overview

--since/--until filter pack creation time in UTC, not the earliest incident timestamp. Bounds are inclusive and require a timezone. --category, --service and --health filters combine. Search is parameterised and sorts by creation time then identity. --limit defaults to 20, accepts 1–200, and reports matched/returned counts when results are limited.

The stats command reports identities, locations, records without locations, health counts, last-known integrity states and summed category counts. Different reports can describe overlapping logs; sums are not deduplicated real-world incident/event totals.

## Recheck and maintenance

Recheck compares current bytes with hashes recorded at indexing time, not just the current manifest's claims. Rewriting both an artifact and its manifest therefore produces a changed finding until explicitly reindexed. Missing or unsafe paths are marked missing/unreadable. Recheck updates catalogue integrity metadata, never evidence files. It does not continuously monitor disk changes.

--id selects one full pack ID. The default recheck limit is 100 locations, maximum 1000. Exceeding the limit stops before partial updates; narrow the query or raise the limit. Files are read under the portable pack's size policies. Local path tokens in default recheck output are identifiers, not an anonymity guarantee.

```powershell
.\.venv\Scripts\python evidence_catalogue.py forget FULL_64_HEX_PACK_ID --db reports/evidence.sqlite3
```

Forget removes only that identity's database metadata and registered locations. It does not delete files. An unknown identity returns exit 1. No other command prunes metadata automatically.

## Boundaries

Search never creates a missing database. Schema versions and expected tables are checked, and unrelated databases are rejected. Indexing metadata uses transactions; a failed insert rolls back its pack/location records. SQLite lock timeout is five seconds. No server, remote sync, user authentication, database encryption, backup scheduler or database size quota is provided.

Search HTML cannot overwrite the database or write inside registered evidence directories. Reports are escaped, static and offline. The index and expected hashes are local trust material, not signed attestations; changing the database itself can defeat recheck confidence. Protect and back it up appropriately.

Exit 0 means success (including empty searches). Exit 1 means recheck warnings or an unknown forget ID. Exit 2 means schema, input, filtering, I/O or database failure. Integrity state is independent of recorded service health.

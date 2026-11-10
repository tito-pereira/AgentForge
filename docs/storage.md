# Local state, migrations and recovery

`ContractStore(project_root)` uses a caller-authorized existing local directory.
It initializes `.corinthos/state.db` when needed. Artifacts and snapshots remain
private. Keep `.corinthos/`, backups, journals, and the legacy `.nukytera/`
and `.agentforge/` directories out of Git. The library uses normal OS
permissions and parameterized SQL.

## SQLite version 1

| Table | Contents |
| --- | --- |
| `contracts` | Logical contract identity, project/type and applicable active revision pointer. |
| `revisions` | Canonical document and SHA-256, exact identity, content version and predecessor. |
| `contract_references` | Exact revision-to-revision dependency edges. |
| `audit_events` | Ordered publication events and activation facts, with provenance in the referenced revision. |

Each connection enables foreign keys. The application marker `0x4E554B59` and
SQLite `user_version = 1` identify the database schema. Initialization is an
atomic version 0-to-1 migration for an empty database. Incompatible, foreign and
corrupt stores fail without being rebuilt. The database schema version is
independent of the JSON wire version `1.0`.
Phase 1.1 keeps the application marker, schema version and table meanings when
the state directory changes.

Publication starts an immediate transaction and resolves references within the
transaction. The publisher supplies the exact predecessor. The store compares it
with the current head and uses a conditional update for the active pointer. The
revision, dependencies, activation and audit event commit together. Conflicting
or failed writes roll back. Retry a busy write against the current head.
Identical retries return the same reference without an extra publication event.
New validation runs have separate contract identities. Result, report and request
records preserve historical snapshots.

## Artifacts and trust boundaries

Evidence is read from `.corinthos/artifacts/` using a portable relative path with
slash separators. Paths with traversal, Windows devices, symlinks, junctions,
or hard links are rejected. The kernel hashes regular files and compares their
bytes with the recorded digest. The owner controls permissions and redacts
evidence before storage. Use a new relative path for changed evidence bytes.
Publication rejects changing the digest associated with a retained evidence path.
Database and artifact integrity checks operate within
the local OS account's trust boundary. SQLite is neither encrypted nor a signed
audit ledger. A separate trusted caller must authenticate Engine actors and
approval provenance.

## Migrating existing project state

Treat a repository folder rename and a private state migration as separate
operations. Use an authorized project root under your control as the parent of
both private directories. Close the legacy `.nukytera/` database cleanly and
stop all users of both directories, including artifact writers. The source
must be a writable SQLite v1 database in rollback-journal mode, with no WAL,
shared-memory or rollback journal sidecars. Unsafe filesystem entries,
incomplete trees and incompatible or corrupt databases block migration.
Preserve the source and its sidecars if the database needs recovery first.
Creating a new copy on Windows requires Python 3.12.4 or later for private
staging directory permissions.

After installing the current package, run this in a Python session launched
from the authorized project root.

```python
from pathlib import Path

from corinthos.contracts.migration import migrate_legacy_state

migrated = migrate_legacy_state(Path.cwd())
```

The explicit migration verifies the legacy SQLite v1 database, copies its
directory tree to a staging directory under the same root, and compares
the inventory and ordinary file digests. It reopens the copied store and checks
exact revision documents, references and evidence before publishing
`.corinthos/` through an atomic move that requires the target to be absent.
The move is available on Windows and Linux filesystems that support it. If the
move is unavailable, migration stops. Atomic publication controls when the
destination becomes visible. Power-loss durability is outside that guarantee.

Published JSON, approval receipts, evidence hashes, backups and snapshots
retain their ordinary file contents. Relative evidence references continue to
resolve beneath the migrated artifact directory. An evidence path that cannot
be verified under the authorized artifact root blocks migration. Custom file
ownership, access control lists and NTFS alternate data streams are outside the
copy and verification guarantees. Preserve the original. If your project
depends on this metadata, use a separate backup and recovery process and verify
the required metadata before relying on the copy.

A successful copy returns `True`. An absent legacy directory or a verified
target with matching inventory and ordinary file digests returns `False`.
A conflict leaves the existing target intact and reports an error. The source
stays at `.nukytera/` for recovery.
Keep it offline while using the verified target. On failure, preserve the
original and resolve the reported issue before retrying. The library migrates
only the supplied root. Opening `ContractStore` does not start a migration.

## Backup and recovery

Call `store.backup()` to make a consistent private `state.backup.db` using
SQLite's backup API. The method fails if a backup already exists. It copies the
database only. Retain and verify the referenced artifacts separately. Keep
backups protected like the live database. Before a future migration, verify a backup and
preserve the original state and related artifacts. Version 1 does not migrate
unknown or nonempty unmarked databases.

If a store fails integrity checks, stop writers and preserve the original files
and any SQLite sidecars. To check a backup, copy it as `.corinthos/state.db` under
a separate authorized recovery project. Open it and inspect its exact revisions,
active pointers and events before deciding how to recover. Keep artifact paths
and digests associated with the original records.

SQLite commits only database state. Git operations, artifact writes and external
tools have their own failure boundaries. An interrupted execution requires its
own evidence inspection and reconciliation before retrying external work.

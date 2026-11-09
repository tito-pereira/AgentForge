# Local state, migrations and recovery

`ContractStore(project_root)` uses a caller-authorized existing local directory.
It initializes `.nukytera/state.db` when needed. Artifacts and snapshots remain
private. Keep `.nukytera/`, backups, journals, and the legacy `.agentforge/`
directory out of Git. The library uses normal OS permissions and parameterized SQL.

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

Publication starts an immediate transaction and resolves references within the
transaction. The publisher supplies the exact predecessor. The store compares it
with the current head and uses a conditional update for the active pointer. The
revision, dependencies, activation and audit event commit together. Conflicting
or failed writes roll back. Retry a busy write against the current head.
Identical retries return the same reference without an extra publication event.
New validation runs have separate contract identities. Result, report and request
records preserve historical snapshots.

## Artifacts and trust boundaries

Evidence is read from `.nukytera/artifacts/` using a portable relative path with
slash separators. Paths with traversal, Windows devices, symlinks, junctions,
or hard links are rejected. The kernel hashes regular files and compares their
bytes with the recorded digest. The owner controls permissions and redacts
evidence before storage. Use a new relative path for changed evidence bytes.
Publication rejects changing the digest associated with a retained evidence path.
Database and artifact integrity checks operate within
the local OS account's trust boundary. SQLite is neither encrypted nor a signed
audit ledger. A separate trusted caller must authenticate Engine actors and
approval provenance.

## Backup and recovery

Call `store.backup()` to make a consistent private `state.backup.db` using
SQLite's backup API. The method fails if a backup already exists. It copies the
database only. Retain and verify the referenced artifacts separately. Keep
backups protected like the live database. Before a future migration, verify a backup and
preserve the original state and related artifacts. Version 1 does not migrate
unknown or nonempty unmarked databases.

If a store fails integrity checks, stop writers and preserve the original files
and any SQLite sidecars. To check a backup, copy it as `.nukytera/state.db` under
a separate authorized recovery project. Open it and inspect its exact revisions,
active pointers and events before deciding how to recover. Keep artifact paths
and digests associated with the original records.

SQLite commits only database state. Git operations, artifact writes and external
tools have their own failure boundaries. An interrupted execution requires its
own evidence inspection and reconciliation before retrying external work.

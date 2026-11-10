# Local state, migrations and recovery

`ContractStore(project_root)` uses a caller-authorized existing local directory.
It initializes `.corinthos/state.db` when needed. Artifacts and snapshots remain
private. Keep `.corinthos/`, backups, journals, and the legacy `.nukytera/`
and `.agentforge/` directories out of Git. The library uses normal OS
permissions and parameterized SQL.

## SQLite version 3

| Table | Contents |
| --- | --- |
| `contracts` | Logical contract identity, project/type and applicable active revision pointer. |
| `revisions` | Canonical document and SHA-256, exact identity, content version and predecessor. |
| `contract_references` | Exact revision-to-revision dependency edges. |
| `audit_events` | Ordered publication events and activation facts, with provenance in the referenced revision. |
| `pm_sessions` | Current negotiation snapshot and optimistic session version. |
| `pm_turns` | Append-only accepted actions, actor labels and complete session snapshots. |
| `pm_approvals` | Exact local review bindings, expiry and one-way receipt consumption. |
| `wf_sessions` | Current planning snapshots in a namespace separate from PM sessions. |
| `wf_turns` | Append-only accepted planning choices and snapshot versions. |
| `wf_approvals` | Exact per-document planning receipts, kinds, expiry and consumption. |
| `wf_mandates` | Explicit human grants for dependency-only Workflow replans. |

Each connection enables foreign keys. The application marker `0x4E554B59` and
SQLite `user_version = 3` identify the current database schema. Initialization is an
atomic version 0-to-3 migration for an empty database. Incompatible, foreign and
corrupt stores fail without being rebuilt. The database schema version is
independent of the JSON wire version `1.0`.
Phase 1.1 preserved SQLite version 1 during the naming migration. Phase 2 adds
operational tables with a versioned forward migration, keeping contract wire
version `1.0`, existing table meanings and published document bytes.

Checkpoint 3.0.A–D adds only planning and publication authority state. A verified
version 2 store is backed up to a unique `state.pre-v3-*.db` before the four new
tables and their immutable-history triggers commit transactionally. PM sessions,
turns, receipts and all existing contract rows retain their bytes and meanings.
Failure rolls back to v2 with the completed backup retained. Version 1 stores
retain their pre-v2 backup and upgrade through both migrations in the same
bounded transaction. Fresh stores require no pre-upgrade backup. The verified
Phase 2 package itself creates the v2 regression fixture used by migration tests.

The generic CAS/append-only turn mechanics are shared with PM persistence.
Workflow-specific table names are fixed internal constants. PM listing and
validation continue to see only PM sessions. Execution scheduling, attempt
leases and general external-process recovery are later checkpoint work.

## Upgrading a version 1 store

Opening a verified version 1 store takes an immediate write reservation, checks
SQLite and foreign-key integrity, and creates a consistent private
`state.pre-v2-<unique-id>.db` backup. The backup uses a separate read connection
while the write reservation prevents concurrent changes. Its integrity and
version markers are checked before publication at an unused filename.

The new tables, append-only turn triggers, immutable receipt bindings and SQLite
version 2 marker commit together. An interrupted or failed upgrade rolls back
the schema transaction and retains any completed backup. Existing contract
documents, digests, references, active pointers and audit rows are preserved.
Read-only, corrupt, incompatible and unsupported future-version stores fail
without reset. Retain the pre-upgrade backup for recovery with the earlier
release. Restoring that backup deliberately returns to its recorded state and
requires stopping all writers first.

## Negotiation and approval transactions

Every accepted edit updates its session with a compare-and-swap version and
appends a uniquely identified turn in the same transaction. Stale versions fail
and must be reloaded. A session snapshot is limited to 1 MiB. Arbitrary partial
keystrokes and model conversation streams are outside this storage API.

An exact review freezes the final document, including its approval metadata,
revision and creation time, before hashing and display. The terminal bridge
requires a distinct random confirmation phrase on the foreground OS terminal.
Piped input and assistant text cannot provide that terminal action. Actor IDs
encode the local account label. This local boundary trusts the OS account and
the Python process, and provides no remote identity authentication.

Publication uses three bounded transactions. First, the approved session version
and exact receipt are committed as `PUBLISHING`. Second, the real Contract Kernel
publishes the immutable document with a verifier bound to that receipt and hash.
Third, receipt consumption and the `PUBLISHED` snapshot commit together.

On restart, recovery reserves the writer before inspecting publication. An exact
committed revision and matching receipt finish the session without republishing.
An absent revision revokes the interrupted approval and requires another review.
The writer reservation orders recovery against an in-flight Kernel transaction.
An expired, consumed, stale or differently bound receipt fails verification.
An edit invalidates a prepared review. Contract predecessor checks also reject
publication after another session advances the active Project revision.
A concurrent session read in the brief interval before Kernel publication can
revoke the pending receipt as interrupted. That safe conflict requires a renewed
review. A process lease that distinguishes a live approver from a crashed one
is a possible future refinement.

Publication starts an immediate transaction and resolves references within the
transaction. The publisher supplies the exact predecessor. The store compares it
with the current head and uses a conditional update for the active pointer. The
revision, dependencies, activation and audit event commit together. Conflicting
or failed writes roll back. Retry a busy write against the current head.
Identical retries return the same reference without an extra publication event.
New validation runs have separate contract identities. Result, report and request
records preserve historical snapshots.

## Artifacts and trust boundaries

Planning review freezes an explicit set of complete TDC, Module and Workflow
documents. One foreground-terminal action approves that exact set, with a
separate digest-bound receipt for every actual Kernel publication. Reused
published references are displayed alongside changed candidates. Approval of an
earlier technology choice does not authorize a later interface. Consolidation
uses the exact receipts already obtained without asking for another global
approval. Declined, stale, replayed, mutated or expired reviews authorize no
remaining publication.

Documents publish in dependency order. If a process is interrupted, recovery
holds a writer reservation, verifies each committed exact document and receipt,
preserves actual partial publication and revokes uncertain remaining consent.
A fresh review reuses those known committed references rather than duplicating
history. A concurrent read can revoke still-live pending consent in the brief
publication interval, requiring review again. The Kernel remains the only
contract writer and controls all exact predecessor and active-reference checks.

The optional `DELEGATE` terminal choice records a 24-hour mandate for the same
local account. It permits only Workflow checkpoint dependency changes while
preserving every other payload field and exact Project/Module/TDC reference.
The mandate must refer to a completed human-authorized Workflow publication and
its real consumed receipt. A delegated successor has `DELEGATED` provenance and
its own exact receipt. Changed interfaces, technologies, milestones, obligations
or expired mandates require the applicable human action. The full planning
review and the mandate ID remain visible in session history.

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

This directory migration verifies version 1, version 2 and version 3 databases without
upgrading them during the byte comparison. Opening the verified target with the
current Kernel then performs the independent forward schema upgrade above. Repeating
the naming migration before target changes is a no-op. Once the target is
upgraded or otherwise evolves, its differing bytes are treated as a conflict
and preserved. Continue using the verified current target.

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

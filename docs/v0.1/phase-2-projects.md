# v0.1 Phase 2 · projects and Work Items

Phase 2 starts from [the Phase 1 merge](https://github.com/tito-pereira/Corinthos/commit/377bbcb9f842a6472e393465119e3467dd9cb65f)
with tree `a2fe7d71d95881a26621164d437b74c9d74d3338` and
[green post-merge CI](https://github.com/tito-pereira/Corinthos/actions/runs/43415932967).
The [Phase 0 baseline](baseline.md) records the original SQLite layout.

## Project Registry and Project Summary

Terminal Home and desktop share the per-user `recent-projects.json`. Version 1
entries (`path`, `last_opened_at`) remain readable. Explicit project access
records version 2 (`root`, `last_accessed_at`) using the existing lock and atomic
update. The registry retains up to 20 normalized local roots in access order,
including missing roots. Display and compatibility are observed from the project.
The file holds paths and access times. `config.json` and `providers.json` keep
their separate version and ownership.

Project Summary reads the bootstrap and a verified, read-only SQLite snapshot.
It reports initialization and storage, project identity, active Project and
Workflow refs, up to 16 Module and 16 Technology Decision refs, the latest
available Validation run, lifecycle pointers and Work Item counts. Null or
empty fields and source availability distinguish missing, stale and truncated
observations. Historical Validation references do not supply a new gate.
Project Summary is derived on demand. Passive reads do not migrate SQLite,
create a database, record recency or launch a provider.

`corinthos project open ROOT` verifies the project, migrates a verified v6
database and then records recency. A bootstrap-only project keeps its database
absent until an operation, such as creating a Work Item, needs to write.
Follow the [legacy migration procedure](../storage.md#migrating-existing-project-state)
for an older private directory layout. If the recency write fails after
migration, retrying the open reuses the migrated database.

## SQLite v7

The shared store keeps application ID `0x4E554B59` and adds three tables.

| Table | Contents |
| --- | --- |
| `work_items` | Stable Work Item ID, project, optional parent, scope, objective, ordered criteria, status, planning policy, provenance and timestamps. |
| `work_item_dependencies` | Same-project prerequisite edges keyed by item and dependency. |
| `work_item_modules` | Affected-module identifiers and optional exact Module revision refs. |

The migration reserves a writer, verifies the source schema, integrity and
foreign keys, then saves a verified original-version backup
`state.pre-v7-<UUID>.db`. It adds the tables and advances the version marker
in one transaction. Failure rolls back the database and retains a completed
backup. Reopening a valid v7 database creates no additional migration backup.
The migration retains v6 tables and records, including exact JSON bytes,
digests, refs, active pointers and ordered operational histories. Keep the
database and backup private. The [v6 record](sqlite-v6.md) describes the
expected backup. The Phase 2 tests exercise genuine minimal and populated
v6 databases, failure injection, read-only or invalid inputs, and concurrent
openers.

## Work Items and authority

The four scopes are `TASK`, `CHANGE`, `PROJECT`, and `CRITICAL`. Choose the
scope explicitly. An item starts `OPEN` with an objective of up to 600 characters,
1–8 ordered criteria of up to 300 characters each and a planning policy
(default `STANDARD`). Affected modules carry an exact Module ref when resolved
from the active contract. For an unresolved module, the ID remains and the
ref is null. An unaffected module link retains its original exact revision.

| Status | Allowed next states |
| --- | --- |
| OPEN | ACTIVE, BLOCKED, CANCELLED |
| ACTIVE | BLOCKED, COMPLETED, CANCELLED |
| BLOCKED | ACTIVE, CANCELLED |
| COMPLETED, CANCELLED | None |

Terminal transitions record a completion timestamp. Work Items are retained, with no physical deletion.
Same-project parents and dependencies are checked for cycles in the writer
transaction. Trees are read in deterministic pre-order and dependency reads
order prerequisites first. Updating multiple relations together is atomic.
Use `expected_updated_at` on updates and transitions to reject stale edits.

Work Items are operational planning records. Their provenance records a local
operator. A mutation grants no contract publication, technology approval,
Workflow execution, independent Validation or product acceptance authority.
Agent Sessions, Context Projections, switching, adaptive workflows and external
import are deferred.

## CLI

Run from an installed Corinthos checkout or the existing per-user install.

```text
corinthos projects list
corinthos project summary ROOT
corinthos project open ROOT
corinthos work create --root ROOT --scope TASK --objective "Document the interface" --criterion "Run the interface tests"
corinthos work list --root ROOT --scope TASK
corinthos work show WORK_ID --root ROOT
corinthos work update WORK_ID --root ROOT --criterion "Check valid and invalid inputs"
corinthos work status WORK_ID ACTIVE --root ROOT
corinthos work tree --root ROOT
corinthos work dependencies WORK_ID --root ROOT
```

Follow `next_offset` until it is null. Framed pages can contain fewer items
than the requested limit. Use `--help` to see mutation fields, status
preconditions and relation-clear flags. No-argument `corinthos` still opens
terminal Home.

## RPC v1 and v2

Use the local stdio entry point described in [Phase 1](phase-1-desktop.md).
JSON-RPC 2.0 uses UTF-8 JSON Lines with a 65,536-byte frame limit. The
pre-negotiation `system.ready` event is identical for both versions. An
identified `system.handshake` selects `protocol_version` 1 or 2 for the
connection. V1 exposes its original five methods. Errors are bounded
and sanitized. A notification cannot negotiate or perform a Phase 2 mutation.

The [SHA-256 freeze record](rpc-v1.sha256) covers the nine original schemas
using Git LF bytes. Compatibility tests exercise all five v1 methods. The
RPC, SQLite, contract wire and package versions are independent.

| RPC v2 additions | Behavior |
| --- | --- |
| `projects.list` | Page of registry entries, including missing roots. |
| `project.summary`, `project.open` | Derived summary. Explicit open records recency and migrates verified v6. |
| `work.create`, `work.get`, `work.update`, `work.status` | Create, read or mutate one Work Item. Results include allowed next statuses. |
| `work.list`, `work.tree`, `work.dependencies` | Paged records, hierarchy and prerequisite IDs. |

The [v2 schemas](../../schemas/rpc/v2) document envelope, parameters and
results. Clients feature-detect the advertised methods they use. Adding an
optional method is compatible. Removing a supported method or making a
previously valid payload invalid requires a new protocol version.

## Desktop Home and Projects

The contributor Tauri/React application uses RPC v2 through the Rust
sidecar bridge. Home shows saved projects and availability. Open a project
by path or select a registry entry. The project view shows storage, active
identities, Work Item counts and hierarchy. The create form and status control
write through the same Python Application Layer as the CLI. The UI reloads
from the backend after a mutation. Rust owns the connection and process lifecycle.

The Windows CI job builds the normal executable and uses a test observer
for real WebView integration. The fixture uses Phase 1 code to construct
a v6 project. The observer verifies the registry, v7 summary, Work Item
creation and status, closure of the sidecar, and passive provider sentinels.
The per-user source installer and public desktop packaging are separate.

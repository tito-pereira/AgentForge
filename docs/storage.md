# Local state, migrations and recovery

`ContractStore(project_root)` uses a caller-authorized existing local directory.
It initializes `.corinthos/state.db` when needed. Artifacts and snapshots remain
private. Keep `.corinthos/`, backups, journals, and the legacy `.nukytera/`
and `.agentforge/` directories out of Git. The library uses normal OS
permissions and parameterized SQL.

## SQLite version 5

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
| `wf_executions` | Exact Workflow/workspace bindings, configuration digest and optimistic execution version. |
| `wf_checkpoints` | Per-execution checkpoint states, current attempt and inherited historical lineage. |
| `wf_attempts` | Owned/fenced provider or verification attempts, exact context, retained observations and predecessor attempt. |
| `wf_workspace_leases` | Current workspace execution/attempt owner, expiry and monotonic fencing generation. |
| `wf_execution_events` | Append-only execution, attempt, recovery and reconciliation observations. |
| `val_drafts` | Versioned drafts of scoped Validation plans and reviewed procedures. |
| `val_plan_bindings` | Immutable typed procedures and method reviews sealed by an exact published VC. |
| `val_runs` | Fenced run context, exact candidate identity, earlier-run lineage and frozen result. |
| `val_events` | Append-only run claims, check observations, inspection and publication events. |

Each connection enables foreign keys. The application marker `0x4E554B59` and
SQLite `user_version = 5` identify the current database schema. Initialization is an
atomic version 0-to-5 migration for an empty database. Incompatible, foreign and
corrupt stores fail without being rebuilt. The database schema version is
independent of the JSON wire version `1.0`.
Phase 1.1 preserved SQLite version 1 during the naming migration. Phase 2
introduced v2 PM sessions and receipts. The historical Phase 3 A–D delivery
introduced v3 planning and publication authority state. The E–F continuation
added the five v4 execution tables. Phase 4 adds the four v5 Validation tables.
The application ID, wire version `1.0`, published document bytes/hashes, exact
references and earlier table meanings are preserved.

The shared compare-and-swap and append-only turn mechanics serve PM and planning
in separate namespaces. Execution uses its own versioned snapshots, attempts,
workspace leases and append-only observations in the same private database.
PM listing continues to see only PM sessions. The
[runtime guide](workflow-execution.md) explains current execution and recovery.

## Upgrading an existing store

Opening a verified v1 through v4 store takes a bounded immediate write reservation and
checks SQLite integrity, foreign keys, application marker and schema objects.
Before changing the schema, a separate read connection makes a consistent
private original-version backup. Its original markers and integrity are verified
before it is published at an unused filename. The reservation
prevents concurrent writers while the backup observes the committed source.

Every missing schema addition and the v5 marker commit in one transaction.
A failed upgrade rolls back the schema/version changes and retains any
completed verified backup. Fresh empty stores initialize directly at v5
without a pre-upgrade backup. Read-only, corrupt, foreign, incompatible and
unsupported future-version stores fail with existing state preserved.

The [execution storage tests](../tests/test_execution_storage.py) use databases
created by the actual earlier v3 and v4 implementations. The v4 fixture
includes published contracts, approvals, mandates and Workflow execution
history. The tests compare old rows, verify original-version backups and
exercise rollback and reopening without an extra migration.
The [Phase 3 verification record](phase-3-verification.md) identifies actual
installed-wheel results and their environment.

| Starting state | Original-state backup | Missing schema additions |
| --- | --- | --- |
| v1 Contract Kernel | `state.pre-v2-<unique-id>.db` | v2 PM, v3 planning, v4 execution and v5 Validation. |
| v2 Project Manager | `state.pre-v3-<unique-id>.db` | v3 planning, v4 execution and v5 Validation. |
| v3 Workflow planning | `state.pre-v4-<unique-id>.db` | v4 execution and v5 Validation. |
| v4 Workflow execution | `state.pre-v5-<unique-id>.db` | v5 Validation. |
| v5 current store | Existing state remains current. | No forward migration. |

The backup filename records the next migration after the original version.
Directly opening an older store with the current release produces one verified
original-state backup. Contract documents, digests, reference edges, active
pointers, audit order, PM sessions/receipts and existing planning history remain
intact. The [planning migration tests](../tests/test_workflow_storage.py) retain
the genuine Phase 2 input fixture and verify forward preservation and rollback
across the v3 planning additions.
Retain backups for recovery with a compatible earlier release. Stop every writer
before restoring a backup, which returns the database to its recorded state.

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
review. An approval-publication lease that distinguishes a live approver from a
crashed one is a possible future refinement.

Publication starts an immediate transaction and resolves references within the
transaction. The publisher supplies the exact predecessor. The store compares it
with the current head and uses a conditional update for the active pointer. The
revision, dependencies, activation and audit event commit together. Conflicting
or failed writes roll back. Retry a busy write against the current head.
Identical retries return the same reference without an extra publication event.
New validation runs have separate contract identities. Result, report and request
records preserve historical snapshots.

## Execution state, leases and inspected recovery

Version 4 binds an execution to an exact Workflow, authorized workspace and
verification-configuration digest. Version-checked updates preserve checkpoint
state and each attempt's original source context. Claim transactions recheck
the active Project, Workflow, Module and Technology revisions before recording
ownership and effects. A changed source requires explicit reconciliation.

The trusted runner's completion guard runs under the immediate writer
reservation before completion writes. It repeats current source, cancellation,
plan and applicable-gate checks and commits the current gate observations with
the attempt result. A Validation result must be the latest published run for
that exact plan and artifact. A newer failed or interrupted matching run blocks
an older pass, while runs for other artifacts retain their separate scope.

One workspace lease records its execution, attempt, owner, expiry and increasing
fencing generation. Concurrent claimants cannot both own the workspace, and a
stale owner cannot complete a replacement attempt. Lease expiry alone grants
no permission to repeat uncertain process or Git effects. Actual output,
artifacts and late observations remain tied to the original attempt.

Recovery requires confirmed process termination, effects inspection and a
recorded reason. One transaction moves the unfinished checkpoint through
`RECOVERING` to retry readiness, verification-only or blocking and appends
`RECOVERY_STARTED` and `RECOVERY_INSPECTED`. Failure rolls back state, fencing
and events together. Retry creates a linked new attempt when explicitly
requested. Verification-only recovery checks retained files without another
agent dispatch.

Reconciliation creates a successor execution after source, binding and lease
checks. Eligible completed checkpoints retain their old execution/Workflow/
attempt lineage through `inherited_from`. Changed bindings, obligations or
prerequisites reset affected work. Original evidence retains its exact contract
and artifact identity. The [runtime guide](workflow-execution.md) provides
commands, actual state transitions and reconciliation limits. The
[verification record](phase-3-verification.md) identifies the installed-wheel
regression and distinguishes it from production approvals and pilot evidence.

## Validation state and recovery

Version 5 records guided drafts with version-checked updates. Publication commits
the exact Validation Contract, its bound procedures and the independent adequacy
reviews in one transaction. Digests in the published contract bind the two private
records to that revision. The Kernel remains the contract writer.

A Validation run claims an exact plan and artifact under its own worker lease.
Only its current owner can append check observations or complete the run. An
expired lease requires explicit inspection before recovery. Observations retain
their original run and check identity. The ordinary completion path freezes the
result and publishes it under one writer reservation. Inspected recovery freezes
an interrupted result from the retained observations. A separate publication
command can resume a frozen result and returns its existing reference on a retry.
Another attempt gets a new run identity and can link to its predecessor.

A database backup retains draft, plan and run rows. Preserve the original
evidence files separately to keep result references verifiable. The
[Validation guide](validation.md) covers candidates, evidence and gate recovery.

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
must be a writable supported SQLite database, version 1, 2, 3, 4 or 5, in
rollback-journal mode with no WAL, shared-memory or rollback journal sidecars.
Unsafe filesystem entries,
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

The explicit migration verifies the legacy application/schema markers and
database, copies its directory tree to staging under the same root, and compares
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

This directory migration accepts verified version 1, 2, 3, 4 and 5 databases and
preserves their original version during the byte comparison. Opening the verified
target with the current Kernel performs any required independent upgrade to v5.
Repeating the naming migration before target changes is a no-op. Once the target is
upgraded or otherwise evolves, its differing bytes are treated as a conflict
and preserved. Continue using the verified current target.

## Backup and recovery

Call `store.backup()` to make a consistent private `state.backup.db` using
SQLite's backup API. The method fails if a backup already exists. It copies the
database only. Retain and verify the referenced artifacts separately. Keep
backups protected like the live database. Before a future migration, verify a backup and
preserve the original state and related artifacts. The current loader rejects
unknown or nonempty unmarked databases with their contents preserved.

If a store fails integrity checks, stop writers and preserve the original files
and any SQLite sidecars. To check a backup, copy it as `.corinthos/state.db` under
a separate authorized recovery project. Open it and inspect its exact revisions,
active pointers and events before deciding how to recover. Keep artifact paths
and digests associated with the original records.

SQLite commits only database state. Git operations, artifact writes and external
tools have their own failure boundaries. An interrupted execution requires its
own evidence inspection and reconciliation before retrying external work.

## Report snapshots and recovery

Phase 5 uses the existing v5 database and private artifacts. It adds no SQL
tables or migration. Exact ERC revisions and publication events remain owned by
the Kernel. Frozen captures and content-bound generation manifests occupy
`artifacts/runtime/report-draft-*/frozen.json`, with an atomic publication receipt
after the Kernel commit. An incomplete capture remains inspectable. Repeating
publication reconciles the exact committed document before completing its receipt.

One read transaction captures source documents, safe operational projections and
event cutoffs. Source guards exclude Report's own rows/events, while preserving
all original source states. Bulk source checks and preliminary file hashing run
before the writer reservation. Publication uses a connection-local SQLite
`data_version` check to detect intervening commits, with bounded preflight retries,
then stat guards before/after Kernel publication and the Kernel's indexed-evidence
hash checks. Filesystem metadata and SQLite provide separate failure boundaries
under the trusted local-account model.

Current capture is bounded to 50,000 source rows/64 MiB, 8,192 candidate files/
256 MiB and 2,048 evidence refs/32 MiB. Explicit historical cutoffs preserve
reconstructible immutable history and declare unavailable mutable-state gaps.
The [Report guide](report.md) describes publication, revisions, current integrity
observations and safe export recovery. Keep all report artifacts and raw source
proof private. Export completion manifests bind output hashes separately from
the canonical ERC and its original evidence.

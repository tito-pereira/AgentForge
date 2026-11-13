# SQLite v6 compatibility

The baseline is `5a2a8e682b1389d96318feb636b8f52828f943d3`.
[ContractStore](../../src/corinthos/contracts/store.py) sets
`_APPLICATION_ID = 0x4E554B59` and `_SCHEMA_VERSION = 6` in
`PRAGMA application_id` and `PRAGMA user_version`. The database belongs to
the caller-authorized project at `<project>/.corinthos/state.db`. Global
settings and recent-project references have their own per-user files.

## Schema and migration chain

| Version | Existing tables added and their responsibilities |
| --- | --- |
| v1 · Kernel | `contracts` holds logical IDs and active pointers. `revisions` stores canonical JSON, digest and exact predecessor. `contract_references` stores exact edges. `audit_events` retains ordered publication and activation facts. |
| v2 · Project Manager | `pm_sessions`, `pm_turns`, `pm_approvals` store versioned drafts, accepted turns and digest-bound one-way approval receipts. |
| v3 · Workflow planning | `wf_sessions`, `wf_turns`, `wf_approvals`, `wf_mandates` store planning state, recorded choices, exact receipts and bounded delegation. |
| v4 · Workflow execution | `wf_executions`, `wf_checkpoints`, `wf_attempts`, `wf_workspace_leases`, `wf_execution_events` store execution bindings, checkpoint/attempt lineage, lease ownership and fencing, and append-only observations. |
| v5 · Validation | `val_drafts`, `val_plan_bindings`, `val_runs`, `val_events` store versioned plans, procedures/reviews bound to exact VCs, fenced candidate runs and observations/publication records. |
| v6 · Lifecycle | `lc_records`, `lc_projects`, `lc_events` store immutable origins and CAS-versioned state, project trackers and active/pending build pointers, and append-only observations with post-state snapshots. |

These are 23 application tables. Report reuses the Kernel for published ERCs
and uses private frozen captures, generation manifests and publication receipts
under `.corinthos/artifacts/runtime/`. It added no SQLite table. Artifact bytes,
snapshots and exports have separate filesystem lifecycles.

- A fresh empty database applies v1 through v6 in one write transaction. Opening
  a supported older database checks its markers, required tables, SQLite
  `quick_check` and `foreign_key_check`, then applies every missing version
  within a single `BEGIN IMMEDIATE` transaction. The v6 marker and final
  verification occur before commit. Already-valid v6 needs no migration.
- The writer reservation prevents concurrent mutation while a separate read
  connection makes an original-version SQLite backup. Backups are verified
  before exclusive publication as `state.pre-v<N>-<UUID>.db`, where `N`
  is the next version after the source. A failed migration rolls back schema and
  marker changes and retains any completed backup. A regular `store.backup()`
  creates a verified `state.backup.db` and refuses to replace an existing file.
- Normal store connections enable foreign keys, disable trusted schema and use
  bounded contention handling. Opens validate file boundaries and reject
  foreign, unsupported or corrupt stores instead of rebuilding them. Revisions
  and append-only histories have SQLite guards as well as service-level checks.
  `ContractStore.verify_existing` checks saved state through a read-only
  connection, with project opening separate from constructor migration.
- The explicit [legacy directory migration](../storage.md#migrating-existing-project-state)
  verifies and copies an offline `.nukytera/` tree into `.corinthos/`,
  preserving the source. It is a separate step from SQLite schema upgrade.
  Database backups cover the database. Preserve private evidence and snapshots
  separately, including any SQLite sidecars needed for recovery.

## Required proof for a later migration

1. First reopen a real baseline-generated v6 database using the baseline code
   and check that its content, markers and active pointers remain unchanged.
2. Start v7 from that verified v6 database. Capture a verified original-version
   backup before any schema change. Keep the migration and version marker in
   one transaction, and verify markers, schema, integrity and foreign keys
   before accepting the result.
3. Preserve existing contract JSON bytes and digests, exact refs, active
   pointers, approvals, provenance, audit order and operational histories.
   Reuse existing `wf_*`, `val_*` and `lc_*` state. Any new read model must
   derive its facts from existing owners.
4. Exercise failure and retry, including partial migration failure, incompatible
   or read-only input and reopen from a verified backup. Failed migration must
   keep a usable v6 source and must not expose a partially promoted successor.
5. Use both a small baseline-created fixture and a populated fixture covering
   the relevant PM, Workflow, Validation and Lifecycle histories. The
   [existing migration tests](../../tests/test_lifecycle_migration.py) already
   exercise a real v5 source, retention of all 20 old tables and artifacts,
   rollback, concurrent openers and backup/reopen of a populated v6 store.
   [Earlier storage tests](../../tests/test_state_migration.py) and
   [execution migration tests](../../tests/test_execution_storage.py) cover
   earlier versions and original-version backups. Phase 2 must supply the
   actual v6-to-v7 test when that migration exists.

## Reproduce a minimal baseline fixture

Use the exact baseline checkout and an installed contributor environment,
then run the following from that checkout's root. It uses the real Kernel,
the eight checked-in examples and one fixed Project successor. The synthetic
receipts exercise the trusted callback in scratch state only. They provide no
production consent. To retain the fixture for a later migration test, copy the
closed scratch database to a separate test workspace before the temporary
directory is cleaned up.

```python
import json
import sqlite3
from contextlib import closing
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory

from corinthos.contracts import ContractRef, ContractStore, PublishContext, approval_request
from corinthos.contracts.model import canonical_json
from examples.contract_kernel import EXAMPLES, ORDER

documents = [json.loads((EXAMPLES / f"{name}.json").read_text("utf-8")) for name in ORDER]
first = ContractRef.from_document(documents[0])
successor = deepcopy(documents[0])
successor["metadata"].update(
    revision_id="baseline-fixture-project-r2",
    version=2,
    supersedes=first.to_json(),
    approval={
        "kind": "HUMAN",
        "approval_id": "baseline-fixture-approval",
        "actor_id": "demo-owner",
    },
)
successor["payload"]["scope"]["included"].append("Record a synthetic migration fixture")
documents.append(successor)
receipts = {
    approval_request(document)
    for document in documents
    if document["metadata"]["approval"] is not None
}

with TemporaryDirectory(prefix="corinthos-v6-fixture-") as directory:
    store = ContractStore(directory)
    for document in documents:
        origin = document["metadata"]["provenance"]
        store.publish(
            document,
            context=PublishContext(origin["engine"], origin["actor_id"], receipts.__contains__),
        )
    database = store.database_path
    original = database.read_bytes()
    events = store.list_events()
    reopened = ContractStore(directory)
    assert reopened.get(first) == documents[0]
    assert reopened.resolve_active(first.contract_id) == successor
    assert reopened.list_events() == events
    assert database.read_bytes() == original
    assert not list(database.parent.glob("state.pre-v*.db"))

    with closing(sqlite3.connect(f"{database.as_uri()}?mode=ro", uri=True)) as db:
        assert db.execute("PRAGMA application_id").fetchone() == (0x4E554B59,)
        assert db.execute("PRAGMA user_version").fetchone() == (6,)
        assert db.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
        assert not db.execute("PRAGMA foreign_key_check").fetchall()
        queries = {
            "schema": "SELECT type, name, tbl_name, sql FROM sqlite_schema "
            "WHERE sql IS NOT NULL ORDER BY type, name",
            "contracts": "SELECT * FROM contracts ORDER BY contract_id",
            "revisions": "SELECT * FROM revisions ORDER BY revision_id",
            "references": "SELECT * FROM contract_references "
            "ORDER BY source_revision_id, target_revision_id",
            "events": "SELECT sequence, revision_id, activated FROM audit_events ORDER BY sequence",
        }
        logical = {key: [list(row) for row in db.execute(sql)] for key, sql in queries.items()}
    print("Logical SHA-256:", sha256(canonical_json(logical).encode("utf-8")).hexdigest())
    print("Generated SQLite SHA-256 (this run only):", sha256(original).hexdigest())
```

The verified logical digest is
`e71d3a83e913bfb328dacc274f7314a91ca9fbec0eae9f9b25ec928e99bcd1e1`.
It covers ordered DDL, contracts, exact revision bytes and digests, references,
and audit sequence/revision/activation. Audit occurrence timestamps and SQLite
file layout may vary across generations. Capture each generated file's own
SHA-256 for custody and compare every stored row, including timestamps, when
testing a migration of that same fixture. On Windows with CPython 3.12.10,
one generated file had SHA-256
`9f3a503544d82b26e8932ba894db4012a863409c996321175c58992e2399ff6a`.
That file reopened byte-for-byte with SQLite integrity and foreign-key checks
passing. The fixture intentionally leaves operational tables unpopulated. It
complements the populated v6 backup test above.

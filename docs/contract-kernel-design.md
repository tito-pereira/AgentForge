# Contract Kernel design and traceability

Phase 1.0 started from the verified Phase 0.3 merge `830943bb`. Product target
Core v0.1, PRD revision v0.2, package version `0.1.0`, and the historical
`phase-1-baseline` tag identify distinct things. The Phase 0.3 baseline passed 35 tests.

The approved scope is shared infrastructure for six Engines and eight contract
types (architecture §§2.1–2.33). The kernel validates documents, checks stored
relationships, enforces publication authority, and persists exact revisions.
The following serialization, Python API and SQLite layout are implementation
choices within that scope.

## Shape, identity and API

- Draft 2020-12 schemas use one closed `metadata`/`payload` envelope. The eight
  packaged schemas reference common definitions through an offline registry.
- `ContractRef` contains `contract_id`, `revision_id`, `contract_type`, and
  `project_id`. Lookups require all four fields. An integer `version` sequences
  content revisions. `schema_version` selects the wire format (`1.0`). Product
  version, build and run identifiers describe their own distinct lifecycles.
- `load_schema(contract_type, schema_version="1.0")` and
  `validate_schema(document)` check the wire format without opening a store.
  Drafts can be checked independently. Publication takes a `PUBLISHED` document.
- `ContractStore(project_root)` opens or initializes a project-local database.
  `publish(document, *, context)` returns an exact reference. `get(ref)`,
  `list_revisions(contract_id)`, `resolve_active(contract_id)` and `list_events()`
  read published state. `backup()` creates an explicit local backup.
- Validation, integrity, authority, storage and conflict failures use distinct
  kernel exceptions. Exact lookups return detached documents. An active pointer
  lives in SQLite and can advance while prior JSON stays immutable.

## Authority and evidence

The trusted integration supplies the publishing Engine and actor separately
from the document. Human or delegated approval is verified through an injected
trusted verifier. Its request binds the recorded approval identity and kind to
the SHA-256 of the exact document. Without a verifier, an approval claim fails
closed. A document declaring an actor to be human carries no authority on its
own. Trusted callers must authenticate the actor and retain the actual approval
record. The Phase 1 library has no human authentication UI.

Project and technology publication require verified human approval. Workflow
and Module decisions reuse approved references and check changes in binding
scope. Delegation applies to equivalent internal revisions. Validation plans
and results, reports, and revision requests retain their own Engine authority.
Only the Project Manager publishes approved global requirements. Validation
checks plan coverage and result provenance. The library does not run checks or
authenticate external build systems. Result evidence binds to run and target,
with its content digest verified inside the private artifact directory.

## Storage and recovery

Use SQLite through the standard library and an application/version marker.
Version 1 stores logical identities, canonical immutable revisions, exact edges,
active pointers, and ordered audit events. An immediate transaction resolves
references, compares the expected predecessor, publishes, advances the pointer
and appends its event. Identical retries return the existing revision. Historical
revisions remain available after activation changes. Hashes detect inconsistent
stored content; the local OS account remains the file trust boundary.

The current database lives at `.corinthos/state.db`. Artifact verification is
read-only and restricted to `.corinthos/artifacts/`. Keep state, backups and evidence out
of Git. SQLite, artifacts and Git have separate failure and recovery boundaries.
Phase 1.1 preserves the original wire schema URNs, Standard reference and SQLite
markers. The [storage guide](storage.md#migrating-existing-project-state) covers
moving existing state while preserving its exact published contents.

## Acceptance traceability

| Source | Contract or invariant | Implementation and verification |
| --- | --- | --- |
| PRD §4.1, architecture §§2.6–2.8 | Project intent, traceable obligations, approval | Project schema, authority and revision tests |
| PRD §4.2, §§2.16–2.19 | Workflow dependencies, decisions and exact approved project | Workflow schema and graph/integrity tests |
| PRD §4.3, §§2.20–2.23 | Module coverage, provider-owned versioned interfaces | Module schema and verification/compatibility tests |
| PRD §4.4, §§2.24–2.26 | Technology alternatives and human selection | Technology schema, ranking and authority tests |
| PRD §4.5, §§2.27–2.29 | Validation scope, coverage, independence, evidence plan | Validation schema and obligation/matrix tests |
| PRD §4.6, §2.30 | Result run, target, evidence and gate derivation | Result schema, mismatched target and incomplete-run tests |
| PRD §4.7, §2.31 | Report traceability and distinct acceptance states | Report schema and fabricated-source tests |
| PRD §4.8, §2.32 | Revision request base, scope and negotiation boundary | Request schema and stale-base/authority tests |
| RF06/RF10, §§2.12–2.13, 2.18 | SQLite transactions, immutable history, concurrency and privacy | Store and artifact tests, reopen and rollback demo |
| PRD §5 and §2.33 | M1–M5, installability and regression | Standard tests, kernel tests and Windows/Ubuntu CI |

The [shape tests](../tests/test_contract_schemas.py) run eight JSON examples and
their invalid variants through the installed schemas. The
[semantic tests](../tests/test_contract_semantics.py) exercise the same public
publication API for each type. The [store tests](../tests/test_contract_store.py)
verify recovery and atomicity against real SQLite files. The
[boundary tests](../tests/test_contract_boundaries.py) cover exact approval,
artifact integrity, unsafe paths and the executable example.

## Engineering Completion Gate

| Commandment | Prepublication evidence |
| --- | --- |
| M1 | This design maps scope, authority, APIs, invariants and tests to all eight approved contract types. |
| M2 | The decision record explains the existing Python, JSON Schema and SQLite choices and the publication trust boundary. No new dependency was required. |
| M3 | The locally installed wheel passed 146 tests under Windows Python 3.12.14, including the original 35, rollback, concurrent writers, forged approval and evidence retention. The cross-platform workflow checks the published commit separately. |
| M4 | The README demo publishes eight types and reopens nine revisions. The contract API and SQLite recovery procedure are documented beside the tests that exercise them. |
| M5 | Shared definitions cover the common envelope. One exact reference model and one publication transaction serve all contract types. Ruff lint and formatting checks passed. |

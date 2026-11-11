# Contracts and references

Baseline dated November 8, 2026, aligned with product requirements revision v0.2
and the approved catalogue of eight contract types. The Contract Kernel installs
their executable Draft 2020-12 schemas with the Python package. The existing
Standard schema validates the M1–M5 policy configuration separately.

## Approved conceptual catalogue

The reference column preserves section identifiers from the original internal
architecture baseline. The responsibilities are summarized here so this catalogue
can be understood without access to that planning material.

| Contract | Authority and purpose | Original baseline sections |
| --- | --- | --- |
| Project Contract | Project Manager publishes user-approved requirements, constraints, and acceptance criteria. Workflow and Validation consume the same revision. | 2.1, 2.2, 2.4.1, 2.6–2.8, 2.14, and 2.33 |
| Workflow Contract | Workflow publishes modules, decisions, checkpoints, milestones, and execution policy. | 2.15–2.19, consolidated in 2.19 |
| Module Contract | Workflow defines responsibilities, obligations, and versioned horizontal interfaces. | 2.20–2.23, consolidated in 2.23 |
| Technology Decision Contract | Workflow records the human decision, viable alternatives, rationale, scope, and verification criteria for a technology choice. | 2.24–2.26, consolidated in 2.26 |
| Validation Contract | Validation publishes the independent audit plan and its matrix of obligations. | 2.27–2.29, consolidated in 2.29 |
| Validation Result Contract | Validation publishes the immutable result of a specific plan execution against an identified target. | 2.30 |
| Evidence & Report Contract | Report consolidates sources, results, evidence, decisions, and limitations into traceable snapshots. | 2.31 |
| Project Revision Request | Workflow requests a bounded negotiation by Project Manager about a structural incompatibility, tied to the approved base revision. | 2.7 and 2.32 |

## Structure, identity, and versions

The common conceptual structure is `metadata` + `payload`. Metadata preserves
logical identity, immutable revision, contract type, project, content/schema
version, status, creation information, provenance, and applicable authority. It
includes references to the Standard and `supersedes` where specified. The payload
contains the obligations or data particular to each contract type.

Contract references identify the exact revision through `contract_id` and
`revision_id`, as defined by the approved specification. Schema version and
content revision serve different purposes. Published plans remain immutable,
while progress, attempts, logs, and recovery belong to operational state.

A new attempt under unchanged obligations produces a new execution/result.
Changes to the plan produce revisions of affected contracts under the applicable
authorization rules. Provenance distinguishes explicit human approval from action
within previously authorized delegation.

## Executable wire format

The [packaged schemas](../src/corinthos/contracts/schemas) specify every nested
property, required field and allowed value. The offline registry resolves
their shared [`common.schema.json`](../src/corinthos/contracts/schemas/common.schema.json) definitions.
The [examples](../examples/contracts) provide one complete valid document per type.

The `urn:nukytera:contracts:1.0:*` schema URNs and the `nukytera-standard`
identifier are durable wire identities. Corinthos resolves the same URNs in
its offline registry and accepts the same Standard reference. The wire version
`1.0`, contract type codes, required fields and published references are stable.

| Field | Meaning |
| --- | --- |
| `contract_id`, `revision_id`, `contract_type`, `project_id` | Stable identity, exact revision, one of eight types, and owning project. All four are required in references. |
| `version` | Positive, sequential content revision starting at 1. |
| `schema_version` | Wire format `1.0`, independent of content version, package version, product version and run IDs. |
| `status` | `DRAFT` for shape checks or `PUBLISHED` for publication. SQLite records active pointers separately. |
| `created_at`, `supersedes` | Timestamp with time zone and exact prior revision. The first revision has a null predecessor. |
| `standard_ref` | `nukytera-standard` version `0.1`. References to its individual rules use M1–M5. |
| `provenance`, `approval` | Publishing Engine, actor and source. Applicable human or delegated approval records its kind, identity and actor. Null means no approval claim. |

| Schema / example | Publication checks |
| --- | --- |
| [`project`](../examples/contracts/project.json) | Approved intent, stable requirement, constraint and criterion IDs, classified proposals and traceable decisions. |
| [`workflow`](../examples/contracts/workflow.json) | Exact Project and Module revisions, scoped approved technology choices, dependency graphs, checkpoint/milestone obligations and fixed Standard-safe policies. |
| [`module`](../examples/contracts/module.json) | Exact Project obligations, provider-owned interface revisions, scoped decisions and blocking verification coverage including M1–M5. |
| [`technology-decision`](../examples/contracts/technology-decision.json) | One to five ranked viable recommendations at publication, recorded human choice, rationale and verification criteria. A blocked draft can hold zero recommendations and no selection. |
| [`validation`](../examples/contracts/validation.json) | Exact scope and sources, applicable mandatory obligations, coverage matrix, method/evidence expectations and independence policy. |
| [`validation-result`](../examples/contracts/validation-result.json) | One exact plan and target per run, per-check results and evidence, coverage and consistent gate derivation. |
| [`evidence-report`](../examples/contracts/evidence-report.json) | Conclusions trace to exact sources and indexed evidence. Technical validation, delivery, availability and human acceptance have separate fields. |
| [`project-revision-request`](../examples/contracts/project-revision-request.json) | Exact approved Project base, affected IDs, structural diagnostic, sources, alternatives and impact. Publication records a request for negotiation. |

The Validation Result wire statuses `CONFORMANT`, `NONCONFORMANT` and
`NOT_VERIFIED` correspond to the approved outcomes. An individual check may have
a null status with a justified non-applicability reason. Mandatory obligations
cannot be waived this way. `SATISFIED` requires complete mandatory coverage,
matching evidence and a completed run. Evidence references bind the check, exact
plan, run and artifact identity, with a SHA-256 digest of the local file.

## Python API

Import from `corinthos.contracts`. Phase 1.1 is an import-breaking rename.
Use this prefix in callers with the `corinthos-core` distribution installed
in a fresh environment. The public kernel API retains its behavior.

| API | Result and side effects |
| --- | --- |
| `load_schema(contract_type, schema_version="1.0") -> dict` | Return a detached copy of the installed schema. |
| `validate_schema(document) -> None` | Validate JSON shape, including timestamps, without publishing or resolving references. |
| `ContractRef.from_json(mapping)` / `ContractRef.from_document(document)` / `ref.to_json()` | Construct or serialize an exact typed reference. |
| `approval_request(document) -> ApprovalRequest` | Construct the approval subject with exact reference, approval kind/ID/actor and canonical document digest. |
| `PublishContext(engine, actor_id, verify_approval=None)` | Trusted caller identity and optional callback that verifies the exact recorded approval. |
| `ContractStore(project_root)` | Open or initialize the SQLite store under an existing authorized root. |
| `store.publish(document, *, context) -> ContractRef` | Check schema, authority, lineage, references and invariants, then publish atomically. |
| `store.get(ref) -> dict or None` | Read an exact published revision. |
| `store.list_revisions(contract_id) -> list[dict]` | Return detached documents in content-version order. |
| `store.resolve_active(contract_id) -> dict or None` | Read the active pointer for a logical contract. |
| `store.list_events() -> list[dict]` | Read ordered publication events with exact revision identity. |
| `store.verify_artifact(relative_path, sha256) -> None` | Read and verify an existing private artifact. |
| `store.backup() -> Path` | Create a consistent private SQLite backup using the storage guide. |

Use `corinthos.contracts.migration.migrate_legacy_state(project_root) -> bool`
for an explicit offline copy of a legacy store. The
[storage guide](storage.md#migrating-existing-project-state) describes the
preconditions, integrity checks and collision behavior.

`SchemaError` reports invalid shapes and unsupported wire versions.
`IntegrityError` reports bad relationships, evidence or stored content.
`AuthorityError` and `ConflictError` specialize integrity failures for missing
verified permission and conflicting identity/lineage or database contention.
`StoreError` reports unavailable, corrupt or incompatible storage. These errors
derive from `ContractError`.

The calling Engine authenticates the publishing actor and supplies its trusted
approval verifier. For human or delegated approval, the verifier checks an
external decision record tied to the exact request. A declaration in JSON cannot
serve as proof. The [demonstration](../examples/contract_kernel.py) uses synthetic
receipts and an interrupted run in a temporary workspace. The kernel checks
the consistency of evidence and decisions. Independent execution and verification
of real work belong to the [Validation Engine](validation.md).

The user retains authority over product changes and binding technology and
interface decisions. The historical delegation used to finalize contract types
6–8 applied to their conceptual specification. It granted no standing authority
to approve later project changes.

## Project Manager publication flow

The [Project Manager](project-manager.md) collects vision, included/excluded
scope, assumptions, risks, requirements and acceptance criteria, constraints,
success criteria, classified structural proposals and negotiated decisions through
guided questions. Stable IDs and operational decisions survive interruption.
The canonical Project wire shape remains the eight-type Kernel's existing
`metadata`/`payload` schema. Session versions and rejected alternatives belong to
operational state.

The service freezes a complete `PUBLISHED` candidate with its final approval
metadata, exact predecessor and canonical digest. The foreground terminal shows
all fields and differences and asks for a fresh random approval challenge. Its
local receipt binds the exact document, actor, session and expiry. The trusted
callback supplies that proof to `ContractStore.publish`; the Kernel validates
shape, authority, references and lineage as usual. Edits and conflicts require
new review. An approved specification becomes an immutable Project revision.

An unchanged negotiation, refusal, deferral or returned request creates no new
Project revision. PRR intake starts from an exact active approved base and limits
changes to the affected obligations. User-initiated changes may open a revision
session directly. Workflow execution and independent validation follow in their
separately authorized phases.

## Workflow planning publication flow

The [planning service](workflow-planning.md) uses the existing Technology Decision,
Module and Workflow schemas. Technology decisions link an evaluated human choice
to planned module IDs and exact Project obligations. Module definitions preserve
responsibility boundaries, source obligations, relevant exact TDCs, provider-owned
interfaces and exact consumer references. Verification specifications retain
blocking coverage for assigned requirements, constraints, interfaces and M1–M5.
Workflow consolidation includes resolvable module/technology associations,
checkpoint DAGs and optional cumulative milestone plans under the fixed policy.

The service freezes all affected final candidates before authorization. The
foreground terminal shows their entire content, canonical hashes and previous
differences once. Exact per-document receipts bind the actual final set and
support publication in dependency order. New binding technologies, interface
terms and milestone architecture receive applicable HUMAN authorization. An
existing bounded mandate can authorize a dependency-only Workflow revision with
DELEGATED provenance. Changed binding content requires renewed human review.

Published unchanged sources are reused by exact reference. The Kernel remains
the only publication authority, and historical documents retain their identities
and bytes. A partial multi-document publication preserves already committed
facts and requires renewed review for unfinished work. The
[execution service](workflow-execution.md) consumes those exact references and
records actual attempts and checks separately. Conservative reconciliation
preserves old evidence through explicit lineage. Evidenced structural conflicts
can publish bounded PRRs for Project Manager negotiation. General product
evolution retains its later-phase boundary. Validation and
[Report](report.md) provide their separately implemented services.

## Report publication flow

Report reads a coherent source snapshot and freezes a canonical ERC plus a
private content-bound generation manifest. Technical reports publish through
REPORT authority with null approval and NOT_REVIEWED acceptance. Current source
and file guards protect publication, while the Kernel retains exact references,
revision lineage, evidence identity and authority checks. ERCs have immutable
revision history and no active pointer. Exact HUMAN review authority remains
required for an accepted delivered report. The service adds no acceptance
negotiation or progression gate.

## Related documentation

- [Architecture and Engine responsibilities](architecture.md)
- [Project Manager negotiation and approval](project-manager.md)
- [Workflow planning and exact set authorization](workflow-planning.md)
- [Execution, recovery and bounded revision requests](workflow-execution.md)
- [Workflow boundaries and review rules](workflows.md)
- [SQLite storage and recovery](storage.md)
- [Design and acceptance traceability](contract-kernel-design.md)
- [Implementation phases](implementation-plan.md)
- [Decision provenance](decisions.md)

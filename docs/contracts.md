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

The [packaged schemas](../src/nukytera/contracts/schemas) specify every nested
property, required field and allowed value. They share an offline
[`common.schema.json`](../src/nukytera/contracts/schemas/common.schema.json) registry.
The [examples](../examples/contracts) provide one complete valid document per type.

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

Import from `nukytera.contracts`.

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
of real work belong to the future Validation Engine.

The user retains authority over product changes and binding technology and
interface decisions. The historical delegation used to finalize contract types
6–8 applied to their conceptual specification. It granted no standing authority
to approve later project changes.

## Related documentation

- [Architecture and Engine responsibilities](architecture.md)
- [Workflow boundaries and review rules](workflows.md)
- [SQLite storage and recovery](storage.md)
- [Design and acceptance traceability](contract-kernel-design.md)
- [Implementation phases](implementation-plan.md)
- [Decision provenance](decisions.md)

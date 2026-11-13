# Contract compatibility baseline

This record freezes the eight published contract families at main commit
`5a2a8e682b1389d96318feb636b8f52828f943d3`. The
[baseline manifest](baseline.json) records the exact schema digests. The
[operational contract guide](../contracts.md) remains the reference for current
Python APIs and working examples.

## Shared wire and publication rules

- The packaged [common schema](../../src/corinthos/contracts/schemas/common.schema.json)
  defines the `metadata` and `payload` envelope. Draft 2020-12 schemas resolve
  offline under `urn:nukytera:contracts:1.0:*`. The Standard reference stays
  `nukytera-standard` version `0.1`; its mandatory rules are M1–M5. Wire
  version `1.0` is independent of the package, SQLite and future protocol versions.
- A `ContractRef` has exactly `contract_id`, `revision_id`, `contract_type`
  and `project_id`. Publication resolves references to exact published revisions
  of the same project, validates expected types and checks current heads where
  the particular relationship requires freshness. An active pointer can change
  without changing or redirecting a historical reference.
- A new logical contract starts at content version 1 with null `supersedes`.
  A successor keeps the project and type, increases the content version by one,
  identifies the exact latest predecessor and changes the payload. Revision IDs
  are unique in the store. A retry with identical canonical content still
  requires verified authority and creates no new revision or event. Reusing the
  revision ID for different content conflicts. A project has at most one
  logical Project contract and one logical Workflow contract.
- The Kernel accepts only `PUBLISHED` envelopes for publication. It validates
  schema, exact lineage, trusted Engine and actor, applicable approval,
  semantic dependencies and artifact evidence before inserting the canonical
  JSON, its SHA-256, exact reference edges, applicable active pointer and ordered
  audit event in one transaction. Runtime drafts, execution state and derived
  views have separate identities and persistence.
- A claimed HUMAN or DELEGATED approval requires a trusted verifier for the
  exact reference, approval kind, ID, actor and canonical document digest.
  Project Manager and Workflow obtain applicable HUMAN decisions through
  complete frozen review and a foreground terminal challenge. Existing
  dependency-only Workflow delegation requires a recorded, scoped mandate and
  its own verified receipt. Evidence, agent output and advisory observations
  supply no approval authority.

## Eight canonical families

All files below use wire version `1.0`. The general predecessor and retry rules
above apply to each family except where a stricter rule is listed.

| Family and packaged schema | Stable identity and semantic dependencies | Publisher, authority and head |
| --- | --- | --- |
| `PROJECT` · [project](../../src/corinthos/contracts/schemas/project.schema.json) | Requirements, constraints and criteria have unambiguous obligation IDs. Proposals link to in-scope requirements and constraints, and decisions reference actual proposals. Project Manager retains accepted IDs in drafts and bounds PRR-driven changes to their authorized scope. | PROJECT_MANAGER and exact HUMAN approval for every publication. Active pointer advances on a valid successor. |
| `WORKFLOW` · [workflow](../../src/corinthos/contracts/schemas/workflow.schema.json) | Exact active Project base, module IDs and exact Module/TDC associations, module and checkpoint dependency graphs, stable checkpoint and milestone IDs, and coverage of approved requirements. Consumer interface dependencies resolve to preserved provider definitions. | WORKFLOW. A successor requires verified HUMAN or bounded DELEGATED authority. Changes to playtest milestones require HUMAN. The Workflow planner obtains applicable review for the complete final set. Active pointer. |
| `MODULE` · [module](../../src/corinthos/contracts/schemas/module.schema.json) | `module_id` stays unique and stable within the project. The provider owns each interface ID and revision. Published definitions cannot be changed in place. Consumer references name the exact provider Module and required interface revision. Scoped TDC references and blocking checks cover requirements, constraints, interfaces and M1–M5. | WORKFLOW. Provided or consumed interface changes require HUMAN. Successor publication requires verified HUMAN or applicable delegated authority. Active pointer. |
| `TECHNOLOGY_DECISION` · [technology-decision](../../src/corinthos/contracts/schemas/technology-decision.schema.json) | Scoped module and obligation IDs, exact Project references, one to five viable ranked options, explicit selected choice and stable verification criterion IDs. Direct publication checks the active Project source. Reuse in Workflow requires the original obligation to remain equivalent in its current Project base. | WORKFLOW and exact HUMAN approval. Active pointer. |
| `VALIDATION` · [validation](../../src/corinthos/contracts/schemas/validation.schema.json) | Exact scope/target and source refs, stable check IDs, scope-specific gate and a matrix that covers all mandatory obligations. Bound procedures and independent adequacy reviews are sealed against the exact plan revision by the managed service. | VALIDATION. Independent plan authority and scope checks. Active pointer. |
| `VALIDATION_RESULT` · [validation-result](../../src/corinthos/contracts/schemas/validation-result.schema.json) | Each run has a distinct logical contract and run ID, an exact plan and artifact identity, every plan check exactly once, and evidence bound to its check/plan/run/artifact/digest. The evaluator matches the trusted publisher and differs from implementation publishers for Workflow, Module and TDC sources. Gate outcome follows admissible evidence and coverage. | VALIDATION. One published revision per logical result. A re-run creates a separate result. No active pointer. |
| `EVIDENCE_REPORT` · [evidence-report](../../src/corinthos/contracts/schemas/evidence-report.schema.json) | Exact source refs and source cutoff, stable report/evidence identity and candidate lineage. Evidence and metrics trace to declared sources. Technical Validation, delivery, availability and product acceptance stay separate. | REPORT. Ordinary technical reports carry null approval and `NOT_REVIEWED`. Reviewed acceptance requires a delivered version and exact HUMAN approval with matching review ID. Immutable report revision history. No active pointer. |
| `PROJECT_REVISION_REQUEST` · [project-revision-request](../../src/corinthos/contracts/schemas/project-revision-request.schema.json) | Stable `request_id` and exact active Project base at publication. A successor keeps that request ID and base. Affected proposal, requirement, constraint and criterion IDs must exist in the base. Evidence links resolve exactly, and alternatives or a reason for their absence are required. | WORKFLOW. A PRR cannot carry product-change approval or publish a Project revision. Project Manager owns bounded intake and any later HUMAN-approved publication. No active pointer. |

The [authority checks](../../src/corinthos/contracts/authority.py),
[semantic checks](../../src/corinthos/contracts/semantics.py) and
[ContractStore](../../src/corinthos/contracts/store.py) specify the executable
rules. The scoped Validation consumer continues to check the applicable exact
plan, candidate, latest run and evidence. A prior passing result alone does
not satisfy a later gate.

## Compatibility proof

| Check | Baseline coverage |
| --- | --- |
| Packaged schema shape, all eight examples, required fields, exact references and evidence paths | [Schema tests](../../tests/test_contract_schemas.py) |
| Human approval digest binding, atomic publication, unchanged retries, historical refs, active pointers and contention | [Boundary tests](../../tests/test_contract_boundaries.py), [Store tests](../../tests/test_contract_store.py), [Project approval](../../tests/test_project_approval.py) |
| Exact module interfaces, technology links, checkpoint dependencies, PRR stale-base rejection and independent result gates | [Semantic tests](../../tests/test_contract_semantics.py), [Workflow authorization](../../tests/test_workflow_authorization.py), [Workflow reconciliation](../../tests/test_workflow_reconciliation.py), [Validation runtime](../../tests/test_validation_runtime.py) |
| Report source cutoffs, accepted review and current gate provenance | [Report service](../../tests/test_report_service.py), [Report sources](../../tests/test_report_sources.py), [Product review](../../tests/test_product_review.py) |

Future v0.1 changes to wire format or publication authority require an explicit
compatibility decision, versioning and migration or interoperability evidence.
A new read model, application facade or transport should wrap these existing
identities and services. Its records grant no authority to edit published
history or bypass the Kernel. See [SQLite v6](sqlite-v6.md) for persisted
lineage and migration requirements.

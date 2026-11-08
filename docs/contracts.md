# Contracts and references

Baseline dated November 8, 2026, aligned with product requirements revision v0.2
and the approved conceptual catalogue of eight contract types. Phase 1 will
implement their executable schemas. Phase 0 provides a minimal Standard schema
for the M1–M5 policy configuration.

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

## Contract Kernel prerequisites

Phase 1 must define concrete types and schemas, references and invariants,
immutability, authorizations, and persistence, with positive and negative tests.
Those tests must cover invalid contracts, inconsistent revisions, and orphaned
references. Final conceptual consolidations provide the approved baseline for
these implementation decisions.

The user retains authority over product changes and binding technology and
interface decisions. The historical delegation used to finalize contract types
6–8 applied to their conceptual specification. It granted no standing authority
to approve later project changes.

## Related documentation

- [Architecture and Engine responsibilities](architecture.md)
- [Workflow boundaries and review rules](workflows.md)
- [Implementation phases](implementation-plan.md)
- [Decision provenance](decisions.md)

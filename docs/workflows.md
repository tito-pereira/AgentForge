# Workflows, gates, and review

Baseline dated November 8, 2026, aligned with product requirements revision v0.2.
The following flows describe approved behavior for future phases. The Phase 0
scaffold provides CLI help/version, the Standard policy, minimal structural
validation, tests, and static analysis. Explicit technical review provides the
initial control over implementation evidence.

## Execution and authority

User ↔ Project Manager negotiate intent and acceptance criteria. Human approval
permits publication of the Project Contract. Workflow plans modules, interfaces,
and checkpoints, and proposes technologies. Binding decisions about technologies,
interfaces, and milestone design require traceable human authorization.

The conceptual checkpoint lifecycle is `PENDING` → `READY` → `RUNNING` →
`VERIFYING` → `COMPLETED`, with `BLOCKED`, `INTERRUPTED`, and `RECOVERING` for
exceptions and resumption. Dependencies form a directed acyclic graph. Parallel
execution requires resources, isolation, and freedom from conflicts. Future
implementation will specify the complete transitions and their conditions.

Workflow completes checkpoints when their criteria, deliverables, tests,
documentation, and applicable gates are satisfied. A completed checkpoint,
validated module, validated build, and globally validated product each retain
their own scope and evidence requirements.

## Validation and repair

Validation directly reads the approved Project Contract revision and local
obligations. It publishes the audit plan in a Validation Contract, checks the
identified target, and issues one Validation Result Contract per execution.
Findings use the conceptual outcomes `Conformant`, `Nonconformant`, or
`Not verified`. Non-applicability is a justified disposition for a specific check.

The planned gates are Checkpoint Gate, Playtest Readiness Gate, and Product
Validation Gate. A failed check, missing evidence, or `Not verified` outcome for
a mandatory check blocks its scoped gate. Report preserves references to the
conclusions and evidence issued by the responsible components.

Findings return to Workflow, which coordinates corrections and resubmission.
An additional attempt with unchanged criteria preserves the applicable contracts
and produces a new run/result. Independent audit takes place at the points and
scopes defined by the verification plan.

## Revisions and recovery

- Corrections and resumption within current obligations create operational events.
- Equivalent internal replanning may produce a revision under explicit delegation.
- Binding technology, interface, or milestone changes require the applicable human
  approval and revisions of affected contracts.
- Global changes follow negotiation in Project Manager. Workflow may issue a
  substantiated Project Revision Request. An approved change creates a new Project
  Contract revision, followed by selective Change Impact Analysis and Revision
  Reconciliation.

Concurrent revisions must reconcile their base revision before activation.
Recovery requires inspecting the working tree, artifacts, tests, and external
effects that may already have occurred. Interrupted work retains its incomplete
result and available evidence. The [Contract Kernel](contracts.md) persists
immutable revisions, active pointers, exact edges and ordered publication events.
Workflow execution and recovery decisions belong to the future Engines.

## Playtests, delivery, and evolution

Approved cumulative milestones become build candidates once prerequisites are
satisfied. Workflow runs the automatic Build Readiness Gate. Validation audits
the experimental scope and regressions before an isolated build becomes
available. The user chooses when to test. Feedback is optional and retains its
reference to the originating build, milestone, and session.

Technical conformance, delivery, human acceptance, reservations, and availability
to third parties have separate states. Product Acceptance Review is optional.
Product Evolution starts from the delivered version, approved contracts and
decisions, and available feedback. Content changes pass through negotiation and
approval, followed by selective revision and revalidation.

## Related documentation

- [Architecture and current implementation status](architecture.md)
- [Eight contract types](contracts.md)
- [Construction phases and Engineering Completion Gate](implementation-plan.md)
- [Historical verification and limitations](decisions.md)

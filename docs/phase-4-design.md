# Phase 4 Validation Engine design

Phase 4 starts at integrated main `22592bf8a2d8ad1605abf332a65c34138d35069c`.
Its [post-merge CI](https://github.com/tito-pereira/Corinthos/actions/runs/42855963126)
passed 408 tests on Windows CPython 3.12.10 and 406 on Ubuntu CPython 3.12.16,
with two Windows-only process tests skipped. The Phase 3 preliminary engineering
controls and independent technical review remain recorded separately.

## Responsibilities and traceability

| Requirement | Implementation boundary | Verification |
| --- | --- | --- |
| RF05 and architecture 2.27–2.30 | Validation reads the approved Project, Standard and exact scoped contracts directly. It derives the matrix, checks method adequacy and publishes a reusable VC. | Complete scope coverage, missing global obligations, inadequate methods, active source reconciliation, autonomous legitimate authority. |
| RF05 and RF10 | Separate evaluator observes the exact candidate with frozen typed bindings. It retains private check evidence and durable run history. | Exact snapshots, inspected methods, meaningful observed assertions, unsupported tools, interruption, races, tampering and replay. |
| RF05 and architecture 2.30 | Validation derives each VRC and its scoped gate from recorded observations. The Kernel verifies schema, references, evidence and publication authority. | Same-plan new run, interrupted and incomplete evidence, stable findings, deterministic coverage and blockers. |
| RF04/RF06 and architecture 2.15–2.23 | Workflow supplies a retained candidate request and consumes independently published results. Its existing scheduler and repair/reconciliation authority remain. | Required missing plans block, applicable scoped results control progression, newer blockers supersede older passes, old evidence retains identity. |
| RF05 pilot | Audit an isolated copy of the approved local task manager and its exact contracts with a separate evaluator and independent checks. | Compare global audit with a green local suite, verify correction and new results, preserve installed app and daily data. |

Module and Integration use the Checkpoint gate, as does Checkpoint scope.
Playtest Milestone uses Playtest Readiness, and Product uses Product Validation.
The corresponding targets are exact Module, Workflow, Workflow, Workflow and
Project contracts. Product derives global obligations even when local scopes
omit them. The existing schemas and Kernel remain the publication boundary.

## Plan and procedure identity

A draft stores the exact source obligations and explicit check definitions.
Method adequacy is a separate per-check judgment. The evaluator records why
the procedure can observe the cited criterion, referencing actual assertions or
inspection paths. The procedure digest binds that judgment to the concrete
inputs, expected observations and command arguments. Generic acceptance and
return-code-only checks provide insufficient evidence. Standard content is read
through the existing loader and its digest binds the exact plan. Operational
bindings are versioned by the immutable plan reference. The published VC
describes the procedures and records their binding digest in existing fields.

The guided `corinthos validation` family derives, lists, inspects, binds and
publishes plans, runs audits and shows or recovers results. Public entry points
separate the planner, run repository and runner. Reviewers assess exact criteria
and inspected candidate bytes. They do not exercise the owner's approval or
acceptance authority.

## Candidate and evidence

Use a bounded inventory and compare the complete supported source manifest
before and after evaluation. The candidate may be separate from the Kernel
project root. Verification commands use exact argv, pinned executable and
evaluator-input digests, and isolated scratch data. They run with bounded output,
time and owned-process cleanup. They are trusted local evaluator procedures.
Process ownership provides cleanup. Native OS or caller isolation determines
what files the process can access. Generated assets that matter to an audit
must be included in the candidate inventory.

A completed command needs a criterion-specific observation from the reviewed
procedure. Execution, evidence and final eligibility are distinct. Missing
tools, ambiguous outcomes or changed bytes leave the affected checks unverified.
Per-run envelopes bind actual observations to the plan, source, check, method,
evaluator and full artifact identity. Preserve admissible evidence in the
private Kernel artifact store, with hashes verified at publication and consumption.

## Durable state and recovery

Extend the shared SQLite schema additively, preserving earlier rows and the
verified pre-upgrade backup. Store drafts and exact plan bindings separately
from immutable contracts. Claim and fence each run before external effects.
Commit observations and append-only events as work proceeds. Freeze the derived
VRC and publish through the Kernel with idempotent recovery. SQLite, processes
and artifact writes have separate failure boundaries. Inspected recovery records
a truthful interrupted result when appropriate. A retry starts a fresh run.

Workflow retains a candidate identity before independent audit and keeps an
explicit expectation when a formal gate is required. Audit can use the retained
candidate during verification or after blocking without taking over the
implementation lease. Recheck sources, exact evidence and current eligibility
before affected progression. A repair under unchanged obligations can reuse
the VC with a new run. A material formal plan change creates a new VC revision.

Formal human product acceptance, Report/ERC production and full playtest
promotion remain outside Phase 4. Live Claude evidence is still unavailable.

# v0.1 Phase 6 adaptive workflow

Adaptive Workflow uses the Work Item scope to choose a route through Context,
Agent Sessions and the standard Workflow. SQLite stays at v9. The flow view
and Work Item report derive their state from existing records. Contract
publication and independent Validation retain their existing authority.

## Scope Policy v1

Scope increases in the order `TASK < CHANGE < PROJECT < CRITICAL`.

| Assessment field | Meaning |
| --- | --- |
| Selected scope | The scope recorded on the Work Item. |
| Recommended scope | Policy advice based on the available structured facts. |
| Minimum required scope | The structural floor enforced before adaptive execution. |
| Effective flow | The higher of the selected scope and structural floor. If the selected scope is below the floor, explicitly raise it before proceeding. |

Assessment is deterministic, passive and provider-independent. It reports
structured signals and unknowns alongside the policy version and Work Item
timestamp.

| Signal | Policy v1 outcome |
| --- | --- |
| A stale exact affected Module revision | Minimum `PROJECT`. |
| A stale Project or Technology Decision revision in the active Workflow, tied to an exactly matched affected Module | Minimum `PROJECT`. |
| Multiple affected Modules or Work Item dependencies | Recommend `CHANGE` when the structural minimum is `TASK`. |
| A parent Work Item | Report the relationship as a signal. |
| A Module without an exact reference | Report unknown Module authority. The `CHANGE` flow blocks on unresolved affected Modules. |
| Risk without structured evidence | Report `RISK_UNKNOWN`. Objective text supplies no hard policy facts. |

Use an explicit scope update to elevate scope or override a recommendation.
A downgrade requires confirmation and must meet the structural minimum.
The update compares the current `updated_at` token, checks that the Work Item
is nonterminal and records `WORK_ITEM_SCOPE_CHANGED` in the same transaction.
A running Agent Session blocks a downgrade. An unfinished bound Workflow
execution blocks scope changes. A completed current binding also blocks a
downgrade. Confirmation records an operational choice and supplies no
contract or Validation authority.

## Execution routes

| Scope | Route |
| --- | --- |
| `TASK` | Choose a provider and start an Agent Session through the existing Context and Session Supervisor. This reduced route has no Workflow Contract prerequisite. |
| `CHANGE` | Use the same route within the approved boundaries. Resolve exact affected Module references and complete dependent Work Items first. Structural authority signals can require `PROJECT`. |
| `PROJECT` | Reuse an applicable approved Workflow and explicitly bind its standard execution to this Work Item. Missing or ambiguous coverage calls for planning or reconciliation. |
| `CRITICAL` | Use the `PROJECT` route with explicit `HUMAN` approval on the exact Workflow and an independent `CHECKPOINT` gate for each leaf checkpoint. |

Both reduced routes check scope and readiness again inside the write
transaction that creates the Agent Session. Existing project ownership and
active Workflow attempt checks govern concurrent work. The resulting Agent
Session, Context Projection and any later provider-switch Handoff retain their
existing lifecycle and provenance. [Agent Sessions](phase-3-sessions.md) ·
[Deterministic Context](phase-4-context.md) · [Provider switch](phase-5-provider-switch.md)

## Exact Workflow ownership

For `PROJECT` and `CRITICAL`, an applicable Workflow uses current exact
Project, Module and Technology Decision references from the same project.
The published Project has `HUMAN` approval. The Workflow must cover the
stated affected Modules and acceptance criteria. `CRITICAL` requires
`HUMAN` approval on the Workflow itself, so delegated Workflow approval fails
its authority check. Where coverage is missing, use the existing Project
Manager and Workflow planning and approval flow. [Workflow planning](../workflow-planning.md)

Use `workflow configure ... --work-item WORK_ID` to register the standard
execution for that exact Work Item. The optional binding records the Work Item
ID and a SHA-256 fingerprint of its content in the existing execution metadata.
The fingerprint includes scope, objective, criteria, Validation policy, affected
Modules, dependencies and parent. It excludes status and `updated_at`.
The current workspace execution has at most one owner, and a Work Item can
have at most one current binding. An unbound execution supplies no adaptive
completion evidence.

Use `workflow reconcile ... --work-item WORK_ID` to bind an existing unbound
execution explicitly. Reconciliation stays in the same project, exact workspace
and logical Workflow lineage and requires a released workspace claim. An
already bound execution keeps its existing Work Item owner and refreshes the
binding against current facts. New or changed Work Item bindings cannot carry
completed predecessor checkpoints. Stale or conflicting binds prevent dispatch
or adaptive completion until resolved. With `CRITICAL`, configuration and
reconciliation bind one independent `CHECKPOINT` audit expectation per leaf
to the exact Workflow revision and that individual checkpoint. [Workflow execution](../workflow-execution.md)

## Validation, reports and completion

Adaptive Workflow consumes the exact Validation plans and results recorded
against the current bound execution's checkpoint attempts. The existing
Validation consumer checks the exact scope, target, artifact identity and
admissibility. A blocked independent gate yields `BLOCKED`. Missing, stale,
incomplete or unrelated evidence yields `NOT_VERIFIED`. `VERIFIED` requires
a completed current execution and admissible independent evidence on each leaf.
PROJECT accepts an exact checkpoint or Project product result consumed at that
leaf. CRITICAL requires the exact Workflow checkpoint result on every leaf.
Inherited checkpoint history remains visible and does not stand in for a result
consumed by the current execution.
For `CRITICAL`, each leaf requires its own verified independent `CHECKPOINT`
gate for the exact Workflow revision and that leaf's candidate.
[Independent Validation](../validation.md)

A direct `TASK` or `CHANGE` Agent Session has no exact candidate and criterion
binding to Validation results. It can execute and report the outcome, including
a successful session, while its Validation status stays `NOT_VERIFIED` and
adaptive completion stays blocked. Ordinary `work status` transitions remain
operational. Their recorded status alone supplies no independent evidence.

For eligible bound work, `flow complete` explicitly transitions an `ACTIVE`
Work Item to `COMPLETED`. It compares the current `updated_at` token and
rechecks scope, applicable authority, current execution and independent
Validation within the transition transaction. Agent Session success alone
supplies no adaptive completion proof.

`work report` reads a consistent snapshot and returns a deterministic, redacted
view. It includes scope history, objective, acceptance criteria, affected
Modules, dependencies, gates and exact references to available execution,
Context, Handoff, Validation and Evidence & Report records. It carries no raw
provider transcript and publishes no contract. Report status reflects the
observed gates and blockers. Scope assessment, flow status and reports launch
no providers. [Report authority and snapshots](../report.md)

## CLI, Application, RPC and desktop

Use an existing project path for `ROOT`. Use the exact Work Item or Workflow
identifiers returned by inspection, and carry the current timestamp into
scope updates and completion.

```text
corinthos scope assess --root ROOT --work WORK_ID
corinthos scope set --root ROOT --work WORK_ID --scope CHANGE --expected-updated-at UPDATED_AT
corinthos flow status --root ROOT --work WORK_ID
corinthos flow start --root ROOT --work WORK_ID --provider codex --read-only
corinthos work report --root ROOT --work WORK_ID
corinthos flow complete --root ROOT --work WORK_ID --expected-updated-at UPDATED_AT
corinthos workflow --root ROOT configure WORKFLOW_ID --revision REVISION_ID --work-item WORK_ID
corinthos workflow --root ROOT reconcile EXECUTION_ID WORKFLOW_ID --revision REVISION_ID --work-item WORK_ID
```

Add `--confirm-downgrade` when lowering scope. `flow start` stays in the
foreground for the launched Agent Session and prints the flow view after it
returns. Use the session and Validation fields to assess the recorded outcome.

The Application Layer exposes `scope_assess`, `scope_set`, `flow_status`,
`flow_complete` and `work_report`, with `SessionApplication.flow_start` sharing
the existing supervisor. RPC v2 advertises `scope.assess`, `scope.set`,
`flow.status`, `flow.start`, `flow.complete` and `work.report` by method name.
`scope.set`, `flow.start` and `flow.complete` require request IDs.
[Scope schema](../../schemas/rpc/v2/scope-assessment-result.schema.json) ·
[Flow schema](../../schemas/rpc/v2/adaptive-flow-result.schema.json) ·
[Report schema](../../schemas/rpc/v2/work-report-result.schema.json)

In the desktop **Work** view, select a Work Item and open **Adaptive workflow**
to inspect scope, blockers, gates and next actions. The panel exposes scope
changes, explicit provider selection for eligible reduced work, completion when
the gates permit it, and the derived report. PROJECT and CRITICAL planning use
the existing Project Manager and Workflow tools.

## Verification and deferred evidence

The backend fixtures cover scope assessment and overrides, reduced execution
on the same Work Item, exact Workflow binding and reconciliation, and
independent Validation for adaptive completion. The Windows desktop fixture
exercises the WebView with a synthetic provider. It checks passive PROJECT
planning and TASK inspection, then executes a TASK and reads its `NOT_VERIFIED`
report without publishing a Workflow Contract. The two-real-provider switch gate
remains **NOT VERIFIED / DEFERRED** to v0.1 closure.
[Windows desktop fixture](../../apps/desktop/test-windows.ps1) ·
[Phase 5 switch evidence](phase-5-provider-switch.md#verification)

```text
python -m pytest tests/test_scope_policy.py tests/test_adaptive_flow.py tests/test_adaptive_workflow_binding.py
```

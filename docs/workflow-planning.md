# Workflow planning

Construction Phase 3.0 A–D added Adapter Manager boundaries and human-authorized
engineering planning to the existing Project Manager and Contract Kernel. The
owner subsequently authorized E–J. The [execution guide](workflow-execution.md)
covers actual checkpoint attempts, inspected recovery, conservative revision
reconciliation and bounded structural requests. This guide focuses on the
planning and exact-authorization boundary.

`WorkflowPlanner` starts from an exact active approved Project Contract. Its thin
terminal editor collects module responsibilities, technology evaluations,
provider-owned interfaces, consumer links, verification requirements, checkpoints
and optional milestone plans. It publishes Technology Decision, Module and
Workflow Contracts through the existing Kernel. Natural-language consistency,
technology feasibility and architectural fitness remain human review
responsibilities. A verification specification describes future checks and
evidence requirements.

## Guided terminal journey

Use the [Project Manager](project-manager.md) to publish the Project specification
first. Copy its logical contract ID from the published reference. In an activated
venv, run the following, substituting that ID and your existing authorized root.

```text
corinthos workflow --root . plan YOUR_PROJECT_CONTRACT_ID
```

The command displays published revisions for explicit selection. A stale or
unapproved Project base blocks planning. The menu selects numbered records and
generates stable IDs, so ordinary editing requires no JSON.

1. Choose **Modules and responsibilities** and **Add**. Describe the module's
   purpose, responsibilities and exclusions. Select its numbered Project
   requirements and applicable constraints. Explain any omitted global constraint
   and select prerequisite modules.
2. Choose **Technology decisions**. Record the decision's subject, objective,
   relevant modules, source obligations and concrete drivers. Supply genuinely
   evaluated recommendations, with suitability ranks, rationale, advantages,
   limitations, risks and compatibility. Record verification criteria. An empty
   recommendation list remains blocked for publication.
3. Use **Select a technology** to choose a listed option or evaluate a
   human-proposed alternative under the same constraints. Original recommendations
   and ranking remain visible. This draft choice still requires exact publication
   authorization.
4. Choose **Module technology links** to assign the relevant decisions to each
   module. One decision can serve multiple modules, and a module can use several
   relevant decisions.
5. Use **Provider interfaces** to describe actual interface types, inputs,
   outputs, errors, side effects and behavioral guarantees. Changed terms receive
   a new interface revision. **Consumer interfaces** selects an exact provider,
   interface ID and required revision from the current plan. The service fills
   the exact provider contract reference when freezing the candidates.
6. Inspect **Verification requirements**. Source-derived suggestions cover the
   assigned requirements, constraints, interfaces and M1–M5. Refine concrete
   criteria, methods and evidence, or regenerate suggestions. Mandatory checks
   remain blocking. Custom plans need review after source/interface changes.
7. Add **Checkpoints** with a bounded objective, assigned modules/requirements,
   prerequisites, actual deliverables, observable criteria and verification plan.
8. Add **Playtest milestone plans** when relevant. Describe cumulative test scope,
   required checkpoints, predecessor milestones, scenarios, regressions and
   readiness criteria. An empty milestone list is supported. These records are
   plans for future testing.
9. Use **Show complete plan** and **Review complete publication set**. Resolve
   missing coverage, invalid links, cycles or inconsistent dependencies.
10. Choose **Save for later and leave**, or **Authorize and publish at the local
    terminal** after reviewing the complete final set.

Enter an empty answer to finish a text list. For an existing list, Enter keeps
the displayed default and **replace** collects a new list. Numbered links can
be replaced, or cleared with `/clear`. Existing acceptance/readiness criteria
retain their IDs when edited, and `/remove` removes a criterion explicitly.
Accepted operations are saved atomically. EOF or Ctrl-C preserves the last
accepted operation and reports how to resume.

## Commands

Use an explicit venv executable when the environment is inactive. For example,
PowerShell uses `.\.venv\Scripts\corinthos.exe workflow --help` and POSIX uses
`.venv/bin/corinthos workflow --help`. `--root` defaults to the current directory
and may appear before or after the action.

| Command | Behavior |
| --- | --- |
| `workflow plan CONTRACT_ID [--revision REVISION_ID]` | Select an exact approved Project revision and start a planning session. |
| `workflow sessions` | List saved planning sessions and states. |
| `workflow resume [SESSION_ID]` | Continue a saved session, or choose one from a list. |
| `workflow show [SESSION_ID]` | Show the full draft, sources, decisions and preliminary checks. |
| `workflow review [SESSION_ID]` | Freeze a complete exact candidate set and display differences. |
| `workflow publish [SESSION_ID]` | Obtain exact foreground terminal authorization and publish through the Kernel. |
| `workflow publish [SESSION_ID] --mandate MANDATE_ID` | Use a real existing bounded mandate for its permitted dependency-only replan. |
| `workflow defer [SESSION_ID]` | Save for later and invalidate a pending review. |
| `workflow cancel [SESSION_ID]` | Close planning without publishing new documents. |
| `workflow history [SESSION_ID]` | Inspect durable accepted operations and snapshots. |
| `workflow revise CONTRACT_ID [--revision REVISION_ID]` | Start from an exact active Workflow revision and record the reason for a revised plan. |

The planning commands expose saved draft status and publication lineage. The
separate [runtime commands](workflow-execution.md#commands-and-native-provider-setup)
expose checkpoint attempts, actual verification, completion and recovery.

## Exact review and authority

Review shows planning identity, Project/base references, the complete frozen
document set, set digest, expiry, compiled exact references, constraint-scope
explanations and every document field. Each changed document has its own canonical
digest and full predecessor diff. Control characters and direction controls are
escaped visibly, preserving the terminal layout. Optional/empty fields remain
visible.

The foreground OS terminal displays the final set and a fresh random challenge.
An exact `APPROVE` challenge authorizes that set. An exact `DELEGATE` challenge
also records a bounded, 24-hour mandate for this local account to change only
Workflow dependency links while preserving every other approved obligation.
Other answers defer publication. Piped input, assistant text and stored approval
claims cannot authorize production publication.

The terminal action binds each affected document's exact project, identity,
revision, canonical digest, actor and planning session version. Five-minute
review freshness, current sources, receipts and one-way consumption are checked
again at publication. TDCs and applicable new/changed interfaces or milestone
plans receive HUMAN authority. A technology selection cannot authorize an
unreviewed interface change. The complete final set collects applicable decisions
once, and publication reuses their exact receipts without an additional global
approval round.

Already published unchanged sources retain their exact references. The bounded
delegated publication API verifies the real recorded mandate, local actor,
expiry, approved base and permitted change. It rejects binding content changes
and records DELEGATED provenance. General impact analysis and automatic replanning
remain later work.
Revised sessions display an inherited mandate ID when available. The menu can
select that mandate, or the command above can reference its ID. An ID alone
supplies no consent. Missing, expired, stale or out-of-scope mandates fail.

The local account and Python process remain the trust boundary. These receipts
do not establish remote identity or identify the physical person at the keyboard.
Keep the project root, private state and local account under your control.

## Persistence and publication boundaries

Operational planning sessions and accepted turns share the versioned private
SQLite architecture. Immutable TDC, Module and Workflow revisions remain under
the Kernel's public API. Session compare-and-swap prevents silent overwrites.
Accepted edits invalidate earlier reviews. Reusing an ID or advancing an active
source behind a reviewed candidate blocks the affected operation.

Publication orders TDCs first, provider modules before dependent consumers, then
the Workflow. Every candidate reference is fixed before authorization. Module,
checkpoint and milestone graphs must be acyclic, and every assigned obligation
must have blocking verification coverage. Execution policies remain
`DEPENDENCY_AWARE`, `REQUIRED_GATES`, `PERSISTENT_STATE` and
`CUMULATIVE_SINGLE_ACTIVE`.

Each Kernel publication has its own transaction. A later failure can leave
earlier immutable documents committed. Publication reconciliation preserves those
facts, revokes uncertain remaining consent and requires a fresh review for the
remaining set. A concurrent read between consent and publication can trigger the
same safe revocation. This bounded publication reconciliation supports planning;
the [runtime recovery guide](workflow-execution.md#state-leases-and-recovery)
covers inspection of scheduler/process/Git effects before an explicit retry.
Follow the [storage guide](storage.md) for migrations, backup and error recovery.

| Planning state | Meaning |
| --- | --- |
| `DRAFT` | Editable plan with preliminary checks available. |
| `AWAITING_EXPLICIT_APPROVAL` | A complete frozen set awaits exact authorization. |
| `DEFERRED` | Saved for later; edits resume planning. |
| `PUBLISHING` | Exact receipts were committed and publication is being reconciled. |
| `READY_FOR_REVIEW` | Some publication steps need renewed review after interruption. |
| `PUBLISHED` | All compiled exact references exist in the Kernel. |
| `CANCELLED` | Planning closed without further publication. |

Edits move open sessions to `DRAFT`, review to
`AWAITING_EXPLICIT_APPROVAL`, deferral to `DEFERRED`, and exact authorization to
`PUBLISHING`. Reconciliation ends at `PUBLISHED` or `READY_FOR_REVIEW`.
Closed sessions require a new revision session for further content changes.

## Service and adapter boundaries

`from corinthos.workflow import WorkflowPlanner` provides a service independent
of terminal input/output. Construct `WorkflowPlanner(project_root,
assistance=None)` with an existing authorized root. Optional assistance remains
advisory. The [Adapter Manager guide](adapters.md) documents real provider
interfaces and separate live-verification limits.

| API | Purpose |
| --- | --- |
| `start(project_ref, *, actor_id)` | Open planning from an exact active approved Project. |
| `get`, `list`, `history` | Read detached sessions, accepted choices and publication lineage. |
| `edit(session_id, expected_version, operation, *, actor_id)` | Save one closed, structured planning operation with version checking. |
| `assess(session_id)` | Return deterministic `issues` and unresolved `unknowns`. |
| `review(session_id, expected_version, *, actor_id, approval_kind='HUMAN')` | Freeze exact changed documents, compiled references, digest and expiry. |
| `defer`, `cancel` | Change operational state using session ID, version and actor. |
| `revise(workflow_ref, reason, *, actor_id)` | Open a revision from an exact active Workflow. |
| `authorize_interactively(planner, session_id, expected_version)` | Review, authorize and publish via the real terminal bridge. |
| `publish_delegated(planner, session_id, expected_version, mandate_id)` | Verify an existing bounded mandate and publish only its allowed replan. |

The [planning service](../src/corinthos/workflow/service.py) defines closed edit
operations for modules, interfaces, technology evaluations/selection, links,
verification, checkpoints and milestones. The
[terminal adapter](../src/corinthos/workflow/cli.py) collects those fields through
questions. The [authorization bridge](../src/corinthos/workflow/authorization.py)
supplies exact proof to the existing Kernel.

## A–D traceability and continuation

| Checkpoint | Boundary and evidence |
| --- | --- |
| 3.0.A | Verified integrated Phase 2 base and installed-wheel regression, documented service, authority, persistence and adapter design. |
| 3.0.B | Separate Codex/Claude adapters, shared mandatory Standard, actual capability discovery, safe invocation and advisory PM assistance. See [adapters](adapters.md). |
| 3.0.C | Evaluated technology alternatives, human selection, exact set review, per-document receipts and bounded delegation. |
| 3.0.D | Source-linked modules, provider-owned interfaces, mandatory verification plans, dependency graphs, checkpoints, optional milestones and guided publication. |

RF01/RF02 cover Standard translation, adapters and assistance. RF03 covers
technology and engineering planning. RF10 covers private persistent state and
integrity. RF04 execution, RF05 independent validation and RF06 automatic impact
propagation are later integration boundaries. RF07–RF09 remain later product
features. The initial delivery stopped at A–D. The authorized E–J continuation
adds execution, recovery, reconciliation, the selected installed task-manager
pilot and reviewable release evidence. Historical A–D results remain preserved
in the [Phase 3 design](phase-3-design.md).

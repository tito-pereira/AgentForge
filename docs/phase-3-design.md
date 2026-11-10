# Phase 3 design and execution continuation

The initial A–D delivery ended after planning and publication. Its starting point
was main `139d1542f9b15938985909ab1124832cd69de607`, whose post-merge Windows and
Ubuntu jobs passed 245 tests each. A clean independent Python 3.12 installed
wheel baseline also passed all 245 cases before source changes.

The owner subsequently authorized checkpoints E–J, preserving the A–D baseline.
The continuation adds dependency-aware execution, durable attempts and recovery,
revision impact/reconciliation, bounded PRR handoff, the fixed local task-manager
pilot, full verification and a human-reviewable PR. The pilot must be installed
for personal Windows use with durable daily data outside source, tests, worktrees,
venvs and Corinthos private state. Its exact contract approvals remain real
foreground-terminal decisions.

## Boundaries and interfaces

| Component | Public responsibility |
| --- | --- |
| Adapter Manager | Discover supported executables/capabilities, compose the validated Standard with exact task context, invoke a bounded process and normalize observations. |
| Workflow planner | Negotiate technologies, module obligations/interfaces, verification, checkpoint dependencies and optional milestones from an exact active Project revision. |
| Workflow repository | Persist planning snapshots and append-only accepted turns using shared SQLite and optimistic versions. |
| Planning authorization | Freeze an explicit set of complete candidate documents and bind real terminal consent to each exact publication. |
| Workflow runner | Claim one eligible checkpoint, invoke a real adapter, run actual checks and bind preliminary technical review to the observed artifact. |
| Execution repository | Retain v4 execution snapshots, attempts, fenced workspace leases and explicit inspected recovery or successor execution lineage. |
| Revision reconciler | Detect active-source drift, map conservative impact and route bounded structural diagnoses or direct owner changes to Project Manager. |
| Contract Kernel | Validate schemas, authority, exact references, coverage, immutable revisions and actual dependency-ordered publication. |

Adapter invocation is an explicit process boundary. It is neither a scheduler
nor evidence of checkpoint completion. Native settings and authentication remain
under the local user's control. A worktree provides source isolation, while
effective process restrictions depend on the agent's actual native capabilities.
The historical A–D Codex diagnostic was read-only. Actual pilot tasks use the
runner after real concrete Project/plan approvals and retain their own attempt
and artifact evidence.

`AdapterManager` accepts explicit policy/schema paths validated by the existing
Standard loader. `discover`, explicit managed-section `prepare`, `invoke` and
diagnostic `probe` form its boundary. Exact resume is offered only where verified.
Observed process results distinguish completion, failure, timeout, cancellation,
unavailable executables and malformed protocol. Unavailable resource telemetry
remains unknown. PM assistance is an explicit advisory callback.

`WorkflowPlanner` exposes start, get/list/history, version-checked structured edit,
assessment, review, defer/cancel and revision operations. A thin CLI collects
ordinary descriptions and numbered choices without JSON editing. Draft
technology rankings and selections provide no publication authority.

## Planning and authorization transitions

| State | Allowed progression |
| --- | --- |
| DRAFT / NEEDS_CLARIFICATION | Edit or defer until coverage, references and decisions are complete. |
| DEFERRED | Resume the same planning session and accepted history. |
| AWAITING_EXPLICIT_APPROVAL | Inspect a complete frozen candidate set. An edit invalidates review. |
| PUBLISHING | Publish only the exact authorized candidates in dependency order. |
| READY_FOR_REVIEW | Reconcile already committed documents and obtain renewed consent for remaining changed candidates. |
| PUBLISHED | Inspect exact references or start an explicitly based revision. |
| CANCELLED | Preserve history without publishing further documents. |

A single foreground-terminal action may approve the explicit final set of TDC,
Module and Workflow candidates. Every candidate carries its own exact digest and
receipt. Approval of a technology draft alone cannot authorize later interfaces.
Consolidation reuses those per-publication bindings without a second global
prompt. HUMAN authority remains present wherever the Kernel requires it.

An optional explicit bounded mandate permits only Workflow checkpoint dependency
replans under the same Project, modules, technologies, interfaces, milestones and
all other checkpoint obligations. Its provenance and lifetime are recorded.
DELEGATED publication must verify that mandate and its invariant digest. Other
changes require the applicable fresh human review.

## Persistence and publication recovery

The historical A–D migration advanced SQLite v2 to v3 in the existing state database.
It added a separate Workflow planning namespace and exact authorization/mandate
records. Existing PM state and immutable contract data retain their meanings.
The generic compare-and-swap repository mechanics are reused. A verified private
pre-upgrade backup precedes transactional schema changes. Scheduler leases and
general execution recovery belong to the newly authorized E–F continuation.

SQLite publication and external processes are distinct transaction domains.
Planning publication recovery checks exact already-committed documents before
retrying. It preserves legitimate partial publication and revokes uncertain or
expired consent. Process invocation has a bounded lifecycle and no automatic
retry. Full execution-state recovery is now part of the E–F continuation.

## Requirement and evidence matrix

| Requirement | Checkpoint | Required evidence |
| --- | --- | --- |
| RF01 mandatory Standard | B | Equivalent managed instructions, preserved user text, conflict/idempotence tests. |
| RF02 advisory assistance | B | Detached PM input and no mutation, approval or fake fallback. |
| RF03 technology authority | C | Ranked 1–5 viable supplied options, blocked empty set, outside-ranking choice and exact consent tests. |
| RF03 module/workflow planning | D | Complete obligations, provider/consumer revisions, DAGs, policy constants and real Kernel publication. |
| RF04 process boundary | B | Actual supported argv, stdin transport, result/error/cancellation fixtures and separate real Codex diagnostic. |
| RF05 independent gates boundary | A–D | Verification plans retain mandatory gates and make no runtime validation claim. |
| RF06 bounded internal replan | C–D | Exact predecessors, mandate scope and stale/mutated/replayed authority rejection. |
| RF10 persistent planning | C–D | CAS, reopen, pre-upgrade backup, PM preservation and partial-publication recovery tests. |

The initial A–D delivery reserved checkpoints E–J for a subsequent order. That
continuation is now authorized. RF07–RF09 runtime evolution, independent
Validation/Report and formal product acceptance retain their later-phase bounds.

## A–D handoff

The following records the historical local `phase-3.0-workflow-adapters` handoff
at the owner's requested checkpoint D stop.

| Checkpoint | Observed result |
| --- | --- |
| A | Main/CI verified, 245-case clean wheel baseline, design and traceability recorded before implementation. |
| B | Separate executable transports and advisory PM hook tested. Real read-only Codex 0.167.0 diagnostic completed. Claude live verification is unavailable because its executable is absent. |
| C | Exact set authorization, declined/forged/stale/replayed consent, explicit dependency-only mandate and actual Kernel publication tested. |
| D | Guided planning, exact provider/consumer revisions, complete verification coverage, DAGs, milestones and resumable publication tested. |

The final installed wheel passed **320 tests** on independent Windows Python
3.12.10, including all 245 baseline cases. Dependency consistency, Ruff and
formatting passed. The original eight-contract demonstration and PM help flows
also passed. Independent review covered command transport, managed instructions,
context associations, authority/mandates, partial publication, v3 migration,
private-content exclusions, baseline compatibility and 146 documentation links.

Positive approval tests use explicitly synthetic terminal fixtures. The live
Codex check was a read-only protocol diagnostic with an unchanged empty
workspace. It provides no user-project approval, pilot execution or independent
Validation result. Claude live behavior remains **NOT VERIFIED**. Instruction
preparation requires a quiescent editor, and unconfirmed native-process cleanup
revokes resume eligibility. See the [adapter guide](adapters.md) for observed
capabilities and actual enforcement limits.

That handoff completed the requested A–D stop. The later owner instruction
authorizes the remaining execution, release CI and PR work. New results must be
recorded against their actual commit, environment and execution evidence.

## E–J service boundaries

`WorkflowRunner` owns dependency-aware dispatch, actual preliminary checks,
required gate consumption and honest checkpoint state. `ExecutionRepository`
owns durable attempts, workspace leases, versioned snapshots and recovery
decisions. Claim transactions recheck exact active Workflow, Project, Module and
Technology bindings. External processes, Git and SQLite have separate effects
that recovery must inspect before an explicit retry.

`RevisionReconciler.inspect` detects active-source drift before dispatch and
at safe continuation points. `compare` reports conservative affected and
preserved checkpoint sets. The execution repository creates an explicit successor
execution and carries eligible completed work by its original attempt reference.
Historical evidence retains its original contracts and artifact identity.

The E–F migration advances the local schema to v4 for execution snapshots,
checkpoint states, attempt observations and fenced workspace ownership. It
preserves v3 planning/mandates, PM state and immutable contract bytes. The
wire schema remains `1.0`. Backup and migration evidence belongs to the actual
storage checks, separate from any pilot build result.

Only an explicit evidenced `STRUCTURAL_CONFLICT` diagnosis produces a bounded
Kernel PRR. Exact published contract sources may use empty validation evidence
IDs with truthful limitations. Genuine nonempty evidence IDs require a real
published Validation Result. User-initiated global changes use the existing
Project Manager revision flow directly. Requests and failures supply no approval
to change product obligations.

The selected pilot brief defines task rules, SQLite persistence and a terminal
interface with dependent checkpoints. Its concrete contracts currently await
real owner-terminal approvals. Pilot implementation and installation are pending.
Actual Codex pilot execution, installed-application verification and delivery
evidence must be recorded after they occur. The earlier live Codex evidence
remains a read-only adapter diagnostic.

The planned installation checks use isolated demonstration data and cover
backup/restore, reinstallation and working-directory independence. Daily data
remains private. Later formal Validation/Report gates must be reported separately
from a functional installed application and explicit preliminary technical
review. Claude's executable is absent, so live Claude verification remains
`NOT VERIFIED`.

The [Phase 3 verification record](phase-3-verification.md) identifies the current
installed-wheel environment, artifact digest, native diagnostic and remaining
pilot requirements. It preserves the distinction from the historical A–D
evidence above.

# Phase 3 checkpoints A through D

The authorized delivery ends after planning and publication. Its starting point
is main `139d1542f9b15938985909ab1124832cd69de607`, whose post-merge Windows and
Ubuntu jobs passed 245 tests each. A clean independent Python 3.12 installed
wheel baseline also passed all 245 cases before source changes.

## Boundaries and interfaces

| Component | Public responsibility |
| --- | --- |
| Adapter Manager | Discover supported executables/capabilities, compose the validated Standard with exact task context, invoke a bounded process and normalize observations. |
| Workflow planner | Negotiate technologies, module obligations/interfaces, verification, checkpoint dependencies and optional milestones from an exact active Project revision. |
| Workflow repository | Persist planning snapshots and append-only accepted turns using shared SQLite and optimistic versions. |
| Planning authorization | Freeze an explicit set of complete candidate documents and bind real terminal consent to each exact publication. |
| Contract Kernel | Validate schemas, authority, exact references, coverage, immutable revisions and actual dependency-ordered publication. |

Adapter invocation is an explicit process boundary. It is neither a scheduler
nor evidence of checkpoint completion. Native settings and authentication remain
under the local user's control. A worktree provides source isolation, while
effective process restrictions depend on the agent's actual native capabilities.
One harmless read-only diagnostic may verify the real Codex integration. It does
not approve or implement a separate user project.

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

The minimal A–D migration advances SQLite v2 to v3 in the existing state database.
It adds a separate Workflow planning namespace and exact authorization/mandate
records. Existing PM state and immutable contract data retain their meanings.
The generic compare-and-swap repository mechanics are reused. A verified private
pre-upgrade backup precedes transactional schema changes. No execution scheduler,
checkpoint-attempt lease or general process recovery is introduced in this scope.

SQLite publication and external processes are distinct transaction domains.
Planning publication recovery checks exact already-committed documents before
retrying. It preserves legitimate partial publication and revokes uncertain or
expired consent. Process invocation has a bounded lifecycle and no automatic
retry. Full execution-state recovery belongs after checkpoint D.

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

Checkpoints E–J require subsequent authorization. Their scheduler, execution
recovery, impact/PRR production, real pilot, complete release CI and PR handoff
remain outside this A–D delivery. RF07–RF09 runtime evolution, validation/report
and product acceptance remain later responsibilities.

## A–D handoff

The local `phase-3.0-workflow-adapters` branch is ready for the owner's review
at the requested checkpoint D stop.

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

This is the requested A–D stop. New Ubuntu/Windows release CI, public branch/PR
handoff and the remaining execution checkpoints await the owner's next order.

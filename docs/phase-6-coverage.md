# Phase 6 requirements and evidence matrix

The approved product is Core v0.1 under specification revision v0.2. Architecture
sections 2.8–2.19 and final contract consolidations govern authority, revisions,
playtests and retention. Existing behavior is anchored in starting main
`32397d2bc0d02c8e77b5c6e09ca7e83f04995af0` and its actual merge CI. This matrix
is recorded before implementation; OPEN/PARTIAL rows are not completion claims.

| Requirement | Existing entry point / evidence | Remaining Phase 6 behavior | Authority | Required proof / initial status |
| --- | --- | --- | --- | --- |
| RF01 Initialization/Standard | standard.load_standard; AdapterManager.prepare; baseline Standard and tamper tests | Packaged policy/schema, installed init/capabilities outside checkout | Standard/Adapter Manager; no HUMAN approval created | Installed clean-wheel init, repeated initialization, mandatory M1–M5, preserved user blocks; PARTIAL |
| RF02 Negotiation | ProjectManager + project CLI; durable negotiation and exact terminal publication in prior phases | Explicit opt-in advisory action, persisted provenance, restart context | PM advises; owner alone approves requirements | No paid work on reads/help, real bounded advisory path, manual path preserved; PARTIAL |
| RF03 Planning | WorkflowPlanner, exact TDC/Module/Workflow review, checkpoint/milestone schemas | Operational consumption of approved cumulative milestones and reuse | HUMAN for binding choices/milestones; verified delegation only for equivalent replan | Missing/cyclic scope and unapproved plan negatives; real frozen milestone review; PARTIAL |
| RF04 Execution/recovery | WorkflowRunner, ExecutionRepository, process containment and inspected recovery | Lifecycle operations and isolated versions/builds/sessions | Workflow coordinates, retains partial effects | Crash/cancel/restart and no duplicate-effect CLI scenarios; PARTIAL |
| RF05 Audit/repair | ValidationPlanner/Runner, ValidationGateConsumer; six preserved real pilot audits | Sealed build bridge, non-circular readiness then exact scoped validation | Validation independently derives technical outcome | Wrong build/source/run, newer unfinished/blocker, omitted/tampered proof; PARTIAL |
| RF06 Revisions | PM revise/receive_prr and RevisionReconciler | Delivered-base evolution, exact active bases, targeted integration/revalidation | Four approved change classes; reserved decisions retain HUMAN authority | Stale base/receipt, affected transitive work and justified unaffected reuse; PARTIAL |
| RF07 IPE | Approved plan/schema and reusable runners; no operational build/session tracker | Isolated cumulative builds, one active/pending transition, session pins, stable tracker, feedback/triage | Workflow + Validation; optional owner playtest | Real two-candidate cumulative demo, blocked promotion, races/pins/origin negatives; OPEN |
| RF08 Delivery/evolution | Existing delivery proof, ERC authority and immutable history | Recoverable version records, optional exact HUMAN review, selective evolution | PM owns decisions/review; REPORT publishes exact ERC through Kernel | Version preservation, no-review path, labelled accepted/reserved fixtures, real lineage; PARTIAL |
| RF09 Reports | ReportService, coherent sources, five kinds, export/history/recovery | Explicit lifecycle sources/events and native version/build/session/feedback/review projections | Report explains; no validation/promotion/acceptance authority | Actual installed PRODUCT/MILESTONE/HISTORY/EVOLUTION bundles and existing CHECKPOINT regression; PARTIAL |
| RF10 Persistence | SQLite v5, 20 tables; backup/migration and immutable contracts/events | Minimal v6 lifecycle records/projects/events and retention/recovery | Shared infrastructure; logical Engine ownership | Populated v5 plus supported old versions, rollback/reopen/backup, source-byte/order preservation; PARTIAL |

## Universal Engineering Commandments

| Commandment | Required evidence | Initial status |
| --- | --- | --- |
| M1 Precise instructions | Bounded design, ownership/API contract, scoped tasks and this matrix before code | Design recorded; execution proof pending |
| M2 Justified technologies | Existing Python/SQLite/Git and libraries reused; reserved pilot decisions frozen for real review | No new technology assumed; pilot authority pending |
| M3 Meaningful testing | Functional/negative/concurrency/restart/migration tests, external pilot checks and actual installed/platform runs | New Phase 6 proof OPEN; previous results stay attributed |
| M4 Usable documentation | Public installed journeys/API/state/authority/migration/recovery/retention guides and private useful demo handoff | Design/matrix recorded; final guides/proof OPEN |
| M5 Readable/efficient code | Existing service/repository/process patterns, bounded work and independent connected-code review | Design uses minimal shared storage; implementation/review OPEN |

## Contract acceptance and cross-engine proof

| Contract / boundary | Required observed behavior | Initial disposition |
| --- | --- | --- |
| Project | Human-approved exact requirements; unchanged content does not create gratuitous revisions | Existing Kernel/PM evidence reused by exact baseline; evolution regression required |
| Workflow | Valid DAG, complete checkpoints, approved cumulative milestone architecture, one active revision | Existing publication remains; real new milestone decision required |
| Module | Provider-owned exact interfaces and targeted consumer compatibility | Existing invariants remain; affected/unaffected evolution proof required |
| Technology Decision | Genuine reserved authority, viable alternatives and unchanged-decision reuse | Existing authority retained; no invented new technology approval |
| Validation | Complete source-derived matrix and independently reviewed adequate methods | Existing planner remains; exact build/PLAYTEST scope proof required |
| Validation Result | Per-run full target identity, honest interruption and derived gate | Existing VRC history retained; bridge/current-freshness negatives required |
| Evidence Report | Exact immutable sources/evidence; safe exports; human approval never inferred | Existing reports retained; lifecycle source and review tests required |
| Project Revision Request | Genuine scoped incompatibility, exact base, PM triage and actual successor decision | Existing APIs reused; labelled lifecycle/stale-base tests required |
| Native interoperability | Same bounded real brief/Standard/external checks under actual Codex and Claude Code | Codex discovered; owner has no Claude Code. Mandatory live Claude proof OPEN |
| Real pilot | Two meaningful cumulative states, session-safe promotion, failure/recovery, version/report provenance | Preserve prior app/data; concrete milestone proposal and actual new observations OPEN |

Synthetic fixtures, agent code review, formal Validation, manual graph checking
and optional human product acceptance have different authorities. Final status
must separately identify implementation, mandatory proof, PR readiness, integration
and acceptance. An unavailable mandatory provider proof cannot be counted as pass.

## Implemented candidate and remaining execution proof

The initial matrix above is preserved as the pre-implementation gap record.
The [verification record](phase-6-verification.md) links the executable evidence;
[lifecycle](evolution.md) and [builds](builds.md) describe supported installed flows.

| Area | Current disposition |
| --- | --- |
| RF01–RF02 | Packaged initialization/capabilities and explicit persisted advice implemented; focused tests and working-wheel outside-checkout smoke passed. Final platform verification remains separate. |
| RF03–RF06 | Approved milestone consumption, exact build bridge and selective reconciliation implemented/tested. The real successor received genuine foreground HUMAN approval. Actual checkpoint execution, independent audits and inspected recovery are retained. The pilot source repair was reviewed and tested; fresh exact formal proof remains NOT_COMPLETED and is waived for Phase 6.1 delivery. |
| RF07 | Promotion, pins, voluntary switching, feedback and safe retention implemented; real-byte/transaction tests and independent race/reconciliation review passed. An actual M1 Build was promoted and pinned; an M2 controller was interrupted, inspected and recovered. The remaining repaired-candidate Build/admission/promotion journey is NOT_COMPLETED and waived for Phase 6.1 delivery; runtime cumulative gates remain enforced. |
| RF08 | Native versions, original delivery adoption, exact optional review and evolution-to-PM implemented/tested. Actual installed pilot baseline adoption/evolution is recorded. Evolved pilot delivery is NOT_COMPLETED and waived for Phase 6.1 delivery; acceptance remains NOT_REVIEWED. |
| RF09 | Lifecycle source cutoffs, readiness/session projections, typed feedback and original review history implemented/tested. Three actual installed baseline report/export bundles passed verification. Remaining successor MILESTONE/evolved report proof is NOT_COMPLETED and waived for Phase 6.1 delivery. |
| RF10 | v6 migration preserves genuinely populated old tables/artifacts, including unfinished v5 report recovery; populated backup/recovery and old-version regressions exercised. |
| M1–M5 | Bounded design, existing technologies, meaningful security/restart tests, English guides and independent review retained. Exact runtime commit 7d568f55 passed clean-wheel CI with 618 Windows tests and 616 plus two Windows-only skips on Ubuntu. The pilot title-domain defect was repaired and checked in the separate pilot source; it is not an unresolved Core blocker. Final documentation-head CI/Graphify remain separately attributable. |
| Native interoperability | Real Codex artifact checks passed, but protocol completion timed out. Claude Code access is absent; comparable live proof remains NOT_VERIFIED and is waived for Phase 6.1 delivery. |
| Delivery authority | Phase 6.1 permits engineering delivery and PR readiness after the required review/checks, with the proof gaps explicitly retained. The owner separately authorized PR #9 integration after those checks. Neither the waiver nor integration establishes full Core/PRD completion or human acceptance. |

The [Phase 6.1 delivery decision](phase-6-verification.md#phase-61-delivery-decision)
supersedes the original delivery-blocker disposition, without rewriting the initial
matrix or historical results. A future real field test is outside this delivery
gate. Bench, GUI and SaaS remain out of scope.

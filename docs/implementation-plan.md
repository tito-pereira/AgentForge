# Implementation plan

Baseline dated November 8, 2026. Product requirements revision v0.2 targets Core
v0.1. The construction plan divides implementation into seven phases. Phase 0.1
is the authorized English migration and public publication step between the
foundation and Contract Kernel phases.
Phase 0.3 established the Nukytera naming migration. Phase 1 starts from the
verified Phase 0.3 merge `830943bb`.

## Seven construction phases

| Phase | Dependency and deliverable | Completion criterion |
| --- | --- | --- |
| 0 — Foundation | Baseline, repository, package/CLI, Standard policy, instructions, tests, static analysis, and CI. | Install, run, and verify the foundation reproducibly. |
| 1 — Contract Kernel | Builds on the foundation with eight schemas, immutable revisions, integrity, references, and shared persistence. | Tests accept valid contracts and reject invalid data, incorrect references, and inconsistent revisions. |
| 2 — Project Manager | Uses the Kernel to negotiate and publish requirements. | An idea becomes a versioned, explicitly approved specification. |
| 3 — Workflow + Adapters | Uses contracts and Project Manager for modules, technologies, checkpoints, and agent execution. | The first small project runs with traceable decisions and progress. |
| 4 — Validation Engine | Uses contracts, artifacts, and criteria for independent audit and gates. | Failures, regressions, and insufficient evidence block the applicable progression. |
| 5 — Report Engine | Consolidates execution, decision, and validation sources. | A project can be audited end to end through references to real evidence. |
| 6 — Evolution + Hardening | Integrates evolution, playtests, isolated builds, feedback, revisions, and robustness. | Real evolution and tests preserve consistency, history, and approvals. |

The Contract Kernel is shared infrastructure for the six Engines. Phase 0
prepares the foundation. Phase 1 implements contract schemas and persistence.
The Standard policy and its minimal schema belong to the foundation.
`.corinthos/` contains private SQLite state and local evidence.

## Phase 0 checkpoints

| Checkpoint | Required work and evidence |
| --- | --- |
| F0.1 — Discovery and baseline | Inspect the directory, Git, existing files, Python, pip, and tools. Document the baseline version, scope, and decisions. |
| F0.2 — Minimal executable structure | Install the package, run help/version, validate the M1–M5 Standard, and protect private state through Git exclusions. |
| F0.3 — Instructions and documentation | Align AGENTS/CLAUDE and provide a reproducible README, architecture, contracts, workflows, plan, and decisions. |
| F0.4 — Tests and minimal CI | Exercise imports/CLI, valid Standard, negative cases, packaging, pytest, and lint. Configure Linux/Windows CI on Python 3.12. |
| F0.5 — Review and delivery | Check commands, changes, Git, and documentation. Assess M1–M5 using evidence, actual results, risks, and limitations. |

Each checkpoint is reported as done, partial, or blocked. Any unmet mandatory
criterion leaves the phase partial or blocked, with the cause and next action.
Local execution and remote CI execution require separate evidence. Historical
Phase 0 results are recorded in [decisions.md](decisions.md).

## Phase 0.1 migration and publication

| Checkpoint | Acceptance requirement |
| --- | --- |
| 0.1.A — Discover and protect | Inspect repository files, Git history, remotes, private data, and language. Preserve existing work. |
| 0.1.B — Convert to English | Translate public human-readable materials, keep behavior and M1–M5 intact, and provide self-contained local documentation. |
| 0.1.C — Publication safety and licensing | Review ignored files, intended commit content, secrets, author identity, ownership, and the pending license decision. |
| 0.1.D — Revalidate Phase 0 | Execute installation, CLI, tests, lint, format, dependency, and documentation checks against the translated tree. |
| 0.1.E — Publish the foundation | After prerequisites pass, publish the reviewed tree to the authorized public GitHub repository and verify its commit, visibility, and actual CI status. |
| 0.1.F — Report and handoff | Report actual checkpoint status, results, Commandment evidence, publication facts, and remaining limitations. |

English is required for repository artifacts, user-facing messages, documentation,
test descriptions, commit messages, and public GitHub collaboration. Phase 0.1
results must be established by its own validation and delivery report. Historical
test counts and local checks remain tied to their original execution.

## Historical Phase 0.3 naming migration

Migrate active branding, imports, distribution metadata, CLI commands, paths,
documentation, and owned repository/workspace names to Nukytera. Keep package
version `0.1.0`, Standard semantics, M1–M5, the six Engines, eight contract types,
and MPL-2.0 unchanged. Verify the new namespace in clean Windows and Linux venvs,
including packaging, CLI, Standard negative tests, and existing quality checks.

Use a reviewed migration branch and pull request. Merging requires separate
authorization. Preserve history, earlier execution evidence, and the immutable
`phase-1-baseline` tag. The [decision log](decisions.md) records the naming map
and intentional legacy references.

## Phase 1.0 checkpoints

| Checkpoint | Acceptance evidence |
| --- | --- |
| A — Inventory and design | Reviewed baseline, authority and wire decisions, and source-to-test traceability. |
| B — Schemas | Eight installed schemas with a shared envelope, valid examples and invalid shape tests. |
| C — Integrity | Typed exact references, graph and obligation checks, approval provenance, and evidence consistency. |
| D — Storage | SQLite migration, immutable history, transaction rollback, conflict-safe activation and reopen checks. |
| E — Demonstration and documentation | A runnable eight-type example and self-contained API, authority and storage guides. |
| F — Verification | Existing and new tests, wheel installation, lint and format on Windows and Ubuntu. |
| G — Handoff | Independent review and verifiable evidence on the feature PR. |

See the [design and traceability record](contract-kernel-design.md) for the mapping
to approved architecture and PRD v0.2.

## Historical Phase 1.1 naming migration

Use Corinthos for the product, repository and workspace, `corinthos-core` for
the distribution, `corinthos` for the import and CLI, and `.corinthos/` for
private state. Preserve the Phase 1.0 wire identifiers, SQLite markers and
historical evidence. Verify the renamed wheel and all contract behavior in
fresh Windows and Ubuntu venvs. Exercise migration and recovery with disposable
legacy stores before moving private data.

The [decision log](decisions.md#phase-11-corinthos-naming-and-compatibility)
records the name mapping and deliberate exceptions. The project owner reviews
and authorizes the migration merge separately from Phase 2.

## Phase 2.0 Project Manager

Phase 2 starts from merged Phase 1.1 main
`c96ee0c893b1374d13fff64d4d037fb6bad50134`. The original foundation and Kernel
tests remain regression requirements. The approved scope provides structured
human-led negotiation, durable sessions, complete reviews, explicit local
approval and bounded intake of already published PRRs. The
[Project Manager guide](project-manager.md#requirement-traceability) maps
RF02/RF06/RF10 and checkpoints 2.0.A–H to concrete APIs, docs and test files.

| Checkpoint | Required evidence |
| --- | --- |
| 2.0.A | Verified integrated baseline, service/state design and requirement traceability. |
| 2.0.B | Usable guided CLI and separate service with ordinary-language inputs. |
| 2.0.C | Stable classified proposals, explicit decisions and honest preliminary checks. |
| 2.0.D | Complete exact review, local terminal challenge, trusted receipt and Kernel publication. |
| 2.0.E | Versioned SQLite migration, restart, concurrent edits and publication recovery. |
| 2.0.F | Exact PRR intake, bounded edits and preserved unaffected obligations. |
| 2.0.G | Targeted tests, baseline regression, clean wheel installation and actual Windows/Ubuntu checks. |
| 2.0.H | Independent review, exact commit/CI evidence and a human-reviewable feature PR. |

Execution results and remaining limitations are recorded in the PR and
[decision log](decisions.md). Local checks and observed remote CI retain their
own environments and exact tested commit identities.

## Historical Phase 3.0 A–D scope

This increment begins from integrated Phase 2 commit
`139d1542f9b15938985909ab1124832cd69de607`. Its verified installed-wheel baseline
passed the existing 245 tests before changes. The initial authorization covered
construction checkpoints A–D, followed by an explicit stop.

| Checkpoint | Required evidence |
| --- | --- |
| 3.0.A | Verified baseline, executable service/adapter design and requirement traceability. |
| 3.0.B | Separate real provider boundaries, equivalent mandatory Standard, honest capabilities and advisory PM assistance. |
| 3.0.C | Evaluated alternatives, exact human authorization, per-document receipts and verified bounded delegation. |
| 3.0.D | Source-linked modules/interfaces, blocking verification plans, checkpoint/milestone graphs and guided publication. |

The [Workflow planning guide](workflow-planning.md) records the user journey,
API, state/authority boundaries and A–D traceability. The
[Adapter Manager guide](adapters.md) records supported process interfaces and
separates protocol tests from live-provider evidence. The current tests and
documentation support the authorized A–D deliverables, without treating them as
completion of the later release checkpoints.

That historical stop preserved planning/publication evidence. The owner has
subsequently authorized the remaining E–J continuation.

## Phase 3.0 E–J continuation

| Checkpoint | Required evidence |
| --- | --- |
| 3.0.E | Sequential dependency-aware dispatch, actual automated/file checks, explicit preliminary review and admissible required gates. |
| 3.0.F | Versioned execution state, fenced workspace leases, retained attempts and inspected recovery across process/Git/SQLite effects. |
| 3.0.G | Active-source detection, conservative impact, explicit old-evidence inheritance and bounded PRR/Project Manager handoff. |
| 3.0.H | The fixed local task-manager pilot built by real Codex execution, reviewed, installed for personal Windows use and verified with isolated data. |
| 3.0.I | Full regression, safety, documentation and clean installed-wheel Windows/Ubuntu checks at the actual final commit. |
| 3.0.J | Independent review, factual release evidence and an owner-reviewable PR with no automatic merge. |

The [runtime guide](workflow-execution.md) documents actual commands, recovery,
revision handling and service interfaces. The [Phase 3 design](phase-3-design.md)
preserves the A–D handoff and defines continuation boundaries. Pilot delivery
must identify real source/package/launcher/data paths, preserve daily tasks
across reinstall, and verify backup/restore using separate test data. Actual
execution and release evidence are recorded only when observed. The
[Phase 3 verification record](phase-3-verification.md) records the completed
Codex pilot, Windows installation and isolated checks alongside the Core
installed-wheel results. Live Claude remains `NOT VERIFIED`. Formal Validation,
Report and human product acceptance retain their separate scopes.

## Phase 4.0 independent Validation

The [Validation design](phase-4-design.md) maps the approved obligations to
source-derived matrices, separate method review, owned audit execution,
private evidence, durable recovery and immutable scoped results. The
[Validation guide](validation.md) documents all five scopes, guided planning
and run commands, exact procedure and candidate identity, managed Workflow
gate expectations, selective revalidation and the isolated pilot audit.

## Gates and the next phase

Phase 5 adds the [Report Engine](report.md), following the
[source and publication design](phase-5-design.md). It captures exact source
cutoffs, composes the nine ERC sections across five kinds, preserves immutable
revisions, and exposes installed generation, inspection, comparison and export.
Reporting preserves current versus historical eligibility and separate authority.

Each unit has an objective, scope, interfaces, criteria, and tests proportionate
to risk. The Engineering Completion Gate requires precise instructions, justified
technologies, meaningful testing, accurate documentation, and readable code.
Automated tests and explicit technical review provide preliminary engineering
evidence. Independent Validation derives and evaluates formal scoped gates
where required.

Phase 2 provides human-led Project negotiation and Phase 3 adds planning,
Adapter Manager, sequential execution and bounded reconciliation. Phase 4
provides independent audit and formal scoped results. Phase 5 consolidates those
facts into reports. General product evolution remains a later responsibility.
The owner separately authorizes integration and subsequent construction phases.

The delivered Phase 3 task manager provides a separate candidate for independent
audit. Keep its daily installation and data outside the experimental cycle.
The Bench follows construction of the Core.

## Related documentation

- [Architecture](architecture.md)
- [Contract catalogue](contracts.md)
- [Project Manager guide and traceability](project-manager.md)
- [Workflow planning and exact authority](workflow-planning.md)
- [Execution, recovery and revision reconciliation](workflow-execution.md)
- [Workflow scopes and approval rules](workflows.md)
- [Practical decisions and historical verification](decisions.md)
- [Contributor instructions](../AGENTS.md)

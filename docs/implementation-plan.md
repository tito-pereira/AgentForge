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

## Phase 1.1 naming migration

Use Corinthos for the product, repository and workspace, `corinthos-core` for
the distribution, `corinthos` for the import and CLI, and `.corinthos/` for
private state. Preserve the Phase 1.0 wire identifiers, SQLite markers and
historical evidence. Verify the renamed wheel and all contract behavior in
fresh Windows and Ubuntu venvs. Exercise migration and recovery with disposable
legacy stores before moving private data.

The [decision log](decisions.md#phase-11-corinthos-naming-and-compatibility)
records the name mapping and deliberate exceptions. The project owner reviews
and authorizes the migration merge separately from Phase 2.

## Gates and the next phase

Each unit has an objective, scope, interfaces, criteria, and tests proportionate
to risk. The Engineering Completion Gate requires precise instructions, justified
technologies, meaningful testing, accurate documentation, and readable code.
Until Validation is implemented, automated tests and explicit technical review
evaluate the evidence.

Phase 1 publishes shared infrastructure for the six Engines. The project owner
authorizes the merge and the start of Phase 2 separately. Project negotiation,
execution adapters, scheduling, independent audits and report generation remain
future Engine responsibilities.

Once Project Manager, Workflow, a minimal adapter, and operational persistence
exist, run a small isolated pilot. Repeat it once Validation and Report are
operational. The Bench follows construction of the Core.

## Related documentation

- [Architecture](architecture.md)
- [Contract catalogue](contracts.md)
- [Workflow scopes and approval rules](workflows.md)
- [Practical decisions and historical verification](decisions.md)
- [Contributor instructions](../AGENTS.md)

# Implementation plan

Baseline dated November 8, 2026. Product requirements revision v0.2 targets Core
v0.1. The construction plan divides implementation into seven phases. Phase 0.1
is the authorized English migration and public publication step between the
foundation and Contract Kernel phases.

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
`.agentforge/` is reserved for future private state. The eight executable contract
schemas and operational SQLite require a subsequent Phase 1 authorization.

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
| 0.1.E — Publish AgentForge | After prerequisites pass, publish the reviewed tree to the authorized public GitHub repository and verify its commit, visibility, and actual CI status. |
| 0.1.F — Report and handoff | Report actual checkpoint status, results, Commandment evidence, publication facts, and remaining limitations. |

English is required for repository artifacts, user-facing messages, documentation,
test descriptions, commit messages, and public GitHub collaboration. Phase 0.1
results must be established by its own validation and delivery report. Historical
test counts and local checks remain tied to their original execution.

## Gates and the next phase

Each unit has an objective, scope, interfaces, criteria, and tests proportionate
to risk. The Engineering Completion Gate requires precise instructions, justified
technologies, meaningful testing, accurate documentation, and readable code.
Until Validation is implemented, automated tests and explicit technical review
evaluate the evidence.

Starting Phase 1 requires a subsequent user instruction and executable decisions
on schemas, identity, invariants, authorization, and persistence, with positive
and negative fixtures. Implementation decisions must preserve the approved
contract responsibilities and human authority described in the local documents.

Once Project Manager, Workflow, a minimal adapter, and operational persistence
exist, run a small isolated pilot. Repeat it once Validation and Report are
operational. The Bench follows construction of the Core.

## Related documentation

- [Architecture](architecture.md)
- [Contract catalogue](contracts.md)
- [Workflow scopes and approval rules](workflows.md)
- [Practical decisions and historical verification](decisions.md)
- [Contributor instructions](../AGENTS.md)

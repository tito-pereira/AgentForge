# Operational architecture

Documentation baseline dated November 8, 2026. Product requirements revision v0.2
targets Core v0.1. Package version `0.1.0` includes the Phase 0 foundation and
Phase 1 Contract Kernel, Phase 2 Project Manager, Phase 3 Workflow + Adapters and
Phase 4 Validation.
Phase 0.1 translates public materials into English and prepares public publication.
Phase 1.1 establishes the Corinthos runtime names and private state path.
The same requirements revision, product target, package version and Contract
Kernel architecture apply to Corinthos.

## Six approved Engines

| Engine | Approved responsibility and connections | Implementation status |
| --- | --- | --- |
| Standard Engine | Maintains the five universal, versioned, mandatory Engineering Commandments M1–M5 throughout the lifecycle. | YAML policy and minimal structural validation exist. The Engine is planned. |
| Adapter Manager | Translates the same Standard for Codex, Claude Code, and future integrations. | Separate Codex/Claude provider boundaries, context preparation, capabilities and advisory assistance are implemented. Live verification is recorded separately. |
| Project Manager | Negotiates goals and requirements with the user and publishes the approved Project Contract. | Structured service, guided terminal, durable sessions, exact human approval and bounded PRR intake exist. |
| Workflow Engine | Plans modules, interfaces, technologies, and checkpoints; coordinates execution and change impact analysis. | Exact planning/publication, sequential checkpoint attempts, actual engineering checks, leased recovery and conservative reconciliation are implemented. |
| Validation Engine | Independently audits local and global obligations against approved revisions. | Scope-derived matrices, reviewed executable and inspection procedures, durable runs, immutable results and technical gates are implemented. |
| Report Engine | Consolidates results, decisions, and evidence references while preserving the authority of their sources. | Planned. |

The conceptual order is Standard → Adapter Manager → Project Manager → Workflow →
Validation → Report. The approved connections also give Workflow and Validation
direct access to the same Project Contract revision. The Standard applies across
all levels, and interface contracts connect modules horizontally.

The user approves requirements and binding technology or structural decisions.
Project Manager negotiates global intent. Workflow coordinates corrections.
Validation returns findings to Workflow, and Report references the source records.

## Implemented foundation

The Python package uses the `src/corinthos/` layout. Its CLI displays help and
version information and exposes guided project negotiation.
`corinthos.standard.load_standard(policy_path, schema_path)`
loads the YAML policy with `safe_load` and validates its structure against JSON
Schema, using explicit paths. The policy declares `standard_version: "0.1"` and
contains M1–M5 in `commandments`, each with `required: true` and `description`.

The Commandments require precise instructions, justified and authorized technology
choices, meaningful tests, accurate documentation, and readable, maintainable code
with appropriate efficiency. The structural validator protects their declarative
configuration. Tests, static analysis, and explicit technical review assess the
actual code and evidence. Agent instructions document the applicable rules and
authority.

## Shared Contract Kernel

The Contract Kernel provides one publication API for all six Engines. A schema
check validates wire shape. Publication then checks exact references, scoped
obligations, provenance and revision lineage in a SQLite transaction. Published
documents remain immutable as active pointers advance. Progress and attempts
belong to separate operational state.

Private state is stored at `.corinthos/state.db`. Evidence references use verified
digests of local artifacts. SQLite, artifacts and Git have separate transaction
boundaries. Project Manager sessions and approvals share the versioned database.
Workflow execution and independent Validation share the versioned database.
Their drafts, claims, observations and recovery retain separate operational
identities.
See [storage and recovery](storage.md) and the [design record](contract-kernel-design.md).

## Project Manager boundary

The [Project Manager service](project-manager.md) owns product-level negotiation,
structured suggestions and binding demands, preliminary checks, exact review and
approved Project publication. A thin terminal adapter collects ordinary-language
answers and structured choices. An optional assistance callable supplies advisory
text for future integration. Structural checks expose demonstrable omissions and
inconsistent references while natural-language consistency and technical
feasibility require explicit human review.

Operational sessions retain accepted turns, draft versions, proposal decisions,
questions, evidence records and approval linkage. The local terminal bridge binds
one explicit foreground action to a complete frozen candidate and the Kernel's
trusted callback. Publication approves a specification. Workflow planning consumes
its exact immutable revision. Validation reads it directly for independent audit.

A published Project Revision Request can open a bounded session from the active
approved Project base. The owner keeps, defers or approves a change while
unaffected obligations retain their IDs and content. Workflow retains modular
decomposition, technology comparisons and downstream impact propagation.

## Workflow planning and adapter boundaries

The [planning service](workflow-planning.md) consumes the exact active approved
Project revision. It negotiates module responsibilities and source obligations,
evaluated technologies, provider-owned interfaces, exact consumer links,
mandatory verification specifications, checkpoint dependencies and optional
milestone architecture. One complete frozen set collects applicable human
authorizations. Per-document receipts then support dependency-ordered Kernel
publication. Already published unchanged decisions retain their exact references.
A recorded bounded mandate can support a dependency-only Workflow replan while
preserving all other obligations and DELEGATED provenance.

The [Adapter Manager](adapters.md) prepares equivalent mandatory Standard and
exact task context for separate Codex and Claude implementations. Process results
are observable data with explicit capability and telemetry limits. Advisory
assistance can inform a draft through the existing service boundary, while the
human and Kernel retain approval authority. A process success report does not
complete a project checkpoint.

The initial A–D stop is historical. The authorized E–J continuation adds the
[execution service](workflow-execution.md), durable leases and attempts, actual
command/artifact checks, explicit preliminary review and conservative impact
reconciliation. A bounded structural conflict can reach the existing Project
Manager through a real published PRR. Unchanged work retains its original
evidence identity through explicit inheritance. Workflow requests exact scoped
audits and consumes their admissible results.

## Independent Validation boundary

The [Validation service](validation.md) derives applicable requirements and
M1–M5 independently of the implementer's selected checks. The Kernel enforces
scope and mandatory coverage. Separate evaluator inspection establishes method
adequacy. The runner observes a verified candidate copy through bound procedures,
retains private evidence and derives an immutable result and scoped technical
gate. Workflow checks that evidence before affected progression. Changes to
product decisions and formal human acceptance retain their owner authority.
Report and general product evolution remain later work.

## Related documentation

This public overview is versioned with the code and provides the context needed to
understand the foundation. Product decisions retain their provenance in internal
planning; contributors can use these local documents without private access.

- [Engineering instructions](../AGENTS.md)
- [Contract catalogue](contracts.md)
- [Validation methods, evidence and gates](validation.md)
- [Workflows and authority](workflows.md)
- [Implementation plan](implementation-plan.md)
- [Practical decisions and historical verification](decisions.md)

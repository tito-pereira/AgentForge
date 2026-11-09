# Operational architecture

Documentation baseline dated November 8, 2026. Product requirements revision v0.2
targets Core v0.1. Package version `0.1.0` includes the Phase 0 foundation and
Phase 1 Contract Kernel.
Phase 0.1 translates public materials into English and prepares public publication.
The active product identity is Nukytera. Phase 0.3 changes naming while retaining
the same requirements revision, product target, package version, and architecture.

## Six approved Engines

| Engine | Approved responsibility and connections | Phase 0 implementation status |
| --- | --- | --- |
| Standard Engine | Maintains the five universal, versioned, mandatory Engineering Commandments M1–M5 throughout the lifecycle. | YAML policy and minimal structural validation exist. The Engine is planned. |
| Adapter Manager | Translates the same Standard for Codex, Claude Code, and future integrations. | AGENTS.md and CLAUDE.md provide instructions. The Manager and functional adapters are planned. |
| Project Manager | Negotiates goals and requirements with the user and publishes the approved Project Contract. | Planned. |
| Workflow Engine | Plans modules, interfaces, technologies, and checkpoints; coordinates execution and change impact analysis. | Planned. |
| Validation Engine | Independently audits local and global obligations against approved revisions. | Planned. |
| Report Engine | Consolidates results, decisions, and evidence references while preserving the authority of their sources. | Planned. |

The conceptual order is Standard → Adapter Manager → Project Manager → Workflow →
Validation → Report. The approved connections also give Workflow and Validation
direct access to the same Project Contract revision. The Standard applies across
all levels, and interface contracts connect modules horizontally.

The user approves requirements and binding technology or structural decisions.
Project Manager negotiates global intent. Workflow coordinates corrections.
Validation returns findings to Workflow, and Report references the source records.

## Implemented foundation

The Python package uses the `src/nukytera/` layout. Its CLI displays help and
version information. `nukytera.standard.load_standard(policy_path, schema_path)`
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

Private state is stored at `.nukytera/state.db`. Evidence references use verified
digests of local artifacts. SQLite, artifacts and Git have separate transaction
boundaries. Engine-specific recovery and execution state belong to later phases.
See [storage and recovery](storage.md) and the [design record](contract-kernel-design.md).

## Related documentation

This public overview is versioned with the code and provides the context needed to
understand the foundation. Product decisions retain their provenance in internal
planning; contributors can use these local documents without private access.

- [Engineering instructions](../AGENTS.md)
- [Contract catalogue](contracts.md)
- [Workflows and authority](workflows.md)
- [Implementation plan](implementation-plan.md)
- [Practical decisions and historical verification](decisions.md)

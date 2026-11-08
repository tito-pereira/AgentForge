# Operational architecture

Documentation baseline dated November 8, 2026. Product requirements revision v0.2
targets Core v0.1. Scaffold version `0.1.0` implements the Phase 0 foundation.
Phase 0.1 translates public materials into English and prepares public publication.

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

The Python package uses the `src/agentforge/` layout. Its CLI displays help and
version information. `agentforge.standard.load_standard(policy_path, schema_path)`
loads the YAML policy with `safe_load` and validates its structure against JSON
Schema, using explicit paths. The policy declares `standard_version: "0.1"` and
contains M1–M5 in `commandments`, each with `required: true` and `description`.

The Commandments require precise instructions, justified and authorized technology
choices, meaningful tests, accurate documentation, and readable, maintainable code
with appropriate efficiency. The structural validator protects their declarative
configuration. Tests, static analysis, and explicit technical review assess the
actual code and evidence. Agent instructions document the applicable rules and
authority.

## Planned persistence and recovery

Phase 1 introduces the Contract Kernel, shared infrastructure for the six Engines.
Published contracts have immutable revisions. Progress and attempts belong to
separate operational state. Local SQLite, Git references, and local artifacts will
support history, integrity, and recovery.

`.agentforge/` is reserved and excluded from Git. Persistence, transactions,
migrations, and recovery belong to later phases. Their coordination must account
for SQLite and Git having separate transaction boundaries.

## Related documentation

This public overview is versioned with the code and provides the context needed to
understand the foundation. Product decisions retain their provenance in internal
planning; contributors can use these local documents without private access.

- [Engineering instructions](../AGENTS.md)
- [Contract catalogue](contracts.md)
- [Workflows and authority](workflows.md)
- [Implementation plan](implementation-plan.md)
- [Practical decisions and historical verification](decisions.md)

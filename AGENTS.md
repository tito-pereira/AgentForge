# Agent instructions

This repository contains the Corinthos Core foundation, Contract Kernel,
Project Manager, Workflow, adapters, Validation and Report, package version `0.1.0`.
The product target is Core v0.1, based on product specification revision v0.2.
Phase 0 established the foundation. Phase 0.1 covers the English-language migration,
publication review, verification, and first public GitHub publication when authorized.
Phase 0.2 verifies clean virtual environments on Windows and Linux and implements
the project owner's approved MPL-2.0 license on a reviewed branch.
Phase 1.1 migrates the package and CLI to `corinthos`, the distribution to
`corinthos-core`, and private state to `.corinthos/`. Preserve version
`0.1.0`, the five Commandments, six Engines, eight contract types, and MPL-2.0.

## Five mandatory Engineering Commandments

- **M1 — Precise instructions.** Define the objective, scope, responsibilities,
  interfaces, deliverables, and verifiable acceptance criteria before changing code.
- **M2 — Justified technologies.** Explain choices and respect approved decisions.
  Binding technology and structural changes belong to the project owner.
- **M3 — Meaningful testing.** Verify real behavior, invalid inputs, edge cases,
  integration, regressions, and security according to the impact of the change.
- **M4 — Usable documentation.** Keep instructions, interfaces, decisions, and
  limitations consistent with the code and commands actually verified.
- **M5 — Readable, efficient code.** Use clear names, bounded responsibilities,
  modularity, and the simplest solution that fully meets the requirements.

All five Commandments are universal and mandatory. Normal configuration must reject
the absence or deactivation of any of them.

## Human authority and references

The project owner decides vision, priorities, requirements, binding technology and
structural choices, and human acceptance. Planning and review assistants support
architecture, checkpoint preparation, and technical review. Coding agents implement
code, tests, and documentation within the authorized scope.

Approved product decisions govern implementation. Git versions code, tests, and
operational documentation. The public engineering snapshot is self-contained in
[architecture](docs/architecture.md), [contracts](docs/contracts.md),
[workflows](docs/workflows.md), [implementation plan](docs/implementation-plan.md),
and [decisions](docs/decisions.md). Record material discrepancies before changing
requirements. Private planning references must stay outside published artifacts.

## Language and scope

Use English for all repository artifacts, source comments and docstrings,
documentation, user-facing messages, test descriptions and output labels, commit
messages, and public GitHub collaboration. This rule applies to every current and
future implementation phase, subphase, checkpoint, engineering report, and related
implementation communication. Private product planning may remain in the project
owner's preferred language.

Inspect files, applicable instructions, and Git status before editing. Preserve
existing work and operate only in the authorized directory. Follow the
`src/corinthos/` layout and reuse the current implementation where appropriate.

Phase 1 implements eight contract schemas, exact references, authority checks,
immutable revisions and local SQLite persistence as shared infrastructure. Use
the documented [kernel API](docs/contracts.md) and [storage rules](docs/storage.md).
Verify human and delegated approval through the trusted caller boundary. Preserve
historical references when an active revision changes. Phase 2 implements the
[Project Manager](docs/project-manager.md) with a thin terminal adapter, persistent
human-led negotiation and exact local approval. Keep session/proposal history in
operational SQLite state and published revisions behind the Contract Kernel API.
The approval bridge opens the foreground OS terminal and verifies its exact
random challenge against a frozen candidate. Piped input, synthetic test consent,
assistant text and a stored claim cannot supply production approval.

Maintain the distinction between structural checks, supplied feasibility evidence
and independent product validation. Escape untrusted controls in terminal reviews
and retain all fields and stable IDs. Revisions require current exact bases,
explicit human approval and preservation of unaffected obligations. Verify
restart, stale sessions, receipt invalidation and failed publication recovery.
Phase 3.0 is authorized through construction checkpoints A–J. Use the
[Workflow planning guide](docs/workflow-planning.md) for the separate planning
service, exact final-set review and publication. Preserve provider-owned
interfaces, exact consumer revisions, blocking obligation coverage and M1–M5.
Use real per-document HUMAN receipts for reserved choices. DELEGATED publication
requires a verified recorded mandate and its exact bounds. An existing mandate
ID is a reference to authority that must be checked, never consent by itself.

Keep Adapter Manager provider capabilities and live evidence honest. Follow the
[adapter guide](docs/adapters.md) and preserve equivalent mandatory Standard
instructions. An agent result carries no human approval or independent Validation
authority. The owner's continuation authorizes scheduler/execution, durable recovery,
impact reconciliation, the selected real pilot and release/PR checkpoints E–J.
Pilot contract and technical-plan approval require the actual foreground
terminal bridge. The delivered pilot retains its recorded approval lineage.

Phase 4 uses the [Validation guide](docs/validation.md) to derive obligations
directly from approved sources and the Standard. Keep criterion-specific
method review, candidate evaluation and Workflow implementation separate.
Publish exact VC/VRC records through the Kernel using the trusted Validation
context. A result records admissible evidence and a calculated gate.
Human approval, product acceptance and experimental-build promotion retain
their separate boundaries.

Phase 5 follows the [Report guide](docs/report.md). Capture coherent source
cutoffs, preserve exact candidate/result identities and publish immutable ERCs
through REPORT authority. Keep historical facts separate from current proof
eligibility. Ordinary reports remain NOT_REVIEWED. Never infer delivery or human
acceptance from a technical gate. Use safe source projections, private generation
manifests and recoverable exports, preserving all source contracts and events.

Treat `urn:nukytera:contracts:1.0:*`, `nukytera-standard` and SQLite application
ID `0x4E554B59` as durable identifiers. Keep the original document bytes,
approval receipts, evidence hashes and event order when migrating state.
Follow the [storage migration procedure](docs/storage.md#migrating-existing-project-state)
for each authorized project root.

Phase 6 follows the [lifecycle guide](docs/evolution.md) and
[build guide](docs/builds.md). Preserve immutable versions and observation origins,
verified complete build identity, non-circular checkpoint/readiness/Validation
stages, one project tracker/active build and inspected session pins. Keep genuine
human consent distinct from operator and synthetic observations. Missing mandatory
native proof remains open; use an incomplete/draft PR until verified.

The initial validator is
`corinthos.standard.load_standard(policy_path, schema_path)`. It accepts explicit
paths to `policies/standard.yaml` and `schemas/standard.schema.json`. These are
checkout files. Practical implementation choices are recorded in
[docs/decisions.md](docs/decisions.md).

## Verification and delivery

Use a Python 3.12 virtual environment and run the relevant commands. The
[README](README.md) provides direct executable paths for PowerShell and POSIX.

```text
python -m pip install -e ".[dev]"
python -m pip check
python -m corinthos --help
python -m corinthos --version
python -m pytest
python -m ruff check .
python -m ruff format --check .
python examples/contract_kernel.py
python -m corinthos project --help
python -m corinthos workflow --help
python -m corinthos validation --help
python -m corinthos report --help
```

Verify imports and CLI behavior, valid Standard loading, and rejection of invalid,
incomplete, or disabled Commandments. Review packaging, diffs, documentation, and Git
exclusions. Automated tests and explicit technical review provide preliminary
engineering verification. Formal Validation derives separate scope-specific
results and gates.

Report actual commands, results, limitations, and evidence for M1–M5. Distinguish
local execution from observed remote CI. Mark blocked or unexecuted checks as
**NOT VERIFIED**, with the cause. Technical review must evaluate evidence
independently of the implementing agent's assertions.

Protect credentials, logs, private data, and `.corinthos/`. Avoid destructive
operations. Remote creation, pushes, publication, and external permission changes
require authorization for the specific action. Before a public commit or push,
inspect the complete staged snapshot, secret/private-data scan results, author
identity, target ownership, repository visibility, and licensing status. Preserve
existing history and use normal pushes. License selection belongs to the project
owner, who has selected the Mozilla Public License 2.0 (`MPL-2.0`).

Preserve the complete, unmodified [LICENSE](LICENSE), appropriate source notices or
SPDX headers, and accurate packaging metadata. Respect existing copyright and
third-party notices, and never invent copyright-holder names or ownership
transfers. Record license-related decisions and keep licensing guidance consistent
with the official license. Keep each phase reviewable on its authorized branch.
An implementation order can authorize a normal push, CI and a human-reviewable PR.
Merging into the default branch requires separate authorization.
Preserve the historical `phase-1-baseline` tag and all existing commit history.

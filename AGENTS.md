# Agent instructions

This repository contains the AgentForge Core foundation, package version `0.1.0`.
The product target is Core v0.1, based on product specification revision v0.2.
Phase 0 established the foundation. Phase 0.1 covers the English-language migration,
publication review, verification, and first public GitHub publication when authorized.
Phase 0.2 verifies clean virtual environments on Windows and Linux and implements
the project owner's approved MPL-2.0 license on a reviewed branch.

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
`src/agentforge/` layout and reuse the current implementation where appropriate.

The foundation includes packaging, CLI `--help`/`--version`, a Standard policy with
minimal structural validation, tests, lint, CI, and documentation. The six Engines,
eight contract schemas, and operational persistence belong to later phases.
Starting Phase 1 requires a subsequent instruction from the project owner.

The initial validator is
`agentforge.standard.load_standard(policy_path, schema_path)`. It accepts explicit
paths to `policies/standard.yaml` and `schemas/standard.schema.json`. These are
checkout files. Practical implementation choices are recorded in
[docs/decisions.md](docs/decisions.md).

## Verification and delivery

Use a Python 3.12 virtual environment and run the relevant commands. The
[README](README.md) provides direct executable paths for PowerShell and POSIX.

```text
python -m pip install -e ".[dev]"
python -m pip check
python -m agentforge --help
python -m agentforge --version
python -m pytest
python -m ruff check .
python -m ruff format --check .
```

Verify imports and CLI behavior, valid Standard loading, and rejection of invalid,
incomplete, or disabled Commandments. Review packaging, diffs, documentation, and Git
exclusions. Automated tests and explicit technical review provide the initial
verification while the Validation Engine is planned.

Report actual commands, results, limitations, and evidence for M1–M5. Distinguish
local execution from observed remote CI. Mark blocked or unexecuted checks as
**NOT VERIFIED**, with the cause. Technical review must evaluate evidence
independently of the implementing agent's assertions.

Protect credentials, logs, private data, and `.agentforge/`. Avoid destructive
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
with the official license. Phase 0.2 changes belong on a reviewed feature branch
or pull request. Changing the default branch requires separate authorization.

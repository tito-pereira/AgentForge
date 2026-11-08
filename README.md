# AgentForge Core

AgentForge is a local framework for directing programming agents through clear
instructions, explicit human decisions, versioned contracts, and independent
verification. It aims to preserve engineering standards when working with
different agents, initially Codex and Claude Code.

The current implementation is the **Phase 0 foundation**, with package version
`0.1.0`. Phase 0.1 prepares the repository for English-language public development.
The product target remains Core v0.1, based on product specification revision v0.2.

## Current capabilities

- An installable Python package and CLI with `--help` and `--version`.
- A declarative YAML Standard containing five mandatory Engineering Commandments.
- JSON Schema validation that rejects missing or disabled Commandments and invalid
  policy structure, using safe YAML loading.
- Positive and negative tests, Ruff checks, and a GitHub Actions workflow.
- Agent instructions and self-contained engineering documentation.

The six Engines and eight contract schemas are planned. Operational SQLite
persistence, agent execution adapters, project negotiation, workflow execution,
independent validation runners, reports, and experimental builds are future work.
The CLI currently displays help and version information. The future AgentForge
Bench will evaluate human direction of programming agents after the Core is ready.

## Five Engineering Commandments

1. **M1 — Precise instructions.** Define bounded responsibilities, deliverables,
   interfaces, and verifiable acceptance criteria.
2. **M2 — Justified technologies.** Explain technology choices and preserve human
   authority over binding decisions.
3. **M3 — Meaningful testing.** Verify behavior, failure cases, integration,
   regressions, and security in proportion to the change.
4. **M4 — Usable documentation.** Keep setup, interfaces, decisions, and limitations
   accurate and reproducible.
5. **M5 — Readable, maintainable code.** Prefer clear names, modularity, simplicity,
   and appropriate efficiency.

All five are mandatory. The initial policy rejects their removal or deactivation.
Repository artifacts and public collaboration use English.

## Prerequisites

Use Python 3.12 or later with pip and venv, plus Git. Python 3.12 is the current
verification and CI baseline. Run the following commands from the repository
root. Environment activation is optional because each command names its interpreter.

### Windows PowerShell

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m agentforge --help
.\.venv\Scripts\agentforge.exe --version
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
```

If Python is supplied by a local Codex desktop runtime and the `py` launcher cannot
find it, the following optional command can create the environment on installations
with this runtime layout. A regular Python installation is the portable prerequisite.

```powershell
$PythonExe = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
& $PythonExe -m venv .venv
```

Use that command in place of `py -3.12 -m venv .venv` in a clean checkout. A virtual
environment created from an application runtime may need recreation after that
runtime moves during an update.

### POSIX shell

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/python -m pip check
.venv/bin/python -m agentforge --help
.venv/bin/agentforge --version
.venv/bin/python -m pytest
.venv/bin/python -m ruff check .
.venv/bin/python -m ruff format --check .
```

Local validation results and their environment are recorded in
[engineering decisions](docs/decisions.md). The workflow targets Python 3.12 on
Linux and Windows. Remote CI and POSIX execution require their own observed results.

## Standard validation

`policies/standard.yaml` declares M1–M5. `schemas/standard.schema.json` requires
exactly those identifiers, a Boolean `required: true` flag, and a nonblank
description for each one. The loader uses safe YAML parsing and JSON Schema
2020-12 validation. It propagates file, syntax, and validation errors to the caller.

From the repository root in PowerShell.

```powershell
.\.venv\Scripts\python.exe -c "from agentforge.standard import load_standard; policy = load_standard('policies/standard.yaml', 'schemas/standard.schema.json'); print(', '.join(policy['commandments']))"
```

For POSIX, use `.venv/bin/python` as the executable. The API accepts explicit
policy and schema paths. These files belong to the checkout and must accompany
their use. Tests exercise valid policy loading, missing and disabled Commandments,
invalid flags and structures, malformed YAML, and unsafe YAML constructors.

## Repository layout

| Path | Purpose |
| --- | --- |
| `src/agentforge/` | Package version, minimal CLI, and structural Standard loader. |
| `policies/` | Versioned Standard policy. |
| `schemas/` | Structural schema for the initial Standard. |
| `tests/` | CLI, package metadata, and positive/negative policy checks. |
| `AGENTS.md`, `CLAUDE.md` | Equivalent agent obligations and human authority. |
| `docs/` | Architecture, contract catalog, workflows, roadmap, and decisions. |
| `.github/workflows/ci.yml` | Installation, CLI, lint, formatting, and test workflow. |

`.agentforge/` is reserved for future private project state. `.gitignore` protects
local environments, private state, databases, caches, and common secret files.
Review staged content before committing.

## Development roadmap

| Phase | Deliverable |
| --- | --- |
| 0 — Foundation | Package, CLI, initial Standard, instructions, tests, CI, and documentation. |
| 1 — Contract Kernel | Eight contract schemas, immutable revisions, integrity checks, and shared persistence. |
| 2 — Project Manager | Requirements negotiation and explicitly approved Project Contracts. |
| 3 — Workflow + Adapters | Modular planning, checkpoints, and agent execution. |
| 4 — Validation Engine | Independent obligation coverage, evidence, results, and gates. |
| 5 — Report Engine | Traceable reports, decisions, and evidence history. |
| 6 — Evolution + Hardening | Product evolution, isolated builds, feedback, recovery, and robustness. |

These are construction phases. Each requires bounded tasks, tests, documentation,
and review. Phase 1 starts with a subsequent instruction from the project owner.

## Engineering documentation

- [Architecture and six Engines](docs/architecture.md)
- [Eight contract types](docs/contracts.md)
- [Workflows, gates, and authority](docs/workflows.md)
- [Implementation plan and acceptance criteria](docs/implementation-plan.md)
- [Decisions, verification history, and limits](docs/decisions.md)

These documents provide the public engineering context without requiring access
to private planning systems. The project owner retains authority over product
requirements, binding technology and structural decisions, and human acceptance.

## License

License selection is pending. A license has not yet been granted for this repository.

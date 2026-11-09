# Nukytera Core

Nukytera is a local framework for directing programming agents through clear
instructions, explicit human decisions, versioned contracts, and independent
verification. It aims to preserve engineering standards when working with
different agents, initially Codex and Claude Code.

The implementation includes the **Phase 0 foundation** and the **Phase 1 Contract
Kernel**, with package version `0.1.0`. Phase 0 established English-language public
development, clean Windows and Linux environments, MPL 2.0 and the Nukytera identity.
The product target remains Core v0.1, based on product specification revision v0.2.

The brand is **Nukytera**, the Python distribution is `nukytera-core`, and the
import package and CLI command are `nukytera`. Earlier names and execution evidence
are preserved as history in [decisions](docs/decisions.md).

## Current capabilities

- An installable Python package and CLI with `--help` and `--version`.
- A declarative YAML Standard containing five mandatory Engineering Commandments.
- JSON Schema validation that rejects missing or disabled Commandments and invalid
  policy structure, using safe YAML loading.
- Eight packaged contract schemas, exact references, publication authority checks,
  immutable revisions, and transactional local SQLite storage.
- Positive and negative tests, Ruff checks, and a GitHub Actions workflow.
- Agent instructions and self-contained engineering documentation.

The six Engines will use the same kernel. Project negotiation, execution adapters,
workflow scheduling, independent validation runners, report generation and
experimental builds belong to subsequent phases. The CLI displays help and version.

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

Use a normal Python 3.12 installation with pip and venv, plus Git. Run the following
commands from the root of a fresh checkout. Environment activation is optional
because each command names its interpreter.

### Windows PowerShell

```powershell
py -3.12 --version
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -c "from pathlib import Path; import sys; print(sys.executable); assert sys.prefix != sys.base_prefix; assert Path(sys.prefix).resolve() == Path('.venv').resolve(); assert Path(sys.executable).absolute().is_relative_to(Path('.venv').resolve())"
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m nukytera --help
.\.venv\Scripts\nukytera.exe --version
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
```

If the `py` launcher is unavailable, use a normal Python 3.12 executable to create
the environment, after checking its version. For example, if that installation is
available as `python`, the equivalent command is `python -m venv .venv`.

Optional PowerShell activation can be checked separately.

```powershell
.\.venv\Scripts\Activate.ps1
python -c "from pathlib import Path; import sys; print(sys.executable); assert Path(sys.prefix).resolve() == Path('.venv').resolve()"
deactivate
```

If the current PowerShell execution policy blocks activation, keep using the
explicit `.venv` executable paths above. Installation and verification do not
require changing the machine's execution policy.

### POSIX shell

```sh
python3.12 --version
python3.12 -m venv .venv
.venv/bin/python -c "from pathlib import Path; import sys; print(sys.executable); assert sys.prefix != sys.base_prefix; assert Path(sys.prefix).resolve() == Path('.venv').resolve(); assert Path(sys.executable).absolute().is_relative_to(Path('.venv').resolve())"
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/python -m pip check
.venv/bin/python -m nukytera --help
.venv/bin/nukytera --version
.venv/bin/python -m pytest
.venv/bin/python -m ruff check .
.venv/bin/python -m ruff format --check .
```

Optional activation in Bash.

```bash
source .venv/bin/activate
python -c "from pathlib import Path; import sys; print(sys.executable); assert Path(sys.prefix).resolve() == Path('.venv').resolve()"
deactivate
```

In POSIX `sh`, use `. .venv/bin/activate` instead of `source`. If a distribution
packages venv or ensurepip separately, install its Python 3.12 venv support before
creating the environment. Keep installation inside `.venv`.

Local validation results and their environment are recorded in
[engineering decisions](docs/decisions.md). The workflow targets Python 3.12 on
Linux and Windows. Clean-venv verification must identify the exact commit and
environment used. Prior CI results from the runner's global Python do not establish
the clean-venv result.

## Standard validation

`policies/standard.yaml` declares M1–M5. `schemas/standard.schema.json` requires
exactly those identifiers, a Boolean `required: true` flag, and a nonblank
description for each one. The loader uses safe YAML parsing and JSON Schema
2020-12 validation. It propagates file, syntax, and validation errors to the caller.

From the repository root in PowerShell.

```powershell
.\.venv\Scripts\python.exe -c "from nukytera.standard import load_standard; policy = load_standard('policies/standard.yaml', 'schemas/standard.schema.json'); print(', '.join(policy['commandments']))"
```

For POSIX, use `.venv/bin/python` as the executable. The API accepts explicit
policy and schema paths. These files belong to the checkout and must accompany
their use. Tests exercise valid policy loading, missing and disabled Commandments,
invalid flags and structures, malformed YAML, and unsafe YAML constructors.

## Contract Kernel example

After installation, run `examples/contract_kernel.py` with the venv Python.

```powershell
.\.venv\Scripts\python.exe examples/contract_kernel.py
```

```sh
.venv/bin/python examples/contract_kernel.py
```

The example loads eight JSON documents, publishes them in dependency order into a
temporary store, reopens it, resolves a historical revision and rejects a bad
publication. Its synthetic approval receipts and interrupted validation result
exercise the API without certifying a product. See the
[contract API](docs/contracts.md) and [storage guide](docs/storage.md).

## Repository layout

| Path | Purpose |
| --- | --- |
| `src/nukytera/` | Package version, minimal CLI, Standard loader and Contract Kernel. |
| `src/nukytera/contracts/schemas/` | Eight executable schemas and shared definitions, installed with the package. |
| `examples/` | Eight sample contracts and the executable kernel demonstration. |
| `policies/` | Versioned Standard policy. |
| `schemas/` | Structural schema for the initial Standard. |
| `tests/` | CLI, package, policy, contract integrity, authority and persistence checks. |
| `AGENTS.md`, `CLAUDE.md` | Equivalent agent obligations and human authority. |
| `docs/` | Architecture, contract catalog, workflows, roadmap, and decisions. |
| `.github/workflows/ci.yml` | Installation, CLI, lint, formatting, and test workflow. |

`.nukytera/` holds private project state. `.gitignore` protects
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
and review. Phase 1 uses a reviewed pull request. The project owner authorizes
integration and the start of Phase 2 separately.

## Engineering documentation

- [Architecture and six Engines](docs/architecture.md)
- [Eight contract types](docs/contracts.md)
- [SQLite storage and recovery](docs/storage.md)
- [Workflows, gates, and authority](docs/workflows.md)
- [Implementation plan and acceptance criteria](docs/implementation-plan.md)
- [Decisions, verification history, and limits](docs/decisions.md)

These documents provide the public engineering context without requiring access
to private planning systems. The project owner retains authority over product
requirements, binding technology and structural decisions, and human acceptance.

## License

Nukytera is licensed under the [Mozilla Public License 2.0](LICENSE), with SPDX
identifier `MPL-2.0`. Its file-level copyleft requires distributed covered source
files, including modifications, to remain under MPL 2.0. Commercial use and
distribution are permitted subject to the license conditions, including applicable
source-availability and notice requirements. Separate files in a larger work may
use other licenses. See the complete license and
[Mozilla's FAQ](https://www.mozilla.org/en-US/MPL/2.0/FAQ/) for the governing terms
and guidance.

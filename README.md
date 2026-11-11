# Corinthos Core

Corinthos is a local framework for directing programming agents through clear
instructions, explicit human decisions, versioned contracts, and independent
verification. It aims to preserve engineering standards when working with
different agents, initially Codex and Claude Code.

The implementation includes the **Phase 0 foundation**, **Phase 1 Contract
Kernel**, **Phase 2 Project Manager**, **Phase 3 Workflow + Adapters**,
**Phase 4 Validation Engine** and **Phase 5 Report Engine**, with package version `0.1.0`.
Phase 0 established English-language public
development, clean Windows and Linux environments and MPL 2.0.
The product target remains Core v0.1, based on product specification revision v0.2.

The brand is **Corinthos**, the Python distribution is `corinthos-core`, and
the sole supported import prefix and CLI command are `corinthos`. Phase 1.1
changes these identifiers at version `0.1.0`. Update imports and command
invocations in existing integrations and install into a fresh venv. The
Contract Kernel keeps its behavior and durable wire identities.
Earlier names and execution evidence are recorded in [decisions](docs/decisions.md).

## Current capabilities

- An installable Python package and CLI with `--help` and `--version`.
- A declarative YAML Standard containing five mandatory Engineering Commandments.
- JSON Schema validation that rejects missing or disabled Commandments and invalid
  policy structure, using safe YAML loading.
- Eight packaged contract schemas, exact references, publication authority checks,
  immutable revisions, and transactional local SQLite storage.
- Positive and negative tests, Ruff checks, and a GitHub Actions workflow.
- Agent instructions and self-contained engineering documentation.
- Guided project negotiation, persistent sessions, classified suggestions and
  requirements, complete reviews, and explicit local terminal approval.
- Bounded intake of published Project Revision Requests and immutable approved
  Project revisions through the existing Kernel.
- Guided technology and module planning, exact provider/consumer interfaces,
  verification specifications, checkpoints and optional milestone plans.
- Complete TDC/Module/Workflow review and publication with per-document human
  receipts and bounded dependency-only delegation.
- Sequential checkpoint attempts, actual command/artifact checks, explicit
  preliminary technical review, fenced workspace leases and inspected recovery.
- Conservative revision reconciliation and bounded structural requests routed
  through the real Kernel and Project Manager.
- Independent scoped Validation planning, exact reviewed procedures, durable
  evidence-backed runs and formal gate consumption.
- Consistent source snapshots, immutable nine-section reports, revision history,
  comparisons and private canonical JSON/Markdown export through an installed CLI.

The six Engines use the same kernel. Project Manager provides human-led structured
negotiation. Adapter Manager has separate Codex and Claude provider boundaries.
Workflow supports engineering planning, sequential execution and inspected
recovery. Validation derives independent plans and publishes scoped results
for Workflow to consume. Report consolidates exact source facts and history.
Experimental-build promotion remains subsequent work.
Natural-language consistency and technical feasibility require human review.

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
.\.venv\Scripts\python.exe -m corinthos --help
.\.venv\Scripts\corinthos.exe --version
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
.venv/bin/python -m corinthos --help
.venv/bin/corinthos --version
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

## Create your first project specification

After installation, run this from the checkout in PowerShell.

```powershell
.\.venv\Scripts\corinthos.exe project --root . start
```

For POSIX, run `.venv/bin/corinthos project --root . start`. You can select another
existing project directory with `--root`. Corinthos saves accepted answers
privately beneath that directory.

Describe your idea in your own words, for example, "Build a local greeting for
a supplied name." In the numbered menu, add included scope, a requirement and
its observable acceptance criterion, then a project success criterion. For
example, the requirement can be "Print a greeting for the supplied name" and its
criterion "Input Ada produces Hello, Ada."

Use the menu to record constraints, exclusions, assumptions and risks. Classify
each proposal as a negotiable **SUGGESTION** or binding **REQUIREMENT**, choose its
related numbered obligations, and record your decision and reason. **Show
complete draft** displays missing information and all saved choices. **Review
complete contract** shows every contract field, stable ID, review digest and
any previous revision differences. **Save for later and leave** preserves the
session. Resume it through the same venv executable.

```powershell
.\.venv\Scripts\corinthos.exe project --root . resume
```

When ready, choose **Approve at the local terminal**. Read the complete fresh
review and type its exact random `APPROVE` challenge to publish that specification.
Other answers defer publication. Approval requires a foreground local terminal.
Piped scripts can prepare drafts but cannot provide production approval. The
published Project Contract describes what should be built. Workflow coordinates
execution and Validation independently assesses the candidate. Feasibility and
natural-language consistency remain explicit human review responsibilities.

The [Project Manager guide](docs/project-manager.md) covers every command,
negotiation states, exact approval, recovery, revision requests and the Python API.
Use `corinthos project --help` to inspect the command list.

## Plan the approved project

After publishing the Project specification, copy its logical contract ID from
the published reference and substitute it below.

```powershell
.\.venv\Scripts\corinthos.exe workflow --root . plan YOUR_PROJECT_CONTRACT_ID
```

For POSIX, use `.venv/bin/corinthos workflow --root . plan YOUR_PROJECT_CONTRACT_ID`.
Choose the exact approved revision. The numbered editor collects module
responsibilities, assigned requirements/constraints, evaluated technology options,
exact interfaces, verification requirements, checkpoints and optional milestones.
Use **Review complete publication set** to inspect every TDC, Module and Workflow
candidate, its digest, source references and previous differences. The foreground
terminal authorizes the exact set once before dependency-ordered publication.
Existing bounded mandates may authorize dependency-only replans after their
scope, actor and freshness are verified.

**Save for later and leave** preserves accepted planning choices. Resume with
`corinthos workflow --root . resume` through the same venv executable. These are
engineering plans. The authorized E–J continuation adds actual execution,
recovery, a fixed local task-manager pilot and verifiable release evidence.

The [Workflow planning guide](docs/workflow-planning.md) documents the full
journey, commands, APIs, authority and partial-publication boundaries. The
[Adapter Manager guide](docs/adapters.md) records provider capabilities and
separate live-verification evidence.

## Execute and inspect an approved plan

Configure each approved checkpoint's actual verification commands, deliverable
files and permitted source paths through guided questions. Supply the existing
Standard policy/schema when working outside the Corinthos checkout.

```text
corinthos workflow --root PROJECT_ROOT configure WORKFLOW_CONTRACT_ID --policy STANDARD_YAML --policy-schema STANDARD_SCHEMA
corinthos workflow --root PROJECT_ROOT executions
corinthos workflow --root PROJECT_ROOT status EXECUTION_ID
corinthos workflow --root PROJECT_ROOT execute EXECUTION_ID --provider codex --policy STANDARD_YAML --policy-schema STANDARD_SCHEMA
```

Execution requests one eligible checkpoint, records the real provider attempt,
runs actual checks and asks for preliminary technical review of the exact
artifact. A failed or interrupted attempt preserves its evidence. Use the
explicit `recover` journey to inspect effects before retrying or verifying
existing files. Changed active sources require approved-plan reconciliation.
Published independent gates remain mandatory when applicable.

The [execution and reconciliation guide](docs/workflow-execution.md) covers
native Windows executable selection, commands, leases, review, recovery,
preserved evidence and bounded Project Revision Requests.

## Independently validate a candidate

Derive a scoped Verification Matrix from the approved Project, Standard and
applicable source contracts. Inspect the draft, bind and review each method in
the foreground terminal, then publish and run the exact plan.

```text
corinthos validation --root PROJECT_ROOT plan PROJECT_ID --scope PRODUCT --policy STANDARD_YAML --policy-schema STANDARD_SCHEMA
corinthos validation --root PROJECT_ROOT show-draft DRAFT_ID
corinthos validation --root PROJECT_ROOT bind DRAFT_ID CHECK_ID --evaluator EVALUATOR_ID
corinthos validation --root PROJECT_ROOT publish DRAFT_ID --evaluator EVALUATOR_ID
corinthos validation --root PROJECT_ROOT run PLAN_ID --candidate CANDIDATE_DIR --evaluator EVALUATOR_ID
```

The [Validation guide](docs/validation.md) covers evidence, evaluator separation,
formal gate expectations, inspection, recovery and revalidation.

## Source-backed reports

Use an existing authorized Core project and its published Project identity.
The candidate is the exact source/package directory to inventory. Keep exports
outside that candidate so they do not change its identity.

```text
corinthos report --root PROJECT_ROOT generate PROJECT_CONTRACT_ID --candidate CANDIDATE_DIR
corinthos report --root PROJECT_ROOT show-draft DRAFT_ID
corinthos report --root PROJECT_ROOT publish DRAFT_ID
corinthos report --root PROJECT_ROOT show REPORT_ID --revision REPORT_REVISION_ID
corinthos report --root PROJECT_ROOT export REPORT_ID --revision REPORT_REVISION_ID --destination NEW_EXPORT_DIRECTORY
corinthos report --root PROJECT_ROOT verify-export NEW_EXPORT_DIRECTORY
```

The [Report guide](docs/report.md) explains all five report kinds, historical
cutoffs, latest-result selection, M1–M5 proof and gaps, delivery provenance,
comparison, current verification and recoverable exports. Normal technical
reports require no paid agent session or additional human approval.

## Standard validation

`policies/standard.yaml` declares M1–M5. `schemas/standard.schema.json` requires
exactly those identifiers, a Boolean `required: true` flag, and a nonblank
description for each one. The loader uses safe YAML parsing and JSON Schema
2020-12 validation. It propagates file, syntax, and validation errors to the caller.

From the repository root in PowerShell.

```powershell
.\.venv\Scripts\python.exe -c "from corinthos.standard import load_standard; policy = load_standard('policies/standard.yaml', 'schemas/standard.schema.json'); print(', '.join(policy['commandments']))"
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
| `src/corinthos/` | Package version, CLI, Standard loader and Contract Kernel. |
| `src/corinthos/contracts/schemas/` | Eight executable schemas and shared definitions, installed with the package. |
| `src/corinthos/project_manager/` | Negotiation service, persistent sessions, complete reviews and local terminal approval. |
| `src/corinthos/workflow/` | Planning, exact authorization, sequential execution, durable recovery and revision reconciliation. |
| `src/corinthos/adapters/` | Provider discovery, equivalent Standard context and separate Codex/Claude process boundaries. |
| `examples/` | Eight sample contracts and the executable kernel demonstration. |
| `policies/` | Versioned Standard policy. |
| `schemas/` | Structural schema for the initial Standard. |
| `tests/` | CLI, package, policy, contracts, negotiation, approval and persistence checks. |
| `AGENTS.md`, `CLAUDE.md` | Equivalent agent obligations and human authority. |
| `docs/` | Architecture, contract catalog, workflows, roadmap, and decisions. |
| `.github/workflows/ci.yml` | Installation, CLI, lint, formatting, and test workflow. |

`.corinthos/` holds private project state. `.gitignore` protects
local environments, private state, databases, caches, and common secret files.
For existing projects with legacy state, close the writers and follow the
[explicit state migration](docs/storage.md#migrating-existing-project-state)
before opening the store. The migration preserves the original copy, published
documents, approvals, evidence digests, references and audit order.
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
and review. The initial A–D stop is recorded historically. The owner subsequently
authorized E–J, including the installed local task-manager pilot and a reviewed
release. Actual results and outstanding limits remain tied to their evidence.

## Engineering documentation

- [Architecture and six Engines](docs/architecture.md)
- [Eight contract types](docs/contracts.md)
- [Project Manager tutorial, approval and service API](docs/project-manager.md)
- [Workflow planning and exact approval](docs/workflow-planning.md)
- [Execution, recovery and revision reconciliation](docs/workflow-execution.md)
- [Independent Validation and formal gates](docs/validation.md)
- [Report snapshots, history and JSON/Markdown export](docs/report.md)
- [Adapter Manager capabilities and verification](docs/adapters.md)
- [SQLite storage and recovery](docs/storage.md)
- [Phase 3 installed-wheel and native verification](docs/phase-3-verification.md)
- [Workflows, gates, and authority](docs/workflows.md)
- [Implementation plan and acceptance criteria](docs/implementation-plan.md)
- [Decisions, verification history, and limits](docs/decisions.md)

These documents provide the public engineering context without requiring access
to private planning systems. The project owner retains authority over product
requirements, binding technology and structural decisions, and human acceptance.

## License

Corinthos is licensed under the [Mozilla Public License 2.0](LICENSE), with SPDX
identifier `MPL-2.0`. Its file-level copyleft requires distributed covered source
files, including modifications, to remain under MPL 2.0. Commercial use and
distribution are permitted subject to the license conditions, including applicable
source-availability and notice requirements. Separate files in a larger work may
use other licenses. See the complete license and
[Mozilla's FAQ](https://www.mozilla.org/en-US/MPL/2.0/FAQ/) for the governing terms
and guidance.

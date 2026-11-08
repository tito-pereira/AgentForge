# Foundation decisions

Record dated November 8, 2026, for scaffold `0.1.0`. The implementer made the
following practical choices within the Phase 0 order. Their provenance is
technical implementation; no individual human approval is attributed to them.
Product requirements revision v0.2 targets Core v0.1.

## Practical choices

| Choice | Rationale and boundary |
| --- | --- |
| Python 3.12 baseline | Explicit baseline for installation, tests, and CI, consistent with the approved Python stack. The README documents prerequisites. |
| `argparse` and the standard library | CLI help and version need little logic and require no additional CLI framework. |
| `setuptools`, `pyproject.toml`, and `src/` layout | Conventional packaging with local installation and an entry point, separating sources from tests. |
| PyYAML with `safe_load` | Loads the declarative YAML policy through an appropriate parser. |
| `jsonschema` | Validates the policy structure against JSON Schema, including mandatory and enabled M1–M5. |
| `pytest` | Runs smoke, positive, negative, and packaging checks. It was already part of the approved stack. |
| Ruff | Lightweight static analysis available both locally and in CI. |
| GitHub Actions, Linux and Windows, Python 3.12 | Configures installation, lint, and tests for both relevant systems. A configured workflow requires actual execution before success can be claimed. |

The foundation CLI exposes help and version information. The validator
`agentforge.standard.load_standard(policy_path, schema_path)` takes both paths
explicitly. `policies/standard.yaml` and `schemas/standard.schema.json` remain
repository files whose paths the caller supplies when using this API.

The policy contains `standard_version: "0.1"` and a `commandments` map with M1–M5.
Each entry declares `required: true` and a description. The policy version,
scaffold version, and product requirements revision identify separate artifacts.

## Boundaries and assumptions

The minimal schema checks the Standard structure. Tests and technical review
assess code and the adequacy of evidence. The six Engines, eight contract schemas,
SQLite storage, migrations, functional adapters, and operational workflows belong
to subsequent phases.

`.agentforge/` is reserved for future private data and must be ignored by Git,
together with local databases, environments, caches, and secrets. The foundation
uses normal user permissions and operations in the authorized directory.

The original product requirements grouped foundation and Kernel in one
implementation block. The later construction plan and specific Phase 0 order
established the current sequence, reserving contract schemas and operational
persistence for Phase 1. [implementation-plan.md](implementation-plan.md) records
that sequence locally.

## Decisions for the next phase

Phase 1 must define types and schemas for the eight contracts, invariants,
identities/revisions, reference validation, authorization records, the SQLite
model, and migrations. It must define operations and tests for integrity,
interruption, and safe repetition, including the boundary between SQLite and Git.

Material requirement changes and binding technology or structural decisions
require the applicable human authority. Implementation decisions must preserve
their provenance and reference the approved specification.

## Historical Phase 0 verification

The following is the recorded Phase 0 verification from November 8, 2026, on
Windows with Python 3.12.14. It describes that execution. Phase 0.1 must establish
fresh results for the translated repository.

The directory was initially empty, and Git was initialized locally on `main`.
The `.venv/` environment was created without inheriting global packages, using
Python from a locally available application runtime. The original setup also
documented an alternative using a normal Python installation. Public setup
instructions use portable commands; personal runtime paths are omitted.

The direct dependency and tool versions exercised were PyYAML 6.0.3,
jsonschema 4.26.0, pytest 9.2.0, and Ruff 0.17.4. Compatibility ranges are declared
in `pyproject.toml`; later installations may resolve other versions.

| Checkpoint | Recorded result and local evidence |
| --- | --- |
| F0.1 | Done. Empty directory, Git, and Python/pip inspected; baseline and choices documented. |
| F0.2 | Done. Editable installation, CLI, policy, and schema exercised. Git exclusions checked for private state and common secret files. |
| F0.3 | Done. AGENTS/CLAUDE, README, and five technical documents reviewed, with working local links and references to the approved planning sources. |
| F0.4 | Done. 33 tests passed. Ruff lint and format checks passed. CI configured for Windows/Linux. |
| F0.5 | Done. Files and Git state inspected; independent review found no blocking issues, and M1–M5 evidence was recorded below. |

Commands executed from the repository root with `.venv/Scripts/python.exe`
included `-m pip install -e ".[dev]"`, `-m pip check`, `-m agentforge --help`,
`-m pytest`, `-m ruff check .`, and `-m ruff format --check .`. The entry point
`.venv/Scripts/agentforge.exe --version` returned `agentforge 0.1.0`. The README
loading example returned M1, M2, M3, M4, and M5.

`-m pip wheel . --no-deps --wheel-dir .venv/wheelhouse` was also executed. The wheel
and its dependencies were installed into a second clean environment at
`.venv/package-check/`. Help, version, and imports worked from another directory,
with the module loaded from `site-packages`. The policy and schema still require
checkout paths, as described by the API.

| Commandment | Recorded evidence |
| --- | --- |
| M1 | F0.1–F0.5 scope and authority in AGENTS/CLAUDE, the plan, and the original execution order. |
| M2 | Practical choices and provenance in this document; dependencies declared in pyproject. |
| M3 | 33 tests, covering missing/disabled M1–M5, invalid configuration, and unsafe YAML; actual installation and static analysis. |
| M4 | README with executed commands, five technical documents, and references to the approved planning sources. |
| M5 | CLI using argparse, a short validator using appropriate libraries, Ruff, and independent review. |

Remote CI and POSIX commands were unverified in that Phase 0 run. Local validation
used Windows and Python 3.12.14. A virtual environment depends on the interpreter
that created it and may need recreation after its application runtime is updated.
At the end of Phase 0, Git contained 19 new untracked files, with no commits,
remote, or push. These are historical observations. Phase 1 remains subject to
the subsequent authorization required by the plan.

## Phase 0.1 publication decisions

The user authorized an English-only public repository named `AgentForge`,
including a reviewed commit and push after publication prerequisites pass. This
order supersedes the original Portuguese documentation requirement. The Python
package name remains `agentforge`, and the foundation API and M1–M5 identifiers
retain their meaning.

Public documentation uses self-contained local references. Private planning URLs,
personal runtime paths, and private state are excluded from public materials.
The original internal planning retains decision provenance. New test results,
commit identifiers, repository visibility, publication, and remote CI status must
be established by the Phase 0.1 run and its delivery report.

License selection is pending an explicit decision by the project owner. Public
visibility alone grants no open-source license, and no license is inferred here.

## Phase 0.1 local verification

The English-language tree was revalidated on November 8, 2026, on Windows with
Python 3.12.14. The existing 33 tests passed again. Ruff lint and formatting checks
passed, and `pip check` found no broken dependencies. Editable installation, the
README Standard example, and both CLI entry points worked with English output.

A new wheel was built and installed with its dependencies in a fresh isolated
environment under `.venv/phase01-check/`. Help, version, and imports worked from
another directory with the module loaded from `site-packages`. The dependency
versions match the historical Phase 0 versions recorded above.

Comparison with the pre-migration tree confirmed unchanged executable logic,
test files, schema constraints, Commandment identifiers and required flags,
dependency declarations, and CI commands. Changes to these artifacts were limited
to human-readable text. Additional ignore patterns protect editor settings and
conventional credential, environment, and private-key files.

The intended 19-file public tree was reviewed for credentials, private state,
private planning URLs, personal paths, and broken local links. The project owner
explicitly authorized a GitHub-provided private commit email for this repository.
Remote publication and observed CI results are reported separately in the delivery
report. POSIX shell setup was not executed locally.
## Technical references

These references were consulted for packaging, validation, lint, and CI during
the foundation work.

- [Python packaging](https://packaging.python.org/en/latest/guides/distributing-packages-using-setuptools/)
- [jsonschema validation](https://python-jsonschema.readthedocs.io/en/stable/validate/)
- [Ruff installation](https://docs.astral.sh/ruff/installation/)
- [checkout releases](https://github.com/actions/checkout/releases)
- [setup-python releases](https://github.com/actions/setup-python/releases)

Related local documents cover [architecture](architecture.md),
[contracts](contracts.md), [workflows](workflows.md), and
[implementation phases](implementation-plan.md).

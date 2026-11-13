# Corinthos v0.1 Phase 0 baseline

This record freezes the implemented baseline for the v0.1 roadmap.
The roadmap version, Python distribution version, contract wire version and
SQLite schema version identify separate surfaces.

| Git evidence | Exact identity |
| --- | --- |
| Repository and branch | `tito-pereira/Corinthos`, `main` |
| Baseline commit | [`5a2a8e682b1389d96318feb636b8f52828f943d3`](https://github.com/tito-pereira/Corinthos/commit/5a2a8e682b1389d96318feb636b8f52828f943d3) |
| Git tree | `285740bc36368bd851f6c0cf8356dcc0e79092e4` |
| Merge provenance | [PR #11](https://github.com/tito-pereira/Corinthos/pull/11), first parent `b2ec1c2dfc9d525aec524cfd99052015fbb25592`, second parent `335f0610ff350a2de4c5d146ca2be25e9c36df4b` |
| Baseline CI | [Core checks, push to main, run 43272874304](https://github.com/tito-pereira/Corinthos/actions/runs/43272874304) |

The fetched canonical head matched the execution order on 2026-11-13.
`phase-v0.1-0-baseline` is a review branch. The product roadmap establishes a
compatibility line through this commit and its records, without a permanent
release branch or release tag.

## Package and installation

- Distribution `corinthos-core` version `0.1.0`, Python requirement
  `>=3.12`, module `corinthos`, entry point `corinthos.cli:main`.
- Direct package dependencies are `PyYAML>=6,<7` and `jsonschema>=4.23,<5`.
  These are package metadata ranges. The Windows installer separately pins
  CPython 3.14.10 embeddable x64 and six exact wheels with URL, size and
  SHA-256: attrs 26.1.0, jsonschema 4.26.0, jsonschema-specifications 2025.9.1,
  PyYAML 6.0.3, referencing 0.37.0 and rpds-py 2026.9.1.
- [Artifact pins](../../platform/windows/artifacts.json) describe the
  verified downloads. The Python ZIP SHA-256 is
  `90905e64a840557d8c1bc4f5b74db3d7ee85e3ffb217611cac1c7813acea4159`.
- The source-first Windows path is Git clone, `.\install.ps1`, then
  `corinthos` from a new terminal. Setup stages the private runtime and
  application, restricts Python imports with `python314._pth`, builds the
  launcher with the Windows .NET Framework x64 compiler, and adds the
  installation's `bin` to the user's PATH. Health checks gate 100% completion.
  Reinstall verifies the replacement and can restore the prior installation.
  Uninstall checks ownership and inventory and preserves user and project data.
  The source and dependency CI matrix also covers Ubuntu, where the Windows
  installer is inapplicable.

## Observed baseline evidence

Each job log records checkout of the exact baseline SHA. The four package jobs
built and installed a wheel in a clean venv, checked dependencies/imports, ran
the complete suite, verified installed CLI/lifecycle and examples, and passed
Ruff lint/format and the applicable shell activation checks.

| Job | CPython | Passed | Skipped |
| --- | --- | ---: | ---: |
| [Windows](https://github.com/tito-pereira/Corinthos/actions/runs/43272874304/job/131373543020) | 3.12.10 | 714 | 0 |
| [Windows](https://github.com/tito-pereira/Corinthos/actions/runs/43272874304/job/131373543936) | 3.14.10 | 714 | 0 |
| [Ubuntu](https://github.com/tito-pereira/Corinthos/actions/runs/43272874304/job/131373543306) | 3.12.16 | 710 | 4 |
| [Ubuntu](https://github.com/tito-pereira/Corinthos/actions/runs/43272874304/job/131373543477) | 3.14.10 | 710 | 4 |

Ubuntu skips one native `.exe` configuration requirement
(`tests/test_adapter_configuration.py`), two Windows suspended-job assignment
cases (`tests/test_process_control.py`), and one native Windows suffix case
(`tests/test_user_providers.py`).

The [Windows source-install smoke](https://github.com/tito-pereira/Corinthos/actions/runs/43272874304/job/131373542404)
passed with a Python-free PATH. It verified the private interpreter, the
command after moving the source checkout, two independent projects, cache
reuse, hash rejection, PATH deduplication, rollback, and inventory-protected
uninstall. A fresh install with a synthetic provider on PATH and a reinstall
with an explicitly configured provider left both sentinels untouched.
Explicit refresh ran the four bounded version/help probes against the selected
synthetic executable and persisted the observed capabilities.

CPython 3.14.10 reports existing `PurePath.is_reserved()` deprecation warnings
in contract artifact path checks, Workflow verification, and Report sources
and rendering. Python 3.15 compatibility remains **UNVERIFIED**. The prior
[Phase 6.1 delivery exception](../phase-6-verification.md#phase-61-delivery-decision)
preserves the incomplete pilot and unverified comparable live Claude evidence.
The current install smoke proves native probe plumbing with a synthetic
provider. The roadmap's future two-real-provider substitution gate requires
separate evidence.

## Product capabilities to preserve

The [six Engines](../architecture.md#six-approved-engines) are Standard Engine,
Adapter Manager, Project Manager, Workflow Engine, Validation Engine and Report
Engine. Corinthos Workflow Standard is the existing headless engineering and
domain layer as a whole. The Standard Engine owns the mandatory M1–M5 policy.
The shared Contract Kernel enforces eight versioned contract families, exact
references, immutable revisions and authority. Lifecycle services retain
version, build, promotion, playtest and product-review evidence in SQLite v6.

Project Manager offers assisted, guided and advanced authoring over the same
draft. Optional advice needs an explicit accepted edit. Project Completion
assigns 20 points each to vision, included scope, requirements with criteria
and success criteria. The final 20 points require structural readiness for
review. Back abandons unfinished input, accepted edits persist, Save and exit
preserves frozen reviews, and Resume reopens the same session. Publication
requires a fresh, exact review and verified foreground HUMAN approval.

The CLI Home opens with `corinthos`, the current project with `corinthos .`.
Scriptable subcommands remain available. Home uses one versioned global state
directory and a bounded list of up to 20 recent projects. A recent path is
revalidated on open. Provider execution uses operation override, then project
override, then the explicit per-user choice, then safe discovery. An explicit
project reset skips the saved project/bootstrap and per-user choices for that
provider. Setup, reinstall and passive Home startup leave provider executables
untouched. Explicit capability operations probe native executables when needed.

## Roadmap reconciliation

Corinthos Core names the complete installed product. The Phase 0 baseline has
a terminal Home and no desktop GUI, shared Application Layer, or active RPC
protocol. Corinthos Command is a planned operational GUI view. Project State
is a planned logical read model, Work Item a planned universal unit of work,
Agent Session a planned temporary executor, and Context Engine a planned
transverse subsystem. Existing playtest sessions and adapter resume handles
have distinct current semantics.

The implementation vision groups work into A–F. The Architecture and Roadmap
v0.1 supplies the sequenced Phase 0–9 gates used here, including the earlier
Application Layer/protocol spike and later desktop integration. DT-19 governs
the future desktop source-build contract. The implemented source installer
also checks for the Windows .NET Framework compiler and needs network access
for uncached pinned artifacts. GUI toolchain automation belongs to Phase 9.
The product release and versioning decision O3 remains pending before the first
public desktop release.

- [Machine-readable baseline](baseline.json)
- [API and state boundaries](boundaries.md)
- [Eight contract invariants](contracts.md)
- [SQLite v6 compatibility](sqlite-v6.md)
- [Compatibility matrix](compatibility.md)
- [Approved decisions DT-01 through DT-20](adr/README.md)

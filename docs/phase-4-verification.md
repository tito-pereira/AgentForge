# Phase 4 engineering verification

The Validation Engine starts from integrated main
`22592bf8a2d8ad1605abf332a65c34138d35069c`. The baseline's
[post-merge CI](https://github.com/tito-pereira/Corinthos/actions/runs/42855963126)
passed 408 tests on Windows CPython 3.12.10 and 406 on Ubuntu CPython 3.12.16,
with two Windows-only process tests skipped. An installed-wheel baseline check
also passed 65 targeted tests before implementation.

The [design](phase-4-design.md) records responsibilities and traceability. The
[Validation guide](validation.md) provides the public APIs, guided commands,
procedure model, trust boundary and isolated-pilot reproduction steps. Final
commit and platform evidence are recorded on
[PR #7](https://github.com/tito-pereira/Corinthos/pull/7) and its exact-head
checks. The phase preserves package version 0.1.0, schema version 1.0, the
five Commandments, six Engines, eight contract types and MPL-2.0.

## Implemented boundaries

`ValidationPlanner.derive` reads the approved Project and Standard directly,
then derives applicable Module, Technology Decision, Workflow and interface
obligations through the shared Kernel semantics. Publication rederives the
scope and requires complete bindings and criterion-specific independent method
reviews. The immutable VC anchors the exact procedure, review and Standard
digests. It uses legitimate Validation authority with `approval=null`.

`ValidationRunner.run` inventories the full supported candidate, retains an
isolated copy, executes pinned procedures and records exact independent
inspections. Actual observations determine coverage, findings and gate state.
The same unchanged VC supports separate runs and immutable VRC identities.
Evidence envelopes bind the plan, source, method, check, run, evaluator and
complete artifact identity. Repeated byte-identical commands share their actual
observation only inside that run, with an explicit origin reference.

`ValidationRepository` persists drafts, bindings, fenced runs and append-only
events. Freeze and publication share the Kernel writer reservation with fresh
source and candidate guards. Recovery requires inspected stopped processes
and effects. It retains partial observations and derives an interrupted,
blocked result. Reconciliation of a frozen result preserves its identity.

Workflow exposes its retained candidate through `audit-request`. Managed formal
expectations require a published operational run, and completion rechecks gates
inside its writer reservation. A direct repository caller cannot bypass that
check by omitting or replacing the callback. A rejected preliminary review
retains observations of existing formal gates while leaving the audit callback
uninvoked. Prerequisite gate freshness is checked before downstream work.

Module, Integration and Checkpoint use `CHECKPOINT`. Playtest Milestone uses
`PLAYTEST_READINESS`, and Product uses `PRODUCT_VALIDATION`. Exact target
contracts, IDs and candidate identities remain bound to each scope.

## Installed-wheel and regression evidence

The first clean Windows installed-wheel run at implementation commit
`9a2065a1299c10fbfc94433b2bed945694f910d1` passed **437 tests** in 113.27 seconds
on independent CPython 3.12.10. `pip check`, CLI help and the original
eight-contract, nine-revision demonstration passed. Package imports resolved
inside the separate environment's `site-packages` under isolated Python mode.
That wheel's SHA-256 was
`7acf5b1d4431377c496c001fd9bd3ad0dd0842877854ab9df62659aaf3942800`.

Both jobs passed on that commit's
[push CI](https://github.com/tito-pereira/Corinthos/actions/runs/42874733039)
and [PR CI](https://github.com/tito-pereira/Corinthos/actions/runs/42874920399).
Subsequent regression additions and the preliminary-review observation fix
require their own final-head checks. Use the PR's current head and job logs
for the final counts, Python versions and platform-specific skips.

Regression covers incomplete matrices, inadequate or unknown evidence kinds,
source authority and freshness, exact interfaces, mandatory and optional
outcomes, missing and modified evidence, target drift, cancellation, process
cleanup, fenced concurrent writers, crash boundaries and publication rollback.
Isolated Module, Integration and Playtest Milestone tests run actual pinned
commands and inspect their candidates, then publish and consume their scoped
results. Their approved contracts and reviewer callbacks are explicitly
synthetic fixtures. The Workflow integration tests also exercise actual
VERIFYING-to-audit-to-VRC completion with synthetic implementation adapters.

Selective revalidation tests retain exact consumed interface terms across a
compatible provider revision and reject a removed interface. Workflow checks
the known review dependency closure, including applicable non-deliverable
configuration. Unknown command dependencies conservatively cover the whole
candidate. Earlier evidence keeps its original source and artifact identity.

Reproduce the standard checks in a clean Python 3.12 environment using the
[README](../README.md) and [CI workflow](../.github/workflows/ci.yml). CI installs
its built wheel, verifies installed imports, runs the full suite and existing
Project Manager/Workflow commands, adds Validation help, checks dependencies,
lint and formatting, and exercises supported shell activation. Routine CI uses
offline synthetic agent protocols. Live authenticated execution is recorded
separately below.

## Migration and retained history

SQLite v5 adds four Validation tables. The populated v4 regression fixture
executes code archived from the integrated Phase 3.1 commit. All 16 historical
tables contain records, including Kernel contracts and audit events, Project
Manager approvals, Workflow planning approvals and mandates, execution attempts,
workspace leases and execution events. The fixture uses explicit synthetic
approval authority.

Every existing row and stored document/digest field is compared in row order
before and after the upgrade. Injected failure after the new DDL leaves v4 and
all earlier rows intact, with no partial Validation tables and a verified v4
backup. A successful retry preserves both that backup and its own pre-upgrade
backup. Reopening the upgraded state creates no additional backup.

Historical v1, v2 and v3 code fixtures also upgrade to v5 with verified backups
at their genuine starting versions. Checks retain original publication history,
approval and planning records, referenced artifact digests and foreign-key
integrity. Directory-copy migration separately checks exact database bytes
before an independent upgrade. SQLite upgrade preservation compares complete
stored rows and document bytes, accounting for legitimate database-file changes.

The isolated real pilot's approved populated v4 Core state was copied with
SQLite backup and migrated to v5. Its actual Project, Technology Decision,
three Module and Workflow revisions and approval lineage remain readable.
The owner's daily task database was outside this migration.

## Independent audit of the approved task manager

The Phase 3 pilot source at
`005ed647ba611e985534a80f8d98a6c8eff48b07` and its original wheel were copied
into an isolated candidate. The wheel SHA-256 was
`a97cf8c8f9cf91da0b499078498b26ba763ceaef2f19c0e24752bf03c960a99d`.
Canonical Git bytes and the full included wheel participate in the candidate
snapshot. Private records retain exact contract, plan, run, result and evidence
references, source manifests and independent per-criterion observations.

A separate evaluator inspected the actual requirements, source, tests,
interfaces, procedures and documentation. Reviewed procedures installed the
exact wheel offline into isolated Windows Python environments and exercised its
real launcher. They observed SQLite preservation and failure behavior, task
operations, errors, Unicode, backup/restore, source/package consistency and
the approved technology. The default-path procedure used isolated
`LOCALAPPDATA`, separate working directories, process restarts and reinstall.

| Actual audit | Observed result | Consumed gate |
| --- | --- | --- |
| Original Product candidate | 64 covered, zero unverified or nonconformant | Satisfied |
| Original CLI Checkpoint candidate | 36 covered, zero unverified or nonconformant | Satisfied |
| New interrupted Product run on the same artifact | One covered, 63 unverified, interrupted status and retained partial evidence | Blocked, superseding the older matching pass |
| Controlled defect, Product | 64 covered, 18 nonconformant, zero unverified | Blocked |
| Controlled defect, CLI Checkpoint | 36 covered, 12 nonconformant, zero unverified | Blocked |
| Repaired Product candidate, fresh linked run | 64 covered, zero unverified or nonconformant | Satisfied |

The controlled defect made the default database depend on the working
directory in the isolated CLI and matching wheel. **All 20 existing pilot tests
still passed.** The independent cross-directory installed check observed the
contradiction to the approved default path and persistence requirements. The
evaluation retained the findings, exact faulty source/package identity and
negative results.

Removing global success criterion SC1 from a derived matrix prevented plan
publication. Wrong-target, missing-evidence and deliberately modified-evidence
checks each blocked consumption of the actual positive Checkpoint result.
The original isolated evidence bytes were then restored and their digest and
original admissibility reverified. These tests left the original delivery intact.

Workflow ran the storage and task-rules prerequisites with native Codex
0.167.0, actual checks and separate review, preserving the candidate bytes.
The first CLI attempt passed 20 local tests and blocked when its bounded
preliminary-review wait expired. Its older runtime had already been loaded
before the new gate-observation behavior. The inspected recovery separately
consumed the actual blocked Product VRC, and the native repair context retained
that exact result and its findings.

The linked native repair restored only the CLI and original wheel to their
exact canonical bytes. Its 20 tests and independent technical review passed.
A private audit callback then used a field absent from the audit-request
schema and failed before formal dispatch. The stopped attempt and source
observation remained durable. After correcting that private callback, inspected
`VERIFY` recovery reran the actual 20 tests on the retained candidate and
obtained a fresh separate technical review, with no further source changes.

Within that recovered VERIFYING attempt, Validation used freshly inspected
static observations and new installed executable checks. The same Product VC
published a new linked VRC with 64 conformant checks. Workflow consumed that
new satisfied Product result and the admissible Checkpoint result for the exact
restored full identity, then completed with `FORMAL_CHECKPOINT_GATES_SATISFIED`.
Earlier interrupted and nonconformant runs, findings and evidence remain in
history. The Checkpoint defect audit was a separate fresh run. The Product runs
carry the explicit baseline, interruption, defect and repair lineage.

The original pilot source remained clean at its delivered commit. Its installed
launcher, quickstart and daily database were verified as available. The daily
database stayed outside all audit, migration and negative-test paths. Private
handoff records retain the exact run references, original and restored input
digests, native attempt lineage, independent reviews and final gate evidence.

## Review, authority and limits

Separate technical review examined planning completeness and adequacy, runtime
evidence, finalization races, genuine migrations, interface freshness and
Workflow completion. Findings led to atomic finalization/publication, explicit
supported evidence kinds, complete Git-worktree snapshots, repository-owned
completion checks and the corrected normal CLI audit-request constructor.
Focused regressions accompany the fixes.

The evaluator account and its approved procedures are trusted. Native operating
system policy and caller isolation govern file access. Owned-process cleanup
supplies bounded execution and termination. The guide describes this local
trust boundary and the supported procedure/evidence model.

Live Claude remains **NOT VERIFIED**. Technical gates preserve the owner's
separate acceptance authority. Report/ERC production belongs to Phase 5.
Full evolution, experimental-build promotion and Feedback Tracker belong to
Phase 6. The final handoff records the reviewable PR and its checks.

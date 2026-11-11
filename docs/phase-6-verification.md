# Phase 6 candidate verification

Phase 6 starts from integrated commit
`32397d2bc0d02c8e77b5c6e09ca7e83f04995af0`, tree
`cad09ba80f7a6f67e81956e70b289bffd14d21ad`. Its actual push/main
[CI run](https://github.com/tito-pereira/Corinthos/actions/runs/43029442942)
passed 529 tests on Windows and 527 with two platform skips on Ubuntu. Those
results belong to that baseline, not this candidate. The historical
`phase-1-baseline` tag and main history remain preserved.

## New implementation evidence

The initial full source run passed 592 tests with one local Windows directory
symlink privilege skip and two fixture setup errors. The errors were missing
cross-module fixture imports, subsequently corrected and checked in the affected
suites. This initial run is not a final clean-wheel or cross-platform claim.
The clean reviewed wheel at `6930ad41` subsequently passed **615 tests with one
local symlink-privilege skip** on Windows CPython 3.12.10 in 349.85 seconds.
Imports came from a fresh venv's site-packages. Wheel SHA-256:
`406410b84f9ba466e3df4e1970526acaa63ab9491b2017947aea51e72dad68af`.
Dependency checks, installed initialization outside checkout, the original Kernel
demonstration, Ruff and process-scoped PowerShell activation passed. The default
shell's script policy rejected activation; no persistent policy was changed.

The first [PR CI run](https://github.com/tito-pereira/Corinthos/actions/runs/43060355148)
failed overall. Windows passed 616 tests, then the new smoke selected an 8.3 TEMP
alias rejected by the canonical-root guard. Ubuntu passed 596 with two platform
skips but 18 new tests supplied a symlinked venv interpreter to the strict pinned
file guard. The fixtures now explicitly choose canonical ordinary paths, consistent
with existing Validation fixtures. All affected commands use only the stdlib;
production guards remain unchanged. The 31 affected connected tests and installed
smoke passed locally after correction. Final-head Windows/Ubuntu results are
linked from [PR #9 checks](https://github.com/tito-pereira/Corinthos/pull/9/checks)
and the delivery record, rather than attributed to the earlier failed run.

Focused tests exercise real filesystem bytes, subprocesses, SQLite transactions,
Workflow execution and scoped Validation. Test contract authority, agent output
and interactive review fixtures are explicitly synthetic; they are not owner
decisions or the actual pilot demonstration.

| Boundary | Executable evidence |
| --- | --- |
| Packaged Standard, managed blocks, repeat init, explicit assistance | [bootstrap](../tests/test_bootstrap.py) |
| Immutable origins, CAS, atomic rollback, historical events | [repository](../tests/test_lifecycle_repository.py) |
| Actual populated v5 and prior supported migrations; backup/rollback/recovery | [migration](../tests/test_lifecycle_migration.py), existing state/execution migration suites |
| Complete sealed identity, generated outputs, no gate cycle, independent current proof | [build lifecycle](../tests/test_build_lifecycle.py), existing Validation runtime tests |
| Sessions, waiting/promotion, feedback, owned retention and interrupted effects | [playtests](../tests/test_playtest.py), [CLI](../tests/test_playtest_cli.py) |
| Actual approved successor/reconciliation, preserved and freshly repaired work | [reconciliation](../tests/test_playtest_reconciliation.py) |
| Exact delivered versions and evolution context | [versions](../tests/test_version_lifecycle.py) |
| Original delivery adoption, no relabelled identity or daily launcher access | [adoption](../tests/test_version_adoption.py) |
| Candidate/manifest changes during publication roll back records/events | [delivery guards](../tests/test_version_delivery_guards.py) |
| Exact optional acceptance/reservation, no receipt from noninteractive or stale input | [product review](../tests/test_product_review.py) |
| Coherent current sources, historical state and original feedback associations | [lifecycle reports](../tests/test_lifecycle_reporting.py), existing Report suites |
| Installed resources/help outside checkout with preserved owner instructions | [installed smoke](../examples/installed_bootstrap.py), both CI jobs |

Independent connected review reproduced and then verified fixes for session
admission changing during preparation, same-inode retention edits, candidate
mutation during delivery, missing public readiness/session projections and the
original-delivery evolution gap. Regression tests bind the relevant boundaries.
Review is an engineering assessment, separate from formal Validation or acceptance.

## Real pilot preparation and open proof

A consistent SQLite-supported copy preserves the original task manager's twenty
v5 tables, prior approvals/audits/reports and all 323 artifact files present at
copy time. The earlier 310 count described an older retained set. Original source
and database hashes were verified unchanged; the daily app/database were not used.

Two actual in-scope defects were reproduced in the isolated copy:

- Terminal controls in accepted text reached CLI output. Three new checks failed
  before repair; 23 baseline/new tests passed after the bounded presentation fix.
- Destination sidecars appearing during backup/restore validation were missed at
  publication. All six operation/sidecar cases failed before repair; all 24
  cumulative tests passed after the final collision recheck.

These repair implementation obligations without changing the Project, Module or
Technology Decision contracts. A coherent two-milestone Workflow successor is
frozen for genuine foreground HUMAN review. No receipt or publication was
fabricated. The actual two-candidate build/audit/session/recovery demonstration
under that successor remains open until its reserved milestone decision occurs.
Passing repair tests alone is not milestone Validation or product acceptance.

The installed CLI adopted the verified original `0.1.0` delivery into native
version history with its original commit/snapshot identity and unchanged prior
Product VRC. It created an operational evolution request without a gratuitous
Project revision. Actual baseline PRODUCT, HISTORY and EVOLUTION report bundles
were generated, published, exported and verified. They retain `NOT_REVIEWED` and
describe the preserved baseline/proposal, not an approved or tested successor.
No new pilot BUILD or formal Validation run was created before milestone approval.

## Native interoperability

Both providers received prepared equivalent isolated source snapshots, the same
bounded brief, approved references, M1–M5 and frozen external acceptance checks.
Codex native 0.167.0 was actually invoked twice through AdapterManager. The first
bounded run timed out without source changes after failing to locate Python.
One fresh retry supplied the verified Python 3.12.10 path to both prepared briefs.
It produced exactly the four allowed files; external checks and 28 application
tests passed. Both runs reached their 180-second adapter limit with confirmed
cleanup before a terminal completion event. Native status remains `TIMEOUT` and
`verified_task_result=false`; successful artifact checks do not change that fact.

The owner has Claude Free and no Claude Code access. Claude was not invoked and
remains `NOT_VERIFIED`; no subscription/account change or substitute mock was used.
The mandatory comparable native proof remains incomplete. Full Core/PRD completion
and ready-for-review status are therefore not established. The Phase 6 PR must
remain draft/incomplete; integration requires separate authorization. Optional
human feedback/acceptance remain `NOT_REVIEWED` and are not mandatory blockers.

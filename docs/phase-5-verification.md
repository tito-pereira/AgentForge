# Phase 5 Report Engine verification

The starting integrated main is
`2c3bc8a36b86a52658d093042bb0a02378cd1578`, tree
`3074b056f2405e9c0b000c25fc9df6860f051e3a`. Its
[post-merge CI](https://github.com/tito-pereira/Corinthos/actions/runs/43006309503)
passed 441 tests on Windows CPython 3.12.10 and 439 on Ubuntu CPython 3.12.16,
with two Windows-only skips. The isolated installed baseline passed 441.

The implementation is delivered on [PR #8](https://github.com/tito-pereira/Corinthos/pull/8),
starting with implementation commit
`59ad706663dd3fc75bde068a9b1a35d571294f10`. The PR's final head and checks
identify the delivered review snapshot. Integration requires its own order.
Package 0.1.0, schema 1.0, SQLite v5, MPL-2.0, five Commandments, six Engines
and eight contract types remain unchanged. There is no migration or dependency addition.

## Implemented and checked boundaries

The [design](phase-5-design.md) maps source requirements to the implementation.
The [Report guide](report.md) documents the API and installed CLI. The service
collects a coherent read snapshot, composes the existing nine ERC sections and
publishes immutable revisions through the Kernel. It supports CHECKPOINT,
MILESTONE, PRODUCT, HISTORY and EVOLUTION without running another Engine.

Current eligibility selects every applicable exact-scope plan and its latest
result for the same complete candidate. A newer interrupted result cannot be
hidden by an older pass. Missing required proof makes a formerly passing result
unverified. Results for another candidate or conflicting source revision remain
historical facts outside the current digest. Historical cutoffs require both
the original creation time and actual publication/event position; mutable state
that cannot be reconstructed becomes an explicit gap.

The private generation manifest is anchored by a digest in the published ERC.
It retains exact source hashes, selection, event watermarks and delivery inputs.
Bulk SQL reads and file hashing precede the writer reservation. SQLite
`data_version` and metadata guards detect intervening changes around Kernel
publication. Report-owned events do not make unchanged reports stale. Existing
exact HUMAN acceptance reviews participate as historical sources, with their
original approvals and feedback associations preserved.

Normal reports use REPORT authority, `approval=null`, acceptance `NOT_REVIEWED`
and `review_approval_id=null`. Technical status, package delivery, observed
launcher availability and human acceptance remain separate. No report result
changes a Workflow gate or creates product acceptance.

Publication recovery reconciles an already committed exact revision before
repairing its receipt. Malformed unrelated drafts do not poison valid lookups.
Exports reserve an explicit new directory, preserve existing user output and
write completion metadata last. Retry verifies the exact frozen input and
output hashes. Comparison and both export formats reject recognized sensitive
canonical fields. Markdown additionally escapes hostile links, markup and controls.

## Regression evidence

The final source regression before the long-prose review fix passed **527 tests**,
with one local skip because directory-symlink privileges were unavailable, in
212.91 seconds. The added source-backed long-rationale generation, publication
and reopen regression passed separately before the committed wheel build.

The six Report test files cover:

- Coherent concurrent reads, source cutoffs, backdated late publications,
  current freshness, accepted-review history and ordinary-report churn.
- Exact plan, project, checkpoint set, milestone, build, snapshot and run binding;
  mixed or conflicting revisions; omitted, damaged and tampered required proof.
- All five kinds, nine wire sections, M1–M5 mappings, no-result and partial reports,
  unchanged evidence, explicit gaps and per-result metric denominators.
- Dirty candidates at the same commit, canonical package/source matching,
  unsupported delivery records, relative input paths and absent launcher observations.
- Sequential revisions, concurrent successors, immutable historical lookup,
  capture interruption, commit/receipt interruption and exact recovery.
- Forged acceptance and feedback, rehashed manifests, comparison confidentiality,
  long valid approved prose, hostile Markdown, credentials, paths and terminal controls.
- Exclusive exports, partial writes, first-fsync failure, recoverable owned
  outputs, concurrent replacement and preservation of existing user directories.

Existing Kernel, Project Manager, Workflow, adapters, Validation and Windows
process-containment regressions remain in the complete suite. Synthetic trusted
approval fixtures are labelled tests and provide no production consent.

## Installed wheel and platform evidence

A fresh independent Windows CPython 3.12.10 environment installed the canonical
wheel from commit `59ad706663dd3fc75bde068a9b1a35d571294f10`. Every packaged
runtime file was compared byte for byte with the Git blob, using a Git archive
with line-ending conversion disabled. Wheel SHA-256:
`056d0be520f541b20852289290142750f0b438c5a0671c627d39bbed1b7783fe`.
Isolated Python imports resolved inside that environment's `site-packages`.

The full installed regression passed **528 tests, one symlink-privilege skip**
in 209.07 seconds. Dependency consistency, all four service CLI families, Report
generation/publication/recovery/export/verification/history/comparison help,
Ruff and formatting passed. The original demonstration published all eight
contract types and reopened nine revisions.

The implementation commit's
[PR CI](https://github.com/tito-pereira/Corinthos/actions/runs/43021905125)
also passed with installed wheel imports:

| Platform | Actual interpreter | Result |
| --- | --- | --- |
| [Windows](https://github.com/tito-pereira/Corinthos/actions/runs/43021905125/job/130526891081) | CPython 3.12.10 | 529 passed in 260.87 seconds; no skips. |
| [Ubuntu](https://github.com/tito-pereira/Corinthos/actions/runs/43021905125/job/130526891484) | CPython 3.12.16 | 527 passed, two Windows-only process-boundary skips, in 76.60 seconds. |

Both jobs passed dependency checks, installed imports, Report CLI commands,
existing service help, the demonstration, lint, formatting and their platform's
shell activation checks. These observations identify the implementation commit.
Documentation closure has its own final-head PR/push checks; use PR #8's current
head and job logs rather than attributing older CI to a newer commit.

## Actual task-manager report delivery

The installed CLI generated, published, reopened, exported and verified five
reports against a consistent isolated copy of the approved real pilot. Both
canonical JSON and complete nine-section Markdown came from the service.
No hand-authored report substituted for those outputs.

| Report | Preserved observation |
| --- | --- |
| Interrupted HISTORY | One conformant and 63 unverified Product checks; BLOCKED, without reusing the older pass. |
| Negative HISTORY | Exact defective candidate, 18 nonconformant Product checks, separate historical 12-nonconformant Checkpoint result, and the actual green 20-test Workflow observation. |
| Repaired HISTORY | New 64-conformant Product result, recorded failure/recovery trail and final inspected Workflow completion. |
| Current PRODUCT | 64 conformant Product checks; VALIDATED, product 0.1.0 DELIVERED, launcher available, acceptance NOT_REVIEWED. |
| Current CHECKPOINT | Original 36-check CLI result and its original date, eligible only for the restored exact whole candidate; no claim of a new Checkpoint audit. |

The HISTORY revisions share an exact predecessor chain and have cutoffs at
2026-11-10 18:19:26.916026, 22:14:42.330616 and 22:28:56.382125 UTC.
Each digest has its own complete candidate identity. The six original audits
remain separate historical results. The repaired Product's 63 command-backed
observations are not described as 64 independent process executions. Historical
delivery stays unrecorded because today's external delivery file cannot be
backdated; current Product and Checkpoint reports verify that record separately.

Installed CLI history, comparisons, source-integrity checks and export bundle
verification passed. The private quickstart identifies exact ERC revisions,
commands, proof records and outputs. Read the short state/summary at each
Markdown file's start; its later sections retain detailed refs and evidence.

The isolated state preserved every original row and schema across all 20 tables.
Only three Report contract identities, five revisions/publication events and
61 Report source-reference rows were appended. The original Core databases,
approved pilot source, original wheel and all 310 copied referenced artifacts
retained their hashes. The installed task manager and daily database were not
run or opened for reporting. No new audit, paid session, approval or fault/repair
experiment was performed.

## Local architecture analysis

The established Graphify 0.9.102 workflow combines a fresh structural scan with
full-file semantic Markdown fragments grounded in Git blobs and line ranges.
Unchanged fragments can be reused only after exact blob/coverage checks. The
final delivery record binds the private graph, source manifest, output hashes
and representative Report-to-Validation/Workflow/Kernel queries to the actual
final review head. Outputs stay ignored and outside public Git.

Graph edges are navigation aids, not runtime or Validation proof. Unsupported
formats, unresolved historical anchors, external import stubs and unavailable
token telemetry remain explicit coverage limits in that record. No old graph
is manually relabelled as a new scan.

## Separate review and resolutions

A reviewer read connected implementation code and reproduced findings
independently. Changes resolved publication-manifest authentication, delivered
source matching at the same commit, bulk work under the writer reservation,
comparison privacy, incomplete draft/export recovery and missing contract/PRR
history. A later valid-long-prose finding was reproduced and fixed by bounding
the complete presentation note while retaining separate exact identity/hash notes.

The reviewer independently passed 16 focused regressions and a separate long-TDC
reproduction, then reported no remaining actionable implementation defect.
Historical HUMAN review notes preserve exact authority; ordinary new reports
remain `NOT_REVIEWED`. These are technical review observations, separate from
formal product Validation or human acceptance.

## Retention and limits

Source contracts, approvals, Validation results and original evidence remain
immutable. Reports and outputs stay private; this public record contains no
personal delivery path, private planning URL or raw receipt. No destructive
cleanup, paid agent rerun, new approval, fault experiment or daily-data access
is required to obtain a report.

The trusted local OS account, filesystem metadata, authenticated Engine caller
and reviewed evaluators remain part of the model. SQLite and filesystem writes
are separate failure boundaries. A hard crash before an export's first ownership
descriptor may leave an unattributed empty directory; use a fresh destination.
Recognized-secret filtering is a publication guard, not a universal DLP guarantee.
Missing historical mutable state and unavailable process/token telemetry remain
explicit gaps. Observing a launcher file is not a new functional application test.

Live Claude remains `NOT VERIFIED`. Human product acceptance remains
`NOT_REVIEWED` without genuine exact-document authority. Operational build
promotion, Feedback Tracker, full Product Evolution and Bench scoring remain
outside Phase 5. The phase delivers a reviewed PR and does not merge it.

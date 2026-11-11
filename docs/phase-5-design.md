# Phase 5 Report Engine design

The starting main is `2c3bc8a36b86a52658d093042bb0a02378cd1578`, tree
`3074b056f2405e9c0b000c25fc9df6860f051e3a`. Its
[post-merge CI](https://github.com/tito-pereira/Corinthos/actions/runs/43006309503)
passed 441 tests on Windows CPython 3.12.10 and 439 on Ubuntu CPython 3.12.16,
with two Windows-only skips. The completed isolated local wheel also passed 441.
These are baseline observations. Phase 5 records its own final verification.

## Requirements and boundaries

| Requirement | Implementation | Proof |
| --- | --- | --- |
| RF09 and final architecture 2.31 | Operational collection, nine-section composition, five report kinds, Kernel publication, history/comparison and installed CLI/export. | Generated ERC and Markdown from synthetic cases and the approved real pilot. |
| RF10 and 2.12–2.13 | One SQLite read snapshot, exact source/event cutoffs, private frozen generation manifest and restart-safe publication. | Concurrent source changes, interruption, duplicate publication and immutable-history checks. |
| 2.30–2.31 | Exact current results and whole candidate identity, all required proof, source freshness and scope-specific gates. | Later interrupted/failed runs, mixed targets/revisions, damaged non-indexed proof and current versus historical assertions. |
| 2.11, 2.15 and 2.31 | Separate technical, delivery, availability, acceptance and historical feedback states. | Missing-source gaps, explicit trusted delivery import, no invented acceptance or build promotion. |
| Five Commandments and confidentiality | Relevant check/evidence observations or explicit gaps, defined metrics, bounded projections and safe presentation. | Wrong-Commandment evidence, unsupported numbers, secrets, terminal controls, Markdown injection and unsafe paths. |

The existing ERC wire format, Kernel authority and semantic checks remain the
publication boundary. Normal generated reports use REPORT, `approval=null`,
`acceptance=NOT_REVIEWED` and `review_approval_id=null`. The Kernel retains its
trusted exact-document HUMAN boundary for accepted reports. This service adds
no product-acceptance negotiation or technical gate. Collection does not invoke
execution, audit, recovery or publication operations owned by another Engine.

## Services and source snapshot

`report.sources.capture` uses one explicit SQLite read transaction and a pinned
read-only ContractStore view. Canonical documents, publication order, applicable
plans/results and safe operational projections share that snapshot. Both the
publication event time and document time must be within an explicit cutoff.
Current collection chooses the latest applicable result for each exact plan and
whole artifact identity. Checkpoint sets and milestones retain their exact
scope. Module/Integration and other candidates stay supporting or historical
information. Individual checkpoint passes cannot establish a combined gate.

Current eligibility reuses the existing Validation consumer and verifies every
required proof, including proof omitted from the report index. A previously
satisfied result whose proof is now unavailable becomes a reporting gap with
technical `NOT_VERIFIED`. It does not create a blocked VRC. Current target bytes
must have a checked inventory for a validated claim. Source rows and file
identities are checked again at publication. The bounded final integrity guard
allows up to 2,048 evidence references and 32 MiB of evidence, and preserves the
Kernel's in-transaction evidence checks.

An explicit historical cutoff reconstructs immutable publication/event history.
It never invokes the current gate consumer as an as-of oracle or backdates a
mutable execution row. Unreconstructible historical operation state is a stated
gap. Observed evidence availability is dated separately from recorded outcomes.

The manifest preserves exact refs/hashes, operational IDs and event cutoffs,
candidate inventory, selection reasoning, evidence observations and output
digests. Raw negotiations, approval receipts, prompts and stdout are excluded.
A source watermark excludes Report's own contracts/events so publication does
not make another unchanged Report capture falsely stale. Later source changes
invalidate a current publication. Later legitimate history does not invalidate
an explicitly preserved historical cutoff.

## Composition and provenance

`report.composition.compose(snapshot, request)` deterministically produces the
fixed nine payload sections. It keeps one coherent current digest and an exact
historical trail. Different candidates and conflicting source revisions are
partitioned into separate reports and comparisons. Five kinds are supported,
using the existing CHECKPOINT, PLAYTEST_MILESTONE and PRODUCT gate mappings.

M1–M5 use the Kernel's obligation/check mapping and unchanged, verified evidence
objects. Outcomes and gaps remain visible. Per-VRC metrics declare definition,
value, positive check denominator and exact source. Test counts do not imply a
quality score. Unavailable telemetry remains an explicit limitation.

A bounded delivery-record adapter verifies exact Project/package provenance and
reads the package version from verified wheel metadata. It compares package
identity with the selected candidate and observes recorded launcher availability
without running the app or accessing daily data. Paths and original source
digests stay private. Missing or incompatible delivery provenance leaves an
explicit gap. The Core version supplies no product version. Feedback and reviews
are reported only from legitimate existing sources, with original associations.

## Publication, revisions and recovery

`ReportService` provides generate/draft inspection, publish/recover, exact lookup,
list/history, comparison and a separate current-integrity view. A frozen draft
contains the canonical ERC, its content hash and private generation manifest.
Stable report identity and exact predecessor govern sequential revisions.
ERC lookup uses revision history, since ERCs have no active pointer.

Private report-owned artifacts use the existing safe artifact storage. Freeze
and completion writes expose a complete state only after their checks succeed.
Bulk reads, preliminary hashes, composition and rendering occur before a bounded
writer reservation. Publication checks the source guard and calls the existing
Kernel transaction path. A retry first reconciles an already committed exact
revision, then repairs report-owned completion bookkeeping. It never reruns
Validation or Workflow. An idempotent publication return makes no claim that
evidence files were reverified. Current verification is a separate observation.

Existing immutable revisions and report-owned artifact manifests suffice for
this design. No operational SQLite schema migration or dependency is planned.
If implementation disproves that choice, a justified change and genuine v5
upgrade tests are required before adding storage.

## CLI, presentation and exports

The thin `corinthos report` family generates frozen drafts, inspects and publishes
them, lists/reopens history, compares exact revisions, verifies and recovers, and
exports canonical JSON and readable Markdown. Normal operation uses no AI
session and requires no hand-edited ERC JSON.

Canonical JSON remains the exact stored document. Prose projections remove
recognized credentials and unintended private paths before publication.
Markdown additionally escapes hostile controls, links and markup. Immutable
source evidence objects retain their exact bytes and digests. Unsafe fields that
cannot be safely projected without changing identity prevent publication.

Export reserves a new explicit destination directory exclusively, writes bounded
files with exclusive creation and fsync, then writes a completion manifest last.
Existing destinations are preserved. An incomplete owned bundle is inspectable
and recoverable by exact expected hashes. Link/reparse/traversal checks guard
the authorized path. Export failure preserves the published ERC and source data.

## Verification and delivery

The real pilot uses a consistent isolated copy of its existing Core state and
artifacts. It generates a final Product report and separate coherent historical
reports/comparison covering the interrupted, defective and repaired candidates.
The fresh repaired Product result and reused original Checkpoint result retain
their individual dates and identities. Reporting is independently compared with
the six actual audit records, operation history and evidence hashes. Source
contracts, approvals, results, useful app and daily data remain preserved.

Unit/integration/negative tests cover all kinds, partial/no-result data, source
races and cutoffs, scope/target/run integrity, publication history and recovery,
privacy and export failure. Final clean installed wheels run the full suite and
CLI/demo/quality checks on Windows and Ubuntu. Separate technical review, public
snapshot scanning, exact-head CI, local Graphify refresh and factual delivery
records complete the phase. The phase ends at a reviewable PR.

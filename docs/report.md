# Source-backed reports

Report consolidates exact contracts, decisions, operation history and Validation
proof into immutable Evidence & Report Contracts (ERCs). It generates canonical
JSON and readable Markdown through an installed CLI, using deterministic local
code. The [design](phase-5-design.md) explains traceability and failure boundaries.

## Generate, inspect and publish

Use an installed CPython 3.12 environment, the
[verified baseline](../README.md#prerequisites). `PROJECT_ROOT` is the authorized
Core project directory containing its private state. `PROJECT_CONTRACT_ID`
identifies the approved Project Contract. `CANDIDATE_DIR` contains the exact
source and included package files to inventory. Keep exports outside that directory.

```text
corinthos report --root PROJECT_ROOT generate PROJECT_CONTRACT_ID --candidate CANDIDATE_DIR
corinthos report --root PROJECT_ROOT drafts
corinthos report --root PROJECT_ROOT show-draft DRAFT_ID
corinthos report --root PROJECT_ROOT publish DRAFT_ID
corinthos report --root PROJECT_ROOT list PROJECT_ID
corinthos report --root PROJECT_ROOT show REPORT_ID --revision REPORT_REVISION_ID
```

Generation captures and freezes the document without publishing it. Inspect its
scope, candidate, source refs, outcomes, gaps and separate states, then publish
the exact frozen draft. REPORT authority publishes normal technical reports
with null approval and NOT_REVIEWED acceptance. Existing human approvals of a
Project or technical plan provide no product acceptance. The Kernel retains
exact-document HUMAN authority for accepted delivered reports. This service
adds no acceptance negotiation or technical gate.

The generated result supplies the draft and exact report identities. `show`
defaults to readable Markdown. Use `--format json` for canonical JSON. Reports
have no active pointer. An omitted `--revision` selects the latest report
content version through its immutable revision history.

## Select scope and candidate

| Kind | Required scope | Gate support |
| --- | --- | --- |
| `CHECKPOINT` | Repeat `--checkpoint-id` for the complete checkpoint set. | A CHECKPOINT plan for exactly that set. |
| `MILESTONE` | Supply `--milestone-id`. | PLAYTEST_MILESTONE for the exact milestone. |
| `PRODUCT` | The Project. | PRODUCT for the exact project ID. |
| `HISTORY` | Available project history and one coherent candidate digest. | PRODUCT for technical status. |
| `EVOLUTION` | Available lineage and changes, with explicit lifecycle gaps. | PRODUCT for technical status. |

Choose the kind with `--kind`. Module and Integration results remain scoped
supporting information. Several individual checkpoint passes cannot certify a
combined checkpoint set or the entire product.

`--candidate` inventories the current whole candidate, including supported dirty
and untracked files. The identity includes the exact snapshot and a recognized
Git commit where available. Required built files must occupy included paths.
Private state, caches, environments and build directories follow the existing
snapshot exclusion policy. The report bounds candidates to 256 MiB and 8,192
files before hashing. Current validation needs observed candidate bytes.

Use `--snapshot-id`, `--commit` and `--build-id` to bind an explicitly known
identity, including a historical candidate. The CLI accepts either these
identifiers or `--candidate`. Without either, the report records an unknown
candidate and `NOT_VERIFIED`, with explicit gaps. A current satisfied claim
requires its verifiable inventory. An unknown
candidate or missing plan/result produces explicit gaps and NOT_VERIFIED.

## Source capture and time

One SQLite read transaction captures exact published documents, publication
order and safe operational projections. It reads Project and supporting
Workflow, Module, TDC, Validation and revision-request sources without running
their operations. Both publication time and document time must fit the cutoff.
Contracts and event positions remain resolvable in the private generation
manifest. Raw prompts, negotiations, approval receipts and stdout are excluded.

Current selection includes every applicable exact-scope plan and its latest
result for the same complete artifact identity. A newer interrupted or failed
result supersedes an older matching pass. Other candidates remain historical.
The collector checks all required evidence, even when a damaged item is omitted
from the index. A recorded pass whose current proof is inadmissible becomes
NOT_VERIFIED with its reason. It does not create a blocked VRC. An intact actual
blocked VRC can support BLOCKED.

```text
corinthos report --root PROJECT_ROOT generate PROJECT_CONTRACT_ID --kind HISTORY --as-of UTC_CUTOFF --snapshot-id SNAPSHOT_ID --commit COMMIT_SHA
```

Use an ISO timestamp with its UTC offset for `--as-of`. Historical capture
reconstructs immutable publication and operation events at that cutoff. Mutable
execution state is not backdated. Unavailable reconstruction is an explicit gap.
Current evidence availability is observed separately from recorded gate facts.
Supplying a current external delivery file does not establish a historical
delivery event. Historical source facts and candidate identities remain frozen.

## Read the nine sections

The ERC contains scope/cutoff, exact sources, product/delivery lineage,
execution/Validation digest, M1–M5 observations, decisions/change history,
the evidence index, feedback/acceptance and risks/metrics/next actions.

Every Commandment uses relevant unchanged VRC evidence or an explicit gap.
Evidence existence preserves its actual check outcome and method limitations.
Versioned documentation paths and hashes are source references, separate from
Validation evidence. The index contains unchanged evidence objects from cited
VRCs. Operational logs and generated report files retain their own provenance.

Metrics declare an exact VRC source, definition, value and positive check
denominator. Command-backed observations and shared observations are labelled
separately from process executions. Unknown duration/token/process telemetry
stays unknown. Different denominators or more tests imply no universal quality
score. Next actions identify the responsible process and remain advisory.

## Delivery, availability and acceptance

Optional `--delivery-record DELIVERY_RECORD_JSON` imports an existing private
owner-held wheel delivery record. The supported projection uses exact
`project_ref`, `plan_refs`, completed `execution`, `built_package` commit/wheel/
digest and optional `installed.launcher`. It corroborates Workflow completion
from the coherent captured history, retaining a prior completion even after
supersession. The adapter verifies the package, version metadata, full canonical
source inventory and matching packaged Python source bytes. A different dirty
snapshot at the same commit cannot inherit delivery.

The record is bounded to 1 MiB, wheel to 16 MiB and optional launcher to 4 MiB.
Git source verification is bounded in time and size. Missing or unsupported
delivery provenance is stated explicitly. The Core package version never
supplies the product version. Launcher availability records an observed file
and does not run the application or access its daily data.

Delivery, availability, technical validation and human acceptance occupy separate
fields. An adverse technical result does not erase a recorded delivery. Normal
reports remain NOT_REVIEWED. Historical feedback retains its original
build/milestone/session source when supported, and unavailable feedback/review
sources remain gaps. Report provides no Feedback Tracker or build promotion.
Existing Kernel-published HUMAN reviews with matching exact approval IDs retain
their original document hash, dates, delivery and feedback associations in history.
Their acceptance never becomes the new report's approval or acceptance.

## Revision history, comparison and recovery

The default logical report identity is stable for the project, kind and scope.
A changed snapshot follows the exact last revision and increments its content
version. Use `--report-id` for an explicit identity. Use `--previous REPORT_ID
--previous-revision REPORT_REVISION_ID` to bind a requested predecessor, and
`--reason` to explain a correction. Unchanged facts with the same source
watermark reuse the existing capture, avoiding timestamp-only revisions.

```text
corinthos report --root PROJECT_ROOT history REPORT_ID
corinthos report --root PROJECT_ROOT compare LEFT_REPORT RIGHT_REPORT --left-revision LEFT_REVISION --right-revision RIGHT_REVISION
corinthos report --root PROJECT_ROOT recover DRAFT_ID
corinthos report --root PROJECT_ROOT verify REPORT_ID --revision REPORT_REVISION_ID
```

Comparison names both reports, candidates, cutoffs and changed sections. Older
failures stay in history rather than contaminating a current digest. Report
generation never reruns an audit or upstream checkpoint.

Private captures occupy `.corinthos/artifacts/runtime/report-draft-*/`. A frozen
package binds the canonical document to its generation manifest. Completion
bookkeeping follows the Kernel commit. Recovery first reconciles the exact
already-published revision, then finishes that bookkeeping. It preserves identity
when the first response was lost. A duplicate publication return supplies no new
claim about evidence availability. `verify` produces a separate dated observation
and leaves the original ERC untouched.

If capture stopped before a complete frozen package was saved, the incomplete
directory remains inspectable and a new read-only capture can be generated.
Source changes invalidate a pending current publication. Inspect and generate a
new coherent capture. A damaged manifest cannot replace the generation digest
anchored in its published ERC.

## Export and confidentiality

```text
corinthos report --root PROJECT_ROOT export REPORT_ID --revision REPORT_REVISION_ID --destination NEW_EXPORT_DIRECTORY
corinthos report --root PROJECT_ROOT verify-export NEW_EXPORT_DIRECTORY
```

The default bundle contains `report.json`, `report.md` and an export completion
manifest. Select `--format json` or `--format markdown` for one view. Canonical
JSON retains the exact ERC content in canonical serialization with a trailing
newline. Markdown escapes hostile text/links and
provides a sanitized presentation. Recognized sensitive canonical fields block
raw export. Source evidence bytes and their original hashes remain unchanged.
The export manifest binds the exact ERC, generation-manifest digest and actual
output hashes. Verification compares them with the stored source document.

The destination is explicitly authorized by the caller. Its parent must already
exist and remain an ordinary local directory. Link/reparse, reserved-name and
traversal checks apply. The exporter reserves a new directory exclusively and
writes a completion manifest last. Existing user outputs are preserved. A failed
owned bundle stays incomplete and can be recovered by repeating the exact export
on the same frozen input. An export failure preserves its published ERC.
If a hard crash leaves an empty directory before its ownership descriptor was
saved, use a fresh destination; the exporter does not claim an unattributed directory.

Keep reports/manifests and raw evidence private and outside public Git. Retain
required source references, historical observations and proof. This phase adds
no destructive cleanup and promises no complete binary reconstruction from Git.
Evidence availability can change later, which is observed separately. The local
OS account, authenticated Engine caller and reviewed procedures remain trusted.

## Python entry point

```python
from corinthos.contracts import ContractStore
from corinthos.report.service import ReportService

reports = ReportService(ContractStore(project_root))
draft = reports.generate(project_ref, candidate=candidate_root)
published_ref = reports.publish(draft["draft_id"])
document = reports.get(published_ref)
```

`ReportService` also provides `drafts`, `draft`, `latest`, `list`, `history`,
`compare`, `manifest`, `verify` and `recover`. Exact service methods use
`ContractRef` values. `manifest` is a private owner-facing provenance view,
authenticated against the published ERC. Normal terminal output does not dump it.
See the [storage guide](storage.md) for v6 lifecycle persistence and artifact
failure boundaries, and the [evolution guide](evolution.md) for native version,
session, feedback and review sources. Historical lifecycle snapshots reconstruct
post-state events rather than backdating mutable rows. Current generation guards
include lifecycle sources; the optional exact PM review excludes only its own
identified review/consent records. Ordinary reports remain `NOT_REVIEWED`.
Live Claude Code interoperability remains unverified.

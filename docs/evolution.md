# Delivered versions and Interactive Project Evolution

Phase 6 connects the existing Engines through three operational tables, not new
contract types. Approved Project, Workflow, Module and Technology Decision
contracts remain authoritative. See [builds](builds.md), [design](phase-6-design.md)
and [coverage](phase-6-coverage.md). Mandatory live Claude Code interoperability
is unavailable in the current environment; full Core readiness is not claimed.

## Installed starting point

After installing the wheel, run these commands from an authorized project root:

```text
corinthos init .
corinthos adapters capabilities --root .
corinthos project start --help
corinthos project advise --help
corinthos build --help
corinthos version --help
corinthos playtest --help
corinthos project product-review --help
```

Initialization uses packaged approved policy/schema outside the checkout,
validates mandatory M1–M5 and preserves unrelated user instruction content.
Inspect `init --help` for explicit native executable/configuration options.
Missing providers are reported honestly. Free Claude chat does not establish
authenticated Claude Code access. Help, status, history and manual negotiation
start no native work. `project advise` is explicit, advisory and provenance-bound;
its suggestions grant no requirement or Validation authority.

## Delivery and selective evolution

```text
corinthos version deliver BUILD_ID PRODUCT_PLAN PRODUCT_VERSION --package PATH
corinthos version adopt-delivery PRODUCT_REPORT --candidate RETAINED_ROOT --delivery-record RECORD
corinthos version list PROJECT_ID
corinthos version show VERSION_ID
corinthos version verify VERSION_ID
corinthos version evolve VERSION_ID OPERATIONAL --reason "Repair an existing obligation"
corinthos version evolution EVOLUTION_ID
corinthos version impact EVOLUTION_ID
corinthos version negotiate EVOLUTION_ID
```

Delivery requires retained sealed bytes and current independent whole-product
Validation. `--documentation PATH` binds documentation; `--previous-version ID`
preserves incremental lineage in the same project. An identical repeat reconciles
the completed record; conflicting version/package/lineage conflicts. Delivery
records retained packages and does not install a daily app or infer availability.
`adopt-delivery` authenticates an existing Product ERC and its frozen manifest,
verifies the original retained candidate/package and completed execution, and
records that original version without adding a build ID to old Validation.
It inspects no daily launcher, installs nothing and leaves acceptance unreviewed.
Keep the explicitly supplied retained baseline root and delivery files unchanged;
they remain the preserved source of this version. New evolution can then point to
that original version through the same native history.

Evolution binds the preserved version, exact sources, candidate and impact. It
grants no publication authority. The four classes retain their existing paths:

| Class | Required authority/path |
| --- | --- |
| `OPERATIONAL` | Workflow repair/retry/recovery and relevant Validation; unchanged Project obligations. |
| `INTERNAL_REPLAN` | Existing Workflow publication with verified bounded delegation or actual HUMAN authority. |
| `BINDING_PLAN` | Pertinent actual HUMAN technology, interface or milestone decisions. |
| `PROJECT_CHANGE` | `version negotiate` opens a real PM revision session; the owner approves the actual successor. |

Use existing `workflow reconcile`, recovery and PM PRR intake for affected work.
Impact inspection rewrites neither contracts nor old attempts. Unchanged work
needs explicit compatibility evidence; affected work is repaired and revalidated.
User-originated global changes need no invented PRR. Bugs, missing evidence and
agent limitations are not automatic structural incompatibilities. Consent remains
bound to its original exact base.

## Promotion and sessions

Complete approved cumulative checkpoints, materialize an isolated candidate,
record Workflow readiness, then obtain independent exact `PLAYTEST_MILESTONE`
Validation. These stages are separate. Newer unfinished/blocking proof prevents
admission despite an older pass. Complete sealed bytes and manifest determine
build identity; a caller-supplied build label cannot establish it.

```text
corinthos playtest enable PROJECT_ID
corinthos playtest status PROJECT_ID
corinthos playtest promote PROJECT_ID BUILD_ID
corinthos playtest start PROJECT_ID
corinthos playtest sessions PROJECT_ID
corinthos playtest end SESSION_ID --process-stopped --effects-inspected --summary "Actual observations"
```

Enable and start are explicit. Promotion records readiness locally without
launching a test or requiring participation. One project row owns one stable
tracker, one active build and at most one pending successor. Sessions pin actual
immutable build origins and fresh isolated data. A successor waits while old
sessions remain. Agent disappearance never releases pins. End requires actual
stopped-process/effect inspection and remains available if pending proof goes
stale; repeat `promote` separately to recheck eligibility.

`playtest switch SESSION_ID BUILD_ID` creates a voluntary successor session after
inspection, requiring the last old pin and compatible cumulative scope. Old
session origins remain unchanged. Across Workflow revisions, promotion requires
the exact approved descendant, current reconciliation analysis and the actual
execution reconciliation chain. Affected checkpoints need fresh completion;
carried attempts retain their checked original identities. Unrelated lineage and
cumulative scope regression conflict. Session start
prepares a pin/data path; the minimum local journey launches no application or
background daemon.

## Feedback and optional product acceptance

`playtest feedback PROJECT_ID BUILD_ID --body TEXT` records an operator
observation for a previously eligible build. `--interactive` collects actual foreground
terminal input. Automated fixtures retain synthetic labels. Feedback permanently
binds code, milestone, tracker, time and optional session. Triage changes audited
treatment, never observation origin. BUG routes to Workflow/Validation; REQUIREMENT
routes to PM. Routing intent does not claim an actual repair or PRR was created.
Inspect `feedback-list` and `triage --help` for the explicit follow-up journey.

PM's `project product-review` start/show/freeze/approve/defer journey derives a
separate frozen ERC from a normal Product report and verified delivered version.
The owner sees the exact document and enters a fresh foreground OS terminal
challenge. REPORT authority publishes through the Kernel. Receipt creation,
consumption and review completion share one transaction. Piped text, agent
messages, synthetic fixtures, changed documents and replayed receipts supply no
production consent. No review leaves acceptance `NOT_REVIEWED` and does not block
technical work. Reservations preserve technical results and inform negotiation.

## Recovery, retention and limits

Status and operation commands inspect durable state. Build/readiness/session
operations reserve IDs before effects; completed repeats reconcile. Unfinished
effects require actual inspection rather than blind retry. `build recover` and
`playtest abandon` preserve partial files and existing pins when safe completion
cannot be established. SQLite cannot atomically commit external processes/files.

`playtest retention-preview PROJECT_ID` binds owned paths, inventories, policy and
protected references. `retention-apply` requires the exact preview hash and fresh
guards. Active, pending, pinned, delivered and essential proof references remain
protected; retain a prior promoted rollback candidate where possible. Report
storage pressure when nothing can safely be removed. Metadata/events remain.
Actual deletion tests use isolated test-owned artifacts, never real pilot history.

Follow [backup/recovery](storage.md#backup-and-recovery) on a populated separate
copy. Use SQLite-supported snapshots accounting for WAL, retain artifacts, verify
integrity/references and preserve originals. Conversation context is not a native
resume token. This local Core trusts the controlling account: path/link checks,
bounded work and process cleanup do not sandbox hostile code or administrators.
Pinned tool/configuration hashes support local recipe provenance, not a hermetic
environment or universal binary reconstruction.

## Reports and API

Report captures lifecycle origins/events/project pointers coherently. Historical
cutoffs reconstruct prior snapshots from immutable post-state events. PRODUCT,
MILESTONE, HISTORY and EVOLUTION include lineage, readiness, sessions and feedback;
CHECKPOINT remains supported. Ordinary reports stay `NOT_REVIEWED`; prior human
decisions retain their original scope. Private manifests retain detailed origins;
public projections preserve existing redaction/safety. Relevant changes invalidate
unpublished current captures.

Python services are `corinthos.lifecycle.builds.BuildService`,
`corinthos.lifecycle.versions.VersionService`,
`corinthos.lifecycle.playtest.PlaytestService` and
`corinthos.project_manager.product_review.ProductReviewService`.
They reuse `ContractStore` and accept an authorized root or store.
`LifecycleRepository` provides immutable origins, CAS snapshots and append-only
post-state events; Engine services enforce domain transitions. Direct SQL editing
is not a supported operator journey.

# Independent Validation

Validation audits exact candidates against independently derived obligations. It
reads the approved Project Contract and Standard directly, adds applicable
Module, Technology Decision and Workflow obligations, and records the scoped
Verification Matrix in a Validation Contract (VC). A run publishes a separate
immutable Validation Result Contract (VRC) from actual observations and
admissible evidence.

The [design and traceability record](phase-4-design.md) describes requirements,
authority and failure boundaries. The [engineering verification](phase-4-verification.md)
records observed regression and real-pilot evidence. The
[Contract Kernel guide](contracts.md) explains publication and immutable references.

## Choose the audit scope

| Scope | Exact target contract | Target IDs | Gate |
| --- | --- | --- | --- |
| `MODULE` | Module | The module ID | `CHECKPOINT` |
| `INTEGRATION` | Workflow | Declared module or interface IDs | `CHECKPOINT` |
| `CHECKPOINT` | Workflow | Checkpoint IDs | `CHECKPOINT` |
| `PLAYTEST_MILESTONE` | Workflow | Milestone IDs, with cumulative prerequisites | `PLAYTEST_READINESS` |
| `PRODUCT` | Project | The project ID | `PRODUCT_VALIDATION` |

A local result covers its declared obligations. A product matrix also requires
global Project requirements, constraints, success criteria and applicable
Workflow sources. Green local tests do not discharge omitted global obligations.
Validation assesses a milestone candidate's technical readiness. Workflow
coordinates Build Readiness; [playtest promotion](evolution.md) consumes its
separate current admission gates.

## Derive and review a plan

Use an installed CPython 3.12 environment, the
[contributor setup](../README.md#contributor-setup), and an existing project directory
containing approved contracts. Set `PROJECT_ROOT` to that directory.
`STANDARD_YAML` and `STANDARD_SCHEMA` are the paths to the existing Standard
files in the Corinthos checkout. Use real IDs from your published references.

```text
corinthos validation --root PROJECT_ROOT --help
corinthos validation --root PROJECT_ROOT plan PROJECT_ID --scope PRODUCT --policy STANDARD_YAML --policy-schema STANDARD_SCHEMA
corinthos validation --root PROJECT_ROOT drafts
corinthos validation --root PROJECT_ROOT show-draft DRAFT_ID
```

To derive a checkpoint plan, use
`plan PROJECT_ID --scope CHECKPOINT --target WORKFLOW_ID --target-id CHECKPOINT_ID`
with the same policy flags. For scopes with several IDs, repeat `--target-id`.
Optional `--revision` and `--target-revision` select exact revisions. Publication
requires current approved sources. Resolve drift through the existing revision
process before creating a new plan.

Inspect the source references, criterion, required evidence, method constraints
and gate classification for each check. Then bind and independently review each
check in the foreground terminal.

```text
corinthos validation --root PROJECT_ROOT bind DRAFT_ID CHECK_ID --evaluator EVALUATOR_ID
corinthos validation --root PROJECT_ROOT publish DRAFT_ID --evaluator EVALUATOR_ID
corinthos validation --root PROJECT_ROOT show-plan PLAN_ID --revision PLAN_REVISION_ID
```

Enter a substantive rationale about the exact assertion or observable fact
that evaluates the criterion. A presence check can establish that a file
exists. Accuracy of installation instructions requires inspecting the relevant
instructions and their behavior. For an approved formula, use observed expected
values and relevant negative cases. A return code or a green count alone gives
no criterion-specific proof. Complete every binding, retain the approved
method and evidence requirements, and record why the methods are adequate.
Changes to binding bytes or the criterion invalidate its earlier method review.

The planner derives M1–M5, source obligations and scope coverage. Kernel
publication separately enforces mandatory coverage, exact references and
authority. Validation publishes the VC using its own Engine provenance under
existing approved obligations. Any change to binding product decisions goes
through the applicable owner approval. The exact published revision anchors
the typed procedure mapping, adequacy reviews and Standard digest.

## Supported observations

| Evidence kind | Procedure |
| --- | --- |
| `Independent check observation` | A reviewed executable observation, exact inspected files, or both as appropriate to the criterion. |
| `Independent review record` | Inspection of bound candidate-relative files with actual findings. |
| `Observed check results and a technical review tied to the implementation commit.` | A command observation and independent inspection tied to a verified Git source snapshot, directly or through a verified sealed build manifest. |

Bind a direct executable and separate arguments. The executable and absolute
evaluator inputs are pinned by digest. Each `{candidate}` or `{scratch}`
placeholder must occupy a full argument. Use up to 64 arguments including the
executable, a timeout of 1–600 seconds, and an exact success line of up to 512
characters. A demonstrated-failure line is optional and has the same limit. A
trusted reviewed procedure must produce its success line once with exit 0, or
its contradiction line once with exit 1. Combined command output is bounded
to 1 MiB and must be UTF-8. Unavailable tools, other exits, ambiguous output,
timeouts, changed inputs and unconfirmed process cleanup are unverified
observations. Arbitrary shell wrappers and unrecognized evidence kinds are
outside the supported procedure model.

Use portable candidate-relative files for review. The reviewer inspects those
files in the exact candidate copy and records criterion-specific observations
in the foreground terminal. Missing files or an unavailable reviewer leave the
affected check unverified. Domain integrations may supply a separately trusted
reviewer callback bound to the same identity and observed files.

The evaluator process and local account are trusted to run and inspect the
approved procedures. A different identifier alone supplies no independence.
The implementation publisher cannot act as the evaluator for that plan. Keep
method review and candidate evaluation separate from implementation and use
actual inspected evidence. A prior engineering review flag, a synthetic fixture
and the implementing agent's message carry no formal Validation authority.
Neither a plan nor a satisfied technical gate represents human acceptance.

## Run, inspect and recover

```text
corinthos validation --root PROJECT_ROOT run PLAN_ID --revision PLAN_REVISION_ID --candidate CANDIDATE_DIR --evaluator EVALUATOR_ID
corinthos validation --root PROJECT_ROOT runs
corinthos validation --root PROJECT_ROOT show-run RUN_ID
corinthos validation --root PROJECT_ROOT history RUN_ID
```

Use an ordinary existing candidate directory. Include all source and generated
files needed to evaluate the candidate. The runner inventories supported files,
binds their hashes to the snapshot identity and includes the commit for an exact
recognized Git root. A Git commit alone gives no identity for dirty, untracked
or generated inputs. Private state, virtual environments and ordinary cache and
build directories are excluded from the inventory. Put required built artifacts
at explicit included paths. The runner copies the identified bytes into private
state up to a 256 MiB copy limit, observes that isolated copy and checks for
drift. Commands get separate scratch data, bounded output, time and process
ownership. Native OS policy or caller isolation governs which files the
evaluator process can access.

For a sealed Build, Validation verifies the owned candidate and manifest before
using the original source snapshot's Git commit for compound evidence. The
candidate retains its complete build identity; the evidence envelope records
the source identity and manifest hash separately as `build_source`. A supplied
build ID or a file claiming a source commit cannot establish this provenance.

A completed command or inspection can support `CONFORMANT` or
`NONCONFORMANT` when the planned evidence is sufficient. Missing, interrupted
or inadequate evidence yields `NOT_VERIFIED`. An optional check may be
inapplicable only with a scope-specific justification and no mandatory
obligation is exempted. A demonstrated failing check can be covered while its
gate remains blocked. A satisfied gate requires completed execution and all
mandatory checks conformant with admissible evidence. The CLI returns success
for a satisfied run and failure for a blocked or unverified run.

Review the result reference and its gate, check results, evidence and findings
with `show-run`. Evidence envelopes are stored privately under
`.corinthos/artifacts/runtime/<run-id>/`. Each binds the exact VC, run, check,
source, method, evaluator and entire candidate identity to a unique file and
verified digest. Keep private data and credentials out of commands, rationales,
and evidence before sealing. Retained observations include command arguments,
pinned input hashes, process termination facts and matched observations. A
reviewed procedure can emit up to eight additional retained lines prefixed
`Observed: ` or `Observed contradiction: `. They are bounded and recognizable
token patterns are redacted. Keep all emitted details suitable for retention.
Unsupported or omitted output cannot become proof merely through its digest.

An interrupted process can leave a retained run without a result. Inspect the
recorded effects and confirm processes stopped before recovering.

```text
corinthos validation --root PROJECT_ROOT recover RUN_ID
corinthos validation --root PROJECT_ROOT publish-frozen RUN_ID
```

Recovery asks for exact `STOPPED` and `INSPECTED` confirmations and an actual
inspection reason. It preserves valid partial observations and publishes an
interrupted blocked result. When an exact result is already frozen, use
`publish-frozen` to reconcile its publication. It uses the same run and result
identity. Damaged evidence cannot be republished as intact. A fresh run uses a
new identity and can cite `--previous-run RUN_ID` after the earlier run is
finalized. Lease expiry provides no permission to repeat uncertain effects.
The [storage guide](storage.md) describes v5, verified backups and recovery.

## Workflow, findings and revalidation

Configure applicable formal scope expectations through
`workflow configure ... --formal-audits` or retain applicable managed plans
already discovered by Workflow. An explicit expectation blocks if its plan or
admissible result is missing. The [Workflow guide](workflow-execution.md) shows
the exact retained candidate and recovery flow.

```text
corinthos workflow --root PROJECT_ROOT audit-request ATTEMPT_ID
corinthos validation --root PROJECT_ROOT run PLAN_ID --workflow-attempt ATTEMPT_ID --evaluator EVALUATOR_ID
corinthos validation --root PROJECT_ROOT impact PLAN_ID --revision PLAN_REVISION_ID
```

The request identifies a retained verifying or blocked candidate. Validation
checks the exact requested scope and expected artifact identity. It does not
take ownership of the Workflow implementation lease. Workflow consumes current
admissible scoped results, rechecks applicable gates before completion and
reassesses relevant dependencies before downstream work. A newer matching
blocked result prevents reuse of an older pass.

Use findings to investigate and repair within approved obligations. Workflow
coordinates correction and resubmission. Validation reports the observed
contradiction and affected scope. For a code repair with unchanged criteria,
run the existing plan on the new candidate. When approved sources, criteria or
methods change, inspect the affected obligations and provider/consumer terms,
then publish from a newly derived draft using the exact previous active VC.
Use `publish DRAFT_ID --evaluator EVALUATOR_ID --previous PLAN_ID --previous-revision PLAN_REVISION_ID`
to bind the successor to that revision.
Keep earlier evidence on its original sources and candidate. Rerun checks where
continuing validity cannot be established. Ordinary bugs stay in the repair
loop. An evidenced structural conflict follows the existing Project Manager
route.

## Python entry points

```python
from corinthos.validation.planning import ValidationPlanner
from corinthos.validation.repository import ValidationRepository
from corinthos.validation.runtime import ValidationRunner
```

`ValidationPlanner(store, policy_path, policy_schema_path)` provides `derive`
and `publish`. `ValidationRunner(store)` provides `inspect_plan`,
`inspect_impact`, `run`, `recover` and `publish_frozen`. The
`ValidationRepository(store)` exposes drafts, exact plan bindings and run
history. Pass exact `ContractRef` values to service methods that take contract
references. An integration that supplies a reviewer callback must enforce its
own reviewer identity and preserve actual method and artifact observations.

## Reproduce the isolated pilot audit

Use the approved task-manager source and wheel from the owner's existing
delivery and a separately authorized copy of its exact Core project state.
Stop writers before copying the state and preserve the referenced artifacts.
Use a clean candidate copy, including the identified wheel at an included path.
Retain exact source and package hashes. Keep the installed app and its daily
database outside the audit.

Derive the applicable local and product plans. Bind inspected procedures that
install the exact wheel offline into a separate Windows Python 3.12 environment
and exercise its actual launcher. Use explicit isolated databases to observe
records, task operations, errors, Unicode, backup and restore. For the default
path check, set the launched process's `LOCALAPPDATA` to a dedicated audit
directory, start from two separate working directories, and check that the
same task persists after process restart and reinstall. Independently inspect
the approved interfaces, technology and installation/backup documentation.

Keep a separate candidate for controlled defects. A changed default database
path can leave explicit-database local tests green while the product path and
persistence checks fail. Retain the failed run, coordinate the correction
through Workflow and audit the repaired candidate with the same VC when the
approved criteria and methods are unchanged. Preserve each result's exact
scope, evidence and limitations.

The [Report Engine](report.md) consolidates exact plans, results and retained
evidence into immutable ERCs. The [lifecycle guide](evolution.md) covers delivered
versions, evolution and optional product review; the [build guide](builds.md)
covers sealed identity, readiness and playtest admission. Live Claude remains
unverified.

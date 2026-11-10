# Workflow execution, recovery and revision reconciliation

The Phase 3 E–G runtime executes one eligible checkpoint at a time from an exact
approved Workflow. It reconstructs bounded context, invokes the chosen adapter,
runs actual commands, verifies declared files and records explicit preliminary
technical review. Durable attempts and original artifact identities explain what
was observed. Independent Validation, Report and formal product acceptance retain
their separate authority.

Start with the [planning journey](workflow-planning.md) and the
[adapter prerequisites](adapters.md). Each project has its own existing authorized
root and private `.corinthos/` state. The execution workspace is that project root.
Keep the selected pilot source separate from Corinthos source, and keep the
pilot's daily application database separate from both project and test data.

## Configure actual checks without editing JSON

Use an installed or activated `corinthos` executable. Substitute the actual
approved Workflow contract ID and an existing project root.

```text
corinthos workflow --root PROJECT_ROOT configure WORKFLOW_CONTRACT_ID --policy STANDARD_YAML --policy-schema STANDARD_SCHEMA
```

Choose the exact published Workflow revision. For each approved checkpoint, the
guided questions collect the following bindings.

- Map every verification-plan item to an actual automated command or explicit
  technical review. Every checkpoint needs at least one automated command.
- Enter the executable and each argument separately. Values are passed directly
  as an argument list, with `shell=False`. Select the relative working directory.
- Map every declared deliverable to concrete relative file paths.
- Specify explicit permitted source files or directories. Paths must be portable
  and contained in the authorized workspace. Private state and Git internals
  remain protected.

Active published checkpoint Validation plans are discovered and attached as
required gates. Configuration exposes those exact references. The runtime also
checks applicable plans during execution. A missing, failed, stale, interrupted
or wrong-artifact result cannot satisfy an independent gate. The CLI provides
no switch to disable this policy or manufacture a Validation Result.

Before recording completion, the trusted runner repeats source/cancellation/plan
checks, rediscovers applicable active Validation plans and consumes their current
evidence under the SQLite writer reservation. Those observations commit with the
completion result. A supplied result must be the latest published run for the
same exact plan and artifact. A newer failed or interrupted matching run blocks
an older pass. A result for another artifact does not replace that scoped run.

For example, a Python verification command can use the actual interpreter path,
then separate arguments `-m` and `pytest`. A deliverable such as "Source and
tests" can map to `src/tasks/store.py` and `tests/test_store.py`. These are user
bindings to the approved wording. They grant no additional product scope.

Accepted configuration registers an execution ID without invoking an agent.
Identical registration is idempotent. A conflicting configuration needs explicit
reconciliation. The same project root and Standard paths must be used on return.
The policy files belong to the Corinthos checkout and must be supplied explicitly
when using the installed wheel from another working directory.

## Commands and native provider setup

| Command | Behavior |
| --- | --- |
| `workflow configure CONTRACT_ID [--revision REVISION_ID]` | Bind an exact approved Workflow to real checks and files through guided questions. |
| `workflow executions` | List durable execution identities and states. |
| `workflow status [EXECUTION_ID]` | Show checkpoints, attempts, evidence and lease observations. |
| `workflow execute [EXECUTION_ID] --provider codex --timeout 300` | Run one currently eligible checkpoint, actual checks and explicit technical review. |
| `workflow execution-history [EXECUTION_ID]` | Inspect append-only runtime observations. |
| `workflow recover [EXECUTION_ID] [CHECKPOINT_ID]` | Inspect previous effects, then explicitly choose retry readiness, verification-only or blocking. |
| `workflow reconcile EXECUTION_ID CONTRACT_ID [--revision REVISION_ID]` | Compare a replacement approved plan, validate its bindings and create a successor execution. |
| `workflow changes CONTRACT_ID [--revision REVISION_ID]` | Inspect exact active-source drift and conservative affected/preserved IDs. |
| `workflow request CONTRACT_ID [--revision REVISION_ID] [--request-id REQUEST_ID]` | Diagnose structural incompatibility, route a direct owner change, or retain ordinary repair scope. |

All commands accept `workflow --root PROJECT_ROOT`. Runtime configuration,
execution, recovery and reconciliation also accept `--policy PATH` and
`--policy-schema PATH`. `--provider` is `codex` or `claude`. If discovery cannot
find the verified native executable, specify `--provider-executable PATH` and
repeat `--provider-arg VALUE` for each fixed host-prefix argument. This supports,
for example, a verified `node.exe` host followed by its actual provider script.
Provider-specific supported interfaces, authentication and enforcement limits are
documented in [adapters](adapters.md). Windows shell scripts are rejected as
executable hosts. Native sandbox/approval settings remain in force.

Agents, check commands and discovery use the shared owned-process lifecycle.
Windows assigns suspended starts to a kill-on-close Job before resuming them.
POSIX uses an isolated process group. Finalization also cleans up ordinary
descendants after a successful parent exit. Unconfirmed cleanup remains a
recovery blocker. These controls manage the owned process tree, while deliberate
effects through external services or brokers retain the
[adapter boundary's limits](adapters.md#discovery-and-invocation).

Running `execute` requests one attempt. A provider exit code or "done" statement
does not complete a checkpoint. Use `status` to inspect its observed result before
requesting another eligible checkpoint. Native resume is restricted to its
verified provider/context binding. A fresh process reconstructs durable context
and uses an explicit new attempt when the old native binding is unavailable.

`execute` returns success only for a completed attempt or an execution that was
already complete. Blocked/interrupted attempts and a noncomplete execution with
no eligible work return a failure status. Verification-only recovery also returns
a failure status while its checks or technical review remain blocked.

## Actual preliminary technical review

The local CLI reviewer opens the real foreground OS terminal and displays the
checkpoint, all completion criteria, exact source/artifact identity, changed
paths, declared deliverables, actual command results and retained evidence.
After inspecting those facts, enter the fresh exact `ACCEPT` challenge and
record actual observations. Other input records reservations. Piped input cannot
provide this production reviewer action.

This review is preliminary engineering control under the construction plan.
It supplies neither a contract approval receipt nor a Phase 4 Validation Result
or human product-acceptance record. Domain integrations can inject an independent
trusted reviewer callback, while preserving the same complete criterion and
artifact binding. Synthetic positive-review fixtures remain test evidence only.

Every declared output must exist and match its permitted path and content
inventory. Unexpected changed paths, failed commands, incomplete criterion
review or missing required gate evidence keep the attempt blocked or unverified.
Changing an artifact after review requires renewed verification of that artifact.

## State, leases and recovery

Checkpoint progression is `PENDING` → `READY` → `RUNNING` → `VERIFYING` →
`COMPLETED`. `BLOCKED` and `INTERRUPTED` preserve exceptions. Explicit inspected
recovery atomically transitions an unfinished checkpoint through `RECOVERING`
to `READY` for retry, `VERIFYING` for existing-file checks, or `BLOCKED`.
Append-only `RECOVERY_STARTED` and `RECOVERY_INSPECTED` events retain those
transitions. A failed transaction rolls back its state, fence and events.
The runtime checks dependencies and exact current
Project/Workflow/Module/Technology bindings before effects and at continuation
points. Claim transactions repeat those source checks under the SQLite writer
reservation.

The workspace lease permits one owned attempt at a time. Owner identity,
expiry and an increasing fencing generation prevent a stale process from
completing another attempt. Expiry alone supplies no permission to rerun
uncertain external effects. Heartbeats renew ownership and check for source
changes. Interrupted cleanup remains visible and can retain a blocking lease.

`recover` shows the earlier attempt and the current workspace inventory. Inspect
the process, working tree, artifacts, tests and external effects first. Enter
`STOPPED` and `INSPECTED` only after those observations are true, then record a
specific summary and choose an outcome.

| Recovery choice | Effect |
| --- | --- |
| `RETRY` | Mark ready for a separately requested new agent attempt, retaining the predecessor attempt. |
| `VERIFY` | Create a new verification-only attempt against the inspected current artifact, without dispatching the agent again. |
| `BLOCK` | Preserve incomplete state and evidence while diagnosis continues. |

Recovery retains immutable source references and actual observations. It never
deletes unknown user changes or promises exactly-once Git/process effects.
SQLite state, filesystem writes, Git operations and external processes have
separate transaction boundaries. Preserve originals on storage errors and use
the [backup and migration guide](storage.md).

## Revision impact and preserved work

`RevisionReconciler.inspect` follows the Workflow's canonical active bindings.
Archived Project/provider references can continue proving unchanged obligations
or compatible consumed terms. They remain exact readable history rather than
being silently relabelled as new evidence. Any changed active canonical source
blocks dispatch under the old execution plan.

`compare` maps stable obligation changes, exact module/technology changes,
provider-consumer dependencies and checkpoint dependencies to an affected set.
Changed scope, global constraints, success criteria or unscoped decisions
conservatively affect the plan. Affected checkpoints propagate to dependent
checkpoints and milestone plans. Formatting checks cannot prove arbitrary
natural-language compatibility.

Publish the applicable approved replacement plan before `reconcile`. The CLI
shows proposed affected/preserved IDs and lets the operator retain or replace
actual command/file bindings. Domain validation checks those bindings again.
Only unchanged `COMPLETED` checkpoints are eligible for inheritance. Changed
configuration resets that checkpoint and any dependent whose prerequisite was
reset. After configuration choices, the CLI displays exact carried, reset and
removed checkpoint IDs before recording the reconciliation reason.
The repository creates a successor execution only after its lease and current
sources are safe. It carries eligible completed work by an explicit reference
to the old execution, Workflow and attempt. Original artifact/evidence identities
remain unchanged. The repository independently applies stricter compatibility
checks before accepting any proposed preservation set.

Ordinary repair, retry, resumption and agent switching preserve product
obligations and create operational history. A real bounded internal replan may
create a Workflow successor under a verified mandate. Binding technology,
interface or milestone changes require applicable new human authorization.
Global requirement changes return to Project Manager and the owner.

## Bounded structural requests and direct owner changes

`workflow request` asks which situation applies. Ordinary bugs, failed checks,
missing evidence and agent limitations stay within repair/recovery. An owner's
direct product change opens a real Project Manager revision session without a
manufactured structural conflict.

For an actual structural conflict, the guided questions collect affected stable
Project IDs, confirmed facts, uncertainties, an exact published contract source,
truthful limitations, real alternatives or a reason none are available, and a
bounded impact statement. The complete diagnosis is shown before `REQUEST`
publishes through `ContractStore.publish`. The request carries no HUMAN approval
claim and changes no approved product requirement.

Contract-only evidence uses `evidence_ids: []` with explicit limitations. Nonempty
IDs require an actual published Validation Result containing those evidence IDs.
The service rejects stale/cross-project bases and impact outside the exact plan.
A stable `--request-id` supports idempotent retries of the same diagnosis.
Changing an already used request identity fails as a conflict.

The printed exact request reference can enter the existing `project request`
journey. Its PM session preserves unaffected obligations and records keep,
return, clarification, deferral or an explicitly human-approved changed revision.
Keeping or deferring creates no new Project revision. The request itself grants
no authority to change the product.

## Public service entry points

```python
from corinthos.workflow.execution_repository import ExecutionRepository
from corinthos.workflow.reconciliation import RevisionReconciler
from corinthos.workflow.runtime import WorkflowRunner
from corinthos.workflow.verification import CheckpointSpec, CommandCheck, TechnicalReview
```

- `WorkflowRunner(project_root, adapters, reviewer=...)` provides
  `prepare_bindings`, `configure`, `run_next` and `verify_existing`.
- `CheckpointSpec` binds approved deliverables, `CommandCheck` argument lists,
  explicit allowed paths, review items and actual `RequiredGate` references.
- `ExecutionRepository` provides durable registration, get/list/history, attempts,
  fenced transitions, explicit `recover` and conservative `reconcile`.
- `RevisionReconciler(store_or_root)` provides `inspect`, `compare`,
  `create_revision_request`, `negotiate_request` and `start_project_revision`.

These APIs use the existing Kernel and private SQLite schema. Full general
product-evolution automation, builds promoted for playtest, independent
Validation/Report and formal product acceptance remain later-phase capabilities.

# Agent adapters

The Adapter Manager shares a validated versioned Standard and bounded context
with separate Codex and Claude Code command adapters. It discovers installed
capabilities, prepares explicit managed instructions, starts an external process
and returns observed events and results. Checkpoint scheduling and durable
execution recovery require later authorization beyond construction checkpoint B.

## Policy and context

Construct `AdapterManager(policy_path, policy_schema_path, *, store=None,
commands=None)`. Both paths are explicit files supplied by the caller. The
existing Standard loader validates them, and the adapter additionally requires
version `0.1` with mandatory M1, M2, M3, M4 and M5. The installed wheel uses
these supplied policy files. The caller must provide them with its deployment.

An actual task uses `ContextInput` with an existing `ContractStore`. Its fields
are `workspace`, `project_ref`, `objective`, `deliverables`, `verification_plan`,
`module_refs`, `technology_refs`, `workflow_ref`, `interface_obligations`,
`prior_facts`, `task_id` and `attempt_id`. References use the existing typed
`ContractRef`. The service resolves every supplied reference, checks its type,
project and active revision, and confines the workspace to that store's project
root. Task and attempt IDs are generated when omitted.
Supplied Modules and technology decisions must match the exact supplied
Workflow selections and their Module associations. The Workflow must reference
the same exact Project revision as the task.

The prompt contains the same canonical Standard, Standard digest, exact approved
documents, task obligations and prior facts for both providers. Each invocation
reconstructs that context. Contract approval remains with the trusted Kernel
caller and the applicable human decision.

## Explicit instruction preparation

`prepare(provider, workspace, *, context=None)` composes the mandatory Standard
into `AGENTS.md` for Codex and `CLAUDE.md` for Claude. An existing
`AGENTS.override.md` is the effective Codex target. Optional task context is
validated and identified by digest, while dynamic task data travels through
stdin during invocation.

The managed section carries a checksum. Preparation preserves existing bytes
outside that section, including UTF-8 BOM and line endings. Repeating the same
preparation is idempotent. Partial, duplicated or edited managed sections require
explicit conflict resolution. Linked files, redirected directories, oversized
files and concurrent changes detected before replacement are rejected.
Review instruction-file changes before committing them.

`invoke` and `probe` leave instruction preparation to this explicit action.
Codex's instruction hierarchy can select overrides and has a configured size
limit. Native instructions communicate policy, while the supplied stdin context
also carries the complete mandatory Standard. The adapter reports capabilities
without promising that natural-language instructions enforce every obligation.

## Discovery and invocation

`discover("codex")` and `discover("claude")` inspect native executable version
and help output. Discovery records the supported JSON, stdin, exact resume and
restricted diagnostic capabilities. Missing or unsupported installations produce
an explicit result. On Windows use a native executable, including a native
binary supplied by an installed CLI package. Batch and PowerShell wrappers are
rejected. `commands` permits trusted explicit executable-prefix argument tuples
for an integration or a labelled synthetic test harness.

The verified Codex command family uses `exec --json -`. A diagnostic adds
`--sandbox read-only`. The separate Claude integration uses
`--print --output-format stream-json --verbose` and piped text, after discovery
confirms those flags. Its restricted diagnostic disables built-in tools and MCP
tool calls with supported flags. Existing user authentication and native
configuration remain inherited. Configured hooks and services retain their own
effects, so a worktree or tool restriction alone is insufficient to guarantee
an OS sandbox.

`invoke(provider, context, *, timeout=120, cancel=None, on_event=None,
resume_session_id=None)` performs one explicit process call. The command is an
argument list with `shell=False`, the working directory is explicit and the
prompt travels over stdin. The native process inherits the current environment
to preserve authentication and settings. Environment values and raw stderr are
excluded from normalized events and diagnostics.

Timeouts use a monotonic clock. Output has line, total-byte and event-count
limits. Cancellation uses an isolated process group on POSIX and native
process-tree termination on Windows. The result records whether cleanup was
confirmed. A restricted host may deny process-tree cleanup, which requires
operator inspection before another attempt. The adapter performs no retries.

## Results and native resume

`AgentResult` records provider, status, task/attempt IDs, observed version, exit
code, native session ID, normalized progress events, final output, usage, cost
estimate, telemetry scope, error kind, elapsed seconds and cleanup status.
Statuses include `COMPLETED`, `FAILED`, `TIMEOUT`, `CANCELLED`, `UNAVAILABLE`,
`UNSUPPORTED` and `PROTOCOL_ERROR`.

Completion requires zero exit status and the provider's terminal success event.
Partial or malformed streams, missing completion, structured authentication or
quota failures and failing observers remain explicit. Agent output is untrusted
data for subsequent engineering verification. The adapter does not activate a
checkpoint or manufacture an approval from that output.

Native resume requires a specific observed UUID and supported native flags.
The manager binds it in memory to the provider, workspace, Standard and approved
task context, with confirmed prior cleanup. Only the attempt ID and prior facts
may differ. The binding prevents blind cross-context reuse and simultaneous
resume through the same manager. Process restart loses this binding. Durable
execution recovery belongs to the subsequent checkpoint F and requires renewed
authorization before implementation.

Token and cost fields remain null when unavailable. Codex turn usage is observed
from its completion event. Claude's reported conversation cost is a client-side
estimate and may include earlier resumed turns. Consumers must preserve this
scope when recording or comparing resource use.

## Advisory Project Manager boundary

`pm_assistance(provider, workspace, *, timeout=60)` returns a callable for the
existing Project Manager assistance argument. Explicit opt-in creates this
connection. It receives detached session data and returns advisory strings.
Unavailable or incomplete responses remain visible as an advisory limitation.
Project Manager retains its negotiation history, draft edits and foreground
terminal approval boundary.

`probe(provider, workspace, prompt, *, timeout=60, cancel=None, on_event=None)`
is a separate restricted engineering/advisory diagnostic. It requires no invented
Project Contract and makes no claim to execute an approved product checkpoint.
Live probes require the caller's authorization and native authentication.
Protocol tests use labelled synthetic executables and supply separate evidence
from any live provider verification.

## Checkpoint B verification

On November 10, 2026, the actual adapter completed an authorized read-only
engineering diagnostic using installed Codex CLI `0.167.0`. It returned
`COMPLETED`, exit code `0`, confirmed cleanup and
`CORINTHOS_ADAPTER_SMOKE_OK` in its output. The isolated ignored diagnostic
workspace remained unchanged.

- Task `probe-f7b7a473ff8c48c69f42513fd11644ab`
- Attempt `attempt-2989a46e617c49bbae086030bc26d029`
- Native session `01a1c53d-bbb3-7fc3-8c3a-19ed93e98b76`
- Observed turn usage was 22,484 input tokens, including 13,696 cached input
  tokens, 428 output tokens and 395 reasoning output tokens. Cost was unavailable.

This run exercised the restricted diagnostic boundary. The real product pilot
belongs to checkpoint H and requires subsequent authorization. Live Claude
verification remains `NOT VERIFIED` because discovery did not find its native
executable in this environment. The adapter's 30 synthetic protocol cases passed
on Windows, including timeout and process-tree cancellation under the normal
account. A restricted account denied tree cleanup during an earlier check, and
the result exposed `cleanup_confirmed=False` for that environment.

## Official interfaces consulted

- [Codex non-interactive execution](https://developers.openai.com/codex/noninteractive)
- [Codex instruction discovery](https://developers.openai.com/codex/guides/agents-md)
- [Claude Code CLI reference](https://code.claude.com/docs/en/cli-reference)
- [Claude Code programmatic execution](https://code.claude.com/docs/en/headless)

Installed help/version takes precedence when selecting flags for a particular
executable. Claude's live installation and authentication are verified
separately from the Codex diagnostic.

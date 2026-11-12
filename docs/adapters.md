# Agent adapters

The Adapter Manager shares a validated versioned Standard and bounded context
with separate Codex and Claude Code command adapters. It discovers installed
capabilities, prepares explicit managed instructions, starts an external process
and returns observed events and results. The separately authorized
[execution runtime](workflow-execution.md) owns checkpoint scheduling, engineering
verification and durable recovery through construction checkpoints E-J.

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
limits. Discovery also bounds captured output and execution time. All native
calls own their process lifecycle, including ordinary descendants left after a
successful parent exit. Windows starts the process suspended, assigns it to a
kill-on-close Job Object, then resumes its sole initial thread through documented
Windows APIs. POSIX uses an isolated process group. Finalization terminates
remaining owned processes and confirms that the Job or group is empty before
reporting confirmed cleanup. An assignment failure prevents user code from
starting. A restricted host or uncertain cleanup requires operator inspection
before another attempt. The adapter performs no retries.

This ownership boundary covers ordinary descendants. It is not a general OS
sandbox and cannot contain effects deliberately routed through external services
or an independently running broker. Authentication, native hooks and configured
services remain the caller's responsibility.

### Per-user and project provider configuration

Use **Providers** on the Corinthos Home screen to inspect observed native
capabilities, refresh detection, or change a per-user executable choice. The
installer refreshes the same registry and succeeds when no provider is available.
Run `corinthos adapters refresh` to repeat the bounded version/help checks from
any directory.

The versioned `providers.json` in Corinthos user state stores a map by provider
identifier. Each entry can hold an explicit native executable and the last
observed version, interface flags and discovery diagnostic. Observations are for
inspection. Runtime discovery rechecks the actual executable and never promotes
an observed path to a configured choice. Unrecognized provider entries are
preserved, and execution requires a supported native adapter.

`corinthos init` does not require an installed or discoverable provider. Later,
inspect saved choices, explicitly probe capabilities, or set a project override:

```text
corinthos adapters show --root PROJECT --provider codex
corinthos adapters capabilities --root PROJECT --provider codex
corinthos adapters configure codex --root PROJECT --executable ABSOLUTE_NATIVE_PATH
corinthos adapters reset codex --root PROJECT
```

The same commands accept `claude`. Configuration requires an existing initialized
root, an absolute native executable and successful bounded version/help probes
with the required JSON/stdin interfaces. Invalid or unsupported replacements
leave the previous choice intact. `show` reads saved configuration only;
`capabilities` reports the effective executable, discovery source, interfaces
and diagnostic. It performs bounded native probes, not an agent task.

Choices are local operational files `.corinthos/adapter-codex.json` and
`.corinthos/adapter-claude.json`, not product contracts. Each update replaces only
one provider's bounded private JSON file atomically. It does not rebuild
`bootstrap.json`, rewrite instructions or open/replace `state.db`. Precedence is
an explicit one-off CLI executable, then the project's saved operational choice
or initial bootstrap executable, then the per-user choice, then automatic
discovery. Project reset saves an explicit null choice that forces discovery in
that project, even if an initial or per-user executable exists. Per-user reset
clears the user-level choice and its last observation.

Saved choices are consumed by installed capability checks, PM advice and the
Workflow execution CLI. Workflow's explicit executable/argument-prefix options
override the saved choice for that operation. Without explicit Standard paths,
Workflow uses checkout policy/schema files when both exist in the working
directory. From an installed app outside a checkout it uses the saved project
Standard or the bundled default for a project without a bootstrap profile.

### Windows npm discovery

For Codex on Windows, discovery inspects only absolute PATH directories and fixed
package paths associated with recognized npm shims. It checks the `@openai/codex`
package name/bin/version and matching Windows platform dependency, or the known
legacy in-package vendor layout. It never invokes the shim or recursively searches
the disk for `codex.exe`. Redirected paths and oversized metadata are rejected.
The selected native binary must report the matching `codex-cli` version and the
required interfaces before npm discovery reports it available. These layout and
capability checks are not package-publisher authentication.

The `discovery` result distinguishes `npm`, native `path`, conscious `explicit`
selection, `npm-unresolved`, `ambiguous` and `none`. A shim without a safely
resolved native package gets a specific diagnostic. Multiple native candidates
are not silently ranked; use `configure` or a one-off `--codex-executable` to
select one. Missing paths, failed probes and unsupported JSON/stdin interfaces
remain separate diagnostics. Not discovered does not mean definitely uninstalled.

The actual npm Codex 0.167.0 native executable passed bounded version/help and
capability checks before this correction. That evidence does not establish a
completed native task, authentication, every Codex version or cross-provider
interoperability. Provider tasks and product acceptance retain their separate
verification and authority requirements.

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
execution recovery belongs to checkpoint F and uses an explicit inspected
recovery decision; it does not invent a native resume binding after restart.

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

This run exercised the restricted diagnostic boundary. The separately authorized
real product pilot belongs to checkpoint H. Live Claude
verification remains `NOT VERIFIED` because discovery did not find its native
executable in this environment. The adapter's 30 synthetic protocol cases passed
on Windows, including timeout and cancellation under the normal
account. A restricted account denied tree cleanup during an earlier check, and
the result exposed `cleanup_confirmed=False` for that environment.

The subsequent lifecycle regression tests exercise actual synthetic parent and
child processes. They verify that successful adapter, checker and discovery
parents cannot leave ordinary children writing after confirmed cleanup, and that
failed Windows assignment or an interrupt kills the still-suspended process.

## Official interfaces consulted

- [Codex non-interactive execution](https://developers.openai.com/codex/noninteractive)
- [Codex instruction discovery](https://developers.openai.com/codex/guides/agents-md)
- [Claude Code CLI reference](https://code.claude.com/docs/en/cli-reference)
- [Claude Code programmatic execution](https://code.claude.com/docs/en/headless)

Installed help/version takes precedence when selecting flags for a particular
executable. Claude's live installation and authentication are verified
separately from the Codex diagnostic.

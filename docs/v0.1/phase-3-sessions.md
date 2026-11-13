# v0.1 Phase 3 · Agent Session Supervisor

Phase 3 starts from [the Phase 2.1 merge](https://github.com/tito-pereira/Corinthos/commit/5d913b7b18ef720f963e7614046a4062a4b2367f),
tree `4cd28b64ef4f06535cf0a621b141d70e7f6c127d`, with
[green post-merge CI](https://github.com/tito-pereira/Corinthos/actions/runs/43445000687).

## Persistence and ownership

SQLite v8 adds `agent_sessions` and the append-only `agent_session_events`.
A session has an immutable project, Work Item and provider. A partial unique
index holds one mutable slot per project database. The verified migration
retains all v7 records, including exact contract bytes and Work Item
relationships. It copies the original v7 into a verified
`state.pre-v8-<UUID>.db` before upgrading in a single transaction. Rollback
leaves v7 usable, and reopening v8 creates no new migration backup.

The Python Session Supervisor owns the workers, renewable SQLite leases and
generation fences. A local process-ownership lock covers selection, provider
execution and cleanup. The Windows Job Object owns the native tree. On POSIX
the guardian inherits the lock, observes loss of the supervisor and retains
ownership until it confirms group termination. An expired lease alone grants
no execution slot. The next explicit start or recovery can reconcile an
expired owner once ownership is available. If cleanup cannot be proved the
session remains fenced for operator inspection. Passive views read stored
state without reconciling or probing a provider.

| State | Effect |
| --- | --- |
| STARTING | Owns the project slot while preparing the selected native executable. |
| RUNNING | The managed process started. Events and telemetry are fenced by owner and generation. |
| CANCELLING | Explicit cancellation was recorded. The owning worker is stopping its process. |
| SUCCEEDED, FAILED | The provider run ended and cleanup was confirmed. |
| CANCELLED, TIMED_OUT | A request or deadline stopped the run and cleanup was confirmed. |
| INTERRUPTED | The run lost supervision or stopped before a trusted outcome. |

Explicit recovery applies only to INTERRUPTED sessions with a native binding.
It reuses the same provider and Work Item, checks the same execution envelope,
and increments the run generation. Supply the original explicit instruction
and executable override again, where used. The instruction itself is not
stored. The binding covers the Work Item input, adapter and executable
identity, managed instruction bytes and mode. An unsupported native resume
stays unavailable. Work Item status and approval/Validation state are owned by
their existing services and do not change as a result of a session outcome.

## Adapter observations

The supervisor reuses the native Adapter Manager. Provider-owned code resolves
the executable, defines native flags, parses JSON events and extracts telemetry.
Operation override, project choice, user choice and safe discovery are checked
in that order. Only an explicit start/recovery probes the selected provider.
The Codex and Claude Code adapters use the shared native transport. The
supervisor does not select a provider by inspecting event layouts.

The event history includes created/started/finished, output, tool activity,
usage, warning/error, cancellation, timeout, interruption and recovery.
Events are bounded, ordered and append-only. Raw native transcripts, stderr,
tool arguments, configuration credentials and input prompts are not retained
in the history. Bounded normalized agent messages omit controls and redact
common credential patterns. Use inputs without credentials. Telemetry uses
provider-reported counters, replacing observed cumulative snapshots without
summing them. Missing values remain null, actual zero is retained, and costs
use exact decimal text plus a currency code. Usage belongs to the current run
generation. Phase 3 neither estimates pricing nor aggregates across generations.

## Application, CLI and desktop

The existing desktop sidecar runs the Python supervisor. Rust transports a
fixed set of local commands and keeps the process lifecycle. The Agents tab
can start, inspect, cancel and explicitly recover sessions. It reads normalized
events through bounded polling and shows missing observations as Unknown.
Project State composes a bounded summary from existing session storage.
The Phase 2 `project.summary` wire fields retain their original shape.

```text
corinthos session start --root ROOT --work WORK_ID --provider codex --read-only
corinthos session list --root ROOT
corinthos session show SESSION_ID --root ROOT
corinthos session events SESSION_ID --root ROOT --after 0
corinthos session cancel SESSION_ID --root ROOT --generation GENERATION
corinthos session recover SESSION_ID --root ROOT
```

The CLI start/recover prints the initial record, waits as the foreground
supervisor, and prints the final record. A second terminal can inspect or
cancel. The sidecar replies with the initial record and continues serving
requests. `--timeout` is bounded from 1 to 3600 seconds and includes selected
provider preparation. Keep `--read-only` for inspection-only work. On
desktop shutdown active runs are interrupted after cleanup unless an explicit
cancellation won.

Additive JSON-RPC v2 operations are `session.start`, `session.get`,
`session.list`, `session.events`, `session.cancel`, and `session.recover`.
Clients feature-detect them through the existing handshake. Events use a
sequence cursor and do not introduce unsolicited notifications. The nine
RPC v1 schema hashes remain frozen. The existing eight contract wire schemas
and application publication authority have their independent compatibility
rules.

## Verification

The CI gates use deterministic local native fixtures under the same supervisor,
including creation, durable events, cancel, timeout, recovery and reaping.
The Windows desktop integration uses the actual WebView and a genuine v7
fixture built from Phase 2.1 source. It preserves source-install CI and requires
no credentials.

For opt-in live verification run
`python examples/agent_session_live.py PROVIDER --executable NATIVE_PATH`.
The harness uses a disposable Git project and a read-only marker task. It
checks persisted terminal state, normalized output, unchanged Work Item and
marker, and process cleanup confirmed by the supervisor.

- Codex 0.167.0 was verified with a real provider on Windows. The harness
  observed output and token counts, and the provider reported no cost.
- Claude Code adapter behavior is covered with a synthetic native fixture.
  A usable authenticated native executable was unavailable in the execution
  environment. The second real-provider gate is **NOT VERIFIED**.

Context Projection, handoff, provider switching, adaptive workflows and
public desktop packaging remain deferred.

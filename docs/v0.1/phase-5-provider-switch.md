# v0.1 Phase 5 provider switch

## Continuity and authority

An operator selects a target provider for an existing Agent Session. Corinthos
continues the same Work Item in a new Agent Session with its own identity. The
target receives a verified Context Projection assembled from the exact source
Session Handoff and selected Work Item context. Provider-native resume applies
only to recovery within the original session and provider. Native session IDs,
credential stores and private conversation history stay outside switch context.
If a captured observation echoes the source's native ID, the switch blocks
launch and retains the immutable evidence for audit.

The Handoff and Projection carry `DERIVED` authority. The Work Item retains its
identity, contents and status. Contracts and Validation continue to govern
product obligations and gates. Provider output remains an observation.

## Source and target

The source and target providers must differ. A new continuation requires an
open Work Item owned by the source project, confirmed source cleanup and no
unrelated active Agent Session in that project. Pin the source generation when
replaying a request. A generation mismatch is a conflict.

For a live `STARTING` or `RUNNING` source, `switch.execute` preflights the
selected target with an eight-second capability deadline. That check requires
JSON events, prompt input over stdin and read-only support when the source uses
read-only mode. Preflight performs capability discovery before requesting
cancellation. An unavailable or unsupported target leaves the live source
untouched. The result can report `TARGET_UNAVAILABLE` or `TARGET_UNSUPPORTED`.

An accepted cancellation uses the existing generation and lease fencing and
returns `STOPPING_SOURCE` while the supervisor stops and reaps the process.
`CANCELLED` requires confirmed cleanup. Repeated calls against a live
`CANCELLING` source see the same cancellation. They add no cancellation event
and hold no SQLite writer lock while waiting for cleanup. Expired leases are
reconciled under the native project ownership lock. Unconfirmed cleanup blocks
continuation. Phase 4.1 bounded cancellation contention handling still applies.
[Session ownership and recovery](phase-3-sessions.md) · [Cancellation under SQLite contention](phase-4-context.md#cancellation-under-sqlite-contention)

Once the source is stably `SUCCEEDED`, `FAILED`, `CANCELLED`, `TIMED_OUT` or
`INTERRUPTED`, the switch verifies its current generation and terminal event
cutoff. Corinthos creates or reuses the immutable Handoff for that exact
session, generation and cutoff. A terminal source can proceed directly to this
step with the same provenance checks.

The target projection binds the same project and Work Item, selected provider
and exact Handoff. Its canonical payload records `required_handoff_id`. The
required Handoff takes the first source position after the Work Item and is
verified against the stored Handoff and its digest. A newer Handoff cannot
replace it. A missing, invalid or oversized required Handoff blocks creation.
The projection digest covers the target provider, ordered redacted captures and
policy versions. Ordinary Context Projections retain the Phase 4 format.
[Deterministic Context Engine](phase-4-context.md)

Before launch, the supervisor rechecks the source generation and terminal
cleanup, Handoff provenance and projection binding. Its project ownership lock
serializes target lookup and creation. The new Agent Session inherits the
source read-only mode and timeout and uses a managed empty instruction. Once the
target row exists, normal Session Supervisor lifecycle and fencing apply.

## Status, advancement and replay

`switch.status` is read-only and runs no provider probes. It derives the stage,
source state and cleanup, Work Item, exact Handoff and Projection IDs and digests,
target session and blocker from existing records. The derived switch key hashes
the project, Work Item, source session, source generation and target provider.
SQLite stays at v9. Sessions, Handoffs and Projections hold the durable facts.

| Stage | Meaning |
| --- | --- |
| `SOURCE_ACTIVE` | The source is starting or running. |
| `STOPPING_SOURCE` | Cancellation is recorded and source cleanup is pending. |
| `SOURCE_TERMINAL` | A stable source can produce its exact Handoff. |
| `HANDOFF_READY` | The exact source Handoff exists. |
| `PROJECTION_READY` | The verified projection for this target and Handoff exists. |
| `TARGET_SESSION_ACTIVE` | An existing matching target session is active. |
| `TARGET_SESSION_TERMINAL` | An existing matching target session has a terminal result. |
| `BLOCKED` | Read the blocker or handle a state conflict before continuing. |

`switch.execute` advances as far as safe in one call. After a cancellation
request, poll status and call execute again once the source is terminal. If the
target becomes unavailable after source cleanup, the saved Handoff and Projection
remain available for replay. A capability blocker from execute reflects that
attempt. Passive status can still report the stored `PROJECTION_READY` stage.

Replay uses the same source generation and explicit target. Once the exact
projection exists, replay reuses that immutable capture even if later Work Item
context changes. A matching target session is keyed by project, Work Item,
provider and exact projection. An active or terminal match is returned even if
the target failed. A new attempt after target failure requires a separate
session operation.

| Boundary | Result after reconstruction and replay |
| --- | --- |
| A. Source cancellation recorded | Wait for confirmed cleanup using the existing cancellation. |
| B. Source terminal | Derive or reuse the Handoff from the terminal event. |
| C. Handoff stored | Reuse it when creating the projection. |
| D. Projection stored | Reuse its identity to find or create the target session. |
| E. Target row stored before response | Return the same row. Reconcile an expired orphan with normal session semantics. |

## CLI, RPC and desktop

Use the same source ID, provider and generation for each step. `ROOT`,
`SESSION_ID` and `GENERATION` stand for the authorized project and source session
values.

```text
corinthos switch status --root ROOT --session SESSION_ID --provider claude --generation GENERATION
corinthos switch start --root ROOT --session SESSION_ID --provider claude --generation GENERATION
```

The CLI prints a JSON switch view. If the source is stopping, rerun `status` until
it is terminal before repeating `start`. A CLI invocation that owns a newly
launched target stays in the foreground, waits for it and prints its session
result. Use the target session state to assess its outcome. A target owned by a
different supervisor remains under that supervisor. `start` reports a blocked
switch with exit status 1.

The Application Layer exposes `SessionApplication.switch_status` and
`SessionApplication.switch_execute`. RPC v2 advertises `switch.status` and
`switch.execute` by method name. Both accept `root`, `source_session_id`,
`target_provider` and optional `source_generation`. `switch.execute` requires a
request ID. Clients advance explicitly and poll for status. RPC v1 stays frozen.
[RPC switch result schema](../../schemas/rpc/v2/switch-result.schema.json)

Open the selected source session in **Agents**. Under **Provider switch**, choose
a target explicitly and click **Switch provider**. If the source needs cleanup,
the panel polls for the state change. Click **Continue switch** when ready and
**Open target session** after creation. The panel displays the same Work Item,
source state, cleanup warnings and the exact Handoff, Projection and target
references. Phase 8 is the planned point for moving this control to Command.

## Verification

**IMPLEMENTED.** Service fixtures cover the A–E boundaries, provider
unavailability, failure, concurrency, passive status and replay. The Windows
desktop fixture checks the switch through the WebView using local synthetic
providers.

**SYNTHETIC BIDIRECTIONAL VERIFIED.** Both adapter integration cases passed on
Windows CPython 3.12.10. Independent Codex-like and Claude-like executables
exercise the real adapter protocols in both directions. Each target proves it
received an observation from the exact Handoff, starts a new session on the same
Work Item and uses normal process cleanup.

```text
python -m pytest tests/test_provider_switch.py tests/test_provider_switch_integration.py
```

**Real Codex switch leg verified:** a synthetic Claude source switched to native
Codex CLI 0.167.0 on Windows in a disposable Git repository. The read-only Codex
session reproduced the marker from the exact Handoff and reached `SUCCEEDED`
after confirmed cleanup. Replay returned the same target session. An initial
attempt in a directory without Git metadata failed at the provider process.

**TWO-REAL-PROVIDER SWITCH NOT VERIFIED / DEFERRED.** Live acceptance requires a
second independently available and authenticated provider, with both relevant
directions exercised where supported. Synthetic protocol fixtures use local
executables and require no provider credentials.

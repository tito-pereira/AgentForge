# v0.1 Phase 4 · Deterministic Context Engine

Phase 4 starts from [the Phase 3 merge](https://github.com/tito-pereira/Corinthos/commit/13e7bf556788e737493d767b30e12a6613c8fa73),
tree `08fc3dee56402fc0017e70bffb758a84d0dda578`, with
[green post-merge CI](https://github.com/tito-pereira/Corinthos/actions/runs/43457403798).

## Context ownership and selection

The Context Index is an on-demand projection of existing exact relationships.
A Context Source records its identity, version or event cutoff, capture digest,
selector reason and redaction categories.

| Authority class | Owners and examples |
| --- | --- |
| CANONICAL | Exact published Project, Workflow, Module, Technology Decision, Validation, Validation Result and Evidence Report revisions selected through structured relationships. |
| OPERATIONAL | Work Item and relations, existing lifecycle and Validation observations, normalized Agent Session history, and verified metadata of explicitly referenced local evidence. |
| DERIVED | Session Handoff. The Context Index and Context Projection are also derived. |

Selector policy v1 starts with the Work Item and active Project Contract. It
then follows at most six parents and eight dependencies, exact affected
Modules, relevant Workflow and Technology Decisions, exact related Validation
and evidence, local lifecycle and recent terminal session facts, and the latest
eligible Handoff for the same Work Item. Traversal follows structured data and
uses stable ordering and tie-breaking. Unknown relationships stay absent.
The engine does not crawl the repository or read provider credential stores.
Local evidence uses explicitly referenced, verified digests and safe relative
paths. Verification reads up to 16 explicitly referenced artifacts per projection,
each capped at 2 MiB. A source capture is bounded to 32 KiB. The selection admits up to 40
sources and 128 KiB of canonical UTF-8 JSON. Sources beyond the budget are
omitted as whole records according to selection priority.

## Redaction and verification

Redaction policy v1 sanitizes captures and provenance before their digest or
durable storage. It recognizes sensitive field names, low-entropy assignments,
bearer credentials and common tokens, private-key blocks, private references and
host-specific paths. Explicit credential-bearing paths are excluded. Redaction
stores deterministic markers and categories. Normalized captures intentionally
omit raw provider transcripts, credential files and unreferenced project files.

Canonical JSON uses sorted object keys, compact separators and UTF-8. Each
source digest covers its redacted capture. The source-set digest covers the
ordered audit descriptors. The projection digest covers the canonical project,
Work Item, target provider, both policy versions and ordered sources with
their captures and provenance. Incidental projection IDs and creation times
are excluded. The provider target participates in identity. Formatting for a
provider does not participate.

Creation deduplicates by projection digest. Verify reconstructs the payload
from stored captures and rejects inconsistent metadata, order or digests.
Reopening the store and reordering discovery preserve the same result.
Changes to selected admissible content yield a new projection. Earlier
captures and digests remain available. Changes exclusively to excluded secret
values do not become digest inputs.

## SQLite v9 and session binding

The shared store adds `context_projections`, `context_projection_sources` and
`session_handoffs`, plus a nullable foreign key on `agent_sessions`. The
migration verifies v8, creates a verified original `state.pre-v9-<UUID>.db`,
then changes schema and version in one transaction. It retains v8 rows and
previous backups. The projection, captures and handoff cannot be updated,
replaced or deleted by ordinary database operations. Session binding is
immutable and checked against project, Work Item and target provider.

A new session creates or reuses a verified projection before launch. It binds
the ID in SQLite and includes the ID and digest in the execution envelope.
The selected adapter renders the projection and a redacted explicit instruction
after freezing. It uses bounded data with authority labels. Context selection
and audit never probe or launch native providers. Same-session recovery keeps
the exact projection and verifies its existing native binding. Legacy v8 sessions
have a null projection and keep their original recovery rules.

## Session Handoff

An explicit terminal or interrupted session can produce a deterministic Handoff
for its exact generation and last durable event sequence. Up to 12 recent
normalized events are retained within a 24 KiB payload. Observations carry
sequence and source session provenance. The Handoff is immutable and idempotent
for that cutoff. A later projection may select the Handoff as DERIVED. Session,
Work Item, contract and Validation ownership remain separate.

## Application, CLI, RPC and desktop

Project State composes bounded counts and latest context references from the
existing repository. Strict project-summary and session DTOs preserve their
earlier wire fields. New RPC v2 methods are capability-detected. They do not
add broadcast notifications. The RPC v1 schema freeze remains covered.

```text
corinthos context create --root ROOT --work WORK_ID --provider codex
corinthos context list --root ROOT --work WORK_ID
corinthos context show PROJECTION_ID --root ROOT
corinthos context sources PROJECTION_ID --root ROOT
corinthos context verify PROJECTION_ID --root ROOT
corinthos context for-session SESSION_ID --root ROOT
corinthos handoff create --root ROOT --session SESSION_ID
corinthos handoff list --root ROOT --work WORK_ID
corinthos handoff show HANDOFF_ID --root ROOT
```

RPC adds `context.create/get/list/sources/verify/for_session` and
`handoff.create/get/list`. The desktop Context tab audits source order,
authority, reason, provenance, policy versions, digests, redaction and
handoffs. Agents can display the bound projection without changing session
results. Capture payloads are kept out of projection audit responses. Handoff
details expose only the bounded, redacted derived payload.

Tests cover genuine SQLite v8 fixtures, reproducibility, source selectivity,
verification against corruption, redaction and session-binding behavior.
Windows desktop integration covers the real WebView with a deterministic local
provider and leaves active process cleanup under the supervisor. The deferred
Phase 3 live test with a second independent provider remains **NOT VERIFIED**.
Provider switching and cross-provider resume remain outside Phase 4.

## Cancellation under SQLite contention

Explicit session cancellation retries only when SQLite reports `BUSY` or
`LOCKED` while starting a write transaction. It makes three acquisition
attempts with a 100 ms lock timeout and waits 25, 50 and 100 ms between attempts
before falling back to the normal SQLite wait once. It rechecks the session
generation, live lease and state under the acquired writer lock. A repeated
request for the same active generation records one `CANCEL_REQUESTED` event.
Contention during commit rolls back and is reported as a conflict. The
supervisor still confirms process cleanup before recording `CANCELLED`.

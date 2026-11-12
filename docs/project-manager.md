# Project Manager

Project Manager turns a human's idea into a reviewed specification. It provides
three ways to edit one persistent Project Draft, deterministic checks and
explicit local approval through the Contract Kernel. Package version
`0.1.0`, product target Core v0.1 and product requirements revision v0.2 identify
separate artifacts.

Optional assistance uses the configured [agent adapters](adapters.md).
Natural-language consistency, criterion testability and technical feasibility
require human review. Project Manager records these limits as `NOT_VERIFIED`
and displays actual assumptions, risks and supplied evidence. The
[Workflow runtime](workflow-execution.md) consumes approved specifications, and
[Validation](validation.md) independently assesses implementation evidence.

## A first project

Install the package using the [README](../README.md). Open a terminal in the
checkout and run the venv's `corinthos` command. This example uses PowerShell.

```powershell
.\.venv\Scripts\corinthos.exe project --root . start
```

For POSIX, use `.venv/bin/corinthos project --root . start`. The root must be an
existing directory you control. Accepted answers are stored privately beneath
that root. Use `--root` consistently when returning to a project.

1. Describe your idea, for example, "Build a local greeting for a supplied name."
2. Choose **Guide me through the specification**. Keep or refine the idea, then
   enter "Greeting output for a supplied name" as included scope.
3. Add the requirement "Print a greeting for the supplied name" and the
   observable acceptance criterion "Input Ada produces Hello, Ada."
4. Add a constraint if needed, such as "Run offline." Add a success criterion
   such as "A fresh installation reproduces the documented greeting."
5. Check **Project Completion** and use **Review current draft** to inspect the
   specification and resolve any structural blockers. Choose **Review complete
   contract** there or run `project review` to freeze an exact review candidate.
6. Choose **Save and exit** to leave with your accepted edits saved. Use **Approve
   at the local terminal** in the review or advanced menu, or run
   `project approve`, when ready to review and publish the specification.

### Authoring modes

- **Help me develop the idea** asks you to select Codex or Claude Code and uses
  the project's configured adapter in read-only mode. A detailed initial idea
  can yield proposed scope, requirements with acceptance criteria, constraints
  and success criteria, alongside missing details and open questions. Review
  individual suggestions, accept them, edit them before accepting, or reject
  them. Explore alternatives and trade-offs, answer questions, or continue with
  just the missing information. Advice becomes draft content only through an
  explicit authoring choice. It carries no approval or feasibility authority.
  If assistance is unavailable, continue in guided or advanced mode.
- **Guide me through the specification** works without an agent. It takes you
  through the vision, included scope, requirements and their acceptance criteria,
  optional constraints and project success criteria in order.
- **Configure it manually** opens the advanced editor. Add, edit or remove
  requirements, criteria and constraints. Edit all scope sections, record
  proposals and decisions, answer questions, record feasibility and inspect the
  complete draft or history. Review and approval are available here.

All three modes use the same session, stable IDs and accepted edit history.
Use `0` for **Back** and `S` for **Save and exit** in menus, or `/back` and
`/save` at text prompts. Where indicated, an empty entry finishes a list.
Leaving a partially entered operation preserves earlier accepted edits and
discards the unfinished operation. Ctrl-C also preserves accepted edits.
Run `corinthos project --root . resume` to reopen the same draft and see its
completion again. Previously saved sessions use the same authoring flow. Use
`project defer` to move a session to `DEFERRED` and invalidate any pending review.

### Project Completion

The bar allocates 20 percentage points each for a vision, included scope, at
least one requirement with structurally valid acceptance criteria for every
requirement, and project success criteria. The final 20 points require the draft
to pass the structural readiness checks for complete review. Outstanding
required questions, undecided proposals and other structural issues block those
final points.

For example, vision and included scope alone yield `[████░░░░░░] 40%`. Filling
the four required areas yields 80% if a blocking question remains. With all
structural checks satisfied, the bar shows `[██████████] 100%` even if
constraints, exclusions, assumptions, risks, proposals and feasibility evidence
are empty. Resolve proposals and questions when they exist. Record negotiated
decisions when the proposals require them.

100% means the draft meets the structural prerequisites for a complete review.
Review still assesses the substance of the specification. Technical feasibility,
independent Validation and product acceptance are separate decisions.

## Commands

The following examples assume `corinthos` is available through an activated venv.
An explicit venv executable works equally well. `--root` defaults to the current
directory and may appear before or after the project action.

| Command | Behavior |
| --- | --- |
| `corinthos project start` | Capture an idea and open the authoring menu. |
| `corinthos project sessions` | List saved sessions and their states. |
| `corinthos project resume [SESSION_ID]` | Continue the same draft from the authoring menu, selecting a session when its ID is omitted. |
| `corinthos project show [SESSION_ID]` | Show complete operational state and preliminary checks. |
| `corinthos project review [SESSION_ID]` | Freeze and display a complete, short-lived candidate. |
| `corinthos project approve [SESSION_ID]` | Open the foreground OS terminal, create a fresh exact review and request its approval challenge. |
| `corinthos project defer [SESSION_ID]` | Save for later and invalidate a pending review. |
| `corinthos project cancel [SESSION_ID]` | Close negotiation without publishing. |
| `corinthos project history [SESSION_ID]` | Inspect durable accepted turns and decisions. |
| `corinthos project advise [SESSION_ID] --provider {codex,claude}` | Request read-only advisory output for one saved draft. |
| `corinthos project revise CONTRACT_ID [--revision REVISION_ID]` | Select an exact published Project revision and negotiate a user-requested change. |
| `corinthos project request CONTRACT_ID [--revision REVISION_ID]` | Select an exact published PRR and choose structural review, clarification or return. |

The `revise` and `request` commands display published revisions for explicit
selection. A stale Project base requires explicit reconciliation. A new session
has its own session ID while a revision session retains the existing project and
contract identities. **Keep existing specification** closes a revision session
without creating another published revision.

## Project Contract fields

The complete published candidate follows the existing Project schema. Empty
optional lists are displayed explicitly.

| Field | Content |
| --- | --- |
| `metadata.contract_id`, `revision_id`, `contract_type`, `project_id` | Logical identity, exact immutable revision, `PROJECT`, and owning project. |
| `metadata.version`, `schema_version`, `status`, `created_at`, `supersedes` | Sequential content version, wire `1.0`, `PUBLISHED`, timestamp and exact predecessor or null. |
| `metadata.standard_ref` | `standard_id: nukytera-standard` and `version: 0.1`. |
| `metadata.provenance` | Publishing `engine: PROJECT_MANAGER`, `actor_id` and session `source`. |
| `metadata.approval` | `kind: HUMAN`, unique `approval_id` and local `actor_id` verified by the trusted bridge. |
| `payload.vision` | The project's ordinary-language purpose. |
| `payload.scope` | `included`, `excluded`, `assumptions` and `risks` lists. |
| `payload.requirements` | `requirement_id`, `description` and `acceptance_criteria`, each with `criterion_id` and `criterion`. |
| `payload.constraints` | `constraint_id` and `description` for each constraint. |
| `payload.success_criteria` | `criterion_id` and `criterion` for each project success criterion. |
| `payload.structural_proposals` | `proposal_id`, `kind`, `description`, `requirement_ids` and `constraint_ids`. |
| `payload.negotiated_decisions` | `decision_id`, `proposal_ids`, `decision` and `rationale`. |

## Structured choices and analysis

Requirements have descriptions and one or more acceptance criteria. Editing an
existing criterion keeps its ID, and `/remove` explicitly removes that criterion.
Adding a criterion creates a fresh ID. The service rejects identifier reuse and
broken proposal links. It compares session versions before saving each edit.
When refining proposal links, Enter retains the displayed default, new item
numbers replace it, and `/clear` removes all links of that kind.

`SUGGESTION` records a negotiable preference. `REQUIREMENT` records a binding
demand. Proposal status, alternatives and scope belong to operational history.
Accepted proposals and their decisions enter the consolidated candidate. Rejected
and withdrawn alternatives remain inspectable in history. Accepted binding
proposals need links to requirements or constraints. Refinements require a fresh
decision, and every edit invalidates an earlier candidate review.

Deterministic checks cover required fields, identifiers, references, empty or
placeholder criteria, exact normalized included/excluded overlap, pending
questions, undecided proposals and bounded revision scope. Feasibility entries
distinguish `NOT_VERIFIED`, `ASSUMPTION` and supplied `CONFIRMED` evidence. These
records express the user's evidence and judgement. They do not establish
independent implementation conformance. Human reviewers assess ambiguities and
natural-language contradictions beyond these structural checks.

## Complete review and local approval

The review shows every metadata and payload field, all stable IDs, exact content
version, prior reference, SHA-256 digest, expiry, unresolved limitations and a full
diff from the previous published revision. Terminal controls and direction
controls are escaped visibly, including text supplied through imported records.

Approval opens the real foreground OS terminal. It displays a fresh complete
candidate and a random `APPROVE` challenge. Enter that exact challenge to approve
the displayed specification. Every other answer defers publication. EOF, Ctrl-C
and a closed terminal leave accepted negotiation data available. Piped input,
redirected output and background interactions fail the production approval check.

The local account provides the approval provenance label. Its hash fits the
Kernel's identifier format. This trust boundary relies on the local OS account
and foreground terminal access. The application cannot identify the physical
person at a keyboard or protect state from software with the same account's
permissions. Keep that account and private project directory under your control.

The frozen document already contains its unique approval identity. Its canonical
digest covers that final document, avoiding a self-referential digest field.
Reviews expire after five minutes. The local receipt binds project, session,
session version, exact revision, actor, digest and expiry. The trusted callback
checks these values and the current state during `ContractStore.publish`.
Edits, conflicts, stale reviews, mismatched receipts and reused approval claims
require renewed review. There is no CLI consent flag or text-file approval input.

## Persistent states and recovery

| State | Meaning and next action |
| --- | --- |
| `DRAFT` | An editable negotiation. Assess or continue editing. |
| `NEEDS_CLARIFICATION` | Required information or a choice is unresolved. Edit or answer the questions. |
| `AWAITING_EXPLICIT_APPROVAL` | A frozen candidate awaits its separate terminal action. Editing invalidates it. |
| `DEFERRED` | Saved for later. Resume reopens the negotiation. |
| `PUBLISHING` | An exact consent receipt is committed and Kernel publication is being reconciled. |
| `READY_FOR_REVIEW` | Interrupted consent was revoked before publication. Prepare a fresh review. |
| `PUBLISHED` | The exact Project revision exists in the Kernel. Start a revision session for changes. |
| `CLOSED_UNCHANGED` | The owner kept the approved specification. |
| `CANCELLED` | The negotiation was closed without publication. |
| `RETURNED` | A PRR was returned for technical clarification or recovery. |

| Accepted action | Transition |
| --- | --- |
| Start or open a revision | New session enters `DRAFT`. |
| Edit an open session, including resume | Current draft becomes `DRAFT` or `NEEDS_CLARIFICATION`, with any frozen review invalidated. |
| Review a structurally complete draft | Open session becomes `AWAITING_EXPLICIT_APPROVAL`. |
| Defer or decline the terminal challenge | Open session becomes `DEFERRED`. |
| Approve the exact foreground challenge | `AWAITING_EXPLICIT_APPROVAL` becomes `PUBLISHING`, then `PUBLISHED` after reconciliation. |
| Recover an interrupted publication | `PUBLISHING` becomes `PUBLISHED` if its exact revision committed, or `READY_FOR_REVIEW` with consent revoked. |
| Keep, cancel or return | Negotiation enters `CLOSED_UNCHANGED`, `CANCELLED` or `RETURNED`. Further changes require a new session. |

Only accepted transitions and their snapshots are durable. Session versions use
compare-and-swap so concurrent clients reload before making further choices.
Stale Project bases block approval rather than silently replacing approved work.

Receipt/session preparation, Kernel publication and final session completion
have separate transaction boundaries. Reading an interrupted publication
reconciles it with the exact stored revision and receipt. If publication committed,
the session becomes `PUBLISHED`. Otherwise consent is revoked and a new review is
required. Reconciliation preserves the Kernel's idempotent publication behavior.
Use `resume`, `show` and `history` to inspect recovered state. Preserve original
files on storage errors and follow the [storage recovery guide](storage.md).

A concurrent read during the short interval between recording consent and Kernel
publication can treat the pending receipt as interrupted and revoke it. The
approver must review again after that conflict. The
[approval transaction guide](storage.md#negotiation-and-approval-transactions)
records this current recovery limitation and its transaction boundaries.

## Project Revision Requests

A PRR must already be published through the Kernel. Intake verifies its exact
reference, project, request ID and active approved Project base. The CLI displays
the exact request's diagnostic, evidence, alternatives, trade-offs and risks before
triage and makes them available on show, resume and review. It offers
structural negotiation, clarification, or return for technical recovery. A bug,
failed test or missing evidence calls for diagnosis and appropriate clarification.
The request carries no approval to change the product.

Structural review opens a new session tied to the request and base revision. It
limits edits to the affected proposals and associated requirements, constraints
and criteria. Unaffected content and IDs are preserved. New linked obligations
must stay within that bounded scope. The owner can keep, defer or cancel the
specification, or review and explicitly approve changed content. Unchanged
content creates no new revision. An approved change uses the exact predecessor
and creates one immutable new Project revision.

The Project Manager records chronology and leaves downstream impact propagation,
module replanning and independent revalidation to Workflow and Validation.
User-initiated revisions can start with `revise` directly.

## Service API

`from corinthos.project_manager import ProjectManager` provides a terminal-free
service. Construct `ProjectManager(project_root, assistance=None)` with an existing
authorized root. An optional assistance callable receives a detached snapshot and
returns advisory text. Its output carries no authority to approve or publish.

| API | Purpose |
| --- | --- |
| `start(idea, *, actor_id)` | Create a unique project and negotiation session. |
| `get(session_id)`, `list()`, `history(session_id)` | Read detached persisted views and recover interrupted publication where applicable. |
| `edit(session_id, expected_version, operation, *, actor_id)` | Save one explicit structured choice with version checking. |
| `assess(session_id)` | Return deterministic `issues` and unresolved `unknowns`. |
| `review(session_id, expected_version, *, actor_id)` | Freeze a complete candidate, digest and expiry after structural checks. |
| `defer`, `cancel`, `keep` | Change operational state using session ID, expected version and keyword actor ID. |
| `revise(base_ref, reason, *, actor_id)` | Start an owner-requested revision from an exact active Project reference. |
| `receive_prr(prr_ref, triage, *, actor_id)` | Open bounded negotiation, clarification or return from an exact published PRR. |

Edit actions are `set_vision`, `set_scope`, `upsert_requirement`,
`remove_requirement`, `upsert_constraint`, `remove_constraint`,
`upsert_success_criterion`, `remove_success_criterion`, `propose`,
`decide_proposal`, `set_question`, `record_feasibility` and `resume`.
The [service source](../src/corinthos/project_manager/service.py) defines the
closed operation fields. The [terminal adapter](../src/corinthos/project_manager/cli.py)
collects them through questions. Production publication belongs to the trusted
[approval bridge](../src/corinthos/project_manager/approval.py).

## Requirement traceability

RF02 governs negotiation, RF06 governs revisions and reconciliation, and RF10
governs persistence and recovery. Original architecture §§2.6–2.8
define proposals and revision authority, and §§2.12–2.14 define state and CLI.
The public requirements and their verification are recorded below.

| Checkpoint | Requirement and implemented boundary | Source and verification |
| --- | --- | --- |
| 2.0.A | RF02/RF06/RF10, define service, operational state, exact approvals and Engine boundaries. | This guide, [architecture](architecture.md), [service](../src/corinthos/project_manager/service.py), and [storage](storage.md). |
| 2.0.B | RF02, a guided ordinary-language CLI and separate service. | [CLI tests](../tests/test_project_cli.py), [service tests](../tests/test_project_manager.py), existing [CLI regressions](../tests/test_cli.py). |
| 2.0.C | RF02, stable proposals, classified demands, explicit decisions and honest preliminary analysis. | [Service tests](../tests/test_project_manager.py), guided draft/review and renderer tests in [CLI tests](../tests/test_project_cli.py). |
| 2.0.D | RF02/RF10, complete exact review, foreground terminal challenge, trusted receipt and Kernel publication. | [Approval tests](../tests/test_project_approval.py), [CLI pipe rejection](../tests/test_project_cli.py), existing [authority tests](../tests/test_contract_boundaries.py). |
| 2.0.E | RF06/RF10, versioned SQLite state, restart, CAS and interrupted publication recovery. | [Repository tests](../tests/test_project_repository.py), [approval recovery tests](../tests/test_project_approval.py), [legacy migration tests](../tests/test_state_migration.py). |
| 2.0.F | RF02/RF06/RF10, exact PRR intake, bounded revision and unchanged-content preservation. | [Service tests](../tests/test_project_manager.py), [approval tests](../tests/test_project_approval.py), existing [semantic tests](../tests/test_contract_semantics.py). |
| 2.0.G | M1–M5, packaging, security, documentation and reproducible Windows/Ubuntu checks. | All targeted tests, baseline suite, [README](../README.md) and [CI workflow](../.github/workflows/ci.yml). Actual results belong to the exact tested commit. |
| 2.0.H | Owner-reviewed integration and separate Phase 3 authorization. | Reviewed PR and exact-SHA CI evidence. Historical verification is in [decisions](decisions.md). |

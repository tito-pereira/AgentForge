# Claude Code instructions

Read and apply [AGENTS.md](AGENTS.md), the shared operational source of repository
rules. This file preserves equivalent obligations for Claude Code.

- **M1 — Precise instructions.** State the objective, scope, context, interfaces,
  deliverables, and verifiable acceptance criteria.
- **M2 — Justified technologies.** Explain choices and preserve human authority
  over binding technology and structural decisions.
- **M3 — Meaningful testing.** Verify actual behavior, failures, edge cases,
  integration, regressions, and security according to the change's impact.
- **M4 — Usable documentation.** Update instructions, decisions, and limitations
  to reflect implementation and commands actually verified.
- **M5 — Readable, efficient code.** Use clear names, modularity, and simplicity,
  with efficiency appropriate to the requirements.

M1–M5 are universal and mandatory. The project owner retains authority over vision,
priorities, requirements, binding decisions, and human acceptance. Agents implement
the authorized scope and report real evidence and limitations.

Use English for all repository artifacts, source comments and docstrings,
documentation, user-facing messages, test descriptions and output labels, commit
messages, and public GitHub collaboration. This rule applies to every current and
future implementation phase, subphase, checkpoint, engineering report, and related
implementation communication. Private product planning may remain in the project
owner's preferred language.

Phase 0 established the foundation. Phase 0.1 prepares its English-language public
repository. Phase 0.2 verifies clean Windows/Linux virtual environments and applies
the approved MPL-2.0 license on a reviewed branch. The conventions, installation
and verification commands, and delivery
rules are in [AGENTS.md](AGENTS.md). Public engineering context is available through
the [README](README.md) and local documentation. Keep private planning references
outside published artifacts.

Phase 1.1 migrates the brand to Corinthos, the distribution to `corinthos-core`,
the package and CLI to `corinthos`, and private state to `.corinthos/`.
Preserve version `0.1.0`, the five Commandments, six Engines, eight contract
types and MPL-2.0. Keep earlier names in historical evidence and preserve
durable wire identifiers.

Use the [Contract Kernel API](docs/contracts.md) for schema checks, exact
references, immutable publication and [private SQLite state](docs/storage.md).
Trusted callers verify actor identity and approval of the exact publication.
Published records retain historical references after active pointers change.
Phase 2 provides the [Project Manager](docs/project-manager.md), a separate
negotiation service and thin terminal adapter with durable operational sessions.
Production approval requires the foreground OS terminal, complete frozen review
and exact random challenge. Synthetic test consent, assistant text, piped input
and persisted claims carry no production authority. Preserve review digests,
receipt invalidation, exact bases, unaffected obligations and crash recovery.
Keep structural checks and supplied feasibility evidence distinct from independent
product validation. Render every review field and escape untrusted terminal
controls. Real agent adapters, Workflow, Validation and Report belong to later
authorized phases.
Follow the [storage migration procedure](docs/storage.md#migrating-existing-project-state)
for each authorized project. Preserve the published bytes, approval receipts,
evidence hashes, event order, and SQLite application and schema markers.

Inspect Git status, preserve existing work, protect secrets and private state, and
respect the authorized directory. Mark results **NOT VERIFIED** when execution or
evidence is missing. Local tests and explicit technical review provide the initial
verification. Operational agent integration belongs to later phases.

Starting Phase 3 requires a subsequent instruction from the project owner. External
actions require authorization for their specific scope, including public commits,
pushes, and repository creation. Follow the staged-content, identity, ownership,
visibility, and licensing checks in [AGENTS.md](AGENTS.md).

The project owner selected Mozilla Public License 2.0 (`MPL-2.0`). Preserve the
complete [LICENSE](LICENSE), source notices/SPDX headers, packaging metadata, and
accurate copyright and third-party notices. Never invent copyright-holder names
or ownership transfers. Record license-related decisions. Phase 2 changes belong
on a reviewed feature branch and pull request. Merging into the default branch
requires separate authorization. Preserve the historical `phase-1-baseline` tag
and existing commit history.

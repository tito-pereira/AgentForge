# Phase 3 engineering verification

The Phase 3 branch starts from integrated main
`139d1542f9b15938985909ab1124832cd69de607`. Its post-merge Windows and Ubuntu
jobs passed 245 tests each. The [design record](phase-3-design.md) preserves the
earlier A–D stop and its separate 320-test result.

## Installed-wheel regression

A new virtual environment based on independent Windows CPython 3.12.10 x64
installed the built `corinthos-core` 0.1.0 wheel. All **408 tests passed** in
108.61 seconds. `pip check` passed. Import origins for the package, adapters and
Workflow runtime were inside the new environment's `site-packages`, with
`PYTHONPATH` unset. The installed license metadata check passed with the full
unchanged MPL-2.0 text.

The tested wheel SHA-256 was
`a3f4f69fd65a60b29b3e51299302a27008be504036121ae5eb2c25e082105759`.
The wheel is a local engineering artifact; no package-registry publication is
implied. CI builds its own wheel at the exact checked-out PR head.

The regression covers preserved baseline behavior, genuine older-state fixture
migrations, planning and authorization boundaries, durable attempts and leases,
concurrent claims and fencing, recovery rollback, revision propagation and
retained evidence, actual command execution, explicit technical review, missing
or inadmissible Validation results, source drift, cancellation, timeout, write
scope and normal-parent-exit descendant cleanup. Positive contract-approval and
Validation-result fixtures are explicitly synthetic tests. They supply no
production consent or product-validation evidence.

Reproduce the package and regression checks using a clean Python 3.12 environment:

```text
python -m pip wheel . --no-deps --wheel-dir WHEEL_DIRECTORY
python -m pip install WHEEL_FILE
python -m pip install "pytest>=8,<10" "ruff>=0.9,<1"
python -m pip check
python -m pytest -p no:cacheprovider
python -m ruff check .
python -m ruff format --check .
python examples/contract_kernel.py
python -m corinthos project --help
python -m corinthos workflow --help
```

Keep generated test directories inside ignored local environments or the
operating system's temporary directory. Runtime tests use local synthetic
providers; routine CI does not authenticate to or invoke paid agents. The
[CI workflow](../.github/workflows/ci.yml) verifies Windows and Ubuntu Python
3.12 against the actual PR head, installed-wheel imports, the full suite, CLI,
the eight-contract demonstration, formatting and shell activation. Actual remote
job outcomes and tested SHAs belong to the PR's checks and delivery record.

## Native integration and independent review

A separate read-only native Codex **0.167.0** diagnostic completed after the
process-containment fix. It returned the expected smoke marker, confirmed owned
process cleanup and left its isolated workspace unchanged. Private records retain
the actual session, attempt, output, normalized events and available usage. This
was a transport diagnostic, separate from pilot implementation and contract
approval. It produced no Validation Result or acceptance claim.

No native Claude executable was found in the available paths. Live behavior remains
**NOT VERIFIED**; faithful offline protocol tests cover the adapter boundary.

Independent technical review found and corrected a normal-parent-exit child
cleanup defect, a recovered-attempt dispatch condition, preservation across
changed milestones/decisions, carry selection for pending checkpoints and CLI
failure exit statuses. The review also checked source freshness, exact authority,
genuine gate evidence, rollback and scoped recovery. Final gate/source checks now
run inside the completion writer reservation. New or revised Validation plans
and later matching interrupted/failed runs cannot race a successful completion.
Owned process-tree controls
and their [documented limits](adapters.md) remain distinct from the native OS
sandbox and formal independent Validation.

## Pilot and later authority

The selected task-manager brief and its concrete Project draft are prepared in a
separate permanent local repository. Its real Project Contract and complete
technical/interface plan still require the owner's foreground-terminal actions.
Pilot dispatch, implementation, installation and daily-data acceptance checks are
therefore **pending**. No test fixture or diagnostic substitutes for them.

Formal Validation and Report Engines, product acceptance, Phase 4 and integration
into main remain outside this engineering verification record. Required formal
gates without admissible published evidence continue to block their applicable
progression. A functioning application, preliminary checkpoint completion and
human product acceptance retain their separate meanings.

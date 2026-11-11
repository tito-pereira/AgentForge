# Isolated builds and milestone admission

`corinthos build` is the Workflow-owned operational journey for approved playtest
milestones. It uses the existing Workflow, execution and independent Validation
services. It does not approve a milestone, deliver a product or record acceptance.

Complete the milestone's required checkpoints first. A checkpoint specification
that requires its own future playtest result is diagnosed as circular and needs
explicit reconciliation; the command never drops that gate or completes work early.

```text
corinthos build --root PROJECT prepare WORKFLOW MILESTONE EXECUTION --revision REVISION
corinthos build --root PROJECT show BUILD
corinthos build --root PROJECT list PROJECT_ID
corinthos build --root PROJECT readiness BUILD --check-executable ABSOLUTE_EXECUTABLE --check-arg=ARGUMENT
corinthos build --root PROJECT validate BUILD VALIDATION_PLAN --revision REVISION --evaluator INDEPENDENT_ID
corinthos build --root PROJECT admission BUILD
corinthos build --root PROJECT recover OPERATION
```

Use `--source` only for the actual authorized execution workspace. Optional
`--recipe-executable`, repeated `--recipe-arg=VALUE`, `--recipe-timeout` and repeated
`--package PATH` prepare and retain real package outputs. Arguments remain separate;
there is no shell command string. Executables and absolute input files are pinned by
SHA-256. Recipe and check processes receive isolated temporary/application data paths,
bounded output/time and the existing process containment. These trusted local
commands are not a hostile-code sandbox.

Pinned inputs must be ordinary files with no redirected path. POSIX venv Python
launchers are commonly symlinks; select an intentionally resolved native interpreter
for stdlib-only checks, as the test fixtures do with `Path(sys.executable).resolve()`.
Resolving a venv launcher can select its base interpreter and different installed
packages. For recipes requiring additional packages, explicitly select an ordinary
runtime/tool with those dependencies and record its real inputs; do not silently
assume a launcher alias preserves the venv environment. The input guard remains
strict about links and is not disabled for CI.

Preparation first records an operation intent. It physically copies the bounded
source inventory, executes the explicit recipe and seals a complete final inventory
of source, packages, configuration and generated files. The immutable BUILD origin
binds the approved exact sources, cumulative milestone/checkpoint closure, recipe,
source observation, actual candidate identity and manifest digest. Payloads live at
`.corinthos/snapshots/BUILD/candidate`; the manifest is a sibling, not a self-hashed
candidate file. Development edits cannot modify these copied bytes.

Ordinary development snapshots exclude environments, caches and generated outputs.
Sealed candidates include every actual file, so changing or adding an excluded
development path such as `dist/package.whl` still invalidates the build. Private/Git
internals, links and unsafe paths are rejected. The copied candidate normally has no
Git commit of its own; the real source commit remains manifest provenance.

Readiness runs the supplied check for every exact cumulative scenario in another
isolated copy. The Python API can bind different typed `CommandCheck` procedures to
individual scenarios. A foreground technical review inspects the actual checks and
all readiness criteria. Missing review, failed checks, altered bytes or incomplete
process cleanup cannot create readiness. A newer readiness attempt invalidates the
older pass until that attempt finishes successfully. Readiness is preliminary
Workflow evidence, separate from independent Validation.

Use the existing `corinthos validation` journey to derive and publish a complete,
independently reviewed `PLAYTEST_MILESTONE` plan. The build validate command then
audits the sealed candidate with its complete observed build identity. Validation
uses that identity in its initial observation, repeated guards, isolated copy,
evidence, result and frozen-publication recovery. A caller marker or an old result
cannot supply a new build ID. Raw non-build Validation behavior remains available.

Admission rechecks active exact sources, checkpoint proof, the complete sealed
inventory, readiness evidence and every applicable active milestone plan. Each
plan's newest exact-identity durable run must be published and its latest result
must satisfy the real gate with admissible proof. A newer unfinished, interrupted,
blocked or unverified audit prevents fallback to an older pass. An ancestor plan
does not replace the selected milestone's coverage. Playtest promotion uses this
same admission inside its guarded transaction and enforces cumulative progression.

`--operation ID` makes an exact preparation replay idempotent. A different source,
recipe or scope under that ID conflicts. An unfinished preparation for the same
workspace blocks another attempt until actual process/effect inspection. Recover
asks for those observations in a foreground terminal. It completes an already
anchored intact seal without reexecuting its recipe; a preparation without a valid
anchored seal is abandoned with its effects and inspection retained. Start a new
operation after that inspection. Readiness recovery leaves an interrupted readiness
blocked. Nothing silently treats lease expiry or an agent disappearing as proof
that external effects stopped.

The Python API is `corinthos.lifecycle.builds.BuildService`. Its public operations
are `prepare`, `get`, `identity_for_candidate`, `readiness`, `validate`, `recover`
and `require_eligible(build_id, connection)`. The last operation requires the matching
project's writer transaction and returns the sealed identity, exact scope, owned
paths/manifest hash and current record version. Session services consume it rather
than trusting a stored availability boolean. Retiring/retired builds cannot admit
new sessions; historical metadata and evidence remain separate from payload retention.

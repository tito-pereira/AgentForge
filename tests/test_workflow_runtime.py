# SPDX-License-Identifier: MPL-2.0
"""Runtime tests use labelled synthetic adapters, reviews and Validation publishers."""

import json
import os
import sys
import threading
import time
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest

from corinthos.adapters import AgentResult
from corinthos.adapters.model import Capabilities
from corinthos.adapters.process import run_process
from corinthos.adapters.providers import PROVIDERS
from corinthos.adapters.service import AdapterManager
from corinthos.contracts import (
    ContractRef,
    ContractStore,
    IntegrityError,
    PublishContext,
    approval_request,
)
from corinthos.workflow.execution_repository import ExecutionRepository
from corinthos.workflow.runtime import WorkflowRunner
from corinthos.workflow.verification import (
    CheckpointSpec,
    CommandCheck,
    RequiredGate,
    TechnicalReview,
    ValidationGateConsumer,
    command_check,
    workspace_snapshot,
)

_EXAMPLES = Path(__file__).resolve().parents[1] / "examples" / "contracts"


@pytest.mark.parametrize("kind", ["agent", "checker", "discovery"])
def test_completed_transports_stop_owned_background_children(tmp_path, kind):
    marker, release = tmp_path / "late.txt", tmp_path / "release.txt"
    child = (
        "import time; from pathlib import Path; release=Path("
        + repr(str(release))
        + "); deadline=time.monotonic()+5\n"
        "while not release.exists() and time.monotonic()<deadline: time.sleep(.01)\n"
        "if release.exists(): Path(" + repr(str(marker)) + ").write_text('late')"
    )
    parent = (
        "import subprocess,sys; subprocess.Popen([sys.executable,'-c',"
        + repr(child)
        + "],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL); "
        'print(\'{"type":"turn.completed","usage":{}}\',flush=True)'
    )
    command = (sys.executable, "-c", parent)
    if kind == "agent":
        result = run_process(
            PROVIDERS["codex"],
            command,
            "",
            tmp_path,
            capabilities=Capabilities("codex", True, "synthetic-test"),
            task_id="synthetic-task",
            attempt_id="synthetic-attempt",
            timeout=10,
            cancel=threading.Event(),
            on_event=None,
        )
        assert result.status == "COMPLETED"
        if os.name == "nt":
            assert result.cleanup_confirmed is True
    elif kind == "checker":
        result = command_check(
            ContractStore(tmp_path),
            tmp_path,
            "synthetic-attempt",
            CommandCheck("synthetic-check", "Check owned cleanup", command),
            threading.Event(),
        )
        assert result["state"] == "PASSED"
        if os.name == "nt":
            assert result["cleanup_confirmed"] is True
    else:
        result = AdapterManager._help(command, ())
        if os.name == "nt":
            assert "turn.completed" in result
    release.write_text("Only released after lifecycle cleanup.", encoding="utf-8")
    time.sleep(0.2)
    assert not marker.exists()


def _example(name):
    return json.loads((_EXAMPLES / (name + ".json")).read_text(encoding="utf-8"))


def _publish(store, document):
    """Synthetic trusted publication is confined to this test module."""
    proof = approval_request(document) if document["metadata"]["approval"] is not None else None
    origin = document["metadata"]["provenance"]
    return store.publish(
        document,
        context=PublishContext(
            origin["engine"], origin["actor_id"], lambda request: request == proof
        ),
    )


def _seed(root, *, second=False):
    store = ContractStore(root)
    for name in ("project", "technology-decision", "module"):
        _publish(store, _example(name))
    workflow = _example("workflow")
    checkpoint = workflow["payload"]["checkpoints"][0]
    checkpoint.update(
        deliverables=["Greeting source"], verification_plan=["Exercise the greeting source"]
    )
    if second:
        dependent = deepcopy(checkpoint)
        dependent.update(
            checkpoint_id="second",
            depends_on=["greet"],
            deliverables=["Usage guide"],
            verification_plan=["Check the usage guide"],
            completion_criteria=[
                {"criterion_id": "CP2", "criterion": "The greeting has a usage guide."}
            ],
        )
        workflow["payload"]["checkpoints"].append(dependent)
    return store, _publish(store, workflow)


def _spec(*, second=False, failing=False, gates=()):
    if second:
        return CheckpointSpec(
            "second",
            (
                CommandCheck(
                    "guide-check",
                    "Check the usage guide",
                    (
                        sys.executable,
                        "-c",
                        "from pathlib import Path; assert 'Usage' in Path('README.md').read_text()",
                    ),
                ),
            ),
            {"Usage guide": ["README.md"]},
            ("README.md",),
            required_gates=gates,
        )
    check = "from pathlib import Path; assert Path('greeting.py').read_text() == 'answer = 42\\n'"
    if failing:
        check = "from pathlib import Path; assert not Path('isolated-failure').exists()"
    return CheckpointSpec(
        "greet",
        (
            CommandCheck(
                "source-check", "Exercise the greeting source", (sys.executable, "-c", check)
            ),
        ),
        {"Greeting source": ["greeting.py"]},
        ("greeting.py",),
        required_gates=gates,
    )


class SyntheticAdapter:
    def __init__(self, store, *, status="COMPLETED", cleanup=True, effect=None):
        self.store, self.status, self.cleanup, self.effect = store, status, cleanup, effect
        self.calls = []

    def invoke(self, provider, context, **options):
        # Assert the durable attempt already exists before a synthetic external effect.
        attempt = ExecutionRepository(self.store).get_attempt(context.attempt_id)
        assert attempt["state"] == "RUNNING"
        self.calls.append(context)
        if self.effect:
            self.effect(context)
        return AgentResult(
            provider,
            self.status,
            context.task_id,
            context.attempt_id,
            version="synthetic-test",
            exit_code=0 if self.status == "COMPLETED" else 1,
            output="Synthetic agent claims everything passed.",
            cleanup_confirmed=self.cleanup,
        )


def _accept(request):
    """A synthetic trusted independent reviewer receives actual observed evidence."""
    return TechnicalReview(
        "synthetic-independent-review",
        True,
        tuple(item["criterion_id"] for item in request["checkpoint"]["completion_criteria"]),
        request["artifact_identity"],
        ("Synthetic reviewer inspected supplied evidence.",),
    )


def _write_code(context):
    (context.workspace / "greeting.py").write_text("answer = 42\n", encoding="utf-8")


def _inspection():
    return {
        "process_stopped": True,
        "effects_inspected": True,
        "summary": "Synthetic operator inspected retained source and stopped processes.",
    }


def test_sequential_dependencies_require_real_files_checks_and_explicit_review(tmp_path):
    store, reference = _seed(tmp_path, second=True)

    def effects(context):
        if context.deliverables == ("Greeting source",):
            _write_code(context)
        else:
            (context.workspace / "README.md").write_text("Usage guide", encoding="utf-8")

    adapter = SyntheticAdapter(store, effect=effects)
    runner = WorkflowRunner(tmp_path, adapter, reviewer=_accept)
    execution = runner.configure(
        reference, [_spec(), _spec(second=True)], actor_id="synthetic-operator"
    )
    first = runner.run_next(execution["execution_id"])
    assert first["checkpoint_id"] == "greet" and first["state"] == "COMPLETED"
    assert first["details"]["checks"][0]["state"] == "PASSED"
    assert (
        first["details"]["technical_review"]["origin"] == "EXPLICIT_PRELIMINARY_ENGINEERING_REVIEW"
    )
    assert first["details"]["artifact_identity"]["snapshot_id"]
    second = runner.run_next(execution["execution_id"])
    assert second["checkpoint_id"] == "second" and second["state"] == "COMPLETED"
    assert runner.run_next(execution["execution_id"]) is None
    assert len(adapter.calls) == 2
    assert "Exact local implementation" in adapter.calls[0].prior_facts[1]
    reopened = WorkflowRunner(tmp_path, adapter, reviewer=_accept)
    assert reopened.repository.get(execution["execution_id"])["state"] == "COMPLETED"


def test_agent_success_claim_without_deliverables_blocks_dependents(tmp_path):
    store, reference = _seed(tmp_path, second=True)
    adapter = SyntheticAdapter(store)
    runner = WorkflowRunner(tmp_path, adapter, reviewer=_accept)
    execution = runner.configure(
        reference, [_spec(), _spec(second=True)], actor_id="synthetic-operator"
    )
    result = runner.run_next(execution["execution_id"])
    assert result["state"] == "BLOCKED"
    assert result["details"]["reason"] == "DECLARED_DELIVERABLE_MISSING_OR_UNSAFE"
    assert runner.run_next(execution["execution_id"]) is None
    assert len(adapter.calls) == 1


def test_failed_checks_require_explicit_linked_retry_without_plan_revision(tmp_path):
    store, reference = _seed(tmp_path)
    (tmp_path / "isolated-failure").write_text("Dedicated failure injection", encoding="utf-8")
    adapter = SyntheticAdapter(store, effect=_write_code)
    runner = WorkflowRunner(tmp_path, adapter, reviewer=_accept)
    execution = runner.configure(reference, [_spec(failing=True)], actor_id="synthetic-operator")
    failed = runner.run_next(execution["execution_id"])
    assert (
        failed["state"] == "BLOCKED"
        and failed["details"]["reason"] == "AUTOMATED_VERIFICATION_FAILED"
    )
    assert runner.run_next(execution["execution_id"]) is None
    (tmp_path / "isolated-failure").unlink()
    current = runner.repository.get(execution["execution_id"])
    runner.repository.recover(
        execution["execution_id"],
        "greet",
        current["version"],
        actor_id="synthetic-operator",
        inspection=_inspection(),
        decision="RETRY",
    )
    repaired = runner.run_next(execution["execution_id"])
    assert (
        repaired["state"] == "COMPLETED" and repaired["previous_attempt_id"] == failed["attempt_id"]
    )
    assert len(store.list_revisions(reference.contract_id)) == 1
    assert len(adapter.calls) == 2


def test_explicit_rejected_review_can_resume_verification_without_another_agent_call(tmp_path):
    store, reference = _seed(tmp_path)
    adapter = SyntheticAdapter(store, effect=_write_code)

    def reject(request):
        return replace(
            _accept(request),
            accepted=False,
            findings=("Synthetic review requires another inspection.",),
        )

    runner = WorkflowRunner(tmp_path, adapter, reviewer=reject)
    execution = runner.configure(reference, [_spec()], actor_id="synthetic-operator")
    failed = runner.run_next(execution["execution_id"])
    assert failed["details"]["reason"] == "TECHNICAL_REVIEW_REJECTED"
    runner.reviewer = _accept
    current = runner.repository.get(execution["execution_id"])
    snapshot = workspace_snapshot(tmp_path)
    recovered = runner.repository.recover(
        execution["execution_id"],
        "greet",
        current["version"],
        actor_id="synthetic-operator",
        inspection=_inspection(),
        decision="VERIFY",
        owner_id=runner.owner_id,
        context={"source_snapshot": {"snapshot_id": snapshot["artifact_identity"]["snapshot_id"]}},
    )
    completed = runner.verify_existing(recovered["checkpoints"]["greet"]["attempt_id"])
    assert completed["state"] == "COMPLETED" and len(adapter.calls) == 1
    assert completed["previous_attempt_id"] == failed["attempt_id"]


@pytest.mark.parametrize(
    "status,cleanup", [("TIMEOUT", True), ("CANCELLED", True), ("COMPLETED", False)]
)
def test_partial_or_unclean_agent_outcomes_never_complete(tmp_path, status, cleanup):
    store, reference = _seed(tmp_path)
    adapter = SyntheticAdapter(store, status=status, cleanup=cleanup, effect=_write_code)
    runner = WorkflowRunner(tmp_path, adapter, reviewer=_accept)
    execution = runner.configure(reference, [_spec()], actor_id="synthetic-operator")
    result = runner.run_next(execution["execution_id"])
    assert result["state"] == "INTERRUPTED"
    assert runner.run_next(execution["execution_id"]) is None
    assert runner.repository.get(execution["execution_id"])["lease"]["attempt_id"] == (
        None if cleanup else result["attempt_id"]
    )


def test_writes_outside_declared_responsibility_are_flagged(tmp_path):
    store, reference = _seed(tmp_path)

    def effect(context):
        _write_code(context)
        (tmp_path / "unrelated.py").write_text("Unapproved change", encoding="utf-8")

    runner = WorkflowRunner(tmp_path, SyntheticAdapter(store, effect=effect), reviewer=_accept)
    execution = runner.configure(reference, [_spec()], actor_id="synthetic-operator")
    result = runner.run_next(execution["execution_id"])
    assert result["state"] == "BLOCKED" and result["details"]["reason"] == "WRITE_SCOPE_EXCEEDED"
    assert (tmp_path / "unrelated.py").exists()


def test_missing_real_validation_result_keeps_required_gate_unverified(tmp_path):
    store, reference = _seed(tmp_path)
    requirement = RequiredGate(
        ContractRef(
            "future-validation", "future-validation-r1", "VALIDATION", reference.project_id
        ),
        None,
        "CHECKPOINT",
        ("greet",),
        reference,
    )
    runner = WorkflowRunner(tmp_path, SyntheticAdapter(store, effect=_write_code), reviewer=_accept)
    execution = runner.configure(
        reference, [_spec(gates=(requirement,))], actor_id="synthetic-operator"
    )
    result = runner.run_next(execution["execution_id"])
    assert result["state"] == "BLOCKED"
    assert result["details"]["reason"] == "REQUIRED_VALIDATION_GATE_NOT_SATISFIED"
    assert result["details"]["gates"][0]["state"] == "NOT_VERIFIED"
    assert not any(event["contract_type"] == "VALIDATION_RESULT" for event in store.list_events())


@pytest.mark.parametrize("invalid", ["unmapped_check", "outside_deliverable", "shell_string"])
def test_configuration_does_not_guess_commands_or_paths(tmp_path, invalid):
    store, reference = _seed(tmp_path)
    spec = _spec()
    if invalid == "unmapped_check":
        spec = replace(
            spec, commands=(replace(spec.commands[0], plan_item="An invented verification item"),)
        )
    elif invalid == "outside_deliverable":
        spec = replace(spec, deliverables={"Greeting source": ["../outside.py"]})
    else:
        spec = replace(spec, commands=(replace(spec.commands[0], argv="python -c false"),))
    runner = WorkflowRunner(tmp_path, SyntheticAdapter(store), reviewer=_accept)
    with pytest.raises(IntegrityError):
        runner.configure(reference, [spec], actor_id="synthetic-operator")


def test_gate_consumer_rechecks_real_kernel_result_artifact_and_evidence(tmp_path):
    from test_contract_semantics import _completed_result

    store = ContractStore(tmp_path)
    examples = {
        name: _example(name)
        for name in (
            "project",
            "technology-decision",
            "module",
            "workflow",
            "validation",
            "validation-result",
        )
    }
    for name in ("project", "technology-decision", "module", "workflow", "validation"):
        _publish(store, examples[name])
    result = _completed_result(examples, tmp_path / ".corinthos" / "artifacts")
    reference = _publish(store, result)
    gate = RequiredGate(
        ContractRef.from_document(examples["validation"]),
        reference,
        "PRODUCT_VALIDATION",
        ("demo-project",),
        ContractRef.from_document(examples["project"]),
    )
    identity = result["payload"]["target_and_execution"]["artifact_identity"]
    consumer = ValidationGateConsumer(store)
    assert consumer.consume(gate, identity)["state"] == "SATISFIED"
    assert consumer.consume(gate, {"snapshot_id": "changed"})["state"] == "BLOCKED"
    evidence = result["payload"]["evidence_refs"][0]
    (tmp_path / ".corinthos" / "artifacts" / evidence["path"]).write_text(
        "Changed evidence", encoding="utf-8"
    )
    assert consumer.consume(gate, identity)["state"] == "BLOCKED"


def test_applicable_published_checkpoint_gate_cannot_be_omitted_from_config(tmp_path):
    store, reference = _seed(tmp_path)
    plan = _example("validation")
    plan["payload"]["validation_scope"].update(
        level="CHECKPOINT", target_ids=["greet"], target_contract_ref=reference.to_json()
    )
    plan["payload"]["gate_policy"]["gate"] = "CHECKPOINT"
    plan["payload"]["verification_matrix"] = [
        item
        for item in plan["payload"]["verification_matrix"]
        if item["source_ref"].get("obligation_id") != "SC1"
    ]
    _publish(store, plan)
    runner = WorkflowRunner(tmp_path, SyntheticAdapter(store, effect=_write_code), reviewer=_accept)
    execution = runner.configure(reference, [_spec()], actor_id="synthetic-operator")
    result = runner.run_next(execution["execution_id"])
    assert result["state"] == "BLOCKED"
    assert result["details"]["gates"][0]["state"] == "NOT_VERIFIED"
    assert (
        result["details"]["gates"][0]["validation_plan_ref"]
        == ContractRef.from_document(plan).to_json()
    )


@pytest.mark.parametrize("during_dispatch", [False, True])
def test_changed_active_plan_stops_dispatch_or_completion(tmp_path, during_dispatch):
    store, reference = _seed(tmp_path)

    def change_project(_context):
        project = store.resolve_active("demo-intent")
        original = ContractRef.from_document(project)
        project["metadata"].update(
            revision_id="changed-project-r2", version=2, supersedes=original.to_json()
        )
        project["payload"]["vision"] = "A newly approved product vision."
        _publish(store, project)

    def effect(context):
        _write_code(context)
        change_project(context)

    adapter = SyntheticAdapter(store, effect=effect if during_dispatch else _write_code)
    runner = WorkflowRunner(tmp_path, adapter, reviewer=_accept)
    execution = runner.configure(reference, [_spec()], actor_id="synthetic-operator")
    if during_dispatch:
        result = runner.run_next(execution["execution_id"])
        assert result["state"] in {"INTERRUPTED", "BLOCKED"}
        assert len(adapter.calls) == 1
    else:
        change_project(None)
        with pytest.raises(IntegrityError, match="changed"):
            runner.run_next(execution["execution_id"])
        assert not adapter.calls


@pytest.mark.parametrize("change", ["artifact", "criteria", "agent_identity", "untyped"])
def test_technical_review_requires_observed_target_and_all_criteria(tmp_path, change):
    store, reference = _seed(tmp_path)

    def reviewer(request):
        review = _accept(request)
        if change == "artifact":
            return replace(review, artifact_identity={"snapshot_id": "wrong-artifact"})
        if change == "criteria":
            return replace(review, criterion_ids=())
        if change == "agent_identity":
            return replace(review, actor_id="codex")
        return {"accepted": True}

    runner = WorkflowRunner(
        tmp_path, SyntheticAdapter(store, effect=_write_code), reviewer=reviewer
    )
    execution = runner.configure(reference, [_spec()], actor_id="synthetic-operator")
    result = runner.run_next(execution["execution_id"])
    assert (
        result["state"] == "BLOCKED"
        and result["details"]["reason"] == "TECHNICAL_REVIEW_MISSING_OR_MISMATCHED"
    )

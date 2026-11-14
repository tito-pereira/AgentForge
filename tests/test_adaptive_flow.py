# SPDX-License-Identifier: MPL-2.0
"""Prove small-work execution and exact independent adaptive completion."""

import json
from dataclasses import replace

import pytest
from jsonschema import ValidationError
from test_application_workspace import _call, _transcript
from test_application_workspace import wire as wire
from test_provider_switch import SwitchManager
from test_work_items import _create, _example, _publish
from test_work_items import work as work
from test_workflow_runtime import SyntheticAdapter, _accept, _seed, _spec, _write_code
from test_workflow_validation import _publish_plan

from corinthos.cli import main
from corinthos.contracts import ConflictError, ContractStore
from corinthos.sessions.repository import SessionRepository
from corinthos.sessions.supervisor import SessionSupervisor
from corinthos.sessions.switch import ProviderSwitchService
from corinthos.validation.runtime import ValidationRunner
from corinthos.work import WorkService
from corinthos.work.adaptive import AdaptiveWorkflowService
from corinthos.work.scope import ScopePolicyService
from corinthos.workflow.runtime import WorkflowRunner
from corinthos.workflow.verification import AuditExpectation


def test_task_runs_without_workflow_but_success_does_not_verify_or_complete(work, wire):
    item = _create(
        work, "Inspect api_key=private-task-value", acceptance_criteria=["Check the output."]
    )
    manager = SwitchManager()
    supervisor = SessionSupervisor(manager_factory=lambda *args, **kw: manager)
    service = AdaptiveWorkflowService(work.root, supervisor)
    repository = SessionRepository(work.root)
    try:
        initial = service.status(item.work_item_id)
        wire("adaptive-flow-result", initial)
        assert initial["stage"] == "READY" and initial["can_start"]
        before = service.report(item.work_item_id)
        assert before == service.report(item.work_item_id) and not manager.selected
        assert "private-task-value" not in json.dumps(before)
        started = service.start(item.work_item_id, "codex", read_only=True)
        session = supervisor.wait(work.root, started["latest_session"]["session_id"])
        assert session.state == "SUCCEEDED" and session.context_projection_id
        assert any(e.kind == "OUTPUT" for e in repository.events(session.session_id))
        report = service.report(item.work_item_id)
        wire("work-report-result", report)
        assert report["flow"]["stage"] == "VALIDATION_REQUIRED"
        assert report["flow"]["latest_projection"]["projection_id"] == session.context_projection_id
        assert report["overall_status"] == "NOT_VERIFIED"
        assert "Prepared fixture output" not in json.dumps(report)
        assert work.get(item.work_item_id) == item
        assert ContractStore(work.root).list_events() == []
        active = work.transition(item.work_item_id, "ACTIVE")
        with pytest.raises(ConflictError, match="unsatisfied"):
            service.complete(item.work_item_id, active.updated_at)
        assert work.get(item.work_item_id) == active
    finally:
        assert supervisor.close()


def test_bounded_change_uses_existing_module_and_continues_across_providers(work):
    store = ContractStore(work.root)
    for kind in ("project", "technology-decision", "module"):
        _publish(store, _example(kind))
    item = _create(work, scope_level="CHANGE", affected_modules=["greeting"])
    manager = SwitchManager()
    supervisor = SessionSupervisor(manager_factory=lambda *args, **kw: manager)
    service = AdaptiveWorkflowService(work.root, supervisor)
    try:
        result = service.start(item.work_item_id, "codex")
        first = supervisor.wait(work.root, result["latest_session"]["session_id"])
        switched = ProviderSwitchService(supervisor).execute(work.root, first.session_id, "claude")
        target = supervisor.wait(work.root, switched["target_session_id"])
        report = service.report(item.work_item_id)
        assert report["flow"]["provider_continuity"]["target_session_id"] == target.session_id
        assert report["flow"]["provider_continuity"]["source_session_id"] == first.session_id
        assert work.get(item.work_item_id) == item
        assert report["overall_status"] == "NOT_VERIFIED"
        assert all(row["contract_type"] != "WORKFLOW" for row in store.list_events())
    finally:
        assert supervisor.close()


def test_scope_is_rechecked_at_durable_session_creation(work, monkeypatch):
    item = _create(work)
    manager = SwitchManager()
    supervisor = SessionSupervisor(manager_factory=lambda *args, **kw: manager)
    service = AdaptiveWorkflowService(work.root, supervisor)
    create = SessionRepository.create

    def change_scope(repository, *args, **kwargs):
        ScopePolicyService(work.root).set(item.work_item_id, "PROJECT", item.updated_at)
        return create(repository, *args, **kwargs)

    monkeypatch.setattr(SessionRepository, "create", change_scope)
    try:
        with pytest.raises(ConflictError, match="scope or readiness changed"):
            service.start(item.work_item_id, "codex")
        assert not manager.selected and not SessionRepository(work.root).list()
        assert service.status(item.work_item_id)["stage"] == "PLANNING_REQUIRED"
    finally:
        assert supervisor.close()


def test_project_reuses_exact_workflow_and_completion_rechecks_independent_result(tmp_path, wire):
    store, workflow = _seed(tmp_path)
    work = WorkService(tmp_path)
    item = _create(
        work,
        scope_level="PROJECT",
        affected_modules=["greeting"],
        acceptance_criteria=["The example output matches the accepted greeting."],
    )
    item = work.transition(item.work_item_id, "ACTIVE")
    critical = _create(
        work,
        scope_level="CRITICAL",
        affected_modules=["greeting"],
        acceptance_criteria=item.acceptance_criteria,
    )
    service = AdaptiveWorkflowService(tmp_path)
    assert service.status(critical.work_item_id)["stage"] == "PLANNING_REQUIRED"
    assert "RISK_UNKNOWN" in service.status(critical.work_item_id)["unknowns"]
    assert service.status(item.work_item_id)["workflow_ref"] == workflow.to_json()
    with pytest.raises(ConflictError, match="not ready"):
        service.start(item.work_item_id, "codex")
    plan = _publish_plan(store, workflow, "CHECKPOINT", workflow, ("greet",))
    validator = ValidationRunner(store)

    def audit(request):
        validator.run(
            plan,
            request["workspace"],
            evaluator="synthetic-independent-evaluator",
            expected_identity=request["artifact_identity"],
            reviewer=lambda inspection: {
                "evaluator": inspection["evaluator"],
                "artifact_identity": inspection["artifact_identity"],
                "inspected": inspection["paths"],
                "status": "CONFORMANT",
                "rationale": "Inspected the isolated synthetic greeting candidate.",
            },
        )

    runner = WorkflowRunner(
        tmp_path, SyntheticAdapter(store, effect=_write_code), reviewer=_accept, auditor=audit
    )
    expectation = AuditExpectation("CHECKPOINT", workflow, ("greet",))
    spec = replace(_spec(), audit_expectations=(expectation,))
    execution = runner.configure(
        workflow, [spec], actor_id="operator", work_item_id=item.work_item_id
    )
    before = service.status(item.work_item_id)
    assert before["execution"]["execution_id"] == execution["execution_id"]
    assert before["validation_state"] == "NOT_VERIFIED" and not before["can_complete"]
    assert runner.run_next(execution["execution_id"])["state"] == "COMPLETED"
    ready = service.status(item.work_item_id)
    wire("adaptive-flow-result", ready)
    assert ready["stage"] == "COMPLETION_READY" and ready["validation_state"] == "VERIFIED"
    assert len(ready["validation_result_refs"]) == 1
    assert service.complete(item.work_item_id, item.updated_at)["stage"] == "TERMINAL"
    assert work.get(item.work_item_id).status == "COMPLETED"
    assert service.report(item.work_item_id)["overall_status"] == "VERIFIED"


def test_adaptive_rpc_is_additive_and_passive_writes_require_ids(work, wire, capsys):
    item = _create(work)
    params = {"root": str(work.root), "work_item_id": item.work_item_id}
    names = {
        "scope.assess",
        "scope.set",
        "flow.status",
        "flow.start",
        "flow.complete",
        "work.report",
    }
    requests = [
        _call("system.handshake", 1, protocol_version=2),
        _call("scope.assess", 2, **params),
        _call("flow.status", 3, **params),
        _call("work.report", 4, **params),
        _call(
            "scope.set", None, **params, scope_level="PROJECT", expected_updated_at=item.updated_at
        ),
        _call("flow.start", None, **params, provider="codex"),
        _call("flow.complete", None, **params, expected_updated_at=item.updated_at),
    ]
    messages = _transcript(requests)
    assert names <= set(messages[1]["result"]["methods"])
    for index, schema in enumerate(
        ("scope-assessment-result", "adaptive-flow-result", "work-report-result"), 2
    ):
        wire(schema, messages[index]["result"])
    assert len(messages) == 5
    for request in requests[4:]:
        with pytest.raises(ValidationError):
            wire("request", request)
    assert work.get(item.work_item_id) == item
    legacy = _transcript([_call("system.handshake", 1, protocol_version=1), requests[2]])
    assert legacy[2]["error"]["code"] == -32601
    assert main(["work", "report", "--root", str(work.root), "--work", item.work_item_id]) == 0
    assert json.loads(capsys.readouterr().out) == messages[4]["result"]

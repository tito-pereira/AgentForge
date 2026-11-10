# SPDX-License-Identifier: MPL-2.0
"""Synthetic native processes verify adapter transport without billed agent calls."""

import json
import os
import sys
import threading
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest

from corinthos.adapters import AdapterManager, ContextInput
from corinthos.contracts import (
    ContractStore,
    IntegrityError,
    PublishContext,
    approval_request,
)

_ROOT = Path(__file__).resolve().parents[1]
_POLICY = _ROOT / "policies" / "standard.yaml"
_SCHEMA = _ROOT / "schemas" / "standard.schema.json"
_SESSION = "a1b2c3d4-1111-4111-8111-123456789abc"
_FAKE = r"""
import json
import sys
import time
from pathlib import Path

provider, mode = sys.argv[1:3]
if '--version' in sys.argv:
    print('synthetic-test-agent 0.167.0')
    raise SystemExit
if '--help' in sys.argv:
    print('--json --sandbox read-only --print -p --output-format stream-json --verbose --resume SESSION_ID stdin --tools --disallowedTools')
    raise SystemExit
text = sys.stdin.read()
Path('captured-test-input.json').write_text(json.dumps({'args':sys.argv[3:], 'input':text}), encoding='utf-8')
session = 'a1b2c3d4-1111-4111-8111-123456789abc'
def emit(value):
    print(json.dumps(value), flush=True)
if mode == 'malformed':
    print('not-json', flush=True)
    raise SystemExit
if mode == 'deep':
    print('[' * 5000 + '0' + ']' * 5000, flush=True)
    raise SystemExit
if provider == 'codex':
    emit({'type':'thread.started', 'thread_id':session})
else:
    emit({'type':'system', 'subtype':'init', 'session_id':session})
if mode == 'delay':
    time.sleep(10)
if mode == 'partial':
    raise SystemExit
if mode in ('auth', 'quota'):
    emit({'type':'error','error':{'code':'authentication_error' if mode=='auth' else 'insufficient_quota'}})
    raise SystemExit(1)
if provider == 'codex':
    emit({'type':'item.completed','item':{'type':'agent_message','text':'Synthetic advisory only.' if mode!='large' else 'x'*4096}})
    emit({'type':'turn.completed','usage':{'input_tokens':7,'cached_input_tokens':2,'output_tokens':3}})
else:
    if mode == 'failed_then_success':
        emit({'type':'result','subtype':'error_during_execution','is_error':True,'session_id':session,'result':'Earlier failure.'})
    emit({'type':'result','subtype':'success','is_error':False,'session_id':session,'result':'Synthetic advisory only.',
          'usage':{'input_tokens':7,'output_tokens':3},'total_cost_usd':0.002})
if mode == 'nonzero':
    raise SystemExit(7)
"""


@pytest.fixture
def factory(tmp_path):
    script = tmp_path / "synthetic_agent.py"
    script.write_text(_FAKE, encoding="utf-8")

    def make(provider="codex", mode="complete", *, store=None):
        return AdapterManager(
            _POLICY,
            _SCHEMA,
            store=store,
            commands={provider: (sys.executable, str(script), provider, mode)},
        )

    return make


def _context(tmp_path):
    store = ContractStore(tmp_path)
    document = json.loads(
        (_ROOT / "examples" / "contracts" / "project.json").read_text(encoding="utf-8")
    )
    proof = approval_request(document)
    reference = store.publish(
        document,
        context=PublishContext(
            "PROJECT_MANAGER", "demo-project-manager", lambda request: request == proof
        ),
    )
    return store, ContextInput(
        tmp_path,
        reference,
        "Implement the approved local greeting.",
        ("Greeting module", "Meaningful tests", "Usage documentation"),
        ("Input Ada produces Hello, Ada.",),
        prior_facts=("No previous attempt.",),
    )


def test_discovery_probes_actual_supported_interfaces_without_invocation(tmp_path, factory):
    capabilities = factory().discover("codex")
    assert capabilities.available and capabilities.version == "0.167.0"
    assert capabilities.json_events and capabilities.stdin_prompt and capabilities.native_resume
    assert capabilities.read_only
    assert not (tmp_path / "captured-test-input.json").exists()


def test_missing_executable_and_unknown_provider_are_controlled(tmp_path):
    manager = AdapterManager(_POLICY, _SCHEMA, commands={"claude": (str(tmp_path / "absent.exe"),)})
    assert manager.discover("claude").available is False
    assert manager.probe("claude", tmp_path, "Read-only diagnostic.").status == "UNAVAILABLE"
    with pytest.raises(IntegrityError, match="codex or claude"):
        manager.discover("unknown")


def test_mandatory_rules_cannot_be_disabled_even_with_a_permissive_schema(tmp_path):
    policy = tmp_path / "policy.json"
    schema = tmp_path / "schema.json"
    policy.write_text(
        json.dumps(
            {
                "standard_version": "0.1",
                "commandments": {"M1": {"required": False, "description": "Disabled"}},
            }
        )
    )
    schema.write_text("{}")
    with pytest.raises(IntegrityError, match="mandatory M1-M5"):
        AdapterManager(policy, schema)


@pytest.mark.parametrize("provider,filename", [("codex", "AGENTS.md"), ("claude", "CLAUDE.md")])
def test_preparation_is_idempotent_and_preserves_user_bytes_and_equivalent_standard(
    tmp_path, factory, provider, filename
):
    manager = factory(provider)
    original = b"\xef\xbb\xbf# Existing user instructions\r\nKeep this unchanged.\r\n"
    target = tmp_path / filename
    target.write_bytes(original)
    prepared = manager.prepare(provider, tmp_path)
    assert prepared.changed and prepared.context_sha256 is None
    first = target.read_bytes()
    assert first.startswith(original)
    assert all(rule.encode() in first for rule in ("M1", "M2", "M3", "M4", "M5"))
    assert manager.prepare(provider, tmp_path).changed is False
    assert target.read_bytes() == first


def test_preparation_uses_existing_codex_override_and_detects_modified_managed_block(
    tmp_path, factory
):
    manager = factory()
    override = tmp_path / "AGENTS.override.md"
    override.write_text("Existing effective instructions.\n", encoding="utf-8")
    assert manager.prepare("codex", tmp_path).instruction_file == override
    assert not (tmp_path / "AGENTS.md").exists()
    override.write_bytes(override.read_bytes().replace(b"M1", b"XX", 1))
    modified = override.read_bytes()
    with pytest.raises(IntegrityError, match="section changed"):
        manager.prepare("codex", tmp_path)
    assert override.read_bytes() == modified


@pytest.mark.parametrize(
    "body", [b"<!-- corinthos:standard end -->", b"<!-- corinthos:standard begin sha256=bad -->"]
)
def test_partial_managed_markers_fail_without_overwriting_instructions(tmp_path, factory, body):
    path = tmp_path / "AGENTS.md"
    path.write_bytes(body)
    with pytest.raises(IntegrityError, match="incomplete"):
        factory().prepare("codex", tmp_path)
    assert path.read_bytes() == body


@pytest.mark.parametrize("provider", ["codex", "claude"])
def test_real_subprocess_transport_has_same_policy_safe_stdin_and_observed_telemetry(
    tmp_path, factory, provider
):
    observed = []
    result = factory(provider).probe(
        provider,
        tmp_path,
        'Advisory text containing $(literal) and "quotes".',
        on_event=observed.append,
    )
    assert result.status == "COMPLETED" and result.exit_code == 0
    assert result.session_id == _SESSION and result.output == "Synthetic advisory only."
    assert result.usage["input_tokens"] == 7
    assert observed == list(result.events)
    captured = json.loads((tmp_path / "captured-test-input.json").read_text(encoding="utf-8"))
    context = json.loads(captured["input"].split("\n", 1)[1])
    assert set(context["standard"]["commandments"]) == {"M1", "M2", "M3", "M4", "M5"}
    assert context["context"]["objective"] == 'Advisory text containing $(literal) and "quotes".'
    assert "$(literal)" not in captured["args"]
    assert not (tmp_path / "AGENTS.md").exists() and not (tmp_path / "CLAUDE.md").exists()
    if provider == "codex":
        assert captured["args"] == ["--sandbox", "read-only", "exec", "--json", "-"]
        assert result.cost_usd is None and result.telemetry_scope == "turn"
    else:
        assert "--tools" in captured["args"] and "mcp__*" in captured["args"]
        assert result.cost_usd == 0.002 and "conversation" in result.telemetry_scope


@pytest.mark.parametrize(
    "mode,status,error",
    [
        ("malformed", "PROTOCOL_ERROR", "MALFORMED_EVENT"),
        ("deep", "PROTOCOL_ERROR", "MALFORMED_EVENT"),
        ("partial", "PROTOCOL_ERROR", "MISSING_COMPLETION"),
        ("nonzero", "FAILED", "PROCESS_OR_PROVIDER_FAILURE"),
        ("auth", "FAILED", "AUTHENTICATION_REQUIRED"),
        ("quota", "FAILED", "QUOTA_OR_RATE_LIMIT"),
    ],
)
def test_partial_error_or_exit_claims_never_count_as_success(
    tmp_path, factory, mode, status, error
):
    result = factory(mode=mode).probe("codex", tmp_path, "Read-only diagnostic.")
    assert result.status == status and result.error_kind == error


def test_claude_failure_cannot_be_cleared_by_a_later_success_claim(tmp_path, factory):
    result = factory("claude", "failed_then_success").probe(
        "claude", tmp_path, "Read-only diagnostic."
    )
    assert result.status == "FAILED" and result.exit_code == 0


@pytest.mark.parametrize("cancelled", [False, True])
def test_timeout_or_explicit_cancellation_stops_process_and_keeps_partial_identity(
    tmp_path, factory, cancelled
):
    cancel = threading.Event()
    timer = threading.Timer(0.5, cancel.set) if cancelled else None
    if timer:
        timer.start()
    try:
        result = factory(mode="delay").probe(
            "codex",
            tmp_path,
            "Read-only diagnostic.",
            timeout=3 if cancelled else 0.5,
            cancel=cancel,
        )
    finally:
        if timer:
            timer.cancel()
    assert result.status == ("CANCELLED" if cancelled else "TIMEOUT")
    assert result.session_id == _SESSION
    assert result.cleanup_confirmed and result.duration_seconds < 8


def test_output_limits_and_failing_progress_observer_stop_safely(tmp_path, factory, monkeypatch):
    from corinthos.adapters import process

    monkeypatch.setattr(process, "_MAX_LINE", 512)
    result = factory(mode="large").probe("codex", tmp_path, "Read-only diagnostic.")
    assert result.status == "PROTOCOL_ERROR" and result.error_kind == "OUTPUT_LIMIT"

    def observer(_event):
        raise RuntimeError("Private callback diagnostic must stay internal")

    result = factory().probe("codex", tmp_path, "Read-only diagnostic.", on_event=observer)
    assert result.status == "FAILED" and result.error_kind == "EVENT_CALLBACK_FAILED"


def test_task_context_resolves_exact_approved_refs_and_resume_uses_only_explicit_uuid(
    tmp_path, factory
):
    store, context = _context(tmp_path)
    manager = factory(store=store)
    result = manager.invoke("codex", context)
    assert result.status == "COMPLETED"
    result = manager.invoke(
        "codex", replace(context, attempt_id="attempt-next"), resume_session_id=result.session_id
    )
    assert result.status == "COMPLETED"
    args = json.loads((tmp_path / "captured-test-input.json").read_text(encoding="utf-8"))["args"]
    assert args == ["exec", "resume", _SESSION, "--json", "-"]
    with pytest.raises(IntegrityError, match="exact observed session UUID"):
        manager.invoke("codex", context, resume_session_id="--last")
    stale = replace(context, project_ref=replace(context.project_ref, revision_id="missing"))
    with pytest.raises(IntegrityError, match="unavailable or stale"):
        manager.invoke("codex", stale)
    with pytest.raises(IntegrityError, match="observed, stopped"):
        manager.invoke(
            "codex",
            replace(context, objective="A different binding task."),
            resume_session_id=_SESSION,
        )
    with pytest.raises(IntegrityError, match="observed, stopped"):
        factory(store=store).invoke("codex", context, resume_session_id=_SESSION)
    with pytest.raises(IntegrityError, match="observed, stopped"):
        manager.invoke("codex", context, resume_session_id="b1b2c3d4-1111-4111-8111-123456789abc")


def test_task_context_rejects_foreign_type_or_workspace(tmp_path, factory):
    store, context = _context(tmp_path)
    manager = factory(store=store)
    with pytest.raises(IntegrityError, match="matching exact contracts"):
        manager.invoke(
            "codex",
            replace(context, project_ref=replace(context.project_ref, contract_type="MODULE")),
        )
    outside = tmp_path.parent / "outside-agent-test-workspace"
    outside.mkdir()
    with pytest.raises(IntegrityError, match="outside"):
        manager.invoke("codex", replace(context, workspace=outside))


@pytest.mark.parametrize("status", ["TIMEOUT", "CANCELLED"])
def test_unconfirmed_resume_cleanup_revokes_requested_binding_without_a_session_event(
    tmp_path, factory, monkeypatch, status
):
    from corinthos.adapters import service

    store, context = _context(tmp_path)
    manager = factory(store=store)
    observed = manager.invoke("codex", context)
    calls = []

    def incomplete_result(*args, **kwargs):
        calls.append(kwargs["resume"])
        return replace(observed, status=status, session_id=None, cleanup_confirmed=False)

    monkeypatch.setattr(service, "run_process", incomplete_result)
    result = manager.invoke("codex", context, resume_session_id=observed.session_id)
    assert result.status == status and result.session_id is None
    with pytest.raises(IntegrityError, match="observed, stopped"):
        manager.invoke("codex", context, resume_session_id=observed.session_id)
    assert calls == [observed.session_id]


@pytest.mark.parametrize(
    "mismatch", ["workflow_module", "workflow_technology", "module_technology", "workflow_project"]
)
def test_individually_active_refs_must_form_one_consistent_approved_context(
    tmp_path, factory, mismatch
):
    store, context = _context(tmp_path)

    def publish(document):
        proof = approval_request(document) if document["metadata"]["approval"] is not None else None
        return store.publish(
            document,
            context=PublishContext(
                document["metadata"]["provenance"]["engine"],
                document["metadata"]["provenance"]["actor_id"],
                lambda request: request == proof,
            ),
        )

    def example(name):
        return json.loads(
            (_ROOT / "examples" / "contracts" / (name + ".json")).read_text(encoding="utf-8")
        )

    technology = example("technology-decision")
    technology_ref = publish(technology)
    module = example("module")
    module_ref = publish(module)
    workflow_ref = publish(example("workflow"))
    other_technology = deepcopy(technology)
    other_technology["metadata"].update(
        contract_id="other-technology", revision_id="other-technology-r1"
    )
    other_technology["payload"]["decision_scope"]["module_ids"] = ["other"]
    other_technology_ref = publish(other_technology)
    other_module = deepcopy(module)
    other_module["metadata"].update(contract_id="other-module", revision_id="other-module-r1")
    other_module["payload"].update(
        module_id="other",
        provided_interfaces=[],
        technology_decision_refs=[other_technology_ref.to_json()],
    )
    other_module["payload"]["verification_spec"]["interface_checks"] = []
    other_module_ref = publish(other_module)
    candidate = replace(
        context,
        module_refs=(module_ref,),
        technology_refs=(technology_ref,),
        workflow_ref=workflow_ref,
    )
    if mismatch == "workflow_module":
        candidate = replace(candidate, module_refs=(other_module_ref,), technology_refs=())
    elif mismatch == "workflow_technology":
        candidate = replace(candidate, technology_refs=(other_technology_ref,))
    elif mismatch == "module_technology":
        candidate = replace(candidate, workflow_ref=None, technology_refs=(other_technology_ref,))
    else:
        project = store.get(context.project_ref)
        project["metadata"].update(
            revision_id="project-new-context", version=2, supersedes=context.project_ref.to_json()
        )
        project["payload"]["vision"] = "A newly approved project vision."
        candidate = replace(candidate, project_ref=publish(project))
    with pytest.raises(
        IntegrityError, match="same exact Project|exact selections|Module decisions"
    ):
        factory(store=store).invoke("codex", candidate)
    assert not (tmp_path / "captured-test-input.json").exists()


def test_pm_hook_returns_only_advisory_text_and_never_mutates_snapshot(tmp_path, factory):
    snapshot = {"payload": {"vision": "A human idea."}, "version": 1}
    original = json.loads(json.dumps(snapshot))
    result = factory().pm_assistance("codex", tmp_path)(snapshot)
    assert result == ["Synthetic advisory only."] and snapshot == original
    assert not (tmp_path / ".corinthos" / "state.db").exists()


def test_redirected_instruction_file_is_rejected(tmp_path, factory):
    outside = tmp_path / "outside.md"
    outside.write_text("Preserve external contents", encoding="utf-8")
    try:
        os.link(outside, tmp_path / "AGENTS.md")
    except OSError:
        pytest.skip("The filesystem does not permit the synthetic link fixture.")
    with pytest.raises(IntegrityError, match="unlinked"):
        factory().prepare("codex", tmp_path)
    assert outside.read_text(encoding="utf-8") == "Preserve external contents"

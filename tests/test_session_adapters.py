# SPDX-License-Identifier: MPL-2.0
"""Exercise the existing native transport through the supervisor-owned session seam."""

import os
import sys
from pathlib import Path
from threading import Event

import pytest

from corinthos.adapters import AdapterManager, SessionPlanError

_ROOT = Path(__file__).resolve().parents[1]
_SESSION = "a1b2c3d4-1111-4111-8111-123456789abc"
_SYNTHETIC = """
import json, sys, time
from pathlib import Path

provider, mode = sys.argv[1:3]
args = sys.argv[3:]
with Path(__file__).with_suffix('.log').open('a', encoding='utf-8') as log:
    log.write(f'{provider} {args!r}\\n')
if '--version' in args:
    print('synthetic native fixture 1.2.3')
    raise SystemExit
if '--help' in args:
    print('--json --sandbox read-only --print --output-format stream-json --verbose --resume SESSION_ID stdin --tools --disallowedTools')
    raise SystemExit
sys.stdin.read()
def emit(value):
    print(json.dumps(value), flush=True)
native_id = 'a1b2c3d4-1111-4111-8111-123456789abc'
if mode == 'mismatch':
    native_id = 'a1b2c3d4-2222-4222-8222-123456789abc'
if provider == 'claude':
    emit({'type': 'system', 'subtype': 'init', 'session_id': native_id, 'model': 'observed-model'})
    emit({'type': 'assistant', 'message': {'content': [{'type': 'tool_use'}]}})
    event = json.dumps({'type': 'result', 'is_error': False, 'subtype': 'success',
        'session_id': native_id, 'result': 'z' * 1024, 'usage': {
            'input_tokens': 0, 'output_tokens': 9, 'cache_read_input_tokens': 0}})
    for _ in range(2):
        print(event[:-1] + ', "total_cost_usd": 0.012345678901234567890123}', flush=True)
else:
    emit({'type': 'thread.started', 'thread_id': native_id})
    if mode == 'delay':
        time.sleep(8)
    if mode == 'malformed':
        print('bad synthetic native event', flush=True)
        raise SystemExit
    if mode == 'invalid-exponent':
        print('{"type":"turn.completed","noise":1e9999999999999999999999999999}', flush=True)
        raise SystemExit
    if mode == 'unhashable-error':
        emit({'type': 'error', 'error': {'code': []}})
        raise SystemExit
    emit({'type': 'item.completed', 'item': {'type': 'agent_message', 'text': 'ordinary output'}})
    emit({'type': 'turn.completed', 'usage': {'output_tokens': 0}})
"""


@pytest.fixture
def native(tmp_path):
    program = tmp_path / "native.py"
    program.write_text(_SYNTHETIC, encoding="utf-8")

    def create(mode="success"):
        return AdapterManager(
            _ROOT / "policies/standard.yaml",
            _ROOT / "schemas/standard.schema.json",
            commands={
                name: (sys.executable, str(program), name, mode) for name in ("codex", "claude")
            },
        )

    return create, program.with_suffix(".log"), tmp_path


def _run(manager, plan, **params):
    return manager.run_session(
        plan,
        task_id="work-test",
        attempt_id="attempt-test",
        **{"timeout": 10, "cancel": None, "on_event": None, **params},
    )


def test_session_uses_selected_provider_and_exact_cumulative_currency(native):
    create, log, root = native
    manager = create()
    assert not log.exists()
    plan = manager.session_plan("claude", root, prompt="Echo a fixed explanation.", read_only=True)
    assert plan.capabilities.native_resume
    assert len(plan.binding_sha256) == 64
    assert (root / "CLAUDE.md").exists() and not (root / "AGENTS.md").exists()
    seen = []
    result = _run(manager, plan, on_start=lambda: seen.append("START"), on_event=seen.append)
    assert result.status == "COMPLETED" and result.cleanup_confirmed and result.exit_code == 0
    assert result.model == "observed-model" and result.session_id == _SESSION
    assert result.reported_cost == "0.012345678901234567890123"
    assert result.reported_cost_currency == "USD"
    assert result.normalized_usage == {"input_tokens": 0, "output_tokens": 9, "cached_tokens": 0}
    assert seen[0] == "START"
    assert all(row["native_session_id"] == _SESSION for row in seen[1:])
    assert any(row["kind"] == "TOOL_ACTIVITY" for row in seen[1:])
    snippets = [row["payload"]["text"] for row in seen[1:] if "text" in row["payload"]]
    assert snippets == ["z" * 768, "z" * 768]
    snapshots = [row["payload"] for row in seen[1:] if row["kind"] == "USAGE"]
    assert len(snapshots) == 2 and snapshots[0] == snapshots[1]
    assert not result.events and not result.output
    assert len(log.read_text("utf-8").splitlines()) == 3
    assert all(line.startswith("claude ") for line in log.read_text("utf-8").splitlines())


def test_session_uses_same_native_recovery_and_rechecks_binding(native):
    create, log, root = native
    manager = create()
    plan = manager.session_plan("codex", root, prompt="Fixed session instruction.")
    before = log.read_bytes()
    same = create()
    digest = same.session_binding("codex", root, prompt="Fixed session instruction.")
    assert digest == plan.binding_sha256 and log.read_bytes() == before
    resumed = same.session_plan(
        "codex",
        root,
        prompt="Fixed session instruction.",
        prepare=False,
        expected_binding_sha256=digest,
    )
    assert resumed.binding_sha256 == plan.binding_sha256
    result = _run(manager, resumed, resume_session_id=_SESSION)
    assert result.session_id == _SESSION and result.status == "COMPLETED"
    assert result.normalized_usage == {"output_tokens": 0}
    assert result.reported_cost is None and result.model is None
    assert "['exec', 'resume', '" + _SESSION in log.read_text("utf-8")

    (root / "AGENTS.md").write_text("The local instruction changed.", encoding="utf-8")
    before = log.read_bytes()
    with pytest.raises(SessionPlanError) as exc:
        same.session_plan(
            "codex",
            root,
            prompt="Fixed session instruction.",
            prepare=False,
            expected_binding_sha256=digest,
        )
    assert exc.value.error_kind == "EXECUTION_BINDING_CHANGED" and log.read_bytes() == before
    with pytest.raises(SessionPlanError) as exc:
        _run(manager, resumed, resume_session_id=_SESSION)
    assert exc.value.error_kind == "EXECUTION_BINDING_CHANGED" and log.read_bytes() == before


@pytest.mark.parametrize("mode", ["malformed", "mismatch", "invalid-exponent", "unhashable-error"])
def test_session_protocol_errors_warn_without_accepting_other_native_identity(native, mode):
    create, _, root = native
    manager = create(mode)
    plan = manager.session_plan("codex", root, prompt="Fixed session instruction.")
    seen = []
    result = _run(manager, plan, on_event=seen.append, resume_session_id=_SESSION)
    assert result.status == "PROTOCOL_ERROR" and result.cleanup_confirmed
    assert seen[-1]["kind"] == "WARNING"
    assert all(row["native_session_id"] in {None, _SESSION} for row in seen)


@pytest.mark.parametrize("action", ["cancel", "timeout"])
def test_session_cancel_or_timeout_returns_reap_confirmation(native, action):
    create, _, root = native
    manager = create("delay")
    cancel = Event()
    seen = []

    def on_event(event):
        seen.append(event)
        if action == "cancel":
            cancel.set()

    plan = manager.session_plan("codex", root, prompt="Fixed session instruction.")
    result = _run(manager, plan, on_event=on_event, timeout=2, cancel=cancel)
    assert seen[0]["native_session_id"] == _SESSION
    assert result.status == {"cancel": "CANCELLED", "timeout": "TIMEOUT"}[action]
    assert result.cleanup_confirmed and result.exit_code is not None


@pytest.mark.skipif(os.name != "posix", reason="POSIX process guardian only.")
def test_session_provider_and_capability_probes_use_the_guardian(native):
    import fcntl

    create, _, root = native
    manager = create()
    with (root / "test.lock").open("xb") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        plan = manager.session_plan(
            "codex", root, prompt="Fixed session instruction.", owner_fd=lock.fileno()
        )
        result = _run(manager, plan, owner_fd=lock.fileno())
    assert result.status == "COMPLETED" and result.exit_code == 0 and result.cleanup_confirmed

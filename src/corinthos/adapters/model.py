# SPDX-License-Identifier: MPL-2.0
"""Explicit inputs and observed results at the external-agent boundary."""

from dataclasses import dataclass, field
from pathlib import Path
from uuid import uuid4

from corinthos.contracts import ContractRef


@dataclass(frozen=True, slots=True)
class Capabilities:
    provider: str
    available: bool
    version: str | None = None
    json_events: bool = False
    stdin_prompt: bool = False
    native_resume: bool = False
    read_only: bool = False
    reason: str | None = None
    executable: str | None = None
    discovery: str | None = None


@dataclass(frozen=True, slots=True)
class ContextInput:
    workspace: Path
    project_ref: ContractRef
    objective: str
    deliverables: tuple[str, ...]
    verification_plan: tuple[str, ...]
    module_refs: tuple[ContractRef, ...] = ()
    technology_refs: tuple[ContractRef, ...] = ()
    workflow_ref: ContractRef | None = None
    interface_obligations: tuple[str, ...] = ()
    prior_facts: tuple[str, ...] = ()
    task_id: str = field(default_factory=lambda: "task-" + uuid4().hex)
    attempt_id: str = field(default_factory=lambda: "attempt-" + uuid4().hex)


@dataclass(frozen=True, slots=True)
class PreparedContext:
    instruction_file: Path
    standard_sha256: str
    context_sha256: str | None
    changed: bool


@dataclass(frozen=True, slots=True)
class AgentResult:
    provider: str
    status: str
    task_id: str
    attempt_id: str
    version: str | None = None
    exit_code: int | None = None
    session_id: str | None = None
    events: tuple[dict, ...] = ()
    output: str = ""
    usage: dict | None = None
    cost_usd: float | None = None
    telemetry_scope: str | None = None
    error_kind: str | None = None
    duration_seconds: float = 0.0
    cleanup_confirmed: bool = True

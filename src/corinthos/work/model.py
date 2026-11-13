# SPDX-License-Identifier: MPL-2.0
"""The operational Work Item model, independent of contract publication."""

from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

from corinthos.contracts import ContractError, ContractRef


class WorkError(ContractError):
    """An invalid Work Item, operation, or project-local reference."""


class ScopeLevel(StrEnum):
    TASK = "TASK"
    CHANGE = "CHANGE"
    PROJECT = "PROJECT"
    CRITICAL = "CRITICAL"


class WorkStatus(StrEnum):
    OPEN = "OPEN"
    ACTIVE = "ACTIVE"
    BLOCKED = "BLOCKED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


TRANSITIONS = {
    WorkStatus.OPEN: frozenset({WorkStatus.ACTIVE, WorkStatus.BLOCKED, WorkStatus.CANCELLED}),
    WorkStatus.ACTIVE: frozenset({WorkStatus.BLOCKED, WorkStatus.COMPLETED, WorkStatus.CANCELLED}),
    WorkStatus.BLOCKED: frozenset({WorkStatus.ACTIVE, WorkStatus.CANCELLED}),
    WorkStatus.COMPLETED: frozenset(),
    WorkStatus.CANCELLED: frozenset(),
}


@dataclass(frozen=True, slots=True)
class WorkProvenance:
    actor_id: str
    source: Literal["LOCAL_OPERATOR"] = "LOCAL_OPERATOR"


@dataclass(frozen=True, slots=True)
class AffectedModule:
    module_id: str
    module_ref: ContractRef | None


@dataclass(frozen=True, slots=True)
class WorkItem:
    work_item_id: str
    project_id: str
    parent_work_item_id: str | None
    scope_level: ScopeLevel
    objective: str
    acceptance_criteria: tuple[str, ...]
    status: WorkStatus
    validation_policy: str
    provenance: WorkProvenance
    created_at: str
    updated_at: str
    completed_at: str | None
    affected_modules: tuple[AffectedModule, ...]
    dependencies: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class WorkTreeNode:
    work_item_id: str
    parent_work_item_id: str | None
    depth: int
    scope_level: ScopeLevel
    status: WorkStatus
    objective: str


@dataclass(frozen=True, slots=True)
class WorkCounts:
    total: int
    by_status: dict[str, int]
    by_scope: dict[str, int]

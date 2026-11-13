# SPDX-License-Identifier: MPL-2.0
"""Test operational Work Items through their project-local service boundary."""

import json
import os
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest

from corinthos.bootstrap import initialize
from corinthos.contracts import (
    ConflictError,
    ContractRef,
    ContractStore,
    PublishContext,
    approval_request,
)
from corinthos.work import WorkError, WorkService

_CONTRACTS = Path(__file__).resolve().parents[1] / "examples/contracts"


@pytest.fixture
def work(tmp_path):
    initialize(tmp_path)
    return WorkService(tmp_path)


def _create(work, objective="Fixture work", **overrides):
    return work.create(
        **(
            {"scope_level": "TASK", "objective": objective, "acceptance_criteria": ["Proof"]}
            | overrides
        )
    )


def _publish(store, document):
    provenance = document["metadata"]["provenance"]
    receipt = approval_request(document) if document["metadata"]["approval"] is not None else None
    return store.publish(
        document,
        context=PublishContext(
            provenance["engine"], provenance["actor_id"], lambda request: request == receipt
        ),
    )


def _example(name):
    return json.loads((_CONTRACTS / f"{name}.json").read_text("utf-8"))


def test_passive_reads_do_not_create_database(work):
    private = work.root / ".corinthos"
    assert not (private / "state.db").exists()
    assert work.list() == []
    assert work.tree() == []
    assert work.counts().total == 0
    assert not (private / "state.db").exists()


@pytest.mark.parametrize("root", ["", "x" * 4097, "with\x00null", "with\ud800surrogate"])
def test_direct_service_requires_safe_bounded_project_paths(root):
    with pytest.raises(ValueError, match="Invalid project root"):
        WorkService(root).list()


@pytest.mark.skipif(os.name != "nt", reason="Windows path syntax")
@pytest.mark.parametrize("root", [r"\\server\share\root", r"C:\Local:alternate-stream"])
def test_direct_service_refuses_windows_redirected_path_syntax(root):
    with pytest.raises(ValueError, match="Invalid project root"):
        WorkService(root).list()


def test_lifecycle_filters_and_reopening(work):
    task, change, project, critical = (
        _create(work, scope, scope_level=scope, acceptance_criteria=["First", "Second"])
        for scope in ("TASK", "CHANGE", "PROJECT", "CRITICAL")
    )
    assert len({item.work_item_id for item in (task, change, project, critical)}) == 4
    assert len({item.project_id for item in (task, change, project, critical)}) == 1
    assert task.acceptance_criteria == ("First", "Second")
    assert (
        task.provenance.source == "LOCAL_OPERATOR" and task.provenance.actor_id == "local-operator"
    )
    assert task.created_at == task.updated_at and task.completed_at is None
    assert work.list(scope_level="CHANGE") == [change]
    assert work.list(limit=1, offset=1) == [change]
    with pytest.raises(WorkError, match="status transition"):
        work.transition(task.work_item_id, "COMPLETED")
    review = work.transition(task.work_item_id, "ACTIVE", expected_updated_at=task.updated_at)
    assert review.updated_at > task.updated_at and review.completed_at is None
    with pytest.raises(ConflictError):
        work.update(task.work_item_id, objective="Stale edit", expected_updated_at=task.updated_at)
    blocked = work.transition(review.work_item_id, "BLOCKED")
    with pytest.raises(WorkError, match="status transition"):
        work.transition(blocked.work_item_id, "COMPLETED")
    work.transition(task.work_item_id, "ACTIVE")
    done = work.transition(task.work_item_id, "COMPLETED")
    cancelled = work.transition(change.work_item_id, "CANCELLED")
    assert done.completed_at == done.updated_at and cancelled.completed_at == cancelled.updated_at
    assert work.list(status="COMPLETED") == [done]
    for item in done, cancelled:
        with pytest.raises(WorkError, match="Terminal"):
            work.transition(item.work_item_id, "ACTIVE")
        with pytest.raises(WorkError, match="Terminal"):
            work.update(item.work_item_id, objective="Cannot rewrite terminal records")
    reopened = WorkService(work.root)
    assert reopened.get(task.work_item_id) == done
    assert reopened.counts().by_status == {
        "OPEN": 2,
        "ACTIVE": 0,
        "BLOCKED": 0,
        "COMPLETED": 1,
        "CANCELLED": 1,
    }
    assert reopened.counts().by_scope == {
        key: 1 for key in ("TASK", "CHANGE", "PROJECT", "CRITICAL")
    }


@pytest.mark.parametrize(
    "payload",
    [
        {"scope_level": "AUTO"},
        {"objective": "x" * 601},
        {"objective": " \n"},
        {"objective": "unsafe\x1b[31m"},
        {"acceptance_criteria": []},
        {"acceptance_criteria": "proof"},
        {"acceptance_criteria": ["proof"] * 9},
        {"acceptance_criteria": ["x" * 301]},
        {"validation_policy": "x" * 65},
        {"validation_policy": "with spaces"},
        {"affected_modules": ["duplicate", "duplicate"]},
        {"depends_on": ["not-a-work-id"]},
    ],
)
def test_invalid_work_item_inputs_do_not_create_database(work, payload):
    with pytest.raises(WorkError):
        work.create(
            **(
                {
                    "scope_level": "TASK",
                    "objective": "Valid input",
                    "acceptance_criteria": ["Proof"],
                }
                | payload
            )
        )
    assert not (work.root / ".corinthos/state.db").exists()


def test_parent_subtree_pagination_and_no_physical_delete(work):
    first = _create(work, "First root")
    second = _create(work, "Second root")
    child = _create(work, "Child", parent_work_item_id=first.work_item_id)
    deep = _create(work, "Nested", parent_work_item_id=child.work_item_id)
    expected = [
        (first.work_item_id, 0),
        (child.work_item_id, 1),
        (deep.work_item_id, 2),
        (second.work_item_id, 0),
    ]
    assert [(node.work_item_id, node.depth) for node in work.tree()] == expected
    assert [(node.work_item_id, node.depth) for node in work.tree(limit=2, offset=1)] == expected[
        1:3
    ]
    assert [node.work_item_id for node in work.tree(parent_work_item_id=child.work_item_id)] == [
        deep.work_item_id
    ]
    for parent in first, child, deep:
        with pytest.raises(WorkError, match="cycle"):
            work.update(first.work_item_id, parent_work_item_id=parent.work_item_id)
    with sqlite3.connect(ContractStore(work.root).database_path) as connection:
        with pytest.raises(sqlite3.IntegrityError, match="retained"):
            connection.execute(
                "DELETE FROM work_items WHERE work_item_id = ?", (second.work_item_id,)
            )
    assert work.update(child.work_item_id, parent_work_item_id=None).parent_work_item_id is None
    assert work.tree(parent_work_item_id=first.work_item_id) == []


def test_dependency_dag_and_edit_rolls_back_as_one_transaction(work):
    first = _create(work, "First")
    chain = _create(work, "Chain", depends_on=[first.work_item_id])
    other = _create(work, "Other", depends_on=[first.work_item_id])
    final = _create(work, "Final", depends_on=[other.work_item_id, chain.work_item_id])
    ordered = [first.work_item_id, *sorted((chain.work_item_id, other.work_item_id))]
    assert work.dependencies(final.work_item_id) == ordered
    assert work.dependencies(final.work_item_id, limit=1, offset=2) == ordered[2:]
    with pytest.raises(WorkError, match="cycle"):
        work.update(first.work_item_id, depends_on=[final.work_item_id])
    with pytest.raises(WorkError, match="depend on itself"):
        work.add_dependency(first.work_item_id, first.work_item_id)
    with pytest.raises(WorkError, match="Duplicate"):
        work.add_dependency(final.work_item_id, other.work_item_id)
    with pytest.raises(WorkError, match="not found"):
        work.update(first.work_item_id, objective="Atomic change", depends_on=["work-" + "0" * 32])
    assert work.get(first.work_item_id) == first
    assert work.remove_dependency(final.work_item_id, other.work_item_id).dependencies == (
        chain.work_item_id,
    )


def test_module_refs_preserve_exact_canonical_identity_and_unresolved_ids(work):
    store = ContractStore(work.root)
    for name in ("project", "technology-decision"):
        _publish(store, _example(name))
    module = _example("module")
    ref = _publish(store, module)
    item = _create(work, affected_modules=["greeting", "planned-module"])
    assert item.project_id == ref.project_id
    assert [(row.module_id, row.module_ref) for row in item.affected_modules] == [
        ("greeting", ref),
        ("planned-module", None),
    ]
    module["metadata"].update(
        revision_id="demo-module-r2",
        version=2,
        supersedes=ref.to_json(),
        approval={"kind": "HUMAN", "approval_id": "fixture-module-approval", "actor_id": "owner"},
    )
    module["payload"]["purpose_and_boundaries"]["responsibilities"].append("Explain the greeting.")
    next_ref = _publish(store, module)
    changed = work.add_module(item.work_item_id, "third-module")
    assert changed.affected_modules[0].module_ref == ref
    changed = work.remove_module(item.work_item_id, "greeting")
    assert (
        work.add_module(changed.work_item_id, "greeting").affected_modules[0].module_ref == next_ref
    )
    assert ContractRef.from_document(store.resolve_active(ref.contract_id)) == next_ref


def test_projects_at_same_root_cannot_share_parent_or_dependency(work):
    local = _create(work)
    store = ContractStore(work.root)
    contract = _publish(store, _example("project"))
    canonical = _create(work, project_id=contract.project_id)
    assert canonical.project_id != local.project_id
    assert work.counts(local.project_id).total == 1
    assert work.list(project_id=contract.project_id) == [canonical]
    with pytest.raises(WorkError, match="another project"):
        work.update(canonical.work_item_id, parent_work_item_id=local.work_item_id)
    with pytest.raises(WorkError, match="same project"):
        work.add_dependency(canonical.work_item_id, local.work_item_id)
    assert work.get(canonical.work_item_id) == canonical


def test_concurrent_compare_and_swap_has_one_winner(work):
    record = _create(work)
    barrier = Barrier(2)

    def update(value):
        barrier.wait(timeout=10)
        try:
            return work.update(
                record.work_item_id, objective=value, expected_updated_at=record.updated_at
            )
        except ConflictError:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(update, ("First", "Second")))
    assert [result for result in results if result is not None] == [work.get(record.work_item_id)]

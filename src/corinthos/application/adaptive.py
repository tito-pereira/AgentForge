# SPDX-License-Identifier: MPL-2.0
"""Shared application operations for proportional Work Item workflows."""

from corinthos.work.adaptive import AdaptiveWorkflowService
from corinthos.work.scope import ScopePolicyService


def scope_assess(root, work_item_id):
    return ScopePolicyService(root).assess(work_item_id)


def scope_set(root, work_item_id, scope_level, expected_updated_at, confirm_downgrade=False):
    return ScopePolicyService(root).set(
        work_item_id, scope_level, expected_updated_at, confirm_downgrade
    )


def flow_status(root, work_item_id):
    return AdaptiveWorkflowService(root).status(work_item_id)


def flow_complete(root, work_item_id, expected_updated_at):
    return AdaptiveWorkflowService(root).complete(work_item_id, expected_updated_at)


def work_report(root, work_item_id):
    return AdaptiveWorkflowService(root).report(work_item_id)

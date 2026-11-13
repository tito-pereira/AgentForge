# SPDX-License-Identifier: MPL-2.0
"""Shared, bounded audit views for frozen context and session handoffs."""

from corinthos.application.workspace import DEFAULT_LIMIT, _page, _page_args
from corinthos.context import ContextService, HandoffService
from corinthos.sessions.repository import SessionRepository

_PROJECTION_FIELDS = (
    "projection_id",
    "project_id",
    "work_item_id",
    "target_provider",
    "selector_policy_version",
    "redaction_policy_version",
    "projection_digest",
    "source_set_digest",
    "created_at",
)
_HANDOFF_FIELDS = (
    "handoff_id",
    "project_id",
    "work_item_id",
    "source_session_id",
    "run_generation",
    "event_cutoff",
    "provider",
    "terminal_state",
    "digest",
    "created_at",
)


def _fields(value, names):
    return {key: getattr(value, key) for key in names}


def context_create(root, work_item_id, provider):
    return _fields(ContextService(root).create(work_item_id, provider), _PROJECTION_FIELDS)


def context_get(root, projection_id):
    return _fields(ContextService(root).get(projection_id), _PROJECTION_FIELDS)


def context_verify(root, projection_id):
    return {
        **_fields(ContextService(root).verify(projection_id), _PROJECTION_FIELDS),
        "verified": True,
    }


def context_list(root, *, work_item_id=None, limit=DEFAULT_LIMIT, offset=0):
    _page_args(limit, offset)
    values = ContextService(root).list(work_item_id=work_item_id, limit=limit, offset=offset)
    return _page(
        "projections", [_fields(value, _PROJECTION_FIELDS) for value in values], limit, offset
    )


def context_sources(root, projection_id, *, limit=DEFAULT_LIMIT, offset=0):
    _page_args(limit, offset)
    values = ContextService(root).sources(projection_id, limit=limit, offset=offset)
    return _page("sources", [value.descriptor() for value in values], limit, offset)


def context_for_session(root, session_id):
    projection_id = SessionRepository(root).get(session_id).context_projection_id
    return {"projection": context_get(root, projection_id) if projection_id else None}


def handoff_create(root, session_id):
    value = HandoffService(root).create(session_id)
    return {**_fields(value, _HANDOFF_FIELDS), "payload": value.canonical_payload}


def handoff_get(root, handoff_id):
    value = HandoffService(root).get(handoff_id)
    return {**_fields(value, _HANDOFF_FIELDS), "payload": value.canonical_payload}


def handoff_list(root, *, work_item_id=None, session_id=None, limit=DEFAULT_LIMIT, offset=0):
    _page_args(limit, offset)
    values = HandoffService(root).list(
        work_item_id=work_item_id, session_id=session_id, limit=limit, offset=offset
    )
    return _page("handoffs", [_fields(value, _HANDOFF_FIELDS) for value in values], limit, offset)

# SPDX-License-Identifier: MPL-2.0
"""Freeze and verify deterministic Work Item context projections."""

from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

from corinthos.contracts.model import ID_PATTERN

from .index import ContextIndex, source_key
from .model import (
    MAX_PROJECTION_BYTES,
    MAX_SOURCES,
    REDACTION_POLICY_VERSION,
    SELECTOR_POLICY_VERSION,
    ContextError,
    Projection,
    canonical_bytes,
    digest,
)
from .redaction import sanitize_text


def identifier(value, label):
    if not isinstance(value, str) or not ID_PATTERN.fullmatch(value):
        raise ContextError(f"Use a valid {label} identity.")
    return value


def page(limit, offset):
    if (
        type(limit) is not int
        or not 1 <= limit <= 25
        or type(offset) is not int
        or not 0 <= offset <= 1_000_000
    ):
        raise ContextError("Use a bounded Context page.")


def _reconstruct(project_id, work_item_id, provider, selector, redaction, sources):
    descriptors = [source.descriptor() for source in sources]
    return {
        "project_id": project_id,
        "work_item_id": work_item_id,
        "target_provider": provider,
        "selector_policy_version": selector,
        "redaction_policy_version": redaction,
        "sources": [
            {**descriptor, "capture": source.capture}
            for source, descriptor in zip(sources, descriptors, strict=True)
        ],
    }, digest(descriptors)


def _payload(project_id, work_item_id, provider, sources):
    return _reconstruct(
        project_id,
        work_item_id,
        provider,
        SELECTOR_POLICY_VERSION,
        REDACTION_POLICY_VERSION,
        sources,
    )


def _verify(projection, sources):
    try:
        if (
            not sources
            or len(sources) > MAX_SOURCES
            or sources[0].reason != "WORK_ITEM"
            or sources[0].identity != projection.work_item_id
            or sources[0].capture["project_id"] != projection.project_id
            or sources != sorted(sources, key=source_key)
            or not all(
                source.ordinal == ordinal and digest(source.capture) == source.digest
                for ordinal, source in enumerate(sources)
            )
        ):
            raise ContextError("Stored Context sources failed verification.")
        payload, source_digest = _reconstruct(
            projection.project_id,
            projection.work_item_id,
            projection.target_provider,
            projection.selector_policy_version,
            projection.redaction_policy_version,
            sources,
        )
        data = canonical_bytes(payload)
        if (
            len(data) > MAX_PROJECTION_BYTES
            or data != canonical_bytes(projection.canonical_payload)
            or digest(payload) != projection.projection_digest
            or source_digest != projection.source_set_digest
        ):
            raise ContextError("Stored Context Projection failed verification.")
    except (KeyError, TypeError, AttributeError):
        raise ContextError("Stored Context Projection failed verification.") from None
    return projection


def _select(project_id, work_item_id, provider, candidates):
    chosen = []
    seen = set()
    for source in sorted(candidates, key=source_key):
        identity = (source.kind, source.identity, source.revision)
        if identity in seen:
            continue
        source = replace(source, ordinal=len(chosen))
        payload, _ = _payload(project_id, work_item_id, provider, [*chosen, source])
        if len(canonical_bytes(payload)) > MAX_PROJECTION_BYTES:
            break
        seen.add(identity)
        chosen.append(source)
        if len(chosen) >= MAX_SOURCES:
            break
    return chosen


class ContextService:
    """Resolve and verify immutable, local Context Projections."""

    def __init__(self, root):
        from .repository import ContextRepository

        self.repository = ContextRepository(root)

    def create(self, work_item_id, provider):
        from corinthos.providers import SUPPORTED_PROVIDERS

        identifier(work_item_id, "Work Item")
        if not isinstance(provider, str) or provider not in SUPPORTED_PROVIDERS:
            raise ContextError("Select a supported target provider.")
        with self.repository.write() as connection:
            (project_id, exact_work_id), candidates = ContextIndex(
                connection, self.repository
            ).select(work_item_id)
            if sanitize_text(exact_work_id) != exact_work_id:
                raise ContextError("The Work Item identity is not admissible as Context.")
            chosen = _select(project_id, exact_work_id, provider, candidates)
            payload, source_set_digest = _payload(project_id, exact_work_id, provider, chosen)
            projection = Projection(
                "projection-" + uuid4().hex,
                project_id,
                exact_work_id,
                provider,
                SELECTOR_POLICY_VERSION,
                REDACTION_POLICY_VERSION,
                payload,
                digest(payload),
                source_set_digest,
                datetime.now(UTC).isoformat(),
            )
            saved = self.repository.save_projection(connection, projection, chosen)
            return self._verify(connection, saved)

    def _get(self, connection, projection_id):
        item = (
            self.repository.get_projection(connection, projection_id)
            if connection is not None
            else None
        )
        if item is None:
            raise ContextError("The Context Projection was not found.")
        return item

    def _verify(self, connection, projection):
        sources = self.repository.projection_sources(
            connection,
            projection.projection_id,
            limit=MAX_SOURCES + 1,
            offset=0,
        )
        return _verify(projection, sources)

    def get(self, projection_id):
        return self.verify(projection_id)

    def verify(self, projection_id):
        identifier(projection_id, "Context Projection")
        with self.repository.read() as connection:
            return self._verify(connection, self._get(connection, projection_id))

    def list(self, work_item_id=None, *, limit=10, offset=0):
        if work_item_id is not None:
            identifier(work_item_id, "Work Item")
        page(limit, offset)
        with self.repository.read() as connection:
            if connection is None:
                return []
            projections = self.repository.list_projections(
                connection, work_item_id=work_item_id, limit=limit, offset=offset
            )
            return [self._verify(connection, projection) for projection in projections]

    def sources(self, projection_id, *, limit=10, offset=0):
        identifier(projection_id, "Context Projection")
        page(limit, offset)
        with self.repository.read() as connection:
            self._verify(connection, self._get(connection, projection_id))
            return self.repository.projection_sources(
                connection, projection_id, limit=limit, offset=offset
            )

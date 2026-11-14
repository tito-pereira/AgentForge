# SPDX-License-Identifier: MPL-2.0
"""The immutable derived records and canonical JSON rules for Context."""

import json
from dataclasses import dataclass
from hashlib import sha256

from corinthos.contracts import IntegrityError

SELECTOR_POLICY_VERSION = 1
REDACTION_POLICY_VERSION = 1
MAX_PROJECTION_BYTES = 128 * 1024
MAX_SOURCES = 40
MAX_CAPTURE_BYTES = 32 * 1024
MAX_HANDOFF_BYTES = 24 * 1024


class ContextError(IntegrityError):
    """Context is unavailable, invalid, or fails verification."""


def canonical_bytes(value):
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise ContextError("Context data cannot be represented as canonical UTF-8 JSON.") from None


def digest(value):
    return sha256(canonical_bytes(value)).hexdigest()


@dataclass(frozen=True, slots=True)
class Source:
    ordinal: int
    kind: str
    authority: str
    identity: str
    revision: str | None
    digest: str
    reason: str
    redaction: tuple[str, ...]
    capture: dict

    def descriptor(self):
        return {
            "ordinal": self.ordinal,
            "kind": self.kind,
            "authority": self.authority,
            "identity": self.identity,
            "revision": self.revision,
            "digest": self.digest,
            "reason": self.reason,
            "redaction": list(self.redaction),
        }


@dataclass(frozen=True, slots=True)
class Projection:
    projection_id: str
    project_id: str
    work_item_id: str
    target_provider: str
    selector_policy_version: int
    redaction_policy_version: int
    canonical_payload: dict
    projection_digest: str
    source_set_digest: str
    created_at: str


@dataclass(frozen=True, slots=True)
class Handoff:
    handoff_id: str
    project_id: str
    work_item_id: str
    source_session_id: str
    run_generation: int
    provider: str
    terminal_state: str
    event_cutoff: int
    canonical_payload: dict
    digest: str
    created_at: str

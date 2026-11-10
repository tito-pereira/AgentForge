# SPDX-License-Identifier: MPL-2.0
"""Complete readable reviews with visibly escaped terminal control characters."""

import difflib
import unicodedata
from datetime import UTC, datetime


def safe_text(value: object) -> str:
    """Keep text readable while making layout and direction controls visible."""
    text = str(value)
    return "".join(
        (f"\\u{ord(character):04x}" if ord(character) <= 0xFFFF else f"\\U{ord(character):08x}")
        if unicodedata.category(character) in {"Cc", "Cf", "Cs", "Zl", "Zp"}
        else character
        for character in text
    )


def render_fields(value: object, indent: int = 0) -> str:
    """Render every nested value, including empty collections and null fields."""
    prefix = " " * indent
    if isinstance(value, dict):
        if not value:
            return prefix + "(none)"
        lines = []
        for key, item in value.items():
            label = safe_text(key).replace("_", " ").capitalize()
            lines.extend((prefix + label, render_fields(item, indent + 2)))
        return "\n".join(lines)
    if isinstance(value, list):
        if not value:
            return prefix + "(none)"
        return "\n".join(
            prefix + f"[{index}]\n" + render_fields(item, indent + 2)
            for index, item in enumerate(value, 1)
        )
    return prefix + ("(none)" if value is None else safe_text(value))


def render_review(
    document: dict,
    *,
    base_document: dict | None = None,
    sha256: str | None = None,
    expires_at: float | None = None,
    warnings: tuple | list = (),
) -> str:
    """Show the complete candidate, immutable review identity and full prior diff."""
    contract_type = safe_text(document.get("metadata", {}).get("contract_type", "PROJECT"))
    lines = [contract_type.replace("_", " ") + " CONTRACT REVIEW"]
    if sha256 is not None:
        lines.extend(("Canonical SHA-256", "  " + safe_text(sha256)))
    if expires_at is not None:
        lines.extend(
            ("Review expires (UTC)", "  " + datetime.fromtimestamp(expires_at, UTC).isoformat())
        )
    if warnings:
        lines.extend(("Outstanding checks and limitations", render_fields(list(warnings), 2)))
    lines.extend(("Complete candidate", render_fields(document, 2)))
    if base_document is not None:
        diff = list(
            difflib.unified_diff(
                render_fields(base_document).splitlines(),
                render_fields(document).splitlines(),
                fromfile="Previously published revision",
                tofile="Candidate revision",
                lineterm="",
            )
        )
        lines.extend(("Full differences from the previous revision", "\n".join(diff) or "(none)"))
    lines.append(
        "Publication approves this specification. Implementation and validation follow later."
    )
    return "\n".join(lines)

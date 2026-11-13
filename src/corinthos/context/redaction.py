# SPDX-License-Identifier: MPL-2.0
"""Deterministic sanitization before derived captures, identities and digests."""

import re
from pathlib import PurePosixPath

_SECRET_NAMES = (
    r"(?:[A-Z0-9]+[_-])*(?:PASSWORD|PASSWD|PASSPHRASE|SECRET|CREDENTIALS?|"
    r"API[_ -]?KEY|ACCESS[_ -]?KEY|AUTH[_ -]?TOKEN|REFRESH[_ -]?TOKEN|"
    r"ACCESS[_ -]?TOKEN|CLIENT[_ -]?SECRET|PRIVATE[_ -]?KEY|SESSION[_ -]?KEY|"
    r"AUTHORIZATION|TOKEN)(?:[_-][A-Z0-9]+)*"
)
_FIELD = re.compile(rf"(?i)^{_SECRET_NAMES}$")
_ASSIGNMENT = re.compile(
    rf"""(?im)(?<![\w-])["']?{_SECRET_NAMES}["']?[ \t]*[:=][ \t]*
    (?:(?:Bearer|Basic|Digest|Token|Negotiate)[ \t]+)?(?:"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*'|[^\s,;]+)""",
    re.X,
)
_PRIVATE_KEY = re.compile(
    r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY(?: BLOCK)?-----[\s\S]*?"
    r"(?:-----END [A-Z0-9 ]*PRIVATE KEY(?: BLOCK)?-----|\Z)",
    re.I,
)
_TOKEN = re.compile(
    r"(?i)\b(?:gh[pousr]_[a-z0-9_]{12,}|github_pat_[a-z0-9_]{12,}|"
    r"sk-[a-z0-9_-]{12,}|xox[baprs]-[a-z0-9-]{12,}|"
    r"AKIA[A-Z0-9]{16}|eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{8,}|"
    r"Bearer[ \t]+[^\s,;]+)"
)
_USERINFO = re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://)[^/\s@]+:[^/\s@]+@")
_ABSOLUTE_PATH = re.compile(
    r"""(?ix)(?<![\w:/])(?:[a-z]:[\\/][^\r\n<>"'|,;]*|
    (?:\\\\|//)[A-Z0-9_.-]+[\\/][^\s<>"'|,;]*|
    /(?:Users|home|tmp|private|var|root|etc|opt|mnt|workspace)/[^\s<>"'|,;]*)"""
)
_PRIVATE_URL = re.compile(r"https?://(?:app\.|www\.)?notion\.(?:so|com)/[^\s<>'\"]+", re.I)
_SENSITIVE_NAME = re.compile(
    r"(?i)(?<![\w.-])(?:\.env(?:[.\w-]*)|\.secrets|secrets(?:[.\w-]*)|"
    r"credentials?(?:[.\w-]*)|auth\.json|tokens?\.json|\.npmrc|\.netrc|\.git-credentials|"
    r"id_(?:rsa|dsa|ecdsa|ed25519)(?:\.pub)?|[^\\/\s]+\.(?:pem|pfx|p12|key))(?=$|[\\/\s\"'<>:])"
)
_POLICY = (
    (_PRIVATE_KEY, "[redacted private key]", "PRIVATE_KEY"),
    (_ASSIGNMENT, "[redacted sensitive assignment]", "SENSITIVE_ASSIGNMENT"),
    (_TOKEN, "[redacted credential]", "CREDENTIAL"),
    (_USERINFO, r"\1[redacted credential]@", "CREDENTIAL"),
    (_PRIVATE_URL, "[redacted private reference]", "PRIVATE_REFERENCE"),
    (_ABSOLUTE_PATH, "[redacted absolute path]", "ABSOLUTE_PATH"),
    (_SENSITIVE_NAME, "[excluded secret path]", "SECRET_PATH"),
)
_SECRET_PATH_PARTS = {".git", ".ssh", ".aws", ".gnupg", ".codex", ".claude"}


def secret_path(path: str) -> bool:
    normalized = path.replace("\\", "/")
    return bool(_SENSITIVE_NAME.search(normalized)) or any(
        part.casefold() in _SECRET_PATH_PARTS for part in PurePosixPath(normalized).parts
    )


def _text(value, categories):
    for regex, marker, reason in _POLICY:
        value, count = regex.subn(marker, value)
        if count:
            categories.add(reason)
    if any(not (char.isprintable() or char in "\n\t") for char in value):
        value = "".join(char if char.isprintable() or char in "\n\t" else " " for char in value)
        categories.add("CONTROL_CHARACTER")
    return value


def sanitize_text(value: str) -> str:
    """Return the policy's deterministic text projection."""
    return _text(value, set())


def redact(value):
    """Remove classified values before computing any digest of a new capture."""
    categories = set()

    def clean(item):
        if isinstance(item, str):
            return _text(item, categories)
        if isinstance(item, (tuple, list)):
            return [clean(child) for child in item]
        if isinstance(item, dict):
            for field in ("path", "relative_path", "location"):
                path = item.get(field)
                if isinstance(path, str) and secret_path(path):
                    categories.add("SECRET_PATH")
                    return {"excluded": "SECRET_PATH"}
                if isinstance(path, str) and sanitize_text(path) != path:
                    categories.add("PRIVATE_ARTIFACT")
                    return {"excluded": "PRIVATE_ARTIFACT"}
            result = {}
            for key, child in sorted(item.items()):
                label = _text(key, categories)
                if _FIELD.fullmatch(key):
                    categories.add("SENSITIVE_FIELD")
                    continue
                if label != key:
                    continue
                result[label] = clean(child)
            return result
        return item

    sanitized = clean(value)
    return sanitized, tuple(sorted(categories))

"""Sanitize untrusted values before they enter public capability output."""

from __future__ import annotations

import math
import re
import unicodedata
from collections.abc import Mapping
from pathlib import Path
from typing import Any


DEFAULT_MAX_LENGTH = 2_048
DEFAULT_MAX_DEPTH = 32
REDACTED = "<redacted>"
REDACTED_PATH = "<path>"

_ASSIGNED_SECRET_RE = re.compile(
    r"(?i)(?P<prefix>\b(?:token|secret|password|api[_-]?key)\b[\"']?\s*[:=]\s*)"
    r"(?P<value>\"[^\"\r\n]*\"|'[^'\r\n]*'|[^\s,;|}\]]+)"
)
_BEARER_RE = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{8,}")
_JWT_RE = re.compile(
    r"(?<![A-Za-z0-9_-])[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\."
    r"[A-Za-z0-9_-]{8,}(?![A-Za-z0-9_-])"
)
_GITHUB_TOKEN_RE = re.compile(
    r"(?<![A-Za-z0-9_])(?:gh[pousr]_[A-Za-z0-9_-]{8,}|"
    r"github_pat_[A-Za-z0-9_-]{8,})(?![A-Za-z0-9_])",
    re.IGNORECASE,
)
_OPENAI_KEY_RE = re.compile(
    r"(?<![A-Za-z0-9])sk-(?:proj-)?[A-Za-z0-9_-]{8,}(?![A-Za-z0-9_-])",
    re.IGNORECASE,
)
_AWS_ACCESS_KEY_RE = re.compile(
    r"(?<![A-Z0-9])(?:AKIA|ASIA)[A-Z0-9]{16}(?![A-Z0-9])"
)
_FILE_URL_RE = re.compile(r"(?i)\bfile://[^\s|<>\"'`]+")
_WINDOWS_ABSOLUTE_RE = re.compile(
    r"(?<![A-Za-z0-9_])(?:[A-Za-z]:[\\/]|\\\\[^\\/\s]+[\\/])"
    r"[^\s|<>\"'`]+"
)
_UNIX_ABSOLUTE_RE = re.compile(r"(?<![A-Za-z0-9_.~-])/(?:[^\s|<>\"'`]+)")
_SENSITIVE_KEY_RE = re.compile(r"(?i)^(?:token|secret|password|api[_-]?key)$")


def _replace_assigned_secret(match: re.Match[str]) -> str:
    return f"{match.group('prefix')}{REDACTED}"


def _remove_controls(value: str) -> str:
    value = re.sub(r"[\r\n\t\v\f]+", " ", value)
    return "".join(
        character
        for character in value
        if unicodedata.category(character) not in {"Cc", "Cf"}
    )


def _replace_home(value: str, home: str) -> str:
    home = home.rstrip("/\\")
    if not home:
        return value
    variants = {home, home.replace("\\", "/"), home.replace("/", "\\")}
    for variant in sorted(variants, key=len, reverse=True):
        if not variant:
            continue
        value = re.sub(
            re.escape(variant) + r"(?=$|[\\/])",
            "~",
            value,
            flags=re.IGNORECASE if re.match(r"^[A-Za-z]:", variant) else 0,
        )
    return value


def _truncate(value: str, max_length: int) -> str:
    if max_length < 0:
        raise ValueError("max_length must not be negative")
    if len(value) <= max_length:
        return value
    if max_length == 0:
        return ""
    return value[: max_length - 1] + "…"


def sanitize_text(
    value: object,
    *,
    home: str | Path | None = None,
    max_length: int = DEFAULT_MAX_LENGTH,
) -> str:
    """Return a single-line, bounded, redacted representation of untrusted text."""

    if isinstance(value, bytes):
        text = value.decode("utf-8", errors="replace")
    else:
        text = str(value)

    text = _remove_controls(text)
    text = _ASSIGNED_SECRET_RE.sub(_replace_assigned_secret, text)
    for pattern in (
        _BEARER_RE,
        _JWT_RE,
        _GITHUB_TOKEN_RE,
        _OPENAI_KEY_RE,
        _AWS_ACCESS_KEY_RE,
    ):
        text = pattern.sub(REDACTED, text)

    text = _FILE_URL_RE.sub(REDACTED_PATH, text)
    home_text = str(Path.home() if home is None else home)
    text = _replace_home(text, home_text)
    text = _WINDOWS_ABSOLUTE_RE.sub(REDACTED_PATH, text)
    text = _UNIX_ABSOLUTE_RE.sub(REDACTED_PATH, text)
    text = re.sub(r"(?<!\\)\|", r"\\|", text)
    text = re.sub(r"\s+", " ", text).strip()
    return _truncate(text, max_length)


def _sort_key(value: Any) -> str:
    return repr(value)


def sanitize(
    value: Any,
    *,
    home: str | Path | None = None,
    max_length: int = DEFAULT_MAX_LENGTH,
    max_depth: int = DEFAULT_MAX_DEPTH,
    _depth: int = 0,
) -> Any:
    """Recursively sanitize JSON-like values while preserving container shape."""

    if _depth > max_depth:
        return "<max-depth>"
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else sanitize_text(value, max_length=max_length)
    if isinstance(value, (str, bytes, Path)):
        return sanitize_text(value, home=home, max_length=max_length)
    if isinstance(value, Mapping):
        sanitized_items: list[tuple[str, Any]] = []
        for key, item in value.items():
            safe_key = sanitize_text(key, home=home, max_length=max_length)
            if _SENSITIVE_KEY_RE.fullmatch(safe_key):
                safe_item = REDACTED
            else:
                safe_item = sanitize(
                    item,
                    home=home,
                    max_length=max_length,
                    max_depth=max_depth,
                    _depth=_depth + 1,
                )
            sanitized_items.append((safe_key, safe_item))
        return {key: item for key, item in sorted(sanitized_items, key=lambda pair: pair[0])}
    if isinstance(value, (list, tuple)):
        return [
            sanitize(
                item,
                home=home,
                max_length=max_length,
                max_depth=max_depth,
                _depth=_depth + 1,
            )
            for item in value
        ]
    if isinstance(value, (set, frozenset)):
        return [
            sanitize(
                item,
                home=home,
                max_length=max_length,
                max_depth=max_depth,
                _depth=_depth + 1,
            )
            for item in sorted(value, key=_sort_key)
        ]
    return sanitize_text(value, home=home, max_length=max_length)

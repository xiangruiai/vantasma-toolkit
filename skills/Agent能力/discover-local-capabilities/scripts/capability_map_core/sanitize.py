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
_SENSITIVE_KEY_RE = re.compile(r"(?i)^(?:token|secret|password|api[_-]?key)$")
_PATH_START_CHAR = r"[^`\s/\\|<>\"']"
_PATH_TOKEN_BODY = r"(?:\\ |[^`\s|<>\"'])+"
_FILE_URL_PREFIX = r"\bfile://"
_WINDOWS_DRIVE_PREFIX = r"(?<![A-Za-z0-9_])[A-Za-z]:[\\/]"
_UNC_PREFIX = r"\\\\[^\\/\s]+[\\/]"
_FORWARD_UNC_PREFIX = (
    r"(?<![A-Za-z0-9_.~:/-])//(?=" + _PATH_START_CHAR + r")"
)
_UNIX_PREFIX = (
    r"(?<![A-Za-z0-9_.~/-])/(?=" + _PATH_START_CHAR + r")"
)
_ABSOLUTE_PATH_PREFIX = (
    rf"(?:{_FILE_URL_PREFIX}|{_WINDOWS_DRIVE_PREFIX}|"
    rf"{_UNC_PREFIX}|{_FORWARD_UNC_PREFIX}|{_UNIX_PREFIX})"
)
_QUOTED_ABSOLUTE_PATH_RE = re.compile(
    rf"(?:\"{_ABSOLUTE_PATH_PREFIX}[^\"\r\n]*\"|"
    rf"'{_ABSOLUTE_PATH_PREFIX}[^'\r\n]*')",
    re.IGNORECASE,
)
_ABSOLUTE_PATH_CANDIDATE_RE = re.compile(
    _ABSOLUTE_PATH_PREFIX + _PATH_TOKEN_BODY,
    re.IGNORECASE,
)
_ABSOLUTE_PATH_START_RE = re.compile(r"^" + _ABSOLUTE_PATH_PREFIX, re.IGNORECASE)
_UNESCAPED_WHITESPACE_RE = re.compile(r"(?<!\\)\s")
_PATH_TRUNCATING_CHARACTERS = frozenset("`\"'<>|")


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


def _redact_absolute_paths(value: str) -> str:
    stripped = value.strip()
    if len(stripped) >= 2 and stripped[0] in {'"', "'"}:
        quote = stripped[0]
        interior = stripped[1:-1] if stripped[-1] == quote else stripped[1:]
        if _ABSOLUTE_PATH_START_RE.match(interior) and f"\\{quote}" in interior:
            return REDACTED_PATH

    value = _QUOTED_ABSOLUTE_PATH_RE.sub(REDACTED_PATH, value)
    stripped = value.strip()
    unquoted_path = _ABSOLUTE_PATH_CANDIDATE_RE.search(stripped)
    if unquoted_path and _UNESCAPED_WHITESPACE_RE.search(
        stripped[unquoted_path.start() :]
    ):
        return REDACTED_PATH
    if (
        unquoted_path
        and unquoted_path.end() < len(stripped)
        and stripped[unquoted_path.end()] in _PATH_TRUNCATING_CHARACTERS
    ):
        return REDACTED_PATH
    return _ABSOLUTE_PATH_CANDIDATE_RE.sub(REDACTED_PATH, value)


def _escape_markdown_pipes(value: str) -> str:
    def ensure_odd_backslashes(match: re.Match[str]) -> str:
        backslashes = match.group("backslashes")
        if len(backslashes) % 2 == 0:
            backslashes += "\\"
        return backslashes + "|"

    return re.sub(r"(?P<backslashes>\\*)\|", ensure_odd_backslashes, value)


def _collision_key(base_key: str, index: int, max_length: int) -> str:
    suffix = f" [{index}]"
    if len(suffix) > max_length:
        raise ValueError("max_length is too small to disambiguate mapping keys")
    prefix = _truncate(base_key, max_length - len(suffix))
    return prefix + suffix


def sanitize_text(
    value: str,
    *,
    home: str | Path | None = None,
    max_length: int = DEFAULT_MAX_LENGTH,
) -> str:
    """Return a single-line, bounded, redacted representation of untrusted text."""

    if not isinstance(value, str):
        raise TypeError(
            f"sanitize_text requires str, got {type(value).__name__}"
        )
    text = value

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

    home_text = str(Path.home() if home is None else home)
    text = _replace_home(text, home_text)
    text = _redact_absolute_paths(text)
    text = _escape_markdown_pipes(text)
    text = re.sub(r"\s+", " ", text).strip()
    return _truncate(text, max_length)


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
        if not math.isfinite(value):
            raise TypeError("sanitize only accepts finite JSON numbers")
        return value
    if isinstance(value, str):
        return sanitize_text(value, home=home, max_length=max_length)
    if isinstance(value, Mapping):
        sanitized_items: list[tuple[str, str, Any]] = []
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError(
                    "sanitize only accepts mappings with string keys, "
                    f"got {type(key).__name__}"
                )
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
            sanitized_items.append((safe_key, key, safe_item))

        result: dict[str, Any] = {}
        for safe_key, _, safe_item in sorted(
            sanitized_items, key=lambda entry: (entry[0], entry[1])
        ):
            result_key = safe_key
            collision_index = 2
            while result_key in result:
                result_key = _collision_key(safe_key, collision_index, max_length)
                collision_index += 1
            result[result_key] = safe_item
        return result
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
    raise TypeError(
        "sanitize only accepts JSON-like values, "
        f"got {type(value).__name__}"
    )

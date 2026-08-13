"""Bounded, non-executing MCP configuration and plugin discovery."""

from __future__ import annotations

import errno
import hashlib
import heapq
import json
import os
import platform
import re
import stat
import unicodedata
from collections import deque
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:  # Python 3.11+; the conservative fallback keeps Python 3.10 usable.
    import tomllib as _tomllib
except ImportError:  # pragma: no cover - exercised by patching on newer Python
    _tomllib = None  # type: ignore[assignment]

from .models import (
    CAPABILITY_SCOPES,
    Capability,
    Diagnostic,
    ResolverRecord,
    SourceLocation,
)
from .roots import RootSpec, path_like_identity
from .sanitize import sanitize_text


MAX_CONFIG_BYTES = 1024 * 1024
MAX_STRUCTURE_DEPTH = 32
MAX_STRUCTURE_ITEMS = 10_000
MAX_PLUGIN_DEPTH = 64
MAX_PLUGIN_ENTRIES = 25_000
_READ_CHUNK_BYTES = 64 * 1024
_PLUGIN_MARKERS = frozenset({".codex-plugin", ".claude-plugin"})
_TRANSPORTS = frozenset({"stdio", "http", "sse", "unknown"})
_FD_SCANDIR = os.scandir
_DIRFD_OPEN = os.open
_DIRFD_STAT = os.stat
_SENSITIVE_IDENTITY_RE = re.compile(
    r"(?i)(?:token|secret|password|api[_-]?key)\s*[:=]"
)


@dataclass(frozen=True)
class ConnectorConfigSpec:
    """An injected MCP configuration source with path-free public evidence."""

    path: Path
    scope: str
    provider: str
    format: str
    logical_key: str
    public_location: str

    def __post_init__(self) -> None:
        path = Path(self.path)
        scope = self.scope.casefold().strip()
        provider = sanitize_text(self.provider, max_length=128)
        structured_format = self.format.casefold().strip()
        logical_key = self.logical_key.strip()
        public_location = sanitize_text(self.public_location, max_length=512)
        if scope not in CAPABILITY_SCOPES:
            raise ValueError(f"Unsupported connector scope: {self.scope!r}")
        if not provider:
            raise ValueError("Connector provider must not be empty")
        if structured_format not in {"json", "toml"}:
            raise ValueError("Connector format must be json or toml")
        if (
            not logical_key
            or path_like_identity(logical_key)
            or _SENSITIVE_IDENTITY_RE.search(logical_key)
        ):
            raise ValueError(
                "Connector logical_key must be non-sensitive and path-independent"
            )
        if not public_location:
            raise ValueError("Connector public_location must not be empty")
        object.__setattr__(self, "path", path)
        object.__setattr__(self, "scope", scope)
        object.__setattr__(self, "provider", provider)
        object.__setattr__(self, "format", structured_format)
        object.__setattr__(self, "logical_key", logical_key)
        object.__setattr__(self, "public_location", public_location)


@dataclass(frozen=True)
class ConnectorDiscoveryResult:
    capabilities: tuple[Capability, ...] | list[Capability] = field(
        default_factory=tuple
    )
    resolvers: tuple[ResolverRecord, ...] | list[ResolverRecord] = field(
        default_factory=tuple
    )
    skill_roots: tuple[RootSpec, ...] | list[RootSpec] = field(default_factory=tuple)
    diagnostics: tuple[Diagnostic, ...] | list[Diagnostic] = field(
        default_factory=tuple
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "capabilities", tuple(self.capabilities))
        object.__setattr__(self, "resolvers", tuple(self.resolvers))
        object.__setattr__(self, "skill_roots", tuple(self.skill_roots))
        object.__setattr__(self, "diagnostics", tuple(self.diagnostics))


@dataclass(frozen=True)
class _ReadResult:
    payload: bytes | None
    exact_path: Path | None
    diagnostics: tuple[Diagnostic, ...] = ()
    physical_identity: str | None = None


@dataclass(frozen=True)
class _ParsedResult:
    value: Any | None
    diagnostics: tuple[Diagnostic, ...] = ()


@dataclass(frozen=True)
class _ManifestOccurrence:
    payload: bytes
    exact_path: Path
    plugin_directory: Path
    marker: str
    source: RootSpec
    physical_id: tuple[int, int]
    location: str


class _EnvPathBlocked(Exception):
    pass


class _InvalidUnicode(ValueError):
    pass


class _BrokenSymlink(OSError):
    pass


def _diagnostic(
    code: str,
    message: str,
    *,
    location: str,
    severity: str = "warning",
) -> Diagnostic:
    return Diagnostic(severity, code, message, {"location": location})


def _has_env_segment(path: Path) -> bool:
    return any(part.casefold() == ".env" for part in path.parts)


def _normalize_external_text(value: str) -> str:
    """Normalize external text while rejecting isolated Unicode surrogates."""

    normalized: list[str] = []
    index = 0
    while index < len(value):
        codepoint = ord(value[index])
        if 0xD800 <= codepoint <= 0xDBFF:
            if index + 1 >= len(value):
                raise _InvalidUnicode
            low = ord(value[index + 1])
            if not 0xDC00 <= low <= 0xDFFF:
                raise _InvalidUnicode
            normalized.append(
                chr(0x10000 + ((codepoint - 0xD800) << 10) + low - 0xDC00)
            )
            index += 2
            continue
        if 0xDC00 <= codepoint <= 0xDFFF:
            raise _InvalidUnicode
        normalized.append(value[index])
        index += 1
    return unicodedata.normalize("NFC", "".join(normalized))


def _resolve_safe_chain(path: Path, *, max_links: int = 64) -> Path:
    """Resolve symlinks without ever traversing a case-insensitive .env hop."""

    absolute = path.absolute()
    resolved = Path(absolute.anchor)
    pending = deque((part, False) for part in absolute.parts[1:])
    seen: set[tuple[Path, tuple[tuple[str, bool], ...]]] = set()
    links = 0
    while pending:
        part, from_link_target = pending.popleft()
        if part in {"", "."}:
            continue
        if part == "..":
            resolved = resolved.parent
            continue
        if part.casefold() == ".env":
            raise _EnvPathBlocked
        candidate = resolved / part
        try:
            entry_stat = os.lstat(candidate)
        except FileNotFoundError as error:
            if from_link_target:
                raise _BrokenSymlink(errno.ENOENT, "broken symbolic link") from error
            raise
        if not stat.S_ISLNK(entry_stat.st_mode):
            resolved = candidate
            continue
        links += 1
        state = (candidate, tuple(pending))
        if links > max_links or state in seen:
            raise OSError(errno.ELOOP, "symbolic link loop")
        seen.add(state)
        target = Path(os.readlink(candidate))
        if _has_env_segment(target):
            raise _EnvPathBlocked
        target_parts = list(target.parts)
        if target.is_absolute():
            resolved = Path(target.anchor)
            target_parts = target_parts[1:]
        pending.extendleft(
            reversed([(target_part, True) for target_part in target_parts])
        )
    return resolved


def _file_id(value: os.stat_result) -> tuple[int, int] | None:
    inode = getattr(value, "st_ino", 0)
    if not inode:
        return None
    return (getattr(value, "st_dev", 0), inode)


def _stat_evidence(value: os.stat_result) -> tuple[int, ...]:
    return tuple(
        int(getattr(value, name))
        for name in (
            "st_dev",
            "st_ino",
            "st_mode",
            "st_nlink",
            "st_size",
            "st_ctime_ns",
            "st_mtime_ns",
        )
        if hasattr(value, name)
    )


def _secure_plugin_backend_supported() -> bool:
    return bool(
        getattr(os, "O_DIRECTORY", 0)
        and getattr(os, "O_NOFOLLOW", 0)
        and _FD_SCANDIR in os.supports_fd
        and _DIRFD_OPEN in os.supports_dir_fd
        and _DIRFD_STAT in os.supports_dir_fd
    )


def _file_flags() -> int:
    return (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0)
    )


def _directory_flags() -> int:
    return (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_DIRECTORY", 0)
    )


def _open_verified_child_directory(
    parent_fd: int, name: str, expected: os.stat_result
) -> int:
    """Open a verified child directory and transfer fd ownership to caller."""

    fd = os.open(name, _directory_flags(), dir_fd=parent_fd)
    try:
        opened = os.fstat(fd)
        if (
            not stat.S_ISDIR(opened.st_mode)
            or _file_id(opened) != _file_id(expected)
            or _stat_evidence(opened) != _stat_evidence(expected)
        ):
            raise OSError(errno.ESTALE, "directory changed")
        return fd
    except BaseException:
        try:
            os.close(fd)
        except OSError:
            pass
        raise


def _read_fd_bounded(fd: int, maximum: int) -> tuple[bytes, bool]:
    payload = bytearray()
    while len(payload) <= maximum:
        remaining = maximum + 1 - len(payload)
        chunk = os.read(fd, min(_READ_CHUNK_BYTES, remaining))
        if not chunk:
            break
        payload.extend(chunk)
    return bytes(payload[:maximum]), len(payload) > maximum


def _physical_identity(value: os.stat_result, payload: bytes) -> str:
    identity = _file_id(value)
    if identity is not None:
        return f"inode:{identity[0]}:{identity[1]}"
    return f"content-sha256:{hashlib.sha256(payload).hexdigest()}"


def _read_verified_regular(
    path: str | Path,
    expected: os.stat_result,
    *,
    location: str,
    dir_fd: int | None = None,
    too_large_code: str,
    open_error_code: str,
    read_error_code: str,
) -> tuple[bytes | None, tuple[Diagnostic, ...], str | None]:
    """Open nonblocking, verify regular-file identity, then read bounded bytes."""

    try:
        fd = os.open(path, _file_flags(), dir_fd=dir_fd)
    except PermissionError:
        return None, (
            _diagnostic(
                "permission_denied",
                "A structured source could not be read due to permissions.",
                location=location,
            ),
        ), None
    except (OSError, TypeError, NotImplementedError):
        return None, (
            _diagnostic(
                open_error_code,
                "A structured source could not be opened safely.",
                location=location,
            ),
        ), None
    try:
        opened = os.fstat(fd)
        if (
            not stat.S_ISREG(opened.st_mode)
            or _file_id(opened) != _file_id(expected)
            or _stat_evidence(opened) != _stat_evidence(expected)
        ):
            return None, (
                _diagnostic(
                    "source_changed",
                    "A structured source changed before it could be read.",
                    location=location,
                ),
            ), None
        payload, oversized = _read_fd_bounded(fd, MAX_CONFIG_BYTES)
        final_stat = os.fstat(fd)
        if dir_fd is None:
            final_path_stat = os.lstat(path)
        else:
            final_path_stat = os.stat(path, dir_fd=dir_fd, follow_symlinks=False)
        if (
            _file_id(final_stat) != _file_id(opened)
            or _file_id(final_path_stat) != _file_id(opened)
            or _stat_evidence(final_path_stat) != _stat_evidence(final_stat)
            or (
                not oversized
                and _stat_evidence(final_stat) != _stat_evidence(opened)
            )
        ):
            return None, (
                _diagnostic(
                    "source_changed",
                    "A structured source changed while it was being read.",
                    location=location,
                ),
            ), None
    except PermissionError:
        return None, (
            _diagnostic(
                "permission_denied",
                "A structured source could not be read due to permissions.",
                location=location,
            ),
        ), None
    except (OSError, TypeError, NotImplementedError):
        return None, (
            _diagnostic(
                read_error_code,
                "A structured source could not be read safely.",
                location=location,
            ),
        ), None
    finally:
        os.close(fd)
    if oversized:
        return None, (
            _diagnostic(
                too_large_code,
                "A structured source exceeded the supported size limit.",
                location=location,
            ),
        ), None
    return payload, (), _physical_identity(opened, payload)


def _read_bounded_path(
    path: Path,
    *,
    location: str,
    too_large_code: str = "config_too_large",
) -> _ReadResult:
    if _has_env_segment(path):
        return _ReadResult(
            None,
            None,
            (
                _diagnostic(
                    "env_path_blocked",
                    "A configured source passing through .env was skipped without reading it.",
                    location=location,
                ),
            ),
        )
    try:
        exact_path = _resolve_safe_chain(path)
        expected = os.lstat(exact_path)
    except _BrokenSymlink:
        return _ReadResult(
            None,
            None,
            (
                _diagnostic(
                    "broken_symlink",
                    "A configured source contains a broken symbolic link.",
                    location=location,
                ),
            ),
        )
    except FileNotFoundError:
        return _ReadResult(None, None)
    except _EnvPathBlocked:
        return _ReadResult(
            None,
            None,
            (
                _diagnostic(
                    "env_path_blocked",
                    "A configured source symlink chain passing through .env was skipped without reading it.",
                    location=location,
                ),
            ),
        )
    except PermissionError:
        return _ReadResult(
            None,
            None,
            (
                _diagnostic(
                    "permission_denied",
                    "A configured source could not be inspected due to permissions.",
                    location=location,
                ),
            ),
        )
    except (OSError, TypeError, NotImplementedError):
        return _ReadResult(
            None,
            None,
            (
                _diagnostic(
                    "source_resolve_error",
                    "A configured source could not be resolved safely.",
                    location=location,
                ),
            ),
        )
    if not stat.S_ISREG(expected.st_mode):
        return _ReadResult(
            None,
            None,
            (
                _diagnostic(
                    "not_regular_file",
                    "A configured source is not a regular file.",
                    location=location,
                ),
            ),
        )
    payload, diagnostics, physical_identity = _read_verified_regular(
        exact_path,
        expected,
        location=location,
        too_large_code=too_large_code,
        open_error_code="source_open_error",
        read_error_code="source_read_error",
    )
    return _ReadResult(payload, exact_path, diagnostics, physical_identity)


def _measure_structure(value: Any) -> str | None:
    stack: list[tuple[Any, int]] = [(value, 0)]
    items = 0
    while stack:
        current, depth = stack.pop()
        if depth > MAX_STRUCTURE_DEPTH:
            return "structure_too_deep"
        items += 1
        if items > MAX_STRUCTURE_ITEMS:
            return "structure_too_large"
        if isinstance(current, Mapping):
            items += len(current)
            if items > MAX_STRUCTURE_ITEMS:
                return "structure_too_large"
            stack.extend((item, depth + 1) for item in current.values())
        elif isinstance(current, (list, tuple)):
            items += len(current)
            if items > MAX_STRUCTURE_ITEMS:
                return "structure_too_large"
            stack.extend((item, depth + 1) for item in current)
    return None


def _strip_toml_comment(line: str) -> str:
    quote = ""
    escaped = False
    output: list[str] = []
    for character in line:
        if escaped:
            output.append(character)
            escaped = False
            continue
        if character == "\\" and quote == '"':
            output.append(character)
            escaped = True
            continue
        if quote:
            output.append(character)
            if character == quote:
                quote = ""
            continue
        if character in {'"', "'"}:
            quote = character
            output.append(character)
        elif character == "#":
            break
        else:
            output.append(character)
    return "".join(output).strip()


def _split_toml_array(raw: str) -> tuple[str, ...]:
    interior = raw[1:-1].strip()
    if not interior:
        return ()
    items: list[str] = []
    start = 0
    quote = ""
    escaped = False
    for index, character in enumerate(interior):
        if escaped:
            escaped = False
            continue
        if character == "\\" and quote == '"':
            escaped = True
            continue
        if quote:
            if character == quote:
                quote = ""
            continue
        if character in {'"', "'"}:
            quote = character
        elif character == ",":
            item = interior[start:index].strip()
            if item:
                items.append(item)
            start = index + 1
    if quote:
        raise ValueError("unterminated TOML array string")
    final = interior[start:].strip()
    if final:
        items.append(final)
    return tuple(items)


def _fallback_toml_value(raw: str) -> str | bool | list[str | bool]:
    value = raw.strip()
    if value.casefold() in {"true", "false"}:
        return value.casefold() == "true"
    if len(value) >= 2 and value[0] == value[-1] == '"':
        decoded = json.loads(value)
        if isinstance(decoded, str):
            return decoded
    if len(value) >= 2 and value[0] == value[-1] == "'":
        return value[1:-1]
    if len(value) >= 2 and value[0] == "[" and value[-1] == "]":
        return [_fallback_toml_value(item) for item in _split_toml_array(value)]
    raise ValueError("unsupported TOML subset value")


def _toml_value_is_syntactically_valid(raw: str) -> bool:
    value = raw.strip()
    if not value:
        return False
    stack: list[str] = []
    quote = ""
    escaped = False
    pairs = {"]": "[", "}": "{"}
    for character in value:
        if escaped:
            escaped = False
            continue
        if quote:
            if character == "\\" and quote == '"':
                escaped = True
            elif character == quote:
                quote = ""
            continue
        if character in {'"', "'"}:
            quote = character
        elif character in "[{":
            stack.append(character)
        elif character in "]}":
            if not stack or stack.pop() != pairs[character]:
                return False
    if quote or stack:
        return False
    if value[0] in {'"', "'", "[", "{"}:
        closing = {'"': '"', "'": "'", "[": "]", "{": "}"}[value[0]]
        return value[-1] == closing
    return bool(
        re.fullmatch(
            r"(?i)(?:true|false|[+-]?(?:inf|nan)|"
            r"[+-]?(?:\d[\d_]*)(?:\.\d[\d_]*)?(?:e[+-]?\d[\d_]*)?|"
            r"\d{4}-\d{2}-\d{2}(?:[Tt ][0-9:.+-Zz]+)?|"
            r"\d{2}:\d{2}:[0-9.]+)",
            value,
        )
    )


def _split_toml_dotted_key(raw: str) -> tuple[str, ...]:
    parts: list[str] = []
    index = 0
    while index < len(raw):
        while index < len(raw) and raw[index].isspace():
            index += 1
        if index >= len(raw):
            break
        if raw[index] in {'"', "'"}:
            quote = raw[index]
            start = index
            index += 1
            escaped = False
            while index < len(raw):
                character = raw[index]
                if escaped:
                    escaped = False
                elif character == "\\" and quote == '"':
                    escaped = True
                elif character == quote:
                    break
                index += 1
            if index >= len(raw):
                raise ValueError("unterminated TOML quoted key")
            token = raw[start : index + 1]
            value = (
                json.loads(token) if quote == '"' else token[1:-1]
            )
            index += 1
        else:
            match = re.match(r"[A-Za-z0-9_-]+", raw[index:])
            if match is None:
                raise ValueError("unsupported TOML key")
            value = match.group(0)
            index += len(value)
        if not isinstance(value, str) or not value:
            raise ValueError("empty TOML key")
        parts.append(value)
        while index < len(raw) and raw[index].isspace():
            index += 1
        if index >= len(raw):
            break
        if raw[index] != ".":
            raise ValueError("unsupported TOML dotted key")
        index += 1
    return tuple(parts)


def _parse_toml_subset(payload: bytes) -> dict[str, Any]:
    """Parse only MCP metadata needed by discovery on Python 3.10."""

    text = payload.decode("utf-8")
    result: dict[str, dict[str, dict[str, Any]]] = {}
    current: dict[str, Any] | None = None
    key_re = re.compile(r"^([A-Za-z][A-Za-z0-9_-]*)\s*=\s*(.+)$")
    retained_fields = frozenset(
        {"command", "url", "type", "transport", "enabled", "disabled"}
    )
    for source_line in text.splitlines():
        line = _strip_toml_comment(source_line)
        if not line:
            continue
        if line.startswith("[["):
            if not line.endswith("]]" ):
                raise ValueError("invalid TOML array table")
            try:
                _split_toml_dotted_key(line[2:-2].strip())
            except ValueError as error:
                raise ValueError("invalid TOML array table") from error
            current = None
            continue
        if line.startswith("["):
            if not line.endswith("]"):
                raise ValueError("invalid TOML table")
            current = None
            try:
                table_parts = _split_toml_dotted_key(line[1:-1].strip())
            except ValueError as error:
                raise ValueError("invalid TOML table") from error
            if (
                len(table_parts) == 2
                and table_parts[0] in {"mcp_servers", "mcpServers"}
            ):
                current = result.setdefault(table_parts[0], {}).setdefault(
                    table_parts[1], {}
                )
            continue
        key_match = key_re.fullmatch(line)
        if key_match is None:
            raise ValueError("invalid TOML assignment")
        if not _toml_value_is_syntactically_valid(key_match.group(2)):
            raise ValueError("invalid TOML value")
        if current is None:
            continue
        key = key_match.group(1)
        try:
            parsed_value = _fallback_toml_value(key_match.group(2))
        except (TypeError, ValueError):
            continue
        if key in retained_fields:
            current[key] = parsed_value
    return result


def _parse_structured(
    payload: bytes,
    *,
    structured_format: str,
    location: str,
) -> _ParsedResult:
    diagnostics: list[Diagnostic] = []
    if payload.startswith(b"\xef\xbb\xbf"):
        diagnostics.append(
            _diagnostic(
                "bom_detected",
                "A UTF-8 BOM was accepted in a structured source.",
                location=location,
                severity="info",
            )
        )
        payload = payload[3:]
    try:
        if structured_format == "json":
            value = json.loads(payload.decode("utf-8"))
        elif _tomllib is not None:
            value = _tomllib.loads(payload.decode("utf-8"))
        else:
            value = _parse_toml_subset(payload)
    except UnicodeDecodeError:
        code = f"invalid_{structured_format}"
        diagnostics.append(
            _diagnostic(
                code,
                "A structured source was not valid UTF-8.",
                location=location,
            )
        )
        return _ParsedResult(None, tuple(diagnostics))
    except RecursionError:
        diagnostics.append(
            _diagnostic(
                "structure_too_deep",
                "A structured source exceeded the supported nesting depth.",
                location=location,
            )
        )
        return _ParsedResult(None, tuple(diagnostics))
    except (ValueError, TypeError):
        code = f"invalid_{structured_format}"
        diagnostics.append(
            _diagnostic(
                code,
                "A structured source could not be parsed.",
                location=location,
            )
        )
        return _ParsedResult(None, tuple(diagnostics))
    structure_issue = _measure_structure(value)
    if structure_issue is not None:
        message = (
            "A structured source exceeded the supported nesting depth."
            if structure_issue == "structure_too_deep"
            else "A structured source exceeded the supported item count."
        )
        diagnostics.append(
            _diagnostic(structure_issue, message, location=location)
        )
        return _ParsedResult(None, tuple(diagnostics))
    return _ParsedResult(value, tuple(diagnostics))


def _server_maps(
    value: Any,
) -> tuple[tuple[str, str, Mapping[str, Any]], ...]:
    if not isinstance(value, Mapping):
        return ()
    servers: list[tuple[str, str, Mapping[str, Any]]] = []
    for field_name in ("mcp_servers", "mcpServers", "servers"):
        container = value.get(field_name)
        if not isinstance(container, Mapping):
            continue
        for name, configuration in container.items():
            if isinstance(name, str) and isinstance(configuration, Mapping):
                servers.append((field_name, name, configuration))
    return tuple(servers)


def _enabled_state(configuration: Mapping[str, Any]) -> str:
    disabled = configuration.get("disabled")
    if isinstance(disabled, bool):
        return "disabled" if disabled else "enabled"
    enabled = configuration.get("enabled")
    if isinstance(enabled, bool):
        return "enabled" if enabled else "disabled"
    return "unknown"


def _transport(configuration: Mapping[str, Any]) -> str:
    declared = configuration.get("transport", configuration.get("type"))
    if isinstance(declared, str):
        normalized = declared.casefold().strip()
        aliases = {
            "stdio": "stdio",
            "http": "http",
            "streamable-http": "http",
            "streamable_http": "http",
            "sse": "sse",
        }
        if normalized in aliases:
            return aliases[normalized]
    if "command" in configuration:
        return "stdio"
    if "url" in configuration:
        return "http"
    return "unknown"


def _name_digest(name: str) -> str:
    return hashlib.sha256(name.encode("utf-8")).hexdigest()


def _mcp_pair(
    name: str,
    configuration: Mapping[str, Any],
    *,
    scope: str,
    provider: str,
    location: str,
    logical_source: str,
    source_identity: str,
    exact_path: Path,
) -> tuple[Capability, ResolverRecord]:
    normalized_name = _normalize_external_text(name)
    safe_name = sanitize_text(normalized_name, max_length=512) or "unnamed-mcp"
    enabled = _enabled_state(configuration)
    transport = _transport(configuration)
    if transport not in _TRANSPORTS:  # defensive enum gate
        transport = "unknown"
    capability = Capability(
        kind="mcp",
        name=safe_name,
        tags=(f"enabled:{enabled}", f"transport:{transport}"),
        source_locations=(SourceLocation(location, scope, provider),),
        scope=scope,
        provider=provider,
        logical_identity=(
            f"mcp-v1:{logical_source}:source:{source_identity}:"
            f"name-sha256:{_name_digest(normalized_name)}"
        ),
    )
    return capability, ResolverRecord(capability.resolver_id, (str(exact_path),))


def _environment_value(
    environ: Mapping[str, str], key: str, *, case_insensitive: bool
) -> str | None:
    if key in environ:
        return environ[key]
    if not case_insensitive:
        return None
    folded = key.casefold()
    for candidate, value in environ.items():
        if candidate.casefold() == folded:
            return value
    return None


def _expand_home(value: str, home: Path) -> Path:
    if value == "~":
        return home
    if value.startswith(("~/", "~\\")):
        return home / value[2:]
    return Path(value)


def _config_specs(
    *,
    home: Path,
    project: Path | None,
    extra_config_paths: Iterable[Path | ConnectorConfigSpec],
    environ: Mapping[str, str],
    windows: bool,
) -> tuple[ConnectorConfigSpec, ...]:
    injected = tuple(extra_config_paths)
    codex_override = _environment_value(
        environ, "CODEX_HOME", case_insensitive=windows
    )
    codex_home = (
        _expand_home(codex_override, home) if codex_override else home / ".codex"
    )
    specs: list[ConnectorConfigSpec] = [
        ConnectorConfigSpec(
            codex_home / "config.toml",
            "user",
            "codex",
            "toml",
            "config:user:codex",
            "<codex-home:config>",
        ),
        ConnectorConfigSpec(
            home / ".claude.json",
            "user",
            "claude",
            "json",
            "config:user:claude",
            "~/.claude.json",
        ),
    ]
    if project is not None:
        specs.extend(
            (
                ConnectorConfigSpec(
                    project / ".mcp.json",
                    "project",
                    "project-mcp",
                    "json",
                    "config:project:mcp",
                    "<project>/.mcp.json",
                ),
                ConnectorConfigSpec(
                    project / ".vscode" / "mcp.json",
                    "project",
                    "vscode",
                    "json",
                    "config:project:vscode",
                    "<project>/.vscode/mcp.json",
                ),
            )
        )
    injected_specs = [item for item in injected if isinstance(item, ConnectorConfigSpec)]
    injected_paths = sorted(
        (Path(item) for item in injected if not isinstance(item, ConnectorConfigSpec)),
        key=lambda item: os.path.normcase(str(item.absolute())),
    )
    specs.extend(injected_specs)
    for index, path in enumerate(injected_paths, start=1):
        structured_format = "toml" if path.suffix.casefold() == ".toml" else "json"
        specs.append(
            ConnectorConfigSpec(
                path,
                "extra",
                f"extra-{structured_format}",
                structured_format,
                f"config:extra:{index}:{structured_format}",
                f"<extra-config:{index}>",
            )
        )
    ordered = sorted(
        specs,
        key=lambda item: (
            item.logical_key,
            item.scope,
            item.provider.casefold(),
            item.provider,
            item.format,
            item.public_location.casefold(),
            item.public_location,
            os.path.normcase(str(item.path.absolute())),
        ),
    )
    unique: list[ConnectorConfigSpec] = []
    seen: set[tuple[str, ...]] = set()
    for spec in ordered:
        full_source = (
            os.path.normcase(str(spec.path.absolute())),
            spec.scope,
            spec.provider,
            spec.format,
            spec.logical_key,
            spec.public_location,
        )
        if full_source in seen:
            continue
        seen.add(full_source)
        unique.append(spec)
    return tuple(unique)


def _plugin_root_specs(
    *,
    home: Path,
    project: Path | None,
    plugin_roots: Iterable[Path | RootSpec],
    environ: Mapping[str, str],
    windows: bool,
) -> tuple[RootSpec, ...]:
    injected = tuple(plugin_roots)
    codex_override = _environment_value(
        environ, "CODEX_HOME", case_insensitive=windows
    )
    claude_override = _environment_value(
        environ, "CLAUDE_CONFIG_DIR", case_insensitive=windows
    )
    codex_home = (
        _expand_home(codex_override, home) if codex_override else home / ".codex"
    )
    claude_home = (
        _expand_home(claude_override, home)
        if claude_override
        else home / ".claude"
    )
    roots: list[RootSpec] = [
        RootSpec(
            codex_home / "plugins",
            "plugin",
            "codex-plugin",
            "plugin:user:codex",
            "<codex-home:plugins>",
        ),
        RootSpec(
            claude_home / "plugins",
            "plugin",
            "claude-plugin",
            "plugin:user:claude",
            "<claude-home:plugins>",
        ),
    ]
    if project is not None:
        roots.extend(
            (
                RootSpec(
                    project / ".codex" / "plugins",
                    "plugin",
                    "codex-plugin",
                    "plugin:project:codex",
                    "<project:codex-plugins>",
                ),
                RootSpec(
                    project / ".claude" / "plugins",
                    "plugin",
                    "claude-plugin",
                    "plugin:project:claude",
                    "<project:claude-plugins>",
                ),
            )
        )
    injected_specs = [item for item in injected if isinstance(item, RootSpec)]
    injected_paths = sorted(
        (Path(item) for item in injected if not isinstance(item, RootSpec)),
        key=lambda item: os.path.normcase(str(item.absolute())),
    )
    roots.extend(injected_specs)
    for index, path in enumerate(injected_paths, start=1):
        roots.append(
            RootSpec(
                path,
                "plugin",
                "plugin-root",
                f"plugin:extra:{index}",
                f"<plugin-root:{index}>",
            )
        )
    return tuple(sorted(roots, key=lambda item: item.logical_key))


def _read_manifest_at(
    directory_fd: int,
    expected: os.stat_result,
    *,
    location: str,
) -> tuple[bytes | None, tuple[Diagnostic, ...]]:
    payload, diagnostics, _ = _read_verified_regular(
        "plugin.json",
        expected,
        location=location,
        dir_fd=directory_fd,
        too_large_code="manifest_too_large",
        open_error_code="manifest_open_error",
        read_error_code="manifest_read_error",
    )
    return payload, diagnostics


def _scan_plugin_root(
    root: RootSpec,
) -> tuple[tuple[_ManifestOccurrence, ...], tuple[Diagnostic, ...]]:
    diagnostics: list[Diagnostic] = []
    try:
        visible_stat = os.lstat(root.path)
    except FileNotFoundError:
        return (), ()
    except PermissionError:
        return (), (
            _diagnostic(
                "permission_denied",
                "A plugin root could not be inspected due to permissions.",
                location=root.public_prefix,
            ),
        )
    except (OSError, TypeError, NotImplementedError):
        return (), (
            _diagnostic(
                "plugin_root_stat_error",
                "A plugin root could not be inspected.",
                location=root.public_prefix,
            ),
        )
    if stat.S_ISLNK(visible_stat.st_mode):
        return (), (
            _diagnostic(
                "symlink_root_rejected",
                "A symbolic-link plugin root was rejected conservatively.",
                location=root.public_prefix,
            ),
        )
    if not stat.S_ISDIR(visible_stat.st_mode):
        return (), (
            _diagnostic(
                "plugin_root_not_directory",
                "A configured plugin root is not a directory.",
                location=root.public_prefix,
            ),
        )
    try:
        physical_root = _resolve_safe_chain(root.path)
        root_fd = os.open(physical_root, _directory_flags())
    except _EnvPathBlocked:
        return (), (
            _diagnostic(
                "env_path_blocked",
                "A plugin root passing through .env was skipped without reading it.",
                location=root.public_prefix,
            ),
        )
    except PermissionError:
        return (), (
            _diagnostic(
                "permission_denied",
                "A plugin root could not be read due to permissions.",
                location=root.public_prefix,
            ),
        )
    except OSError:
        return (), (
            _diagnostic(
                "plugin_root_open_error",
                "A plugin root could not be opened safely.",
                location=root.public_prefix,
            ),
        )
    try:
        opened_root = os.fstat(root_fd)
    except OSError:
        os.close(root_fd)
        return (), (
            _diagnostic(
                "plugin_root_stat_error",
                "An opened plugin root could not be verified.",
                location=root.public_prefix,
            ),
        )
    if (
        not stat.S_ISDIR(opened_root.st_mode)
        or _file_id(opened_root) != _file_id(visible_stat)
        or _stat_evidence(opened_root) != _stat_evidence(visible_stat)
    ):
        os.close(root_fd)
        return (), (
            _diagnostic(
                "source_changed",
                "A plugin root changed before it could be traversed.",
                location=root.public_prefix,
            ),
        )

    occurrences: list[_ManifestOccurrence] = []
    seen_manifests: set[tuple[int, int]] = set()
    stack: list[tuple[int, tuple[str, ...], int]] = [(root_fd, (), 0)]
    entry_count = 0
    stop = False
    limit_exceeded = False
    while stack and not stop:
        directory_fd, parts, depth = stack.pop()
        try:
            try:
                with os.scandir(directory_fd) as iterator:
                    remaining = max(MAX_PLUGIN_ENTRIES - entry_count, 0)
                    entries = heapq.nsmallest(
                        remaining + 1,
                        iterator,
                        key=lambda item: (item.name.casefold(), item.name),
                    )
                if len(entries) > remaining:
                    diagnostics.append(
                        _diagnostic(
                            "plugin_entry_limit",
                            "A plugin root exceeded the supported entry count.",
                            location=root.public_prefix,
                        )
                    )
                    limit_exceeded = True
                    stop = True
                    continue
                entry_count += len(entries)
            except PermissionError:
                diagnostics.append(
                    _diagnostic(
                        "permission_denied",
                        "A plugin directory could not be read due to permissions.",
                        location=root.public_prefix,
                    )
                )
                continue
            except (TypeError, NotImplementedError):
                diagnostics.append(
                    _diagnostic(
                        "secure_plugin_backend_unavailable",
                        "Secure plugin directory-handle traversal is unavailable.",
                        location=root.public_prefix,
                    )
                )
                stop = True
                continue
            except OSError:
                diagnostics.append(
                    _diagnostic(
                        "directory_read_error",
                        "A plugin directory could not be read.",
                        location=root.public_prefix,
                    )
                )
                continue
            for entry in entries:
                if entry.name.casefold() == ".env":
                    diagnostics.append(
                        _diagnostic(
                            "env_path_blocked",
                            "A .env entry inside a plugin root was skipped without reading it.",
                            location=root.public_prefix,
                        )
                    )
                    continue
                try:
                    entry_stat = entry.stat(follow_symlinks=False)
                except PermissionError:
                    diagnostics.append(
                        _diagnostic(
                            "permission_denied",
                            "A plugin-root entry could not be inspected due to permissions.",
                            location=root.public_prefix,
                        )
                    )
                    continue
                except OSError:
                    diagnostics.append(
                        _diagnostic(
                            "plugin_entry_stat_error",
                            "A plugin-root entry could not be inspected.",
                            location=root.public_prefix,
                        )
                    )
                    continue
                if stat.S_ISLNK(entry_stat.st_mode):
                    is_manifest = (
                        entry.name == "plugin.json"
                        and parts
                        and parts[-1] in _PLUGIN_MARKERS
                    )
                    diagnostics.append(
                        _diagnostic(
                            "symlink_manifest_rejected"
                            if is_manifest
                            else "symlink_directory_rejected",
                            "A symbolic-link plugin entry was rejected conservatively.",
                            location=root.public_prefix,
                        )
                    )
                    continue
                is_manifest_entry = (
                    entry.name == "plugin.json"
                    and parts
                    and parts[-1] in _PLUGIN_MARKERS
                )
                if stat.S_ISDIR(entry_stat.st_mode):
                    if depth >= MAX_PLUGIN_DEPTH:
                        diagnostics.append(
                            _diagnostic(
                                "plugin_depth_limit",
                                "A plugin root exceeded the supported traversal depth.",
                                location=root.public_prefix,
                            )
                        )
                        continue
                    try:
                        child_fd = _open_verified_child_directory(
                            directory_fd, entry.name, entry_stat
                        )
                    except PermissionError:
                        diagnostics.append(
                            _diagnostic(
                                "permission_denied",
                                "A plugin directory could not be opened due to permissions.",
                                location=root.public_prefix,
                            )
                        )
                        continue
                    except OSError:
                        diagnostics.append(
                            _diagnostic(
                                "source_changed",
                                "A plugin directory changed before it could be traversed.",
                                location=root.public_prefix,
                            )
                        )
                        continue
                    stack.append((child_fd, parts + (entry.name,), depth + 1))
                    continue
                if is_manifest_entry and not stat.S_ISREG(entry_stat.st_mode):
                    diagnostics.append(
                        _diagnostic(
                            "not_regular_file",
                            "A plugin manifest is not a regular file and was skipped.",
                            location=root.public_prefix,
                        )
                    )
                    continue
                if (
                    not stat.S_ISREG(entry_stat.st_mode)
                    or not is_manifest_entry
                ):
                    continue
                manifest_id = _file_id(entry_stat)
                if manifest_id is None:
                    diagnostics.append(
                        _diagnostic(
                            "manifest_unverifiable",
                            "A plugin manifest had no stable physical identity and was skipped.",
                            location=root.public_prefix,
                        )
                    )
                    continue
                if manifest_id in seen_manifests:
                    continue
                payload, read_diagnostics = _read_manifest_at(
                    directory_fd,
                    entry_stat,
                    location=root.public_prefix,
                )
                diagnostics.extend(read_diagnostics)
                if payload is None:
                    continue
                seen_manifests.add(manifest_id)
                exact_path = physical_root.joinpath(*parts, entry.name)
                plugin_directory = exact_path.parent.parent
                occurrences.append(
                    _ManifestOccurrence(
                        payload,
                        exact_path,
                        plugin_directory,
                        parts[-1],
                        root,
                        manifest_id,
                        root.public_prefix,
                    )
                )
        finally:
            os.close(directory_fd)
    while stack:
        os.close(stack.pop()[0])
    if limit_exceeded:
        occurrences.clear()
    return tuple(occurrences), tuple(diagnostics)


def _plugin_pairs(
    occurrences: Iterable[_ManifestOccurrence],
) -> tuple[
    list[tuple[Capability, ResolverRecord]], list[RootSpec], list[Diagnostic]
]:
    pairs: list[tuple[Capability, ResolverRecord]] = []
    skill_roots: list[RootSpec] = []
    diagnostics: list[Diagnostic] = []
    for occurrence in occurrences:
        parsed = _parse_structured(
            occurrence.payload,
            structured_format="json",
            location=occurrence.location,
        )
        diagnostics.extend(parsed.diagnostics)
        manifest = parsed.value
        if manifest is None:
            continue
        if not isinstance(manifest, Mapping):
            diagnostics.append(
                _diagnostic(
                    "invalid_plugin_manifest",
                    "A plugin manifest root must be an object.",
                    location=occurrence.location,
                )
            )
            continue
        raw_name = manifest.get("name")
        if not isinstance(raw_name, str):
            diagnostics.append(
                _diagnostic(
                    "plugin_name_missing",
                    "A plugin manifest had no usable name and was skipped.",
                    location=occurrence.location,
                )
            )
            continue
        raw_version = manifest.get("version")
        raw_description = manifest.get("description")
        raw_keywords = manifest.get("keywords")
        raw_provider = manifest.get("provider")
        default_provider = occurrence.marker.removeprefix(".")
        external_strings = [raw_name]
        external_strings.extend(
            value
            for value in (raw_version, raw_description, raw_provider)
            if isinstance(value, str)
        )
        if isinstance(raw_keywords, list):
            external_strings.extend(
                item for item in raw_keywords[:128] if isinstance(item, str)
            )
        try:
            normalized_strings = {
                id(value): _normalize_external_text(value)
                for value in external_strings
            }
        except _InvalidUnicode:
            diagnostics.append(
                _diagnostic(
                    "invalid_unicode",
                    "A plugin manifest contained invalid Unicode and was skipped.",
                    location=occurrence.location,
                )
            )
            continue
        normalized_name = normalized_strings[id(raw_name)]
        name = sanitize_text(normalized_name, max_length=512)
        if not name:
            diagnostics.append(
                _diagnostic(
                    "plugin_name_missing",
                    "A plugin manifest had no usable name and was skipped.",
                    location=occurrence.location,
                )
            )
            continue
        version = (
            sanitize_text(normalized_strings[id(raw_version)], max_length=256)
            if isinstance(raw_version, str)
            else None
        )
        description = (
            sanitize_text(normalized_strings[id(raw_description)], max_length=2_048)
            if isinstance(raw_description, str)
            else ""
        )
        keywords = tuple(
            sanitize_text(normalized_strings[id(item)], max_length=256)
            for item in raw_keywords[:128]
            if isinstance(item, str)
            and sanitize_text(normalized_strings[id(item)], max_length=256)
        ) if isinstance(raw_keywords, list) else ()
        provider = (
            sanitize_text(normalized_strings[id(raw_provider)], max_length=256)
            if isinstance(raw_provider, str)
            and sanitize_text(normalized_strings[id(raw_provider)], max_length=256)
            else default_provider
        )
        version_label = version or "unknown"
        source_location = (
            f"{occurrence.source.public_prefix}::plugin:{name}@{version_label}"
        )
        physical = f"{occurrence.physical_id[0]}:{occurrence.physical_id[1]}"
        capability = Capability(
            kind="plugin",
            name=name,
            description=description,
            tags=keywords,
            source_locations=(
                SourceLocation(source_location, "plugin", provider),
            ),
            scope="plugin",
            provider=provider,
            version=version,
            logical_identity=(
                f"plugin-v1:{occurrence.marker}:provider-sha256:{_name_digest(provider)}:"
                f"{_name_digest(normalized_name)}:"
                f"{_name_digest(normalized_strings[id(raw_version)] if isinstance(raw_version, str) else '')}:"
                f"physical:{physical}"
            ),
        )
        resolver = ResolverRecord(
            capability.resolver_id,
            (
                str(occurrence.exact_path),
                str(occurrence.plugin_directory),
            ),
        )
        pairs.append((capability, resolver))
        skill_roots.append(
            RootSpec(
                occurrence.plugin_directory,
                "plugin",
                name,
                f"plugin-skill-root:{capability.id}",
                f"<plugin:{capability.id}>",
            )
        )
        for container_name, server_name, configuration in _server_maps(manifest):
            try:
                pair = _mcp_pair(
                    server_name,
                    configuration,
                    scope="plugin",
                    provider=name,
                    location=f"<plugin:{capability.id}>/manifest",
                    logical_source=(
                        f"plugin:{capability.id}:container:{container_name}"
                    ),
                    source_identity=f"manifest:{physical}",
                    exact_path=occurrence.exact_path,
                )
            except _InvalidUnicode:
                diagnostics.append(
                    _diagnostic(
                        "invalid_unicode",
                        "A plugin-declared MCP name contained invalid Unicode and was skipped.",
                        location=occurrence.location,
                    )
                )
                continue
            pairs.append(pair)
    return pairs, skill_roots, diagnostics


def discover_connectors(
    *,
    home: Path,
    project: Path | None = None,
    extra_config_paths: Iterable[Path | ConnectorConfigSpec] = (),
    plugin_roots: Iterable[Path | RootSpec] = (),
    environ: Mapping[str, str] | None = None,
    platform_name: str | None = None,
) -> ConnectorDiscoveryResult:
    """Discover MCPs and verified plugins without executing or networking."""

    injected_home = Path(home)
    injected_project = None if project is None else Path(project)
    environment = os.environ if environ is None else environ
    operating_system = platform.system() if platform_name is None else platform_name
    windows = operating_system.casefold().startswith("win")
    pairs: list[tuple[Capability, ResolverRecord]] = []
    diagnostics: list[Diagnostic] = []

    for spec in _config_specs(
        home=injected_home,
        project=injected_project,
        extra_config_paths=extra_config_paths,
        environ=environment,
        windows=windows,
    ):
        read = _read_bounded_path(spec.path, location=spec.public_location)
        diagnostics.extend(read.diagnostics)
        if read.payload is None or read.exact_path is None:
            continue
        parsed = _parse_structured(
            read.payload,
            structured_format=spec.format,
            location=spec.public_location,
        )
        diagnostics.extend(parsed.diagnostics)
        if parsed.value is None:
            continue
        for container_name, name, configuration in _server_maps(parsed.value):
            try:
                pair = _mcp_pair(
                    name,
                    configuration,
                    scope=spec.scope,
                    provider=spec.provider,
                    location=spec.public_location,
                    logical_source=(
                        f"{spec.logical_key}:container:{container_name}"
                    ),
                    source_identity=read.physical_identity or "unknown",
                    exact_path=read.exact_path,
                )
            except _InvalidUnicode:
                diagnostics.append(
                    _diagnostic(
                        "invalid_unicode",
                        "An MCP name contained invalid Unicode and was skipped.",
                        location=spec.public_location,
                    )
                )
                continue
            pairs.append(pair)

    plugin_specs = _plugin_root_specs(
        home=injected_home,
        project=injected_project,
        plugin_roots=plugin_roots,
        environ=environment,
        windows=windows,
    )
    occurrences: list[_ManifestOccurrence] = []
    seen_manifest_ids: set[tuple[int, int]] = set()
    if not _secure_plugin_backend_supported():
        diagnostics.append(
            _diagnostic(
                "secure_plugin_backend_unavailable",
                "Secure plugin directory-handle traversal is unavailable; plugin roots were skipped.",
                location="<plugin-roots>",
            )
        )
    else:
        for root in plugin_specs:
            try:
                root_occurrences, root_diagnostics = _scan_plugin_root(root)
            except (TypeError, NotImplementedError):
                diagnostics.append(
                    _diagnostic(
                        "secure_plugin_backend_unavailable",
                        "Secure plugin directory-handle traversal is unavailable for a configured root.",
                        location=root.public_prefix,
                    )
                )
                continue
            diagnostics.extend(root_diagnostics)
            for occurrence in root_occurrences:
                if occurrence.physical_id in seen_manifest_ids:
                    continue
                seen_manifest_ids.add(occurrence.physical_id)
                occurrences.append(occurrence)
    plugin_pairs, skill_roots, plugin_diagnostics = _plugin_pairs(occurrences)
    pairs.extend(plugin_pairs)
    diagnostics.extend(plugin_diagnostics)

    pairs.sort(
        key=lambda pair: (
            pair[0].kind,
            pair[0].name.casefold(),
            pair[0].name,
            pair[0].provider.casefold(),
            pair[0].version or "",
            pair[0].id,
        )
    )
    skill_roots.sort(
        key=lambda item: (
            item.provider.casefold(),
            item.provider,
            item.logical_key,
        )
    )
    diagnostics.sort(
        key=lambda item: (
            item.code,
            item.message,
            json.dumps(item.to_public_dict(), ensure_ascii=False, sort_keys=True),
        )
    )
    return ConnectorDiscoveryResult(
        capabilities=tuple(pair[0] for pair in pairs),
        resolvers=tuple(pair[1] for pair in pairs),
        skill_roots=tuple(skill_roots),
        diagnostics=tuple(diagnostics),
    )


__all__ = [
    "MAX_CONFIG_BYTES",
    "MAX_STRUCTURE_DEPTH",
    "MAX_STRUCTURE_ITEMS",
    "ConnectorConfigSpec",
    "ConnectorDiscoveryResult",
    "discover_connectors",
]

"""Bounded, non-executing MCP configuration and plugin discovery."""

from __future__ import annotations

import errno
import hashlib
import json
import os
import re
import stat
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


def _resolve_safe_chain(path: Path, *, max_links: int = 64) -> Path:
    """Resolve symlinks without ever traversing a case-insensitive .env hop."""

    absolute = path.absolute()
    resolved = Path(absolute.anchor)
    pending = deque(absolute.parts[1:])
    seen: set[tuple[Path, tuple[str, ...]]] = set()
    links = 0
    while pending:
        part = pending.popleft()
        if part in {"", "."}:
            continue
        if part == "..":
            resolved = resolved.parent
            continue
        if part.casefold() == ".env":
            raise _EnvPathBlocked
        candidate = resolved / part
        entry_stat = os.lstat(candidate)
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
        pending.extendleft(reversed(target_parts))
    return resolved


def _file_id(value: os.stat_result) -> tuple[int, int] | None:
    inode = getattr(value, "st_ino", 0)
    if not inode:
        return None
    return (getattr(value, "st_dev", 0), inode)


def _stat_evidence(value: os.stat_result) -> tuple[int, ...]:
    return tuple(
        int(getattr(value, name))
        for name in ("st_dev", "st_ino", "st_mode", "st_size", "st_mtime_ns")
        if hasattr(value, name)
    )


def _file_flags() -> int:
    return (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )


def _directory_flags() -> int:
    return _file_flags() | getattr(os, "O_DIRECTORY", 0)


def _read_fd_bounded(fd: int, maximum: int) -> tuple[bytes, bool]:
    payload = bytearray()
    while len(payload) <= maximum:
        remaining = maximum + 1 - len(payload)
        chunk = os.read(fd, min(_READ_CHUNK_BYTES, remaining))
        if not chunk:
            break
        payload.extend(chunk)
    return bytes(payload[:maximum]), len(payload) > maximum


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
    except OSError:
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
                    "source_not_file",
                    "A configured source is not a regular file.",
                    location=location,
                ),
            ),
        )
    try:
        fd = os.open(exact_path, _file_flags())
    except PermissionError:
        return _ReadResult(
            None,
            None,
            (
                _diagnostic(
                    "permission_denied",
                    "A configured source could not be read due to permissions.",
                    location=location,
                ),
            ),
        )
    except OSError:
        return _ReadResult(
            None,
            None,
            (
                _diagnostic(
                    "source_open_error",
                    "A configured source could not be opened safely.",
                    location=location,
                ),
            ),
        )
    try:
        opened = os.fstat(fd)
        if (
            not stat.S_ISREG(opened.st_mode)
            or _file_id(opened) != _file_id(expected)
            or _stat_evidence(opened) != _stat_evidence(expected)
        ):
            return _ReadResult(
                None,
                None,
                (
                    _diagnostic(
                        "source_changed",
                        "A configured source changed before it could be read.",
                        location=location,
                    ),
                ),
            )
        payload, oversized = _read_fd_bounded(fd, MAX_CONFIG_BYTES)
        final_stat = os.fstat(fd)
        if _file_id(final_stat) != _file_id(opened) or (
            not oversized and _stat_evidence(final_stat) != _stat_evidence(opened)
        ):
            return _ReadResult(
                None,
                None,
                (
                    _diagnostic(
                        "source_changed",
                        "A configured source changed while it was being read.",
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
                    "A configured source could not be read due to permissions.",
                    location=location,
                ),
            ),
        )
    except OSError:
        return _ReadResult(
            None,
            None,
            (
                _diagnostic(
                    "source_read_error",
                    "A configured source could not be read safely.",
                    location=location,
                ),
            ),
        )
    finally:
        os.close(fd)
    if oversized:
        return _ReadResult(
            None,
            exact_path,
            (
                _diagnostic(
                    too_large_code,
                    "A structured source exceeded the supported size limit.",
                    location=location,
                ),
            ),
        )
    return _ReadResult(payload, exact_path)


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


def _fallback_toml_scalar(raw: str) -> str | bool:
    value = raw.strip()
    if value.casefold() in {"true", "false"}:
        return value.casefold() == "true"
    if len(value) >= 2 and value[0] == value[-1] == '"':
        decoded = json.loads(value)
        if isinstance(decoded, str):
            return decoded
    if len(value) >= 2 and value[0] == value[-1] == "'":
        return value[1:-1]
    raise ValueError("unsupported TOML subset value")


def _parse_toml_subset(payload: bytes) -> dict[str, Any]:
    """Parse only simple MCP tables and scalar fields on Python 3.10."""

    text = payload.decode("utf-8")
    result: dict[str, dict[str, dict[str, Any]]] = {}
    current: dict[str, Any] | None = None
    table_re = re.compile(
        r"^\[\s*(mcp_servers|mcpServers)\s*\.\s*"
        r"(?:\"((?:\\.|[^\"])*)\"|'([^']*)'|([A-Za-z0-9_-]+))\s*\]$"
    )
    key_re = re.compile(r"^([A-Za-z][A-Za-z0-9_-]*)\s*=\s*(.+)$")
    for source_line in text.splitlines():
        line = _strip_toml_comment(source_line)
        if not line:
            continue
        table_match = table_re.fullmatch(line)
        if table_match:
            table_name = table_match.group(1)
            quoted = table_match.group(2)
            if quoted is not None:
                server_name = json.loads(f'"{quoted}"')
            else:
                server_name = table_match.group(3) or table_match.group(4) or ""
            current = result.setdefault(table_name, {}).setdefault(server_name, {})
            continue
        key_match = key_re.fullmatch(line)
        if current is None or key_match is None:
            raise ValueError("unsupported TOML subset syntax")
        current[key_match.group(1)] = _fallback_toml_scalar(key_match.group(2))
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


def _server_maps(value: Any) -> tuple[tuple[str, Mapping[str, Any]], ...]:
    if not isinstance(value, Mapping):
        return ()
    servers: list[tuple[str, Mapping[str, Any]]] = []
    for field_name in ("mcp_servers", "mcpServers", "servers"):
        container = value.get(field_name)
        if not isinstance(container, Mapping):
            continue
        for name, configuration in container.items():
            if isinstance(name, str) and isinstance(configuration, Mapping):
                servers.append((name, configuration))
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
    return hashlib.sha256(name.encode("utf-8", errors="replace")).hexdigest()


def _mcp_pair(
    name: str,
    configuration: Mapping[str, Any],
    *,
    scope: str,
    provider: str,
    location: str,
    logical_source: str,
    exact_path: Path,
) -> tuple[Capability, ResolverRecord]:
    safe_name = sanitize_text(name, max_length=512) or "unnamed-mcp"
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
            f"mcp-v1:{logical_source}:name-sha256:{_name_digest(name)}"
        ),
    )
    return capability, ResolverRecord(capability.resolver_id, (str(exact_path),))


def _environment_value(environ: Mapping[str, str], key: str) -> str | None:
    if key in environ:
        return environ[key]
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
) -> tuple[ConnectorConfigSpec, ...]:
    injected = tuple(extra_config_paths)
    codex_override = _environment_value(environ, "CODEX_HOME")
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
    unique: dict[str, ConnectorConfigSpec] = {}
    for spec in sorted(specs, key=lambda item: item.logical_key):
        unique.setdefault(spec.logical_key, spec)
    return tuple(unique.values())


def _plugin_root_specs(
    *,
    home: Path,
    project: Path | None,
    plugin_roots: Iterable[Path | RootSpec],
    environ: Mapping[str, str],
) -> tuple[RootSpec, ...]:
    injected = tuple(plugin_roots)
    codex_override = _environment_value(environ, "CODEX_HOME")
    claude_override = _environment_value(environ, "CLAUDE_CONFIG_DIR")
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
    try:
        fd = os.open("plugin.json", _file_flags(), dir_fd=directory_fd)
    except OSError:
        return None, (
            _diagnostic(
                "manifest_open_error",
                "A plugin manifest changed before it could be opened safely.",
                location=location,
            ),
        )
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
                    "A plugin manifest changed before it could be read.",
                    location=location,
                ),
            )
        payload, oversized = _read_fd_bounded(fd, MAX_CONFIG_BYTES)
        final_stat = os.fstat(fd)
        if _file_id(final_stat) != _file_id(opened) or (
            not oversized and _stat_evidence(final_stat) != _stat_evidence(opened)
        ):
            return None, (
                _diagnostic(
                    "source_changed",
                    "A plugin manifest changed while it was being read.",
                    location=location,
                ),
            )
    except OSError:
        return None, (
            _diagnostic(
                "manifest_read_error",
                "A plugin manifest could not be read safely.",
                location=location,
            ),
        )
    finally:
        os.close(fd)
    if oversized:
        return None, (
            _diagnostic(
                "manifest_too_large",
                "A plugin manifest exceeded the supported size limit.",
                location=location,
            ),
        )
    return payload, ()


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
    except OSError:
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
    while stack and not stop:
        directory_fd, parts, depth = stack.pop()
        try:
            try:
                with os.scandir(directory_fd) as iterator:
                    entries = []
                    remaining = MAX_PLUGIN_ENTRIES - entry_count
                    for entry in iterator:
                        entries.append(entry)
                        if len(entries) > remaining:
                            break
            except PermissionError:
                diagnostics.append(
                    _diagnostic(
                        "permission_denied",
                        "A plugin directory could not be read due to permissions.",
                        location=root.public_prefix,
                    )
                )
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
                entry_count += 1
                if entry_count > MAX_PLUGIN_ENTRIES:
                    diagnostics.append(
                        _diagnostic(
                            "plugin_entry_limit",
                            "A plugin root exceeded the supported entry count.",
                            location=root.public_prefix,
                        )
                    )
                    stop = True
                    break
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
                        child_fd = os.open(
                            entry.name, _directory_flags(), dir_fd=directory_fd
                        )
                        opened = os.fstat(child_fd)
                        if (
                            not stat.S_ISDIR(opened.st_mode)
                            or _file_id(opened) != _file_id(entry_stat)
                        ):
                            os.close(child_fd)
                            raise OSError(errno.ESTALE, "directory changed")
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
                if (
                    not stat.S_ISREG(entry_stat.st_mode)
                    or entry.name != "plugin.json"
                    or not parts
                    or parts[-1] not in _PLUGIN_MARKERS
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
        if not isinstance(raw_name, str) or not sanitize_text(
            raw_name, max_length=512
        ):
            diagnostics.append(
                _diagnostic(
                    "plugin_name_missing",
                    "A plugin manifest had no usable name and was skipped.",
                    location=occurrence.location,
                )
            )
            continue
        name = sanitize_text(raw_name, max_length=512)
        raw_version = manifest.get("version")
        version = (
            sanitize_text(raw_version, max_length=256)
            if isinstance(raw_version, str)
            else None
        )
        raw_description = manifest.get("description")
        description = (
            sanitize_text(raw_description, max_length=2_048)
            if isinstance(raw_description, str)
            else ""
        )
        raw_keywords = manifest.get("keywords")
        keywords = tuple(
            sanitize_text(item, max_length=256)
            for item in raw_keywords[:128]
            if isinstance(item, str) and sanitize_text(item, max_length=256)
        ) if isinstance(raw_keywords, list) else ()
        raw_provider = manifest.get("provider")
        default_provider = occurrence.marker.removeprefix(".")
        provider = (
            sanitize_text(raw_provider, max_length=256)
            if isinstance(raw_provider, str)
            and sanitize_text(raw_provider, max_length=256)
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
                f"{_name_digest(raw_name)}:{_name_digest(raw_version if isinstance(raw_version, str) else '')}:"
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
        for server_name, configuration in _server_maps(manifest):
            pairs.append(
                _mcp_pair(
                    server_name,
                    configuration,
                    scope="plugin",
                    provider=name,
                    location=f"<plugin:{capability.id}>/manifest",
                    logical_source=f"plugin:{capability.id}",
                    exact_path=occurrence.exact_path,
                )
            )
    return pairs, skill_roots, diagnostics


def discover_connectors(
    *,
    home: Path,
    project: Path | None = None,
    extra_config_paths: Iterable[Path | ConnectorConfigSpec] = (),
    plugin_roots: Iterable[Path | RootSpec] = (),
    environ: Mapping[str, str] | None = None,
) -> ConnectorDiscoveryResult:
    """Discover MCPs and verified plugins without executing or networking."""

    injected_home = Path(home)
    injected_project = None if project is None else Path(project)
    environment = os.environ if environ is None else environ
    pairs: list[tuple[Capability, ResolverRecord]] = []
    diagnostics: list[Diagnostic] = []

    for spec in _config_specs(
        home=injected_home,
        project=injected_project,
        extra_config_paths=extra_config_paths,
        environ=environment,
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
        for name, configuration in _server_maps(parsed.value):
            pairs.append(
                _mcp_pair(
                    name,
                    configuration,
                    scope=spec.scope,
                    provider=spec.provider,
                    location=spec.public_location,
                    logical_source=spec.logical_key,
                    exact_path=read.exact_path,
                )
            )

    occurrences: list[_ManifestOccurrence] = []
    seen_manifest_ids: set[tuple[int, int]] = set()
    for root in _plugin_root_specs(
        home=injected_home,
        project=injected_project,
        plugin_roots=plugin_roots,
        environ=environment,
    ):
        root_occurrences, root_diagnostics = _scan_plugin_root(root)
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

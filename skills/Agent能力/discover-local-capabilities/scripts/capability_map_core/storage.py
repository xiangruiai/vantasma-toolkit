"""Safe public capability-map storage and a private exact-path resolver."""

from __future__ import annotations

import errno
import hashlib
import json
import os
import platform
import re
import stat
import tempfile
from collections import deque
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Protocol

from .models import Diagnostic
from .sanitize import REDACTED_PATH, sanitize, sanitize_text


MAP_FILENAME = "本机能力地图.md"
INVENTORY_FILENAME = "capability-inventory.json"
CONFIG_FILENAME = "capability-map.config.json"
RECEIPT_FILENAME = "setup-receipt.md"
RESOLVER_FILENAME = "capability-resolver.json"
MAX_OBSIDIAN_CONFIG_BYTES = 1024 * 1024
MAX_STORAGE_TARGET_BYTES = 64 * 1024 * 1024
_READ_CHUNK_BYTES = 64 * 1024
_WINDOWS_ABSOLUTE_RE = re.compile(r"^(?:[A-Za-z]:[\\/]|[\\/]{2}[^\\/])")
_IGNORABLE_FSYNC_ERRORS = frozenset(
    {
        errno.EINVAL,
        errno.EBADF,
        errno.EROFS,
        errno.EPERM,
        getattr(errno, "ENOTSUP", errno.EINVAL),
        getattr(errno, "EOPNOTSUPP", errno.EINVAL),
    }
)


@dataclass(frozen=True)
class StoragePaths:
    """Exact runtime locations for one capability-map installation."""

    public_root: Path
    map_path: Path
    inventory_path: Path
    config_path: Path
    receipt_path: Path
    private_root: Path
    resolver_path: Path
    backup_root: Path | None = None
    staging_root: Path | None = None

    def __post_init__(self) -> None:
        for name in (
            "public_root",
            "map_path",
            "inventory_path",
            "config_path",
            "receipt_path",
            "private_root",
            "resolver_path",
        ):
            object.__setattr__(self, name, Path(getattr(self, name)))
        for name in ("backup_root", "staging_root"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, Path(value))

        expected_public = {
            "map_path": self.public_root / MAP_FILENAME,
            "inventory_path": self.public_root / INVENTORY_FILENAME,
            "config_path": self.public_root / CONFIG_FILENAME,
            "receipt_path": self.public_root / RECEIPT_FILENAME,
        }
        for name, expected in expected_public.items():
            if getattr(self, name) != expected:
                raise ValueError(f"{name} must be {expected.name!r} inside public_root")
        if self.resolver_path != self.private_root / RESOLVER_FILENAME:
            raise ValueError(
                f"resolver_path must be {RESOLVER_FILENAME!r} inside private_root"
            )


@dataclass(frozen=True)
class VaultCandidate:
    """An exact runtime Vault candidate with a path-free display label."""

    path: Path
    display_label: str
    open: bool = False
    source_configs: tuple[Path, ...] | list[Path] = field(
        default_factory=tuple, repr=False
    )

    def __post_init__(self) -> None:
        safe_label = sanitize_text(self.display_label, max_length=128)
        if not safe_label:
            safe_label = "Vault"
        object.__setattr__(self, "path", Path(self.path))
        object.__setattr__(self, "display_label", safe_label)
        object.__setattr__(self, "open", bool(self.open))
        object.__setattr__(
            self,
            "source_configs",
            tuple(sorted({Path(path) for path in self.source_configs}, key=str)),
        )


@dataclass(frozen=True)
class VaultDiscoveryResult:
    candidates: tuple[VaultCandidate, ...] | list[VaultCandidate] = field(
        default_factory=tuple
    )
    diagnostics: tuple[Diagnostic, ...] | list[Diagnostic] = field(
        default_factory=tuple
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "candidates", tuple(self.candidates))
        object.__setattr__(self, "diagnostics", tuple(self.diagnostics))


@dataclass(frozen=True)
class PublicArtifacts:
    """Caller-provided public documents; storage sanitizes them before writing."""

    map_markdown: str
    inventory: str | Mapping[str, Any]
    config: str | Mapping[str, Any]
    receipt_markdown: str

    def __post_init__(self) -> None:
        if not isinstance(self.map_markdown, str):
            raise TypeError("map_markdown must be a string")
        if not isinstance(self.receipt_markdown, str):
            raise TypeError("receipt_markdown must be a string")
        if not isinstance(self.inventory, (str, Mapping)):
            raise TypeError("inventory must be a JSON string or mapping")
        if not isinstance(self.config, (str, Mapping)):
            raise TypeError("config must be a JSON string or mapping")


@dataclass(frozen=True)
class StorageWriteResult:
    """Content-addressed result of a complete public/private bundle write."""

    generation_id: str
    hashes: dict[str, str]
    changed_paths: tuple[Path, ...]
    receipt_info: dict[str, Any]


class ResolverRecordLike(Protocol):
    """Structural protocol shared by model and CLI resolver records."""

    resolver_id: str
    exact_locations: Sequence[str]


@dataclass(frozen=True)
class _ResolverEntry:
    resolver_id: str
    exact_locations: tuple[str, ...]


@dataclass(frozen=True)
class _Snapshot:
    existed: bool
    payload: bytes | None
    mode: int | None
    device: int | None = None
    inode: int | None = None
    size: int | None = None
    mtime_ns: int | None = None
    ctime_ns: int | None = None


@dataclass(frozen=True)
class _PreparedTarget:
    label: str
    target: Path
    payload: bytes
    expected_hash: str
    mode: int
    json_document: bool = False


def _environment_value(
    environ: Mapping[str, str], key: str, *, case_insensitive: bool
) -> str | None:
    if not case_insensitive:
        return environ.get(key)
    folded = key.casefold()
    for candidate, value in environ.items():
        if candidate.casefold() == folded:
            return value
    return None


def _expand_injected_path(value: str | os.PathLike[str], home: Path) -> Path:
    raw = os.fspath(value)
    if raw == "~":
        return home
    if raw.startswith(("~/", "~\\")):
        return home / raw[2:].replace("\\", os.sep)
    path = Path(raw)
    if path.is_absolute() or _WINDOWS_ABSOLUTE_RE.match(raw):
        return path
    return Path(os.path.abspath(path))


def _safe_vault_subdirectory(value: str | os.PathLike[str]) -> Path:
    raw = os.fspath(value)
    if not raw.strip():
        raise ValueError("vault_subdirectory must not be empty")
    if Path(raw).is_absolute() or PureWindowsPath(raw).is_absolute():
        raise ValueError("vault_subdirectory must be relative")
    parts = PurePosixPath(raw.replace("\\", "/")).parts
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise ValueError("vault_subdirectory must not contain traversal segments")
    return Path(*parts)


def _normalized_compare_path(path: Path) -> str:
    return os.path.normcase(os.path.abspath(os.path.normpath(os.fspath(path))))


def _is_within(path: Path, root: Path) -> bool:
    try:
        return os.path.commonpath(
            (_normalized_compare_path(path), _normalized_compare_path(root))
        ) == _normalized_compare_path(root)
    except ValueError:
        return False


def _resolve_storage_path(path: Path, *, reject_root_symlink: bool) -> Path:
    """Resolve existing ancestors without trusting a symlinked output root."""

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
            raise ValueError("storage paths must not traverse .env")
        candidate = resolved / part
        try:
            metadata = os.lstat(candidate)
        except FileNotFoundError as error:
            if from_link_target:
                raise ValueError("storage path contains a broken symlink") from error
            resolved = candidate
            continue
        except OSError as error:
            raise ValueError("storage path could not be resolved safely") from error
        if not stat.S_ISLNK(metadata.st_mode):
            resolved = candidate
            continue
        if reject_root_symlink and not pending:
            raise ValueError("storage output root must not be a symbolic link")
        links += 1
        state = (candidate, tuple(pending))
        if links > 64 or state in seen:
            raise ValueError("storage path contains a symbolic-link loop")
        seen.add(state)
        try:
            target = Path(os.readlink(candidate))
        except OSError as error:
            raise ValueError("storage symlink could not be read safely") from error
        target_parts = list(target.parts)
        if target.is_absolute():
            resolved = Path(target.anchor)
            target_parts = target_parts[1:]
        pending.extendleft(
            reversed([(target_part, True) for target_part in target_parts])
        )
    return Path(os.path.normpath(resolved))


def default_storage_paths(
    *,
    platform_name: str | None = None,
    environ: Mapping[str, str] | None = None,
    home: Path | None = None,
    local_root: str | os.PathLike[str] | None = None,
    public_root: str | os.PathLike[str] | None = None,
    selected_vault: str | os.PathLike[str] | None = None,
    obsidian_vault: str | os.PathLike[str] | None = None,
    vault_subdirectory: str | os.PathLike[str] = "Agent/本机能力地图",
    private_root: str | os.PathLike[str] | None = None,
    backup_root: str | os.PathLike[str] | None = None,
    staging_root: str | os.PathLike[str] | None = None,
) -> StoragePaths:
    """Return exact OS-aware storage locations from fully injectable inputs."""

    injected_home = Path.home() if home is None else Path(home)
    environment = os.environ if environ is None else environ
    operating_system = platform.system() if platform_name is None else platform_name
    windows = operating_system.casefold().startswith("win")

    if local_root is not None and public_root is not None:
        left = _expand_injected_path(local_root, injected_home)
        right = _expand_injected_path(public_root, injected_home)
        if left != right:
            raise ValueError("local_root and public_root disagree")
    selected_local = local_root if local_root is not None else public_root
    if selected_vault is not None and obsidian_vault is not None:
        left = _expand_injected_path(selected_vault, injected_home)
        right = _expand_injected_path(obsidian_vault, injected_home)
        if left != right:
            raise ValueError("selected_vault and obsidian_vault disagree")
    vault_value = selected_vault if selected_vault is not None else obsidian_vault
    if selected_local is not None and vault_value is not None:
        raise ValueError("choose either a local root or an Obsidian Vault")

    if operating_system.casefold() in {"darwin", "mac", "macos"}:
        system_data_root = (
            injected_home
            / "Library"
            / "Application Support"
            / "Vantasma"
            / "Agent能力地图"
        )
    elif windows:
        local_app_data = _environment_value(
            environment, "LOCALAPPDATA", case_insensitive=True
        )
        data_home = (
            _expand_injected_path(local_app_data, injected_home)
            if local_app_data
            else injected_home / "AppData" / "Local"
        )
        system_data_root = data_home / "Vantasma" / "Agent能力地图"
    else:
        xdg_data_home = _environment_value(
            environment, "XDG_DATA_HOME", case_insensitive=False
        )
        data_home = (
            _expand_injected_path(xdg_data_home, injected_home)
            if xdg_data_home
            else injected_home / ".local" / "share"
        )
        system_data_root = data_home / "vantasma" / "agent-capabilities"

    vault_path: Path | None = None
    if vault_value is not None:
        vault_path = _expand_injected_path(vault_value, injected_home)
        selected_public_root = vault_path / _safe_vault_subdirectory(
            vault_subdirectory
        )
    elif selected_local is not None:
        selected_public_root = _expand_injected_path(selected_local, injected_home)
    else:
        selected_public_root = system_data_root

    selected_private_root = (
        _expand_injected_path(private_root, injected_home)
        if private_root is not None
        else system_data_root / ".private"
    )
    resolved_public_root = _resolve_storage_path(
        selected_public_root, reject_root_symlink=True
    )
    resolved_private_root = _resolve_storage_path(
        selected_private_root, reject_root_symlink=True
    )
    if vault_path is not None:
        resolved_vault = _resolve_storage_path(vault_path, reject_root_symlink=True)
        if not _is_within(resolved_public_root, resolved_vault):
            raise ValueError("public storage must remain inside the selected Vault")
        if _is_within(resolved_private_root, resolved_vault) or _is_within(
            resolved_private_root, resolved_public_root
        ):
            raise ValueError(
                "private resolver storage must be outside the selected Vault"
            )

    selected_backup = (
        None
        if backup_root is None
        else _expand_injected_path(backup_root, injected_home)
    )
    selected_staging = (
        None
        if staging_root is None
        else _expand_injected_path(staging_root, injected_home)
    )
    return StoragePaths(
        public_root=selected_public_root,
        map_path=selected_public_root / MAP_FILENAME,
        inventory_path=selected_public_root / INVENTORY_FILENAME,
        config_path=selected_public_root / CONFIG_FILENAME,
        receipt_path=selected_public_root / RECEIPT_FILENAME,
        private_root=selected_private_root,
        resolver_path=selected_private_root / RESOLVER_FILENAME,
        backup_root=selected_backup,
        staging_root=selected_staging,
    )


def _config_label(path: Path) -> str:
    digest = hashlib.sha256(os.fspath(path).encode("utf-8", "surrogatepass")).hexdigest()
    return f"<obsidian-config:{digest[:12]}>"


def _diagnostic(code: str, message: str, config_path: Path) -> Diagnostic:
    return Diagnostic(
        "warning", code, message, {"location": _config_label(config_path)}
    )


def _has_env_segment(path: Path) -> bool:
    normalized = os.fspath(path).replace("\\", "/")
    return any(part.casefold() == ".env" for part in normalized.split("/"))


def _read_obsidian_config(path: Path) -> tuple[bytes | None, tuple[Diagnostic, ...]]:
    if _has_env_segment(path):
        return None, (
            _diagnostic(
                "obsidian_config_env_blocked",
                "An Obsidian configuration inside .env was not read.",
                path,
            ),
        )
    try:
        before = os.lstat(path)
    except FileNotFoundError:
        return None, ()
    except PermissionError:
        return None, (
            _diagnostic(
                "obsidian_config_permission_denied",
                "An Obsidian configuration could not be opened due to permissions.",
                path,
            ),
        )
    except OSError:
        return None, (
            _diagnostic(
                "obsidian_config_read_error",
                "An Obsidian configuration could not be inspected safely.",
                path,
            ),
        )

    if stat.S_ISLNK(before.st_mode):
        return None, (
            _diagnostic(
                "obsidian_config_symlink",
                "A symbolic-link Obsidian configuration was not followed.",
                path,
            ),
        )
    if not stat.S_ISREG(before.st_mode):
        return None, (
            _diagnostic(
                "obsidian_config_not_regular",
                "An Obsidian configuration is not a regular file.",
                path,
            ),
        )

    flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NONBLOCK", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    try:
        descriptor = os.open(path, flags)
    except PermissionError:
        return None, (
            _diagnostic(
                "obsidian_config_permission_denied",
                "An Obsidian configuration could not be opened due to permissions.",
                path,
            ),
        )
    except OSError:
        return None, (
            _diagnostic(
                "obsidian_config_read_error",
                "An Obsidian configuration could not be opened safely.",
                path,
            ),
        )

    try:
        opened = os.fstat(descriptor)
        before_identity = (before.st_dev, before.st_ino, before.st_mode)
        opened_identity = (opened.st_dev, opened.st_ino, opened.st_mode)
        if not stat.S_ISREG(opened.st_mode) or before_identity != opened_identity:
            return None, (
                _diagnostic(
                    "obsidian_config_changed",
                    "An Obsidian configuration changed while it was opened.",
                    path,
                ),
            )
        chunks: list[bytes] = []
        total = 0
        while total <= MAX_OBSIDIAN_CONFIG_BYTES:
            chunk = os.read(
                descriptor,
                min(
                    _READ_CHUNK_BYTES,
                    MAX_OBSIDIAN_CONFIG_BYTES + 1 - total,
                ),
            )
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
        payload = b"".join(chunks)
        if len(payload) > MAX_OBSIDIAN_CONFIG_BYTES:
            return None, (
                _diagnostic(
                    "obsidian_config_too_large",
                    "An Obsidian configuration exceeded the read limit.",
                    path,
                ),
            )
        return payload, ()
    except PermissionError:
        return None, (
            _diagnostic(
                "obsidian_config_permission_denied",
                "An Obsidian configuration could not be read due to permissions.",
                path,
            ),
        )
    except OSError:
        return None, (
            _diagnostic(
                "obsidian_config_read_error",
                "An Obsidian configuration could not be read safely.",
                path,
            ),
        )
    finally:
        os.close(descriptor)


def _configured_vault_path(
    value: str, *, config_path: Path, home: Path
) -> Path | None:
    if not value.strip():
        return None
    expanded = _expand_injected_path(value, home)
    raw = os.fspath(value)
    if not (
        Path(raw).is_absolute()
        or PureWindowsPath(raw).is_absolute()
        or raw == "~"
        or raw.startswith(("~/", "~\\"))
    ):
        expanded = Path(os.path.abspath(config_path.parent / raw))
    return expanded


def _vault_identity(path: Path) -> tuple[str, str | tuple[int, int]]:
    raw = os.fspath(path)
    network_like = raw.startswith(("//", "\\\\"))
    if not network_like:
        try:
            metadata = os.stat(path)
            return ("physical", (metadata.st_dev, metadata.st_ino))
        except OSError:
            pass
    if PureWindowsPath(raw).is_absolute():
        normalized = str(PureWindowsPath(raw)).casefold()
    else:
        normalized = os.path.normcase(os.path.abspath(os.path.normpath(raw)))
    return ("normalized", normalized)


def _vault_basename(path: Path) -> str:
    raw = os.fspath(path).rstrip("/\\")
    if not raw:
        return "Vault"
    return raw.replace("\\", "/").rsplit("/", 1)[-1] or "Vault"


def discover_obsidian_vaults(
    config_paths: Iterable[Path], *, home: Path | None = None
) -> VaultDiscoveryResult:
    """Read only injected Obsidian app configs and return exact Vault candidates."""

    injected_home = Path.home() if home is None else Path(home)
    configurations = tuple(
        sorted({Path(path) for path in config_paths}, key=lambda item: os.fspath(item))
    )
    diagnostics: list[Diagnostic] = []
    aggregated: dict[
        tuple[str, str | tuple[int, int]], dict[str, Any]
    ] = {}
    for config_path in configurations:
        payload, read_diagnostics = _read_obsidian_config(config_path)
        diagnostics.extend(read_diagnostics)
        if payload is None:
            continue
        try:
            parsed = json.loads(payload.decode("utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
            diagnostics.append(
                _diagnostic(
                    "invalid_obsidian_config",
                    "An Obsidian configuration was not valid UTF-8 JSON.",
                    config_path,
                )
            )
            continue
        if not isinstance(parsed, Mapping) or not isinstance(
            parsed.get("vaults"), Mapping
        ):
            diagnostics.append(
                _diagnostic(
                    "invalid_obsidian_config",
                    "An Obsidian configuration did not contain a vault mapping.",
                    config_path,
                )
            )
            continue
        vaults = parsed["vaults"]
        for entry in vaults.values():
            if not isinstance(entry, Mapping) or not isinstance(
                entry.get("path"), str
            ):
                diagnostics.append(
                    _diagnostic(
                        "invalid_obsidian_vault_entry",
                        "An Obsidian Vault entry did not contain a string path.",
                        config_path,
                    )
                )
                continue
            exact_path = _configured_vault_path(
                entry["path"], config_path=config_path, home=injected_home
            )
            if exact_path is None:
                diagnostics.append(
                    _diagnostic(
                        "invalid_obsidian_vault_entry",
                        "An Obsidian Vault entry contained an empty path.",
                        config_path,
                    )
                )
                continue
            identity = _vault_identity(exact_path)
            current = aggregated.setdefault(
                identity,
                {"paths": set(), "open": False, "source_configs": set()},
            )
            current["paths"].add(exact_path)
            current["open"] = current["open"] or entry.get("open") is True
            current["source_configs"].add(config_path)

    provisional: list[VaultCandidate] = []
    for item in aggregated.values():
        representative = min(item["paths"], key=lambda path: os.fspath(path))
        provisional.append(
            VaultCandidate(
                representative,
                _vault_basename(representative),
                item["open"],
                tuple(item["source_configs"]),
            )
        )

    label_counts: dict[str, int] = {}
    for candidate in provisional:
        folded = candidate.display_label.casefold()
        label_counts[folded] = label_counts.get(folded, 0) + 1
    candidates: list[VaultCandidate] = []
    for candidate in provisional:
        label = candidate.display_label
        if label_counts[label.casefold()] > 1:
            suffix = hashlib.sha256(
                os.fspath(candidate.path).encode("utf-8", "surrogatepass")
            ).hexdigest()[:8]
            label = sanitize_text(f"{label} ({suffix})", max_length=128)
        candidates.append(
            VaultCandidate(
                candidate.path,
                label,
                candidate.open,
                candidate.source_configs,
            )
        )
    candidates.sort(
        key=lambda item: (
            not item.open,
            item.display_label.casefold(),
            item.display_label,
            os.fspath(item.path),
        )
    )
    diagnostics.sort(
        key=lambda item: json.dumps(
            item.to_public_dict(), ensure_ascii=False, sort_keys=True
        )
    )
    return VaultDiscoveryResult(tuple(candidates), tuple(diagnostics))


def build_private_resolver_document(
    paths: StoragePaths, resolver_records: Iterable[ResolverRecordLike]
) -> dict[str, Any]:
    """Build the deterministic private schema containing every exact location."""

    entries = _resolver_entries(resolver_records)
    records = [
        {
            "resolver_id": entry.resolver_id,
            "exact_locations": list(entry.exact_locations),
        }
        for entry in entries
    ]
    storage = {
        "public_root": os.fspath(paths.public_root),
        "map_path": os.fspath(paths.map_path),
        "inventory_path": os.fspath(paths.inventory_path),
        "config_path": os.fspath(paths.config_path),
        "receipt_path": os.fspath(paths.receipt_path),
        "private_root": os.fspath(paths.private_root),
        "resolver_path": os.fspath(paths.resolver_path),
    }
    if paths.backup_root is not None:
        storage["backup_root"] = os.fspath(paths.backup_root)
    if paths.staging_root is not None:
        storage["staging_root"] = os.fspath(paths.staging_root)
    return {"schema_version": 1, "storage": storage, "records": records}


def _resolver_entries(
    resolver_records: Iterable[ResolverRecordLike],
) -> tuple[_ResolverEntry, ...]:
    by_id: dict[str, _ResolverEntry] = {}
    for record in resolver_records:
        resolver_id = getattr(record, "resolver_id", None)
        locations_value = getattr(record, "exact_locations", None)
        if not isinstance(resolver_id, str) or not resolver_id:
            raise ValueError("resolver_id must be a non-empty string")
        if isinstance(locations_value, (str, bytes)) or not isinstance(
            locations_value, Sequence
        ):
            raise TypeError("exact_locations must be a sequence of strings")
        locations = tuple(locations_value)
        if any(not isinstance(location, str) for location in locations):
            raise TypeError("exact_locations must contain strings")
        entry = _ResolverEntry(resolver_id, locations)
        previous = by_id.get(resolver_id)
        if previous is not None and previous.exact_locations != locations:
            raise ValueError(
                f"conflicting resolver records for resolver_id {resolver_id!r}"
            )
        by_id[resolver_id] = entry
    return tuple(by_id[resolver_id] for resolver_id in sorted(by_id))


def _artifact_value(
    artifacts: PublicArtifacts | Mapping[str, Any],
    canonical: str,
    aliases: tuple[str, ...],
) -> Any:
    if isinstance(artifacts, PublicArtifacts):
        return getattr(artifacts, canonical)
    for name in (canonical, *aliases):
        if name in artifacts:
            return artifacts[name]
    raise ValueError(f"artifacts is missing {canonical!r}")


def _coerce_artifacts(
    artifacts: PublicArtifacts | Mapping[str, Any]
) -> PublicArtifacts:
    if isinstance(artifacts, PublicArtifacts):
        return artifacts
    if not isinstance(artifacts, Mapping):
        raise TypeError("artifacts must be PublicArtifacts or a mapping")
    return PublicArtifacts(
        map_markdown=_artifact_value(
            artifacts, "map_markdown", ("map", MAP_FILENAME)
        ),
        inventory=_artifact_value(
            artifacts, "inventory", ("inventory_json", INVENTORY_FILENAME)
        ),
        config=_artifact_value(
            artifacts, "config", ("config_json", CONFIG_FILENAME)
        ),
        receipt_markdown=_artifact_value(
            artifacts, "receipt_markdown", ("receipt", RECEIPT_FILENAME)
        ),
    )


def _exact_values(
    paths: StoragePaths, records: Iterable[ResolverRecordLike]
) -> tuple[str, ...]:
    values = {
        os.fspath(paths.public_root),
        os.fspath(paths.map_path),
        os.fspath(paths.inventory_path),
        os.fspath(paths.config_path),
        os.fspath(paths.receipt_path),
        os.fspath(paths.private_root),
        os.fspath(paths.resolver_path),
    }
    if paths.backup_root is not None:
        values.add(os.fspath(paths.backup_root))
    if paths.staging_root is not None:
        values.add(os.fspath(paths.staging_root))
    for record in records:
        values.update(record.exact_locations)
    variants = set(values)
    for value in values:
        variants.add(value.replace("\\", "/"))
        variants.add(value.replace("/", "\\"))
    return tuple(sorted((value for value in variants if len(value) > 2), key=len, reverse=True))


def _redact_known_exact_values(value: str, exact_values: tuple[str, ...]) -> str:
    redacted = value
    for exact in exact_values:
        flags = re.IGNORECASE if _WINDOWS_ABSOLUTE_RE.match(exact) else 0
        redacted = re.sub(re.escape(exact), REDACTED_PATH, redacted, flags=flags)
    return redacted


def _sanitize_markdown_document(
    value: str, *, exact_values: tuple[str, ...]
) -> str:
    redacted = _redact_known_exact_values(value, exact_values)
    lines = redacted.splitlines()
    safe = "\n".join(sanitize_text(line) for line in lines)
    if value.endswith(("\n", "\r")):
        safe += "\n"
    return safe


def _parse_public_json(value: str | Mapping[str, Any], label: str) -> dict[str, Any]:
    if isinstance(value, str):
        try:
            parsed = json.loads(
                value,
                parse_constant=lambda constant: (_ for _ in ()).throw(
                    ValueError(f"non-finite JSON constant: {constant}")
                ),
            )
        except (json.JSONDecodeError, UnicodeError, ValueError) as error:
            raise ValueError(f"{label} must be valid JSON") from error
    else:
        parsed = dict(value)
    if not isinstance(parsed, Mapping):
        raise ValueError(f"{label} must be a JSON object")
    sanitized = sanitize(parsed)
    if not isinstance(sanitized, dict):  # pragma: no cover - Mapping stays dict
        raise ValueError(f"{label} must be a JSON object")
    return sanitized


def _json_bytes(value: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _assert_public_paths_redacted(
    payloads: Iterable[bytes], exact_values: tuple[str, ...]
) -> None:
    public = b"\n".join(payloads).decode("utf-8")
    for exact in exact_values:
        if exact in public:
            raise ValueError("an exact private path survived public sanitization")


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _target_snapshot(target: Path) -> _Snapshot:
    try:
        before = os.lstat(target)
    except FileNotFoundError:
        return _Snapshot(False, None, None)
    except OSError as error:
        raise ValueError(f"storage target could not be inspected: {target.name}") from error
    if stat.S_ISLNK(before.st_mode):
        raise ValueError(f"refusing symbolic-link target: {target.name}")
    if not stat.S_ISREG(before.st_mode):
        raise ValueError(f"storage target is not a regular file: {target.name}")
    flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NONBLOCK", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    try:
        descriptor = os.open(target, flags)
    except OSError as error:
        raise ValueError(f"storage target changed before opening: {target.name}") from error
    try:
        opened = os.fstat(descriptor)
        before_evidence = (
            before.st_dev,
            before.st_ino,
            before.st_mode,
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
        )
        opened_evidence = (
            opened.st_dev,
            opened.st_ino,
            opened.st_mode,
            opened.st_size,
            opened.st_mtime_ns,
            opened.st_ctime_ns,
        )
        if not stat.S_ISREG(opened.st_mode) or opened_evidence != before_evidence:
            raise ValueError(f"storage target changed while opening: {target.name}")
        if opened.st_size > MAX_STORAGE_TARGET_BYTES:
            raise ValueError(f"storage target exceeds the read limit: {target.name}")
        chunks: list[bytes] = []
        total = 0
        while total <= MAX_STORAGE_TARGET_BYTES:
            chunk = os.read(
                descriptor,
                min(_READ_CHUNK_BYTES, MAX_STORAGE_TARGET_BYTES + 1 - total),
            )
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
        if total > MAX_STORAGE_TARGET_BYTES:
            raise ValueError(f"storage target exceeds the read limit: {target.name}")
        after = os.fstat(descriptor)
        after_evidence = (
            after.st_dev,
            after.st_ino,
            after.st_mode,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        )
        if after_evidence != opened_evidence or total != opened.st_size:
            raise ValueError(f"storage target changed while reading: {target.name}")
        return _Snapshot(
            True,
            b"".join(chunks),
            stat.S_IMODE(opened.st_mode),
            opened.st_dev,
            opened.st_ino,
            opened.st_size,
            opened.st_mtime_ns,
            opened.st_ctime_ns,
        )
    finally:
        os.close(descriptor)


def _prepare_root(root: Path) -> None:
    try:
        metadata = os.lstat(root)
    except FileNotFoundError:
        root.mkdir(parents=True, mode=0o700)
        metadata = os.lstat(root)
    if stat.S_ISLNK(metadata.st_mode):
        raise ValueError("refusing symbolic-link storage root")
    if not stat.S_ISDIR(metadata.st_mode):
        raise ValueError("storage root is not a directory")


def _fsync_directory(directory: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_DIRECTORY", 0)
    try:
        descriptor = os.open(directory, flags)
    except OSError as error:
        if error.errno in _IGNORABLE_FSYNC_ERRORS:
            return
        raise
    try:
        try:
            os.fsync(descriptor)
        except OSError as error:
            if error.errno not in _IGNORABLE_FSYNC_ERRORS:
                raise
    finally:
        os.close(descriptor)


def _write_file_fsynced(path: Path, payload: bytes, mode: int) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0)
    descriptor = os.open(path, flags, mode)
    try:
        offset = 0
        while offset < len(payload):
            written = os.write(descriptor, payload[offset:])
            if written <= 0:
                raise OSError("short storage write")
            offset += written
        os.fchmod(descriptor, mode)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _stage_target(stage_directory: Path, target: _PreparedTarget) -> Path:
    stage_path = stage_directory / target.target.name
    _write_file_fsynced(stage_path, target.payload, target.mode)
    verified = stage_path.read_bytes()
    if _sha256(verified) != target.expected_hash:
        raise OSError(f"staged hash mismatch for {target.label}")
    if target.json_document:
        json.loads(verified.decode("utf-8"))
    return stage_path


def _restore_snapshot(target: Path, snapshot: _Snapshot) -> None:
    if not snapshot.existed:
        try:
            metadata = os.lstat(target)
        except FileNotFoundError:
            return
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            raise RuntimeError(f"unsafe rollback target: {target.name}")
        target.unlink()
        _fsync_directory(target.parent)
        return
    if snapshot.payload is None or snapshot.mode is None:  # pragma: no cover
        raise RuntimeError("invalid rollback snapshot")
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".capability-rollback-", dir=target.parent
    )
    temporary = Path(temporary_name)
    try:
        offset = 0
        while offset < len(snapshot.payload):
            written = os.write(descriptor, snapshot.payload[offset:])
            if written <= 0:
                raise OSError("short rollback write")
            offset += written
        os.fchmod(descriptor, snapshot.mode)
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        os.replace(temporary, target)
        os.chmod(target, snapshot.mode, follow_symlinks=False)
        _fsync_directory(target.parent)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def write_storage_bundle(
    paths: StoragePaths,
    artifacts: PublicArtifacts | Mapping[str, Any],
    resolver_records: Iterable[ResolverRecordLike],
    failure_injector: Callable[[str, Path], None] | None = None,
) -> StorageWriteResult:
    """Atomically replace a complete bundle and roll back every caught failure.

    ``failure_injector`` is a test/host hook called with the artifact label and
    stable target immediately before each changed target is replaced.
    """

    if not isinstance(paths, StoragePaths):
        raise TypeError("paths must be a StoragePaths value")
    public_artifacts = _coerce_artifacts(artifacts)
    records = _resolver_entries(resolver_records)

    exact_values = _exact_values(paths, records)
    map_payload = _sanitize_markdown_document(
        public_artifacts.map_markdown, exact_values=exact_values
    ).encode("utf-8")
    inventory_payload = _json_bytes(
        _parse_public_json(public_artifacts.inventory, "inventory")
    )
    config_payload = _json_bytes(
        _parse_public_json(public_artifacts.config, "config")
    )
    receipt_payload = _sanitize_markdown_document(
        public_artifacts.receipt_markdown, exact_values=exact_values
    ).encode("utf-8")
    private_document = build_private_resolver_document(paths, records)
    resolver_payload = _json_bytes(private_document)
    _assert_public_paths_redacted(
        (map_payload, inventory_payload, config_payload, receipt_payload),
        exact_values,
    )

    raw_targets = (
        ("map", paths.map_path, map_payload, False),
        ("inventory", paths.inventory_path, inventory_payload, True),
        ("config", paths.config_path, config_payload, True),
        ("receipt", paths.receipt_path, receipt_payload, False),
        ("resolver", paths.resolver_path, resolver_payload, True),
    )
    hashes = {label: _sha256(payload) for label, _, payload, _ in raw_targets}
    generation_payload = json.dumps(
        hashes, sort_keys=True, separators=(",", ":")
    ).encode("ascii")
    generation_id = f"gen_{hashlib.sha256(generation_payload).hexdigest()[:24]}"

    _prepare_root(paths.public_root)
    _prepare_root(paths.private_root)
    if paths.staging_root is not None:
        if not _is_within(paths.staging_root, paths.public_root):
            raise ValueError("staging_root must be inside public_root")
        _prepare_root(paths.staging_root)
    for _, target, _, _ in raw_targets:
        if target.parent not in {paths.public_root, paths.private_root}:
            raise ValueError("storage target escaped its declared root")

    snapshots = {target: _target_snapshot(target) for _, target, _, _ in raw_targets}
    prepared: list[_PreparedTarget] = []
    for label, target, payload, json_document in raw_targets:
        snapshot = snapshots[target]
        desired_mode = (
            0o600
            if label == "resolver"
            else snapshot.mode if snapshot.mode is not None else 0o644
        )
        needs_mode_change = (
            label == "resolver"
            and snapshot.mode is not None
            and snapshot.mode != 0o600
        )
        if snapshot.payload == payload and not needs_mode_change:
            continue
        prepared.append(
            _PreparedTarget(
                label,
                target,
                payload,
                hashes[label],
                desired_mode,
                json_document,
            )
        )

    if not prepared:
        receipt_info = {
            "schema_version": 1,
            "generation_id": generation_id,
            "hashes": dict(sorted(hashes.items())),
        }
        return StorageWriteResult(generation_id, hashes, (), receipt_info)

    public_stage_parent = paths.staging_root or paths.public_root
    with tempfile.TemporaryDirectory(
        prefix=".capability-stage-", dir=public_stage_parent
    ) as public_temporary, tempfile.TemporaryDirectory(
        prefix=".capability-stage-", dir=paths.private_root
    ) as private_temporary:
        public_stage = Path(public_temporary)
        private_stage = Path(private_temporary)
        staged: dict[str, Path] = {}
        for target in prepared:
            stage_directory = (
                private_stage if target.label == "resolver" else public_stage
            )
            staged[target.label] = _stage_target(stage_directory, target)
        _fsync_directory(public_stage)
        _fsync_directory(private_stage)

        replaced_targets: list[_PreparedTarget] = []
        try:
            for target in prepared:
                if failure_injector is not None:
                    failure_injector(target.label, target.target)
                if _target_snapshot(target.target) != snapshots[target.target]:
                    raise RuntimeError(
                        f"storage target changed concurrently: {target.label}"
                    )
                os.replace(staged[target.label], target.target)
                replaced_targets.append(target)
                os.chmod(target.target, target.mode, follow_symlinks=False)
                _fsync_directory(target.target.parent)
        except BaseException as original_error:
            rollback_errors: list[BaseException] = []
            for target in reversed(replaced_targets):
                try:
                    _restore_snapshot(target.target, snapshots[target.target])
                except BaseException as rollback_error:
                    rollback_errors.append(rollback_error)
            if rollback_errors:
                raise RuntimeError(
                    "storage bundle failed and rollback was incomplete"
                ) from original_error
            raise

    if os.name != "nt":
        os.chmod(paths.resolver_path, 0o600, follow_symlinks=False)
    _fsync_directory(paths.public_root)
    _fsync_directory(paths.private_root)
    receipt_info = {
        "schema_version": 1,
        "generation_id": generation_id,
        "hashes": dict(sorted(hashes.items())),
    }
    return StorageWriteResult(
        generation_id,
        hashes,
        tuple(target.target for target in prepared),
        receipt_info,
    )


__all__ = [
    "CONFIG_FILENAME",
    "INVENTORY_FILENAME",
    "MAP_FILENAME",
    "MAX_OBSIDIAN_CONFIG_BYTES",
    "PublicArtifacts",
    "RECEIPT_FILENAME",
    "RESOLVER_FILENAME",
    "StoragePaths",
    "StorageWriteResult",
    "VaultCandidate",
    "VaultDiscoveryResult",
    "build_private_resolver_document",
    "default_storage_paths",
    "discover_obsidian_vaults",
    "write_storage_bundle",
]

"""Safe public capability-map storage and a private exact-path resolver."""

from __future__ import annotations

import errno
import hashlib
import inspect
import json
import os
import platform
import re
import secrets
import stat
from collections import deque
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from contextlib import contextmanager
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
try:
    _REPLACE_PARAMETERS = inspect.signature(os.replace).parameters
except (TypeError, ValueError):  # pragma: no cover - unusual Python ports
    _REPLACE_PARAMETERS = {}
_REPLACE_SUPPORTS_DIR_FD = {
    "src_dir_fd",
    "dst_dir_fd",
}.issubset(_REPLACE_PARAMETERS)
_DIR_FD_BACKEND_SUPPORTED = bool(
    getattr(os, "O_DIRECTORY", 0)
    and getattr(os, "O_NOFOLLOW", 0)
    and os.open in os.supports_dir_fd
    and os.stat in os.supports_dir_fd
    and os.mkdir in os.supports_dir_fd
    and os.unlink in os.supports_dir_fd
    and os.rmdir in os.supports_dir_fd
    and os.rename in os.supports_dir_fd
    and os.link in os.supports_dir_fd
    and os.listdir in os.supports_fd
)
_WINDOWS_REPARSE_POINT = 0x400


def _is_link_like(metadata: os.stat_result) -> bool:
    """Treat Windows junctions and other reparse points like symbolic links."""

    return bool(
        stat.S_ISLNK(metadata.st_mode)
        or int(getattr(metadata, "st_file_attributes", 0))
        & _WINDOWS_REPARSE_POINT
    )


def _windows_portable_backend_available() -> bool:
    """Return whether the best-effort path backend is available on this host."""

    return os.name == "nt"


@dataclass(frozen=True)
class AncestorEvidence:
    """Stable identity captured for one existing physical directory."""

    path: Path = field(repr=False)
    device: int
    inode: int
    ctime_ns: int
    mode: int


@dataclass(frozen=True)
class RootEvidence:
    """Canonical root plus the existing ancestry that established its identity."""

    resolved_path: Path = field(repr=False)
    existing_ancestors: tuple[AncestorEvidence, ...] = field(repr=False)


def _capture_root_evidence(path: Path) -> RootEvidence:
    resolved = _resolve_storage_path(path, reject_root_symlink=True)
    current = Path(resolved.anchor)
    ancestors: list[AncestorEvidence] = []
    parts = resolved.parts[1:]
    paths = [current]
    for part in parts:
        current = current / part
        paths.append(current)
    for candidate in paths:
        try:
            metadata = os.lstat(candidate)
        except FileNotFoundError:
            break
        except OSError as error:
            raise ValueError("storage ancestry could not be inspected") from error
        if _is_link_like(metadata) or not stat.S_ISDIR(metadata.st_mode):
            raise ValueError("storage ancestry must contain only physical directories")
        ancestors.append(
            AncestorEvidence(
                candidate,
                metadata.st_dev,
                metadata.st_ino,
                metadata.st_ctime_ns,
                metadata.st_mode,
            )
        )
    return RootEvidence(resolved, tuple(ancestors))


def _validate_root_evidence(evidence: RootEvidence) -> Path:
    try:
        resolved = _resolve_storage_path(
            evidence.resolved_path, reject_root_symlink=True
        )
    except ValueError as error:
        raise ValueError("storage root ancestry changed") from error
    if resolved != evidence.resolved_path:
        raise ValueError("storage root resolved to a different physical location")
    for ancestor in evidence.existing_ancestors:
        try:
            current = os.lstat(ancestor.path)
        except OSError as error:
            raise ValueError("storage root ancestry changed") from error
        if (
            _is_link_like(current)
            or not stat.S_ISDIR(current.st_mode)
            or current.st_dev != ancestor.device
            or current.st_ino != ancestor.inode
            or stat.S_IFMT(current.st_mode) != stat.S_IFMT(ancestor.mode)
        ):
            raise ValueError("storage root ancestry changed")
    return resolved


def _validate_storage_roots(
    paths: StoragePaths,
    *,
    public_operation_evidence: RootEvidence | None = None,
    private_operation_evidence: RootEvidence | None = None,
) -> None:
    public_evidence = paths.public_root_evidence
    private_evidence = paths.private_root_evidence
    if public_evidence is None or private_evidence is None:  # pragma: no cover
        raise ValueError("StoragePaths is missing root evidence")
    public_root = _validate_root_evidence(public_evidence)
    private_root = _validate_root_evidence(private_evidence)
    if public_operation_evidence is not None:
        if _validate_root_evidence(public_operation_evidence) != public_root:
            raise ValueError("public storage root changed during the write")
    if private_operation_evidence is not None:
        if _validate_root_evidence(private_operation_evidence) != private_root:
            raise ValueError("private storage root changed during the write")
    if paths.vault_root is not None:
        vault_evidence = paths.vault_root_evidence
        if vault_evidence is None:  # pragma: no cover
            raise ValueError("StoragePaths is missing Vault evidence")
        vault_root = _validate_root_evidence(vault_evidence)
        if not _is_within(public_root, vault_root):
            raise ValueError("public storage escaped the selected Vault")
        if _is_within(private_root, vault_root) or _is_within(
            private_root, public_root
        ):
            raise ValueError("private resolver storage entered public storage")


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
    vault_root: Path | None = field(default=None, repr=False)
    public_root_evidence: RootEvidence | None = field(
        default=None, repr=False, compare=False
    )
    private_root_evidence: RootEvidence | None = field(
        default=None, repr=False, compare=False
    )
    vault_root_evidence: RootEvidence | None = field(
        default=None, repr=False, compare=False
    )

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
        for name in ("backup_root", "staging_root", "vault_root"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, Path(value))

        staging_relative: Path | None = None
        if self.staging_root is not None:
            if self.staging_root.is_absolute():
                try:
                    staging_relative = self.staging_root.relative_to(self.public_root)
                except ValueError as error:
                    raise ValueError(
                        "staging_root must remain inside public_root"
                    ) from error
            else:
                staging_relative = self.staging_root
            if (
                not staging_relative.parts
                or any(part in {"", ".", ".."} for part in staging_relative.parts)
            ):
                raise ValueError("staging_root must contain safe relative components")
            object.__setattr__(
                self, "staging_root", self.public_root / staging_relative
            )

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
        for evidence_name, root_name in (
            ("public_root_evidence", "public_root"),
            ("private_root_evidence", "private_root"),
        ):
            root = getattr(self, root_name)
            evidence = getattr(self, evidence_name)
            if evidence is None:
                evidence = _capture_root_evidence(root)
                object.__setattr__(self, evidence_name, evidence)
            elif not isinstance(evidence, RootEvidence):
                raise TypeError(f"{evidence_name} must be RootEvidence")
            if evidence.resolved_path != root:
                object.__setattr__(self, root_name, evidence.resolved_path)
                if root_name == "public_root":
                    object.__setattr__(self, "map_path", evidence.resolved_path / MAP_FILENAME)
                    object.__setattr__(
                        self,
                        "inventory_path",
                        evidence.resolved_path / INVENTORY_FILENAME,
                    )
                    object.__setattr__(
                        self, "config_path", evidence.resolved_path / CONFIG_FILENAME
                    )
                    object.__setattr__(
                        self, "receipt_path", evidence.resolved_path / RECEIPT_FILENAME
                    )
                else:
                    object.__setattr__(
                        self, "resolver_path", evidence.resolved_path / RESOLVER_FILENAME
                    )
        if staging_relative is not None:
            object.__setattr__(
                self, "staging_root", self.public_root / staging_relative
            )
        if self.vault_root is not None:
            vault_evidence = self.vault_root_evidence
            if vault_evidence is None:
                vault_evidence = _capture_root_evidence(self.vault_root)
                object.__setattr__(self, "vault_root_evidence", vault_evidence)
            elif not isinstance(vault_evidence, RootEvidence):
                raise TypeError("vault_root_evidence must be RootEvidence")
            object.__setattr__(self, "vault_root", vault_evidence.resolved_path)


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
    cleanup_recovery_paths: tuple[Path, ...] = ()


@dataclass(frozen=True)
class StorageExpectedSnapshot:
    """Plan-time state for one stable target under its captured parent."""

    target: Path = field(repr=False)
    existed: bool
    sha256: str | None
    mode: int | None
    parent_evidence: RootEvidence = field(repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "target", Path(self.target))
        if self.existed != (self.sha256 is not None and self.mode is not None):
            raise ValueError("storage expected snapshot fields are inconsistent")


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
class _CommittedEvidence:
    device: int
    inode: int
    size: int
    ctime_ns: int
    sha256: str


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


def _safe_staging_subdirectory(value: str | os.PathLike[str]) -> Path:
    raw = os.fspath(value)
    normalized = raw.replace("\\", "/")
    if (
        not normalized
        or normalized.startswith("/")
        or Path(raw).is_absolute()
        or PureWindowsPath(raw).is_absolute()
        or bool(PureWindowsPath(raw).drive)
    ):
        raise ValueError("staging_root must be relative to public_root")
    parts = normalized.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ValueError("staging_root must contain safe relative components")
    if any(part.casefold() == ".env" for part in parts):
        raise ValueError("staging_root must not traverse .env")
    return Path(*parts)


def default_storage_root_text(
    *,
    platform_name: str | None = None,
    environ: Mapping[str, str] | None = None,
    home: str | os.PathLike[str] | None = None,
) -> str:
    """Return the platform default as text without host path resolution."""

    operating_system = platform.system() if platform_name is None else platform_name
    environment = os.environ if environ is None else environ
    home_text = os.fspath(Path.home() if home is None else home)
    if operating_system.casefold().startswith("win"):
        local_app_data = _environment_value(
            environment, "LOCALAPPDATA", case_insensitive=True
        )
        data_home = (
            PureWindowsPath(local_app_data)
            if local_app_data
            else PureWindowsPath(home_text) / "AppData" / "Local"
        )
        return str(data_home / "Vantasma" / "Agent能力地图")
    pure_home = PurePosixPath(home_text)
    if operating_system.casefold() in {"darwin", "mac", "macos"}:
        return str(
            pure_home
            / "Library"
            / "Application Support"
            / "Vantasma"
            / "Agent能力地图"
        )
    xdg_data_home = _environment_value(
        environment, "XDG_DATA_HOME", case_insensitive=False
    )
    data_home = (
        PurePosixPath(xdg_data_home)
        if xdg_data_home
        else pure_home / ".local" / "share"
    )
    return str(data_home / "vantasma" / "agent-capabilities")


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
        if not _is_link_like(metadata):
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
    if windows and os.name != "nt":
        raise ValueError(
            "path_semantics_unavailable: Windows storage paths require a Windows host"
        )

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
        None if staging_root is None else _safe_staging_subdirectory(staging_root)
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
        vault_root=None if vault_path is None else resolved_vault,
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

    if _is_link_like(before):
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
        | getattr(os, "O_BINARY", 0)
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
    if _is_link_like(before):
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


def capture_storage_expected_state(
    paths: StoragePaths,
) -> dict[str, StorageExpectedSnapshot]:
    """Capture hash-bound target state without creating storage directories."""

    if not isinstance(paths, StoragePaths):
        raise TypeError("paths must be a StoragePaths value")
    targets = {
        "map": paths.map_path,
        "inventory": paths.inventory_path,
        "config": paths.config_path,
        "receipt": paths.receipt_path,
        "resolver": paths.resolver_path,
    }
    result: dict[str, StorageExpectedSnapshot] = {}
    for label, target in targets.items():
        snapshot = _target_snapshot(target)
        parent_evidence = (
            paths.private_root_evidence
            if label == "resolver"
            else paths.public_root_evidence
        )
        if parent_evidence is None:  # pragma: no cover - StoragePaths enforces it
            raise ValueError("StoragePaths is missing root evidence")
        result[label] = StorageExpectedSnapshot(
            target,
            snapshot.existed,
            None if snapshot.payload is None else _sha256(snapshot.payload),
            snapshot.mode,
            parent_evidence,
        )
    return result


def _matches_expected_snapshot(
    snapshot: _Snapshot, expected: StorageExpectedSnapshot
) -> bool:
    if snapshot.existed != expected.existed:
        return False
    if not snapshot.existed:
        return True
    return bool(
        snapshot.payload is not None
        and snapshot.mode == expected.mode
        and _sha256(snapshot.payload) == expected.sha256
    )


def _validated_expected_state(
    paths: StoragePaths,
    expected_state: Mapping[str, StorageExpectedSnapshot] | None,
) -> dict[str, StorageExpectedSnapshot] | None:
    if expected_state is None:
        return None
    expected_labels = {"map", "inventory", "config", "receipt", "resolver"}
    if set(expected_state) != expected_labels:
        raise ValueError("storage expected state must contain every target")
    stable_targets = {
        "map": paths.map_path,
        "inventory": paths.inventory_path,
        "config": paths.config_path,
        "receipt": paths.receipt_path,
        "resolver": paths.resolver_path,
    }
    validated: dict[str, StorageExpectedSnapshot] = {}
    for label in sorted(expected_labels):
        item = expected_state[label]
        if not isinstance(item, StorageExpectedSnapshot):
            raise TypeError("storage expected state has an invalid snapshot")
        if item.target != stable_targets[label]:
            raise ValueError("storage expected state target mismatch")
        if _validate_root_evidence(item.parent_evidence) != item.target.parent:
            raise ValueError("storage expected state parent mismatch")
        validated[label] = item
    return validated


def _prepare_root(root: Path) -> None:
    try:
        metadata = os.lstat(root)
    except FileNotFoundError:
        root.mkdir(parents=True, mode=0o700)
        metadata = os.lstat(root)
    if _is_link_like(metadata):
        raise ValueError("refusing symbolic-link storage root")
    if not stat.S_ISDIR(metadata.st_mode):
        raise ValueError("storage root is not a directory")


def _secure_storage_backend_available() -> bool:
    return bool(
        _REPLACE_SUPPORTS_DIR_FD
        and _DIR_FD_BACKEND_SUPPORTED
        and callable(getattr(os, "fchmod", None))
    )


def _prepare_root_portable(evidence: RootEvidence) -> Path:
    """Create a captured root one component at a time without following links."""

    resolved = _validate_root_evidence(evidence)
    if not evidence.existing_ancestors:
        raise ValueError("storage root has no existing physical ancestor")
    current = evidence.existing_ancestors[-1].path
    try:
        relative = resolved.relative_to(current)
    except ValueError as error:  # pragma: no cover - evidence construction guarantees
        raise ValueError("storage root escaped its captured ancestor") from error
    for component in relative.parts:
        current = current / component
        try:
            metadata = os.lstat(current)
        except FileNotFoundError:
            current.mkdir(mode=0o700)
            metadata = os.lstat(current)
        if _is_link_like(metadata) or not stat.S_ISDIR(metadata.st_mode):
            raise ValueError("storage ancestry must contain only physical directories")
    return resolved


def _write_file_fsynced_portable(path: Path, payload: bytes, mode: int) -> None:
    """Create one new regular file, fsync it, and never replace a target."""

    flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_BINARY", 0)
    )
    descriptor = os.open(path, flags, mode)
    try:
        offset = 0
        while offset < len(payload):
            written = os.write(descriptor, payload[offset:])
            if written <= 0:
                raise OSError("short portable storage write")
            offset += written
        if os.name != "nt" and callable(getattr(os, "fchmod", None)):
            os.fchmod(descriptor, mode)
        os.fsync(descriptor)
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise OSError("portable storage stage is not a regular file")
    finally:
        os.close(descriptor)


def _move_no_replace_portable(source: Path, destination: Path) -> None:
    """Atomically move a file without clobbering an existing destination."""

    if os.name == "nt":
        os.rename(source, destination)
        return
    os.link(source, destination, follow_symlinks=False)
    os.unlink(source)


def _matches_committed_portable(
    snapshot: _Snapshot, expected_hash: str, expected_size: int
) -> bool:
    return bool(
        snapshot.existed
        and snapshot.payload is not None
        and snapshot.size == expected_size
        and _sha256(snapshot.payload) == expected_hash
    )


def _same_snapshot_portable(left: _Snapshot, right: _Snapshot) -> bool:
    if left.existed != right.existed:
        return False
    if not left.existed:
        return True
    return bool(
        left.payload == right.payload
        and left.mode == right.mode
        and left.device == right.device
        and left.inode == right.inode
        and left.size == right.size
    )


def _write_storage_bundle_portable(
    paths: StoragePaths,
    raw_targets: tuple[tuple[str, Path, bytes, bool], ...],
    hashes: Mapping[str, str],
    generation_id: str,
    *,
    expected_targets: Mapping[str, StorageExpectedSnapshot] | None,
    failure_injector: Callable[[str, Path], None] | None,
) -> StorageWriteResult:
    """Best-effort Windows transaction using same-directory atomic renames."""

    public_evidence = paths.public_root_evidence
    private_evidence = paths.private_root_evidence
    if public_evidence is None or private_evidence is None:  # pragma: no cover
        raise ValueError("StoragePaths is missing root evidence")
    _validate_storage_roots(paths)
    _prepare_root_portable(public_evidence)
    _prepare_root_portable(private_evidence)
    public_operation_evidence = _capture_root_evidence(paths.public_root)
    private_operation_evidence = _capture_root_evidence(paths.private_root)
    _validate_storage_roots(
        paths,
        public_operation_evidence=public_operation_evidence,
        private_operation_evidence=private_operation_evidence,
    )

    snapshots = {target: _target_snapshot(target) for _, target, _, _ in raw_targets}
    if expected_targets is not None:
        for label, target, _, _ in raw_targets:
            if not _matches_expected_snapshot(snapshots[target], expected_targets[label]):
                raise RuntimeError(f"stale storage plan: {label}")

    prepared: list[_PreparedTarget] = []
    for label, target, payload, json_document in raw_targets:
        snapshot = snapshots[target]
        desired_mode = (
            0o600
            if label == "resolver"
            else snapshot.mode if snapshot.mode is not None else 0o644
        )
        needs_mode_change = bool(
            os.name != "nt"
            and label == "resolver"
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

    staged: dict[str, Path] = {}
    claims: dict[str, Path] = {}
    cleanup_recovery_paths: list[Path] = []
    committed: list[_PreparedTarget] = []
    commit_complete = False
    try:
        for target in prepared:
            stage = target.target.parent / (
                f".vantasma-storage-stage-{secrets.token_hex(12)}"
            )
            _write_file_fsynced_portable(stage, target.payload, target.mode)
            verified = _target_snapshot(stage)
            if verified.payload != target.payload:
                raise OSError(f"portable staged hash mismatch for {target.label}")
            if target.json_document:
                json.loads(target.payload.decode("utf-8"))
            staged[target.label] = stage

        for target in prepared:
            _validate_storage_roots(
                paths,
                public_operation_evidence=public_operation_evidence,
                private_operation_evidence=private_operation_evidence,
            )
            current = _target_snapshot(target.target)
            if expected_targets is not None and not _matches_expected_snapshot(
                current, expected_targets[target.label]
            ):
                raise RuntimeError(f"stale storage plan: {target.label}")
            if not _same_snapshot_portable(current, snapshots[target.target]):
                raise RuntimeError(
                    f"storage target changed concurrently: {target.label}"
                )
            if failure_injector is not None:
                failure_injector(target.label, target.target)
            if current.existed:
                claim = target.target.parent / (
                    f".vantasma-storage-claim-{secrets.token_hex(12)}"
                )
                _move_no_replace_portable(target.target, claim)
                claims[target.label] = claim
                claimed = _target_snapshot(claim)
                if not _same_snapshot_portable(claimed, current):
                    raise RuntimeError(
                        f"storage target changed concurrently: {target.label}"
                    )
            _move_no_replace_portable(staged.pop(target.label), target.target)
            after = _target_snapshot(target.target)
            if not _matches_committed_portable(
                after, target.expected_hash, len(target.payload)
            ):
                raise OSError(f"committed hash mismatch for {target.label}")
            committed.append(target)

        commit_complete = True
        for label, claim in tuple(claims.items()):
            try:
                os.unlink(claim)
            except FileNotFoundError:
                claims.pop(label, None)
            except OSError:
                try:
                    os.lstat(claim)
                except (FileNotFoundError, OSError):
                    claims.pop(label, None)
                else:
                    cleanup_recovery_paths.append(claim)
            else:
                claims.pop(label, None)
    except BaseException as original_error:
        if commit_complete:
            raise
        rollback_conflicts: list[str] = []
        rollback_errors: list[BaseException] = []
        for target in reversed(committed):
            try:
                current = _target_snapshot(target.target)
                if not _matches_committed_portable(
                    current, target.expected_hash, len(target.payload)
                ):
                    rollback_conflicts.append(target.label)
                    continue
                os.unlink(target.target)
                claim = claims.pop(target.label, None)
                if claim is not None:
                    _move_no_replace_portable(claim, target.target)
            except BaseException as rollback_error:
                rollback_errors.append(rollback_error)
        for label, claim in tuple(claims.items()):
            target = next(item for item in prepared if item.label == label)
            try:
                if not target.target.exists():
                    _move_no_replace_portable(claim, target.target)
                    claims.pop(label, None)
                else:
                    rollback_conflicts.append(label)
            except BaseException as rollback_error:
                rollback_errors.append(rollback_error)
        details: list[str] = []
        if rollback_conflicts:
            details.append("rollback_conflict: " + ", ".join(rollback_conflicts))
        if rollback_errors:
            details.append("rollback_incomplete")
        if details:
            raise RuntimeError("storage bundle failed; " + "; ".join(details)) from original_error
        raise
    finally:
        for stage in staged.values():
            try:
                os.unlink(stage)
            except FileNotFoundError:
                pass

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
        tuple(cleanup_recovery_paths),
    )


def _fsync_directory_fd(descriptor: int) -> None:
    try:
        os.fsync(descriptor)
    except OSError as error:
        if error.errno not in _IGNORABLE_FSYNC_ERRORS:
            raise


def _write_file_fsynced_at(
    parent_fd: int, name: str, payload: bytes, mode: int
) -> None:
    flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_CLOEXEC", 0)
        | os.O_NOFOLLOW
        | getattr(os, "O_BINARY", 0)
    )
    descriptor = os.open(name, flags, mode, dir_fd=parent_fd)
    try:
        offset = 0
        while offset < len(payload):
            written = os.write(descriptor, payload[offset:])
            if written <= 0:
                raise OSError("short storage write")
            offset += written
        os.fchmod(descriptor, mode)
        os.fsync(descriptor)
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):  # pragma: no cover - open created it
            raise OSError("staged target is not a regular file")
    finally:
        os.close(descriptor)


def _target_snapshot_at(parent_fd: int, name: str) -> _Snapshot:
    try:
        before = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError:
        return _Snapshot(False, None, None)
    except OSError as error:
        raise ValueError(f"storage target could not be inspected: {name}") from error
    if _is_link_like(before):
        raise ValueError(f"refusing symbolic-link target: {name}")
    if not stat.S_ISREG(before.st_mode):
        raise ValueError(f"storage target is not a regular file: {name}")
    flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NONBLOCK", 0)
        | os.O_NOFOLLOW
    )
    try:
        descriptor = os.open(name, flags, dir_fd=parent_fd)
    except OSError as error:
        raise ValueError(f"storage target changed before opening: {name}") from error
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
            raise ValueError(f"storage target changed while opening: {name}")
        if opened.st_size > MAX_STORAGE_TARGET_BYTES:
            raise ValueError(f"storage target exceeds the read limit: {name}")
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
            raise ValueError(f"storage target exceeds the read limit: {name}")
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
            raise ValueError(f"storage target changed while reading: {name}")
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


def _stage_target_at(parent_fd: int, target: _PreparedTarget) -> str:
    name = target.target.name
    _write_file_fsynced_at(parent_fd, name, target.payload, target.mode)
    verified = _target_snapshot_at(parent_fd, name)
    if verified.payload is None or _sha256(verified.payload) != target.expected_hash:
        raise OSError(f"staged hash mismatch for {target.label}")
    if target.json_document:
        json.loads(verified.payload.decode("utf-8"))
    return name


def _commit_staged_no_replace_at(
    *,
    stage_fd: int,
    staged_name: str,
    destination_fd: int,
    destination_name: str,
    expected: _Snapshot,
) -> None:
    """Claim an old target, verify it, then link the staged inode no-clobber."""

    def restore_claim(claim: str) -> None:
        try:
            os.link(
                claim,
                destination_name,
                src_dir_fd=destination_fd,
                dst_dir_fd=destination_fd,
                follow_symlinks=False,
            )
        except FileExistsError:
            return
        os.unlink(claim, dir_fd=destination_fd)

    claim_name: str | None = None
    if expected.existed:
        claim_name = f".capability-claim-{secrets.token_hex(12)}"
        os.rename(
            destination_name,
            claim_name,
            src_dir_fd=destination_fd,
            dst_dir_fd=destination_fd,
        )
        try:
            claimed = _target_snapshot_at(destination_fd, claim_name)
        except BaseException:
            restore_claim(claim_name)
            raise
        if not (
            claimed.existed
            and claimed.payload == expected.payload
            and claimed.mode == expected.mode
            and claimed.device == expected.device
            and claimed.inode == expected.inode
            and claimed.size == expected.size
        ):
            restore_claim(claim_name)
            raise RuntimeError(
                f"storage target changed concurrently: {destination_name}"
            )
    try:
        os.link(
            staged_name,
            destination_name,
            src_dir_fd=stage_fd,
            dst_dir_fd=destination_fd,
            follow_symlinks=False,
        )
    except BaseException:
        if claim_name is not None:
            restore_claim(claim_name)
        raise
    if claim_name is not None:
        os.unlink(claim_name, dir_fd=destination_fd)
    _fsync_directory_fd(destination_fd)


def _sync_committed_target_at(
    parent_fd: int,
    target: _PreparedTarget,
    staged: _Snapshot,
    committed_evidence: dict[str, _CommittedEvidence],
) -> None:
    name = target.target.name
    flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NONBLOCK", 0)
        | os.O_NOFOLLOW
    )
    descriptor = os.open(name, flags, dir_fd=parent_fd)
    try:
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_size != len(target.payload)
            or opened.st_dev != staged.device
            or opened.st_ino != staged.inode
        ):
            raise OSError(f"committed target identity mismatch for {target.label}")
        digest = hashlib.sha256()
        total = 0
        while total < opened.st_size:
            chunk = os.read(
                descriptor, min(_READ_CHUNK_BYTES, opened.st_size - total)
            )
            if not chunk:
                raise OSError(f"short committed read for {target.label}")
            digest.update(chunk)
            total += len(chunk)
        if digest.hexdigest() != target.expected_hash:
            raise OSError(f"committed hash mismatch for {target.label}")
        committed_evidence[target.label] = _CommittedEvidence(
            opened.st_dev,
            opened.st_ino,
            opened.st_size,
            opened.st_ctime_ns,
            digest.hexdigest(),
        )
        os.fchmod(descriptor, target.mode)
        after = os.fstat(descriptor)
        linked = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        if (
            after.st_dev != opened.st_dev
            or after.st_ino != opened.st_ino
            or after.st_size != opened.st_size
            or stat.S_IMODE(after.st_mode) != target.mode
            or linked.st_dev != after.st_dev
            or linked.st_ino != after.st_ino
        ):
            raise OSError(f"committed target changed for {target.label}")
        committed_evidence[target.label] = _CommittedEvidence(
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_ctime_ns,
            digest.hexdigest(),
        )
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    _fsync_directory_fd(parent_fd)


def _committed_evidence_from_snapshot(
    snapshot: _Snapshot,
) -> _CommittedEvidence | None:
    if (
        not snapshot.existed
        or snapshot.payload is None
        or snapshot.device is None
        or snapshot.inode is None
        or snapshot.size is None
        or snapshot.ctime_ns is None
    ):
        return None
    return _CommittedEvidence(
        snapshot.device,
        snapshot.inode,
        snapshot.size,
        snapshot.ctime_ns,
        _sha256(snapshot.payload),
    )


@contextmanager
def _directory_handle(
    root: Path, evidence: RootEvidence
) -> Iterator[int]:
    if not _secure_storage_backend_available():
        raise RuntimeError("secure_storage_backend_unavailable")
    flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | os.O_DIRECTORY
        | os.O_NOFOLLOW
    )
    descriptor = os.open(root, flags)
    try:
        opened = os.fstat(descriptor)
        root_identity = next(
            (
                ancestor
                for ancestor in reversed(evidence.existing_ancestors)
                if ancestor.path == root
            ),
            None,
        )
        if (
            root_identity is None
            or not stat.S_ISDIR(opened.st_mode)
            or opened.st_dev != root_identity.device
            or opened.st_ino != root_identity.inode
        ):
            raise ValueError("storage root changed while opening")
        yield descriptor
    finally:
        os.close(descriptor)


@contextmanager
def _relative_directory_handle(
    root_fd: int, relative: Path
) -> Iterator[int]:
    parts = tuple(part for part in relative.parts if part not in {"", "."})
    if any(part == ".." for part in parts):  # pragma: no cover - caller validates
        raise ValueError("storage staging path escaped its root")
    if not parts:
        yield root_fd
        return
    flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | os.O_DIRECTORY
        | os.O_NOFOLLOW
    )
    opened: list[int] = []
    parent_fd = root_fd
    try:
        for part in parts:
            try:
                descriptor = os.open(part, flags, dir_fd=parent_fd)
            except FileNotFoundError:
                try:
                    os.mkdir(part, 0o700, dir_fd=parent_fd)
                    _fsync_directory_fd(parent_fd)
                except FileExistsError:
                    pass
                try:
                    descriptor = os.open(part, flags, dir_fd=parent_fd)
                except OSError as error:
                    raise ValueError(
                        "storage staging path could not be opened safely"
                    ) from error
            except OSError as error:
                raise ValueError(
                    "storage staging path could not be opened safely"
                ) from error
            metadata = os.fstat(descriptor)
            if not stat.S_ISDIR(metadata.st_mode):  # pragma: no cover - O_DIRECTORY
                raise ValueError("storage staging path is not a directory")
            opened.append(descriptor)
            parent_fd = descriptor
        yield parent_fd
    finally:
        for descriptor in reversed(opened):
            os.close(descriptor)


def _cleanup_stage_at(
    parent_fd: int,
    stage_name: str,
    stage_fd: int,
    stage_identity: tuple[int, int],
) -> None:
    for name in os.listdir(stage_fd):
        metadata = os.stat(name, dir_fd=stage_fd, follow_symlinks=False)
        if stat.S_ISDIR(metadata.st_mode):
            raise RuntimeError("unexpected directory inside storage staging")
        os.unlink(name, dir_fd=stage_fd)
    _fsync_directory_fd(stage_fd)
    try:
        current = os.stat(stage_name, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError as error:
        raise RuntimeError("storage staging directory changed") from error
    if (
        _is_link_like(current)
        or not stat.S_ISDIR(current.st_mode)
        or (current.st_dev, current.st_ino) != stage_identity
    ):
        raise RuntimeError("storage staging directory changed")
    os.rmdir(stage_name, dir_fd=parent_fd)
    _fsync_directory_fd(parent_fd)


@contextmanager
def _stage_directory_at(parent_fd: int) -> Iterator[int]:
    stage_name = f".capability-stage-{secrets.token_hex(12)}"
    os.mkdir(stage_name, 0o700, dir_fd=parent_fd)
    flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | os.O_DIRECTORY
        | os.O_NOFOLLOW
    )
    stage_fd = -1
    try:
        stage_fd = os.open(stage_name, flags, dir_fd=parent_fd)
        opened = os.fstat(stage_fd)
        if not stat.S_ISDIR(opened.st_mode):  # pragma: no cover - O_DIRECTORY
            raise RuntimeError("storage staging target is not a directory")
        stage_identity = (opened.st_dev, opened.st_ino)
        _fsync_directory_fd(parent_fd)
        try:
            yield stage_fd
        finally:
            _cleanup_stage_at(parent_fd, stage_name, stage_fd, stage_identity)
    finally:
        if stage_fd >= 0:
            os.close(stage_fd)
        else:
            try:
                os.rmdir(stage_name, dir_fd=parent_fd)
            except FileNotFoundError:
                pass


def _restore_snapshot_at(
    parent_fd: int, target: Path, snapshot: _Snapshot
) -> None:
    name = target.name
    if not snapshot.existed:
        try:
            current = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            return
        if _is_link_like(current) or not stat.S_ISREG(current.st_mode):
            raise RuntimeError(f"unsafe rollback target: {name}")
        os.unlink(name, dir_fd=parent_fd)
        os.fsync(parent_fd)
        return
    if snapshot.payload is None or snapshot.mode is None:  # pragma: no cover
        raise RuntimeError("invalid rollback snapshot")
    temporary_name = f".capability-rollback-{secrets.token_hex(12)}"
    flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_CLOEXEC", 0)
    )
    descriptor = os.open(temporary_name, flags, snapshot.mode, dir_fd=parent_fd)
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
        os.replace(
            temporary_name,
            name,
            src_dir_fd=parent_fd,
            dst_dir_fd=parent_fd,
        )
        os.fsync(parent_fd)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            os.unlink(temporary_name, dir_fd=parent_fd)
        except FileNotFoundError:
            pass


def write_storage_bundle(
    paths: StoragePaths,
    artifacts: PublicArtifacts | Mapping[str, Any],
    resolver_records: Iterable[ResolverRecordLike],
    failure_injector: Callable[[str, Path], None] | None = None,
    *,
    expected_state: Mapping[str, StorageExpectedSnapshot] | None = None,
) -> StorageWriteResult:
    """Atomically replace a complete bundle and roll back every caught failure.

    ``failure_injector`` is a test/host hook called with the artifact label and
    stable target immediately before each changed target is replaced.
    """

    if not isinstance(paths, StoragePaths):
        raise TypeError("paths must be a StoragePaths value")
    _validate_storage_roots(paths)
    expected_targets = _validated_expected_state(paths, expected_state)
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

    if not _secure_storage_backend_available():
        if not _windows_portable_backend_available():
            raise RuntimeError("secure_storage_backend_unavailable")
        return _write_storage_bundle_portable(
            paths,
            raw_targets,
            hashes,
            generation_id,
            expected_targets=expected_targets,
            failure_injector=failure_injector,
        )

    _prepare_root(paths.public_root)
    _prepare_root(paths.private_root)
    _validate_storage_roots(paths)
    public_operation_evidence = _capture_root_evidence(paths.public_root)
    private_operation_evidence = _capture_root_evidence(paths.private_root)
    _validate_storage_roots(
        paths,
        public_operation_evidence=public_operation_evidence,
        private_operation_evidence=private_operation_evidence,
    )
    if paths.staging_root is not None:
        if not _is_within(paths.staging_root, paths.public_root):
            raise ValueError("staging_root must be inside public_root")
    for _, target, _, _ in raw_targets:
        if target.parent not in {paths.public_root, paths.private_root}:
            raise ValueError("storage target escaped its declared root")

    snapshots = {target: _target_snapshot(target) for _, target, _, _ in raw_targets}
    if expected_targets is not None:
        for label, target, _, _ in raw_targets:
            if not _matches_expected_snapshot(
                snapshots[target], expected_targets[label]
            ):
                raise RuntimeError(f"stale storage plan: {label}")
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
    public_stage_relative = public_stage_parent.relative_to(paths.public_root)
    _validate_storage_roots(
        paths,
        public_operation_evidence=public_operation_evidence,
        private_operation_evidence=private_operation_evidence,
    )
    with _directory_handle(
        paths.public_root, public_operation_evidence
    ) as public_root_fd, _directory_handle(
        paths.private_root, private_operation_evidence
    ) as private_root_fd, _relative_directory_handle(
        public_root_fd, public_stage_relative
    ) as public_stage_parent_fd, _stage_directory_at(
        public_stage_parent_fd
    ) as public_stage_fd, _stage_directory_at(
        private_root_fd
    ) as private_stage_fd:
        staged: dict[str, tuple[int, str]] = {}
        for target in prepared:
            _validate_storage_roots(
                paths,
                public_operation_evidence=public_operation_evidence,
                private_operation_evidence=private_operation_evidence,
            )
            stage_fd = (
                private_stage_fd if target.label == "resolver" else public_stage_fd
            )
            staged[target.label] = (
                stage_fd,
                _stage_target_at(stage_fd, target),
            )
        _fsync_directory_fd(public_stage_fd)
        _fsync_directory_fd(private_stage_fd)

        replaced_targets: list[_PreparedTarget] = []
        committed_evidence: dict[str, _CommittedEvidence] = {}
        try:
            for target in prepared:
                if failure_injector is not None:
                    failure_injector(target.label, target.target)
                _validate_storage_roots(
                    paths,
                    public_operation_evidence=public_operation_evidence,
                    private_operation_evidence=private_operation_evidence,
                )
                destination_fd = (
                    private_root_fd
                    if target.target.parent == paths.private_root
                    else public_root_fd
                )
                pinned_snapshot = _target_snapshot_at(
                    destination_fd, target.target.name
                )
                if expected_targets is not None and not _matches_expected_snapshot(
                    pinned_snapshot, expected_targets[target.label]
                ):
                    raise RuntimeError(f"stale storage plan: {target.label}")
                if pinned_snapshot != snapshots[target.target]:
                    raise RuntimeError(
                        f"storage target changed concurrently: {target.label}"
                    )
                stage_fd, staged_name = staged[target.label]
                staged_snapshot = _target_snapshot_at(stage_fd, staged_name)
                if staged_snapshot.payload != target.payload:
                    raise RuntimeError(
                        f"storage staging changed concurrently: {target.label}"
                    )
                try:
                    _commit_staged_no_replace_at(
                        stage_fd=stage_fd,
                        staged_name=staged_name,
                        destination_fd=destination_fd,
                        destination_name=target.target.name,
                        expected=pinned_snapshot,
                    )
                except FileExistsError as error:
                    raise RuntimeError(
                        f"stale storage plan: {target.label}"
                    ) from error
                replaced_targets.append(target)
                _sync_committed_target_at(
                    destination_fd,
                    target,
                    staged_snapshot,
                    committed_evidence,
                )
                _validate_storage_roots(
                    paths,
                    public_operation_evidence=public_operation_evidence,
                    private_operation_evidence=private_operation_evidence,
                )
        except BaseException as original_error:
            rollback_errors: list[BaseException] = []
            rollback_conflicts: list[str] = []
            for target in reversed(replaced_targets):
                parent_fd = (
                    private_root_fd
                    if target.target.parent == paths.private_root
                    else public_root_fd
                )
                try:
                    current = _target_snapshot_at(parent_fd, target.target.name)
                except (OSError, ValueError):
                    rollback_conflicts.append(target.label)
                    continue
                if (
                    _committed_evidence_from_snapshot(current)
                    != committed_evidence.get(target.label)
                ):
                    rollback_conflicts.append(target.label)
                    continue
                try:
                    _restore_snapshot_at(
                        parent_fd, target.target, snapshots[target.target]
                    )
                except BaseException as rollback_error:
                    rollback_errors.append(rollback_error)
            if rollback_conflicts or rollback_errors:
                details: list[str] = []
                if rollback_conflicts:
                    details.append(
                        "rollback_conflict: " + ", ".join(rollback_conflicts)
                    )
                if rollback_errors:
                    details.append("rollback_incomplete")
                raise RuntimeError(
                    "storage bundle failed; " + "; ".join(details)
                ) from original_error
            raise

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
    "RootEvidence",
    "StoragePaths",
    "StorageExpectedSnapshot",
    "StorageWriteResult",
    "VaultCandidate",
    "VaultDiscoveryResult",
    "build_private_resolver_document",
    "capture_storage_expected_state",
    "default_storage_paths",
    "discover_obsidian_vaults",
    "default_storage_root_text",
    "write_storage_bundle",
]

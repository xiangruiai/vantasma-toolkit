"""FD-bound atomic file transactions with private, recoverable backups."""

from __future__ import annotations

import errno
import hashlib
import inspect
import json
import os
import secrets
import stat
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


_READ_LIMIT = 8 * 1024 * 1024
_CHUNK_SIZE = 64 * 1024
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
    and os.rename in os.supports_dir_fd
)


@dataclass(frozen=True)
class FileMutation:
    """One expected-state-to-target-state transition."""

    path: Path
    operation: str
    expected_exists: bool
    expected_original_sha256: str | None
    original_bytes: bytes = field(repr=False)
    target_bytes: bytes = field(repr=False)
    mode: int
    newline: str
    parent_evidence: tuple[str, int, int] | None = field(
        default=None, repr=False
    )

    def __post_init__(self) -> None:
        path = Path(self.path)
        if not path.is_absolute() or path.name in {"", ".", ".."}:
            raise ValueError("transaction paths must be absolute files")
        if self.operation not in {"install", "update", "uninstall"}:
            raise ValueError("unsupported transaction operation")
        if self.expected_exists != (self.expected_original_sha256 is not None):
            raise ValueError("expected hash/existence mismatch")
        if self.expected_exists:
            digest = hashlib.sha256(self.original_bytes).hexdigest()
            if digest != self.expected_original_sha256:
                raise ValueError("original bytes do not match expected hash")
        elif self.original_bytes:
            raise ValueError("a missing original cannot contain bytes")
        if not 0 <= self.mode <= 0o7777:
            raise ValueError("invalid transaction file mode")
        object.__setattr__(self, "path", path)


@dataclass(frozen=True)
class TransactionReceipt:
    """Evidence for a committed transaction or a no-op."""

    plan_hash: str
    changed_paths: tuple[Path, ...]
    manifest_path: Path | None
    backup_directory: Path | None


class TransactionError(RuntimeError):
    """A failed transaction, including conservative rollback evidence."""

    def __init__(
        self,
        message: str,
        *,
        manifest_path: Path | None = None,
        rollback_conflicts: Iterable[Path] = (),
        cause: BaseException | None = None,
    ) -> None:
        super().__init__(message)
        self.manifest_path = manifest_path
        self.rollback_conflicts = tuple(rollback_conflicts)
        self.cause = cause


@dataclass(frozen=True)
class _Snapshot:
    existed: bool
    payload: bytes | None
    mode: int | None
    device: int | None = None
    inode: int | None = None
    size: int | None = None
    ctime_ns: int | None = None


@dataclass(frozen=True)
class _CommittedEvidence:
    device: int
    inode: int
    size: int
    ctime_ns: int
    mode: int
    sha256: str


def _secure_backend_available() -> bool:
    return bool(
        _REPLACE_SUPPORTS_DIR_FD
        and _DIR_FD_BACKEND_SUPPORTED
        and callable(getattr(os, "fchmod", None))
    )


def _fsync_directory(descriptor: int) -> None:
    try:
        os.fsync(descriptor)
    except OSError as error:
        if error.errno not in _IGNORABLE_FSYNC_ERRORS:
            raise


def _canonical_directory(path: Path) -> Path:
    """Resolve existing ancestors once; later traversal refuses every symlink."""

    return path.resolve(strict=False)


def _open_directory(path: Path, *, create: bool) -> tuple[int, tuple[Path, ...]]:
    canonical = _canonical_directory(path)
    if not canonical.is_absolute():  # pragma: no cover - resolve makes it absolute
        raise ValueError("transaction directory must be absolute")
    flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | os.O_DIRECTORY
        | os.O_NOFOLLOW
    )
    descriptor = os.open(canonical.anchor, flags)
    created: list[Path] = []
    current = Path(canonical.anchor)
    try:
        for component in canonical.parts[1:]:
            try:
                child = os.open(component, flags, dir_fd=descriptor)
            except FileNotFoundError:
                if not create:
                    raise
                os.mkdir(component, 0o700, dir_fd=descriptor)
                _fsync_directory(descriptor)
                current = current / component
                created.append(current)
                child = os.open(component, flags, dir_fd=descriptor)
            except OSError as error:
                raise ValueError("transaction directory could not be opened safely") from error
            metadata = os.fstat(child)
            if not stat.S_ISDIR(metadata.st_mode):  # pragma: no cover - O_DIRECTORY
                os.close(child)
                raise ValueError("transaction path component is not a directory")
            os.close(descriptor)
            descriptor = child
            current = current / component
        return descriptor, tuple(created)
    except BaseException:
        os.close(descriptor)
        raise


def _snapshot_at(parent_fd: int, name: str) -> _Snapshot:
    try:
        before = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError:
        return _Snapshot(False, None, None)
    except OSError as error:
        raise ValueError("transaction target could not be inspected") from error
    if stat.S_ISLNK(before.st_mode):
        raise ValueError("refusing symbolic-link transaction target")
    if not stat.S_ISREG(before.st_mode):
        raise ValueError("transaction target is not a regular file")
    if before.st_size > _READ_LIMIT:
        raise ValueError("transaction target exceeds the read limit")
    flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NONBLOCK", 0)
        | os.O_NOFOLLOW
    )
    descriptor = os.open(name, flags, dir_fd=parent_fd)
    try:
        opened = os.fstat(descriptor)
        expected = (
            before.st_dev,
            before.st_ino,
            before.st_mode,
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
        )
        actual = (
            opened.st_dev,
            opened.st_ino,
            opened.st_mode,
            opened.st_size,
            opened.st_mtime_ns,
            opened.st_ctime_ns,
        )
        if not stat.S_ISREG(opened.st_mode) or actual != expected:
            raise ValueError("transaction target changed while opening")
        chunks: list[bytes] = []
        total = 0
        while total <= _READ_LIMIT:
            chunk = os.read(
                descriptor, min(_CHUNK_SIZE, _READ_LIMIT + 1 - total)
            )
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
        after = os.fstat(descriptor)
        if total > _READ_LIMIT:
            raise ValueError("transaction target exceeds the read limit")
        if (
            after.st_dev,
            after.st_ino,
            after.st_mode,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        ) != actual or total != opened.st_size:
            raise ValueError("transaction target changed while reading")
        return _Snapshot(
            True,
            b"".join(chunks),
            stat.S_IMODE(opened.st_mode),
            opened.st_dev,
            opened.st_ino,
            opened.st_size,
            opened.st_ctime_ns,
        )
    finally:
        os.close(descriptor)


def _matches_expected(snapshot: _Snapshot, mutation: FileMutation) -> bool:
    if snapshot.existed != mutation.expected_exists:
        return False
    if not snapshot.existed:
        return True
    if snapshot.payload is None or snapshot.mode is None:
        return False
    return (
        hashlib.sha256(snapshot.payload).hexdigest()
        == mutation.expected_original_sha256
        and snapshot.mode == mutation.mode
    )


def _write_new_at(parent_fd: int, name: str, payload: bytes, mode: int) -> None:
    flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_CLOEXEC", 0)
        | os.O_NOFOLLOW
    )
    descriptor = os.open(name, flags, mode, dir_fd=parent_fd)
    try:
        offset = 0
        while offset < len(payload):
            written = os.write(descriptor, payload[offset:])
            if written <= 0:
                raise OSError("short transaction write")
            offset += written
        os.fchmod(descriptor, mode)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _verify_parent_evidence(mutations: tuple[FileMutation, ...]) -> None:
    for mutation in mutations:
        evidence = mutation.parent_evidence
        if evidence is None:
            continue
        path_text, expected_device, expected_inode = evidence
        try:
            metadata = os.lstat(path_text)
        except OSError as error:
            raise TransactionError("stale transaction parent evidence", cause=error) from error
        if (
            stat.S_ISLNK(metadata.st_mode)
            or not stat.S_ISDIR(metadata.st_mode)
            or metadata.st_dev != expected_device
            or metadata.st_ino != expected_inode
        ):
            raise TransactionError("stale transaction parent evidence")


def _write_backup_manifest(
    backup_root: Path,
    mutations: tuple[FileMutation, ...],
    plan_hash: str,
) -> tuple[Path, Path]:
    root_fd, _ = _open_directory(backup_root, create=True)
    transaction_name = f"instruction-{plan_hash[:16]}-{secrets.token_hex(6)}"
    transaction_fd = -1
    try:
        os.mkdir(transaction_name, 0o700, dir_fd=root_fd)
        _fsync_directory(root_fd)
        flags = (
            os.O_RDONLY
            | getattr(os, "O_CLOEXEC", 0)
            | os.O_DIRECTORY
            | os.O_NOFOLLOW
        )
        transaction_fd = os.open(transaction_name, flags, dir_fd=root_fd)
        entries: list[dict[str, Any]] = []
        for index, mutation in enumerate(mutations):
            backup_file: str | None = None
            if mutation.expected_exists:
                backup_file = f"original-{index:04d}.bin"
                _write_new_at(
                    transaction_fd, backup_file, mutation.original_bytes, 0o600
                )
            entries.append(
                {
                    "path": str(mutation.path),
                    "operation": mutation.operation,
                    "existed": mutation.expected_exists,
                    "sha256": mutation.expected_original_sha256,
                    "mode": mutation.mode if mutation.expected_exists else None,
                    "newline": mutation.newline,
                    "backup_file": backup_file,
                    "target_sha256": hashlib.sha256(
                        mutation.target_bytes
                    ).hexdigest(),
                }
            )
        document = {
            "schema_version": 1,
            "plan_hash": plan_hash,
            "entries": entries,
        }
        payload = (
            json.dumps(
                document,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode("utf-8")
        _write_new_at(transaction_fd, "manifest.json", payload, 0o600)
        _fsync_directory(transaction_fd)
    finally:
        if transaction_fd >= 0:
            os.close(transaction_fd)
        os.close(root_fd)
    directory = backup_root / transaction_name
    return directory, directory / "manifest.json"


def _committed_evidence(snapshot: _Snapshot, expected_hash: str) -> _CommittedEvidence:
    if (
        not snapshot.existed
        or snapshot.device is None
        or snapshot.inode is None
        or snapshot.size is None
        or snapshot.ctime_ns is None
        or snapshot.mode is None
        or snapshot.payload is None
        or hashlib.sha256(snapshot.payload).hexdigest() != expected_hash
    ):
        raise OSError("committed transaction evidence mismatch")
    return _CommittedEvidence(
        snapshot.device,
        snapshot.inode,
        snapshot.size,
        snapshot.ctime_ns,
        snapshot.mode,
        expected_hash,
    )


def _still_owned(snapshot: _Snapshot, evidence: _CommittedEvidence) -> bool:
    return bool(
        snapshot.existed
        and snapshot.payload is not None
        and snapshot.device == evidence.device
        and snapshot.inode == evidence.inode
        and snapshot.size == evidence.size
        and snapshot.ctime_ns == evidence.ctime_ns
        and snapshot.mode == evidence.mode
        and hashlib.sha256(snapshot.payload).hexdigest() == evidence.sha256
    )


def _restore_at(parent_fd: int, mutation: FileMutation) -> None:
    name = mutation.path.name
    if not mutation.expected_exists:
        os.unlink(name, dir_fd=parent_fd)
        _fsync_directory(parent_fd)
        return
    temporary = f".vantasma-instruction-rollback-{secrets.token_hex(12)}"
    try:
        _write_new_at(parent_fd, temporary, mutation.original_bytes, mutation.mode)
        os.replace(
            temporary,
            name,
            src_dir_fd=parent_fd,
            dst_dir_fd=parent_fd,
        )
        _fsync_directory(parent_fd)
    finally:
        try:
            os.unlink(temporary, dir_fd=parent_fd)
        except FileNotFoundError:
            pass


def apply_file_transaction(
    mutations: Iterable[FileMutation],
    *,
    backup_root: Path,
    plan_hash: str,
    failure_injector: Callable[[str, Path], None] | None = None,
) -> TransactionReceipt:
    """Apply all mutations or conservatively restore only owned commits."""

    values = tuple(mutations)
    if not values:
        return TransactionReceipt(plan_hash, (), None, None)
    if not _secure_backend_available():
        raise RuntimeError("secure_transaction_backend_unavailable")
    if len({item.path for item in values}) != len(values):
        raise ValueError("transaction paths must be unique")
    private_backup = Path(backup_root)
    if not private_backup.is_absolute():
        raise ValueError("backup_root must be absolute")
    if any(private_backup == item.path.parent for item in values):
        raise ValueError("backup_root must not be an instruction directory")

    _verify_parent_evidence(values)
    parent_handles: dict[Path, int] = {}
    staged_names: dict[Path, str] = {}
    committed: list[tuple[FileMutation, _CommittedEvidence]] = []
    manifest_path: Path | None = None
    backup_directory: Path | None = None
    try:
        for mutation in values:
            parent_key = mutation.path.parent
            if parent_key not in parent_handles:
                parent_handles[parent_key], _ = _open_directory(
                    parent_key, create=True
                )
        for mutation in values:
            current = _snapshot_at(parent_handles[mutation.path.parent], mutation.path.name)
            if not _matches_expected(current, mutation):
                raise TransactionError("stale transaction target")

        backup_directory, manifest_path = _write_backup_manifest(
            private_backup, values, plan_hash
        )

        for mutation in values:
            parent_fd = parent_handles[mutation.path.parent]
            temporary = f".vantasma-instruction-stage-{secrets.token_hex(12)}"
            _write_new_at(parent_fd, temporary, mutation.target_bytes, mutation.mode)
            staged_names[mutation.path] = temporary
            staged = _snapshot_at(parent_fd, temporary)
            if (
                staged.payload is None
                or hashlib.sha256(staged.payload).hexdigest()
                != hashlib.sha256(mutation.target_bytes).hexdigest()
            ):
                raise OSError("staged transaction hash mismatch")

        for mutation in values:
            parent_fd = parent_handles[mutation.path.parent]
            current = _snapshot_at(parent_fd, mutation.path.name)
            if not _matches_expected(current, mutation):
                raise TransactionError("stale transaction target")
            temporary = staged_names.pop(mutation.path)
            os.replace(
                temporary,
                mutation.path.name,
                src_dir_fd=parent_fd,
                dst_dir_fd=parent_fd,
            )
            _fsync_directory(parent_fd)
            desired_hash = hashlib.sha256(mutation.target_bytes).hexdigest()
            after = _snapshot_at(parent_fd, mutation.path.name)
            evidence = _committed_evidence(after, desired_hash)
            committed.append((mutation, evidence))
            if failure_injector is not None:
                failure_injector("after_replace", mutation.path)

        return TransactionReceipt(
            plan_hash,
            tuple(item.path for item in values),
            manifest_path,
            backup_directory,
        )
    except BaseException as error:
        conflicts: list[Path] = []
        rollback_errors: list[BaseException] = []
        for mutation, evidence in reversed(committed):
            parent_fd = parent_handles.get(mutation.path.parent)
            if parent_fd is None:  # pragma: no cover - committed implies an fd
                conflicts.append(mutation.path)
                continue
            try:
                current = _snapshot_at(parent_fd, mutation.path.name)
                if not _still_owned(current, evidence):
                    conflicts.append(mutation.path)
                    continue
                _restore_at(parent_fd, mutation)
            except BaseException as rollback_error:
                rollback_errors.append(rollback_error)
        if isinstance(error, TransactionError) and not committed:
            raise
        message = "instruction transaction failed"
        if conflicts:
            message += "; rollback_conflict"
        if rollback_errors:
            message += "; rollback_incomplete"
        raise TransactionError(
            message,
            manifest_path=manifest_path,
            rollback_conflicts=conflicts,
            cause=error,
        ) from error
    finally:
        for path, temporary in tuple(staged_names.items()):
            descriptor = parent_handles.get(path.parent)
            if descriptor is not None:
                try:
                    os.unlink(temporary, dir_fd=descriptor)
                except FileNotFoundError:
                    pass
        for descriptor in parent_handles.values():
            os.close(descriptor)


__all__ = [
    "FileMutation",
    "TransactionError",
    "TransactionReceipt",
    "apply_file_transaction",
]

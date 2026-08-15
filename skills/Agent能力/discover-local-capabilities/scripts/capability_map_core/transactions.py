"""FD-bound atomic file transactions with private, recoverable backups."""

from __future__ import annotations

import errno
import hashlib
import json
import os
import secrets
import stat
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .storage import (
    RootEvidence as DirectoryEvidence,
    _capture_root_evidence,
    _move_no_replace_portable,
    _prepare_root_portable,
    _target_snapshot,
    _validate_root_evidence,
    _write_file_fsynced_portable,
)


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
_DIR_FD_BACKEND_SUPPORTED = bool(
    getattr(os, "O_DIRECTORY", 0)
    and getattr(os, "O_NOFOLLOW", 0)
    and os.open in os.supports_dir_fd
    and os.stat in os.supports_dir_fd
    and os.mkdir in os.supports_dir_fd
    and os.unlink in os.supports_dir_fd
    and os.rename in os.supports_dir_fd
    and os.link in os.supports_dir_fd
    and os.link in os.supports_follow_symlinks
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
    parent_evidence: DirectoryEvidence = field(repr=False)

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
        if not isinstance(self.parent_evidence, DirectoryEvidence):
            raise TypeError("parent_evidence must be DirectoryEvidence")
        _validate_mutation_path(path, self.parent_evidence)
        object.__setattr__(self, "path", path)


@dataclass(frozen=True)
class TransactionReceipt:
    """Evidence for a committed transaction or a no-op."""

    plan_hash: str
    changed_paths: tuple[Path, ...]
    manifest_path: Path | None
    backup_directory: Path | None
    cleanup_recovery_paths: tuple[Path, ...] = ()


class TransactionError(RuntimeError):
    """A failed transaction, including conservative rollback evidence."""

    def __init__(
        self,
        message: str,
        *,
        manifest_path: Path | None = None,
        rollback_conflicts: Iterable[Path] = (),
        recovery_paths: Iterable[Path] = (),
        cause: BaseException | None = None,
    ) -> None:
        super().__init__(message)
        self.manifest_path = manifest_path
        self.rollback_conflicts = tuple(rollback_conflicts)
        self.recovery_paths = tuple(recovery_paths)
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
    ctime_ns: int | None
    mode: int
    sha256: str


def _validate_mutation_path(
    path: Path, parent_evidence: DirectoryEvidence
) -> None:
    name = path.name
    separators = tuple(
        value for value in (os.sep, os.altsep) if value is not None
    )
    if (
        name in {"", ".", ".."}
        or any(character in name for character in ("\x00", "\r", "\n"))
        or any(separator in name for separator in separators)
    ):
        raise ValueError("transaction path must use a safe basename")
    try:
        resolved_parent = path.parent.resolve(strict=False)
    except OSError as error:
        raise ValueError("transaction path parent could not be resolved") from error
    if resolved_parent != parent_evidence.resolved_path:
        raise ValueError("transaction path parent evidence mismatch")


def _secure_backend_available() -> bool:
    return bool(
        _DIR_FD_BACKEND_SUPPORTED
        and callable(getattr(os, "fchmod", None))
    )


def _windows_portable_backend_available() -> bool:
    return os.name == "nt"


def _fsync_directory(descriptor: int) -> None:
    try:
        os.fsync(descriptor)
    except OSError as error:
        if error.errno not in _IGNORABLE_FSYNC_ERRORS:
            raise


def capture_directory_evidence(path: Path) -> DirectoryEvidence:
    """Capture a canonical physical root without creating any directory."""

    candidate = Path(path)
    if not candidate.is_absolute():
        raise ValueError("transaction directory must be absolute")
    return _capture_root_evidence(candidate)


def directory_evidence_dict(evidence: DirectoryEvidence) -> dict[str, Any]:
    """Serialize root identity into the private deterministic plan document."""

    if not isinstance(evidence, DirectoryEvidence):
        raise TypeError("evidence must be DirectoryEvidence")
    return {
        "resolved_path": str(evidence.resolved_path),
        "existing_ancestors": [
            {
                "path": str(item.path),
                "device": item.device,
                "inode": item.inode,
                "mode": item.mode,
            }
            for item in evidence.existing_ancestors
        ],
    }


def _open_evidence_directory(
    evidence: DirectoryEvidence, *, create: bool, label: str
) -> int:
    resolved = _validate_root_evidence(evidence)
    if not evidence.existing_ancestors:  # pragma: no cover - filesystem root exists
        raise ValueError(f"{label} has no existing safe ancestor")
    anchor = evidence.existing_ancestors[-1]
    flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | os.O_DIRECTORY
        | os.O_NOFOLLOW
    )
    descriptor = os.open(anchor.path, flags)
    try:
        opened_anchor = os.fstat(descriptor)
        if (
            not stat.S_ISDIR(opened_anchor.st_mode)
            or opened_anchor.st_dev != anchor.device
            or opened_anchor.st_ino != anchor.inode
        ):
            raise ValueError(f"{label} ancestry changed while opening")
        try:
            relative = resolved.relative_to(anchor.path)
        except ValueError as error:  # pragma: no cover - evidence construction guarantees
            raise ValueError(f"{label} escaped its pinned ancestor") from error
        parts = tuple(part for part in relative.parts if part not in {"", "."})
        if parts and not create:
            raise ValueError(f"{label} parent does not exist")
        for component in parts:
            try:
                child = os.open(component, flags, dir_fd=descriptor)
            except FileNotFoundError:
                if not create:
                    raise ValueError(f"{label} parent does not exist")
                os.mkdir(component, 0o700, dir_fd=descriptor)
                _fsync_directory(descriptor)
                try:
                    child = os.open(component, flags, dir_fd=descriptor)
                except OSError as error:
                    raise ValueError(
                        f"{label} could not be opened safely"
                    ) from error
            except OSError as error:
                raise ValueError(f"{label} could not be opened safely") from error
            metadata = os.fstat(child)
            if not stat.S_ISDIR(metadata.st_mode):  # pragma: no cover - O_DIRECTORY
                os.close(child)
                raise ValueError(f"{label} component is not a directory")
            os.close(descriptor)
            descriptor = child
        return descriptor
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


def _write_backup_manifest(
    backup_root_evidence: DirectoryEvidence,
    mutations: tuple[FileMutation, ...],
    plan_hash: str,
) -> tuple[Path, Path, int]:
    root_fd = _open_evidence_directory(
        backup_root_evidence, create=True, label="backup root"
    )
    transaction_name = f"instruction-{plan_hash[:16]}-{secrets.token_hex(6)}"
    transaction_fd = -1
    completed = False
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
        completed = True
    finally:
        if transaction_fd >= 0 and not completed:
            os.close(transaction_fd)
        os.close(root_fd)
    directory = backup_root_evidence.resolved_path / transaction_name
    return directory, directory / "manifest.json", transaction_fd


def _committed_evidence(
    snapshot: _Snapshot, expected_hash: str, *, include_ctime: bool = True
) -> _CommittedEvidence:
    if (
        not snapshot.existed
        or snapshot.device is None
        or snapshot.inode is None
        or snapshot.size is None
        or snapshot.mode is None
        or snapshot.payload is None
        or hashlib.sha256(snapshot.payload).hexdigest() != expected_hash
    ):
        raise OSError("committed transaction evidence mismatch")
    return _CommittedEvidence(
        snapshot.device,
        snapshot.inode,
        snapshot.size,
        snapshot.ctime_ns if include_ctime else None,
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
        and (evidence.ctime_ns is None or snapshot.ctime_ns == evidence.ctime_ns)
        and snapshot.mode == evidence.mode
        and hashlib.sha256(snapshot.payload).hexdigest() == evidence.sha256
    )


def _link_no_replace(parent_fd: int, source: str, destination: str) -> None:
    os.link(
        source,
        destination,
        src_dir_fd=parent_fd,
        dst_dir_fd=parent_fd,
        follow_symlinks=False,
    )


def _restore_claim_no_replace(
    parent_fd: int, claim_name: str, target_name: str
) -> bool:
    try:
        _link_no_replace(parent_fd, claim_name, target_name)
    except FileExistsError:
        return False
    os.unlink(claim_name, dir_fd=parent_fd)
    _fsync_directory(parent_fd)
    return True


def _preserve_claim_in_backup(
    parent_fd: int,
    claim_name: str,
    backup_fd: int,
    backup_directory: Path,
    recovery_index: int,
) -> Path:
    claimed = _snapshot_at(parent_fd, claim_name)
    if not claimed.existed or claimed.payload is None:
        raise OSError("claimed transaction target disappeared")
    recovery_name = f"claim-recovery-{recovery_index:04d}.bin"
    _write_new_at(backup_fd, recovery_name, claimed.payload, 0o600)
    recovered = _snapshot_at(backup_fd, recovery_name)
    if (
        recovered.payload is None
        or hashlib.sha256(recovered.payload).hexdigest()
        != hashlib.sha256(claimed.payload).hexdigest()
    ):
        raise OSError("claim recovery backup verification failed")
    _fsync_directory(backup_fd)
    os.unlink(claim_name, dir_fd=parent_fd)
    _fsync_directory(parent_fd)
    return backup_directory / recovery_name


def _portable_matches_expected(snapshot: Any, mutation: FileMutation) -> bool:
    if snapshot.existed != mutation.expected_exists:
        return False
    if not snapshot.existed:
        return True
    return bool(
        snapshot.payload is not None
        and hashlib.sha256(snapshot.payload).hexdigest()
        == mutation.expected_original_sha256
        and (os.name == "nt" or snapshot.mode == mutation.mode)
    )


def _write_backup_manifest_portable(
    backup_root_evidence: DirectoryEvidence,
    mutations: tuple[FileMutation, ...],
    plan_hash: str,
) -> tuple[Path, Path]:
    root = _prepare_root_portable(backup_root_evidence)
    directory = root / f"instruction-{plan_hash[:16]}-{secrets.token_hex(6)}"
    directory.mkdir(mode=0o700)
    entries: list[dict[str, Any]] = []
    for index, mutation in enumerate(mutations):
        backup_file: str | None = None
        if mutation.expected_exists:
            backup_file = f"original-{index:04d}.bin"
            _write_file_fsynced_portable(
                directory / backup_file, mutation.original_bytes, 0o600
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
    payload = (
        json.dumps(
            {"schema_version": 1, "plan_hash": plan_hash, "entries": entries},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")
    manifest = directory / "manifest.json"
    _write_file_fsynced_portable(manifest, payload, 0o600)
    return directory, manifest


def _apply_file_transaction_portable(
    values: tuple[FileMutation, ...],
    *,
    backup_root_evidence: DirectoryEvidence,
    plan_hash: str,
    failure_injector: Callable[[str, Path], None] | None,
) -> TransactionReceipt:
    """Best-effort Windows transaction with recoverable originals."""

    for mutation in values:
        _validate_root_evidence(mutation.parent_evidence)
        if not mutation.path.parent.exists():
            raise TransactionError("instruction target parent does not exist")
        current = _target_snapshot(mutation.path)
        if not _portable_matches_expected(current, mutation):
            raise TransactionError("stale transaction target")

    backup_directory, manifest_path = _write_backup_manifest_portable(
        backup_root_evidence, values, plan_hash
    )
    stages: dict[Path, Path] = {}
    claims: dict[Path, Path] = {}
    committed: list[tuple[FileMutation, _CommittedEvidence]] = []
    recovery_paths: list[Path] = []
    cleanup_recovery_paths: list[Path] = []
    commit_complete = False
    try:
        for mutation in values:
            stage = mutation.path.parent / (
                f".vantasma-instruction-stage-{secrets.token_hex(12)}"
            )
            _write_file_fsynced_portable(stage, mutation.target_bytes, mutation.mode)
            staged = _target_snapshot(stage)
            desired_hash = hashlib.sha256(mutation.target_bytes).hexdigest()
            if staged.payload is None or hashlib.sha256(staged.payload).hexdigest() != desired_hash:
                raise OSError("staged transaction hash mismatch")
            stages[mutation.path] = stage

        for mutation in values:
            current = _target_snapshot(mutation.path)
            if not _portable_matches_expected(current, mutation):
                raise TransactionError("stale transaction target")
            if mutation.expected_exists:
                if failure_injector is not None:
                    failure_injector("before_claim", mutation.path)
                claim = mutation.path.parent / (
                    f".vantasma-instruction-claim-{secrets.token_hex(12)}"
                )
                _move_no_replace_portable(mutation.path, claim)
                claims[mutation.path] = claim
                if not _portable_matches_expected(_target_snapshot(claim), mutation):
                    raise TransactionError(
                        "stale transaction target after atomic claim conflict"
                    )
            if failure_injector is not None:
                failure_injector("before_link", mutation.path)
            try:
                _move_no_replace_portable(stages.pop(mutation.path), mutation.path)
            except FileExistsError as error:
                raise TransactionError(
                    "stale transaction target: concurrent create conflict",
                    cause=error,
                ) from error
            after = _target_snapshot(mutation.path)
            evidence = _committed_evidence(
                after,
                hashlib.sha256(mutation.target_bytes).hexdigest(),
            )
            committed.append((mutation, evidence))
            if failure_injector is not None:
                failure_injector("after_replace", mutation.path)

        commit_complete = True
        for path, claim in tuple(claims.items()):
            try:
                os.unlink(claim)
            except FileNotFoundError:
                claims.pop(path, None)
            except OSError:
                try:
                    os.lstat(claim)
                except (FileNotFoundError, OSError):
                    claims.pop(path, None)
                else:
                    cleanup_recovery_paths.append(claim)
            else:
                claims.pop(path, None)
        return TransactionReceipt(
            plan_hash,
            tuple(item.path for item in values),
            manifest_path,
            backup_directory,
            tuple(cleanup_recovery_paths),
        )
    except BaseException as error:
        if commit_complete:
            raise
        conflicts: list[Path] = []
        rollback_errors: list[BaseException] = []
        for mutation, evidence in reversed(committed):
            try:
                current = _target_snapshot(mutation.path)
                if not _still_owned(current, evidence):
                    conflicts.append(mutation.path)
                    continue
                os.unlink(mutation.path)
                claim = claims.pop(mutation.path, None)
                if claim is not None:
                    _move_no_replace_portable(claim, mutation.path)
            except BaseException as rollback_error:
                rollback_errors.append(rollback_error)
        for path, claim in tuple(claims.items()):
            try:
                if not path.exists():
                    _move_no_replace_portable(claim, path)
                    claims.pop(path, None)
                    continue
                recovery = backup_directory / (
                    f"claim-recovery-{len(recovery_paths):04d}.bin"
                )
                claimed = _target_snapshot(claim)
                if claimed.payload is None:
                    raise OSError("claimed transaction target disappeared")
                _write_file_fsynced_portable(recovery, claimed.payload, 0o600)
                recovery_paths.append(recovery)
                os.unlink(claim)
                claims.pop(path, None)
                conflicts.append(path)
            except BaseException as rollback_error:
                rollback_errors.append(rollback_error)
        message = f"instruction transaction failed: {error}"
        if conflicts:
            message += "; rollback_conflict"
        if rollback_errors:
            message += "; rollback_incomplete"
        raise TransactionError(
            message,
            manifest_path=manifest_path,
            rollback_conflicts=conflicts,
            recovery_paths=recovery_paths,
            cause=error,
        ) from error
    finally:
        for stage in stages.values():
            try:
                os.unlink(stage)
            except FileNotFoundError:
                pass


def apply_file_transaction(
    mutations: Iterable[FileMutation],
    *,
    backup_root: Path,
    backup_root_evidence: DirectoryEvidence,
    plan_hash: str,
    failure_injector: Callable[[str, Path], None] | None = None,
) -> TransactionReceipt:
    """Apply all mutations or conservatively restore only owned commits."""

    values = tuple(mutations)
    if not values:
        return TransactionReceipt(plan_hash, (), None, None)
    for mutation in values:
        _validate_mutation_path(mutation.path, mutation.parent_evidence)
    if len({item.path for item in values}) != len(values):
        raise ValueError("transaction paths must be unique")
    private_backup = Path(backup_root)
    if not private_backup.is_absolute():
        raise ValueError("backup_root must be absolute")
    if any(private_backup == item.path.parent for item in values):
        raise ValueError("backup_root must not be an instruction directory")
    if not isinstance(backup_root_evidence, DirectoryEvidence):
        raise TypeError("backup_root_evidence must be DirectoryEvidence")
    if not _secure_backend_available():
        if not _windows_portable_backend_available():
            raise RuntimeError("secure_transaction_backend_unavailable")
        return _apply_file_transaction_portable(
            values,
            backup_root_evidence=backup_root_evidence,
            plan_hash=plan_hash,
            failure_injector=failure_injector,
        )

    parent_handles: dict[Path, int] = {}
    staged_names: dict[Path, str] = {}
    staged_evidence: dict[Path, _CommittedEvidence] = {}
    claim_names: dict[Path, str] = {}
    committed: list[tuple[FileMutation, _CommittedEvidence]] = []
    manifest_path: Path | None = None
    backup_directory: Path | None = None
    backup_fd = -1
    try:
        for mutation in values:
            parent_key = mutation.path.parent
            if parent_key not in parent_handles:
                parent_handles[parent_key] = _open_evidence_directory(
                    mutation.parent_evidence,
                    create=False,
                    label="instruction target parent",
                )
        for mutation in values:
            current = _snapshot_at(parent_handles[mutation.path.parent], mutation.path.name)
            if not _matches_expected(current, mutation):
                raise TransactionError("stale transaction target")

        backup_directory, manifest_path, backup_fd = _write_backup_manifest(
            backup_root_evidence, values, plan_hash
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
            staged_evidence[mutation.path] = _committed_evidence(
                staged,
                hashlib.sha256(mutation.target_bytes).hexdigest(),
                include_ctime=False,
            )

        for mutation in values:
            parent_fd = parent_handles[mutation.path.parent]
            temporary = staged_names[mutation.path]
            desired_hash = hashlib.sha256(mutation.target_bytes).hexdigest()
            if mutation.expected_exists:
                if failure_injector is not None:
                    failure_injector("before_claim", mutation.path)
                claim_name = (
                    f".vantasma-instruction-claim-{secrets.token_hex(12)}"
                )
                _write_new_at(parent_fd, claim_name, b"", 0o600)
                try:
                    os.rename(
                        mutation.path.name,
                        claim_name,
                        src_dir_fd=parent_fd,
                        dst_dir_fd=parent_fd,
                    )
                except BaseException:
                    try:
                        os.unlink(claim_name, dir_fd=parent_fd)
                    except FileNotFoundError:
                        pass
                    raise
                claim_names[mutation.path] = claim_name
                _fsync_directory(parent_fd)
                claimed = _snapshot_at(parent_fd, claim_name)
                if not _matches_expected(claimed, mutation):
                    raise TransactionError(
                        "stale transaction target after atomic claim conflict"
                    )
            if failure_injector is not None:
                failure_injector("before_link", mutation.path)
            try:
                _link_no_replace(parent_fd, temporary, mutation.path.name)
            except FileExistsError as error:
                raise TransactionError(
                    "stale transaction target: concurrent create conflict",
                    cause=error,
                ) from error
            committed.append((mutation, staged_evidence[mutation.path]))
            os.unlink(temporary, dir_fd=parent_fd)
            staged_names.pop(mutation.path)
            if failure_injector is not None:
                failure_injector("after_replace", mutation.path)
            _fsync_directory(parent_fd)
            after = _snapshot_at(parent_fd, mutation.path.name)
            evidence = _committed_evidence(after, desired_hash)
            committed[-1] = (mutation, evidence)

        for mutation, _evidence in committed:
            claim_name = claim_names.get(mutation.path)
            if claim_name is not None:
                claimed = _snapshot_at(
                    parent_handles[mutation.path.parent], claim_name
                )
                if not _matches_expected(claimed, mutation):
                    raise TransactionError(
                        "claimed original changed during transaction conflict"
                    )
        for mutation, _evidence in committed:
            claim_name = claim_names.pop(mutation.path, None)
            if claim_name is not None:
                os.unlink(claim_name, dir_fd=parent_handles[mutation.path.parent])
                _fsync_directory(parent_handles[mutation.path.parent])
        return TransactionReceipt(
            plan_hash,
            tuple(item.path for item in values),
            manifest_path,
            backup_directory,
        )
    except BaseException as error:
        conflicts: list[Path] = []
        recovery_paths: list[Path] = []
        rollback_errors: list[BaseException] = []
        had_transaction_state = bool(committed or claim_names)
        for mutation, evidence in reversed(committed):
            parent_fd = parent_handles.get(mutation.path.parent)
            if parent_fd is None:  # pragma: no cover - committed implies an fd
                conflicts.append(mutation.path)
                continue
            try:
                current = _snapshot_at(parent_fd, mutation.path.name)
                if not _still_owned(current, evidence):
                    conflicts.append(mutation.path)
                else:
                    os.unlink(mutation.path.name, dir_fd=parent_fd)
                    _fsync_directory(parent_fd)
                claim_name = claim_names.pop(mutation.path, None)
                if claim_name is not None:
                    if current.existed and _still_owned(current, evidence):
                        if not _restore_claim_no_replace(
                            parent_fd, claim_name, mutation.path.name
                        ):
                            conflicts.append(mutation.path)
                            recovery_paths.append(
                                _preserve_claim_in_backup(
                                    parent_fd,
                                    claim_name,
                                    backup_fd,
                                    backup_directory,  # type: ignore[arg-type]
                                    len(recovery_paths),
                                )
                            )
                    else:
                        recovery_paths.append(
                            _preserve_claim_in_backup(
                                parent_fd,
                                claim_name,
                                backup_fd,
                                backup_directory,  # type: ignore[arg-type]
                                len(recovery_paths),
                            )
                        )
            except BaseException as rollback_error:
                rollback_errors.append(rollback_error)
        for path, claim_name in tuple(claim_names.items()):
            parent_fd = parent_handles.get(path.parent)
            if parent_fd is None:
                conflicts.append(path)
                continue
            try:
                current = _snapshot_at(parent_fd, path.name)
                if not current.existed and _restore_claim_no_replace(
                    parent_fd, claim_name, path.name
                ):
                    claim_names.pop(path, None)
                    continue
                conflicts.append(path)
                recovery_paths.append(
                    _preserve_claim_in_backup(
                        parent_fd,
                        claim_name,
                        backup_fd,
                        backup_directory,  # type: ignore[arg-type]
                        len(recovery_paths),
                    )
                )
                claim_names.pop(path, None)
            except BaseException as rollback_error:
                rollback_errors.append(rollback_error)
        if (
            isinstance(error, TransactionError)
            and not had_transaction_state
            and manifest_path is None
        ):
            raise
        message = f"instruction transaction failed: {error}"
        if conflicts:
            message += "; rollback_conflict"
        if rollback_errors:
            message += "; rollback_incomplete"
        raise TransactionError(
            message,
            manifest_path=manifest_path,
            rollback_conflicts=conflicts,
            recovery_paths=recovery_paths,
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
        if backup_fd >= 0:
            os.close(backup_fd)


__all__ = [
    "FileMutation",
    "DirectoryEvidence",
    "TransactionError",
    "TransactionReceipt",
    "apply_file_transaction",
    "capture_directory_evidence",
    "directory_evidence_dict",
]

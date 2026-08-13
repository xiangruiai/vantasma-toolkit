"""Complete PATH command discovery with an explicit, isolated version probe."""

from __future__ import annotations

import hashlib
import math
import os
import platform
import queue
import signal
import stat
import subprocess
import tempfile
import threading
import time
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .models import (
    Capability,
    CapabilityStates,
    Diagnostic,
    SourceLocation,
)
from .sanitize import sanitize_text


DEFAULT_WINDOWS_PATHEXT = (".COM", ".EXE", ".BAT", ".CMD")
MAX_PROBE_TIMEOUT_SECONDS = 3.0
MAX_PROBE_OUTPUT_BYTES = 64 * 1024
PROBE_READ_CHUNK_BYTES = 8 * 1024
_PROBE_POLL_SECONDS = 0.02
_PROBE_TERMINATE_GRACE_SECONDS = 0.2
_PROBE_THREAD_JOIN_SECONDS = 0.5
_PROBE_STATUSES = frozenset(
    {"success", "no_output", "nonzero", "timeout", "output_limit", "error"}
)
_MINIMAL_ENVIRONMENT_KEYS = ("PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP")


@dataclass(frozen=True)
class CliResolverRecord:
    """Private CLI locations preserving PATH order and duplicate visibility."""

    resolver_id: str
    exact_locations: tuple[str, ...] | list[str] = field(repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.resolver_id, str) or not self.resolver_id:
            raise ValueError("resolver_id must be a non-empty string")
        locations = tuple(self.exact_locations)
        if any(not isinstance(location, str) for location in locations):
            raise TypeError("exact_locations must contain strings")
        object.__setattr__(self, "exact_locations", locations)

    def to_private_dict(self) -> dict[str, Any]:
        return {
            "resolver_id": self.resolver_id,
            "exact_locations": list(self.exact_locations),
        }


@dataclass(frozen=True)
class CliDiscoveryResult:
    """A complete public CLI inventory plus its private exact-path resolver."""

    capabilities: tuple[Capability, ...] | list[Capability] = field(
        default_factory=tuple
    )
    resolvers: tuple[CliResolverRecord, ...] | list[CliResolverRecord] = field(
        default_factory=tuple
    )
    diagnostics: tuple[Diagnostic, ...] | list[Diagnostic] = field(
        default_factory=tuple
    )
    entry_count: int = 0

    def __post_init__(self) -> None:
        if self.entry_count < 0:
            raise ValueError("entry_count must not be negative")
        capabilities = tuple(self.capabilities)
        resolvers = tuple(self.resolvers)
        diagnostics = tuple(self.diagnostics)
        if any(not isinstance(item, Capability) for item in capabilities):
            raise TypeError("capabilities must contain Capability values")
        if any(not isinstance(item, CliResolverRecord) for item in resolvers):
            raise TypeError("resolvers must contain CliResolverRecord values")
        if any(not isinstance(item, Diagnostic) for item in diagnostics):
            raise TypeError("diagnostics must contain Diagnostic values")
        object.__setattr__(self, "capabilities", capabilities)
        object.__setattr__(self, "resolvers", resolvers)
        object.__setattr__(self, "diagnostics", diagnostics)


@dataclass(frozen=True)
class CliVersionProbeResult:
    """Sanitized result of one explicitly requested version probe."""

    status: str
    output: str = ""
    returncode: int | None = None
    diagnostics: tuple[Diagnostic, ...] | list[Diagnostic] = field(
        default_factory=tuple
    )

    def __post_init__(self) -> None:
        status = self.status.casefold().strip()
        if status not in _PROBE_STATUSES:
            raise ValueError(f"Unsupported probe status: {self.status!r}")
        diagnostics = tuple(self.diagnostics)
        if any(not isinstance(item, Diagnostic) for item in diagnostics):
            raise TypeError("diagnostics must contain Diagnostic values")
        object.__setattr__(self, "status", status)
        object.__setattr__(
            self,
            "output",
            sanitize_text(self.output, max_length=MAX_PROBE_OUTPUT_BYTES),
        )
        object.__setattr__(self, "diagnostics", diagnostics)

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "output": sanitize_text(self.output, max_length=MAX_PROBE_OUTPUT_BYTES),
            "returncode": self.returncode,
            "diagnostics": [item.to_public_dict() for item in self.diagnostics],
        }


@dataclass(frozen=True)
class _CliEntry:
    command_name: str
    grouping_key: str
    visible_name: str
    exact_location: str
    source: SourceLocation
    path_rank: int
    extension_rank: int
    physical_key: tuple[str, ...]
    duplicate_of: str | None = None


def _environment_value(
    environ: Mapping[str, str], key: str, *, case_insensitive: bool
) -> str | None:
    if not case_insensitive:
        return environ.get(key)
    folded_key = key.casefold()
    for candidate, value in environ.items():
        if candidate.casefold() == folded_key:
            return value
    return None


def _is_windows(platform_name: str | None, os_name: str | None) -> bool:
    current_platform = platform.system() if platform_name is None else platform_name
    current_os = os.name if os_name is None else os_name
    return current_os.casefold() == "nt" or current_platform.casefold().startswith(
        "win"
    )


def _path_segments(
    value: str | os.PathLike[str] | Iterable[str | os.PathLike[str]],
    *,
    windows: bool,
) -> tuple[str, ...]:
    if isinstance(value, os.PathLike):
        return (os.fspath(value),)
    if not isinstance(value, str):
        return tuple(os.fspath(item) for item in value)
    separator = os.pathsep
    if windows and ";" in value:
        separator = ";"
    return tuple(value.split(separator))


def _normalise_pathext(
    value: str | Iterable[str] | None,
) -> tuple[str, ...]:
    if value is None:
        candidates: Iterable[str] = DEFAULT_WINDOWS_PATHEXT
    elif isinstance(value, str):
        candidates = value.split(";")
    else:
        candidates = value
    extensions: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        extension = str(candidate).strip()
        if not extension:
            continue
        if not extension.startswith("."):
            extension = "." + extension
        folded = extension.casefold()
        if folded in seen:
            continue
        seen.add(folded)
        extensions.append(extension)
    return tuple(extensions)


def _resolve_path_directory(segment: str, cwd: Path | None) -> Path | None:
    if not segment:
        return cwd
    candidate = Path(segment)
    if candidate.is_absolute():
        return candidate
    if cwd is None:
        return None
    return cwd / candidate


def _public_path_location(path_rank: int, entry_name: str | None = None) -> str:
    prefix = f"<PATH:{path_rank + 1}>"
    if entry_name is None:
        return prefix
    return f"{prefix}::{entry_name}"


def _result_diagnostic(
    code: str,
    message: str,
    *,
    path_rank: int | None = None,
    entry_name: str | None = None,
    error: BaseException | None = None,
) -> Diagnostic:
    details: dict[str, Any] = {}
    if path_rank is not None:
        details["path_rank"] = path_rank
        details["location"] = _public_path_location(path_rank, entry_name)
    if error is not None:
        details["error_type"] = type(error).__name__
    return Diagnostic("warning", code, message, details)


def _windows_command(
    filename: str, pathext: tuple[str, ...]
) -> tuple[str, int] | None:
    folded_name = filename.casefold()
    for index, extension in enumerate(pathext):
        folded_extension = extension.casefold()
        if not folded_name.endswith(folded_extension):
            continue
        command = filename[: len(filename) - len(extension)]
        if command:
            return command, index
    return None


def _physical_key(file_stat: os.stat_result, exact_location: str) -> tuple[str, ...]:
    inode = getattr(file_stat, "st_ino", 0)
    if inode:
        return (
            "inode",
            str(getattr(file_stat, "st_dev", 0)),
            str(inode),
        )
    return ("realpath", os.path.normcase(os.path.realpath(exact_location)))


def _logical_digest(grouping_key: str, *, case_sensitive: bool) -> str:
    evidence = (
        "cli-command-v1\0"
        + ("sensitive\0" if case_sensitive else "insensitive\0")
        + grouping_key
    )
    return hashlib.sha256(evidence.encode("utf-8", errors="surrogatepass")).hexdigest()


def _safe_display_name(value: str, grouping_key: str) -> str:
    sanitized = sanitize_text(value, max_length=512)
    if sanitized:
        return sanitized
    digest = hashlib.sha256(
        grouping_key.encode("utf-8", errors="surrogatepass")
    ).hexdigest()[:12]
    return f"unnamed-cli-{digest}"


def _entry_sort_key(entry: _CliEntry, *, windows: bool) -> tuple[Any, ...]:
    command_key = (entry.grouping_key.casefold(), entry.grouping_key)
    if windows:
        return command_key + (
            entry.extension_rank,
            entry.visible_name.casefold(),
            entry.visible_name,
        )
    return command_key + (entry.visible_name.casefold(), entry.visible_name)


def _capability_sort_key(capability: Capability) -> tuple[str, str]:
    return capability.name.casefold(), capability.name


def discover_clis(
    *,
    path: str
    | os.PathLike[str]
    | Iterable[str | os.PathLike[str]]
    | None = None,
    environ: Mapping[str, str] | None = None,
    cwd: Path | os.PathLike[str] | None = None,
    platform_name: str | None = None,
    os_name: str | None = None,
    pathext: str | Iterable[str] | None = None,
) -> CliDiscoveryResult:
    """Enumerate every executable entry in an injected or environment PATH.

    Empty and relative PATH segments are considered only when ``cwd`` is
    explicitly injected. The function inspects directory metadata only; it
    never invokes a discovered command.
    """

    windows = _is_windows(platform_name, os_name)
    sensitive = not windows
    environment = os.environ if environ is None else environ
    raw_path = path
    diagnostics: list[Diagnostic] = []
    if raw_path is None:
        raw_path = _environment_value(environment, "PATH", case_insensitive=windows)
        if raw_path is None:
            return CliDiscoveryResult(
                diagnostics=(
                    Diagnostic(
                        "warning",
                        "path_missing",
                        "PATH was not supplied and is absent from the environment.",
                    ),
                )
            )

    injected_cwd = None if cwd is None else Path(cwd)
    if injected_cwd is not None and not injected_cwd.is_absolute():
        raise ValueError("cwd must be an absolute injected path")
    extensions: tuple[str, ...] = ()
    if windows:
        raw_pathext = pathext
        if raw_pathext is None:
            raw_pathext = _environment_value(
                environment, "PATHEXT", case_insensitive=True
            )
        extensions = _normalise_pathext(raw_pathext)

    entries: list[_CliEntry] = []
    physical_first: dict[tuple[str, ...], str] = {}
    for path_rank, segment in enumerate(_path_segments(raw_path, windows=windows)):
        directory = _resolve_path_directory(segment, injected_cwd)
        if directory is None:
            diagnostics.append(
                _result_diagnostic(
                    "cwd_not_injected",
                    "An empty or relative PATH entry was skipped because cwd was not injected.",
                    path_rank=path_rank,
                )
            )
            continue

        try:
            iterator = os.scandir(directory)
            try:
                directory_entries = list(iterator)
            finally:
                close = getattr(iterator, "close", None)
                if close is not None:
                    close()
        except (OSError, ValueError) as error:
            diagnostics.append(
                _result_diagnostic(
                    "path_directory_unreadable",
                    "A PATH directory could not be enumerated; discovery continued.",
                    path_rank=path_rank,
                    error=error,
                )
            )
            continue

        candidates: list[_CliEntry] = []
        for directory_entry in sorted(
            directory_entries,
            key=lambda item: (item.name.casefold(), item.name),
        ):
            entry_name = unicodedata.normalize("NFC", directory_entry.name)
            try:
                file_stat = directory_entry.stat(follow_symlinks=True)
            except (OSError, ValueError) as error:
                diagnostics.append(
                    _result_diagnostic(
                        "path_entry_unreadable",
                        "A PATH entry could not be inspected; discovery continued.",
                        path_rank=path_rank,
                        entry_name=entry_name,
                        error=error,
                    )
                )
                continue
            if not stat.S_ISREG(file_stat.st_mode):
                continue

            extension_rank = 0
            if windows:
                command_and_rank = _windows_command(entry_name, extensions)
                if command_and_rank is None:
                    continue
                command_name, extension_rank = command_and_rank
            else:
                if not file_stat.st_mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH):
                    continue
                command_name = entry_name
            normalized_command = unicodedata.normalize("NFC", command_name)
            grouping_key = (
                normalized_command if sensitive else normalized_command.casefold()
            )
            exact_location = os.path.normpath(str(directory / directory_entry.name))
            source = SourceLocation(
                _public_path_location(path_rank, entry_name),
                "extra",
                "PATH",
            )
            candidates.append(
                _CliEntry(
                    command_name=normalized_command,
                    grouping_key=grouping_key,
                    visible_name=entry_name,
                    exact_location=exact_location,
                    source=source,
                    path_rank=path_rank,
                    extension_rank=extension_rank,
                    physical_key=_physical_key(file_stat, exact_location),
                )
            )

        for candidate in sorted(
            candidates, key=lambda item: _entry_sort_key(item, windows=windows)
        ):
            duplicate_of = physical_first.get(candidate.physical_key)
            if duplicate_of is None:
                physical_first[candidate.physical_key] = candidate.source.location
            entries.append(
                _CliEntry(
                    command_name=candidate.command_name,
                    grouping_key=candidate.grouping_key,
                    visible_name=candidate.visible_name,
                    exact_location=candidate.exact_location,
                    source=candidate.source,
                    path_rank=candidate.path_rank,
                    extension_rank=candidate.extension_rank,
                    physical_key=candidate.physical_key,
                    duplicate_of=duplicate_of,
                )
            )

    grouped: dict[str, list[_CliEntry]] = {}
    for entry in entries:
        grouped.setdefault(entry.grouping_key, []).append(entry)

    pairs: list[tuple[Capability, CliResolverRecord]] = []
    for grouping_key, command_entries in grouped.items():
        effective = command_entries[0]
        capability_diagnostics: list[Diagnostic] = []
        for shadow_rank, entry in enumerate(command_entries):
            is_effective = shadow_rank == 0
            capability_diagnostics.append(
                Diagnostic(
                    "info",
                    "cli_path_entry",
                    (
                        "This PATH entry is effective."
                        if is_effective
                        else "This PATH entry is shadowed by an earlier entry."
                    ),
                    {
                        "effective": is_effective,
                        "path_rank": entry.path_rank,
                        "shadow_rank": shadow_rank,
                        "source_location": entry.source.location,
                    },
                )
            )
            if entry.duplicate_of is not None:
                capability_diagnostics.append(
                    Diagnostic(
                        "info",
                        "duplicate_physical_entry",
                        "This visible PATH entry resolves to an already observed physical file.",
                        {
                            "path_rank": entry.path_rank,
                            "shadow_rank": shadow_rank,
                            "source_location": entry.source.location,
                            "duplicate_of": entry.duplicate_of,
                        },
                    )
                )

        display_name = _safe_display_name(
            effective.command_name if sensitive else grouping_key,
            grouping_key,
        )
        aliases = (
            ()
            if sensitive or effective.command_name == grouping_key
            else (effective.command_name,)
        )
        capability = Capability(
            kind="cli",
            name=display_name,
            description="Command discovered in PATH.",
            aliases=aliases,
            tags=("cli",),
            source_locations=tuple(entry.source for entry in command_entries),
            scope="extra",
            provider="PATH",
            states=CapabilityStates(),
            diagnostics=tuple(capability_diagnostics),
            _logical_identity_digest=_logical_digest(
                grouping_key, case_sensitive=sensitive
            ),
        )
        resolver = CliResolverRecord(
            capability.resolver_id,
            tuple(entry.exact_location for entry in command_entries),
        )
        pairs.append((capability, resolver))

    pairs.sort(key=lambda pair: _capability_sort_key(pair[0]))
    return CliDiscoveryResult(
        capabilities=tuple(pair[0] for pair in pairs),
        resolvers=tuple(pair[1] for pair in pairs),
        diagnostics=tuple(diagnostics),
        entry_count=len(entries),
    )


def _minimal_probe_environment(
    environ: Mapping[str, str], *, path: str | None
) -> dict[str, str]:
    minimal: dict[str, str] = {}
    for key in _MINIMAL_ENVIRONMENT_KEYS:
        value = _environment_value(environ, key, case_insensitive=True)
        if value is not None:
            minimal[key] = value
    if path is not None:
        minimal["PATH"] = path
    minimal["NO_COLOR"] = "1"
    return minimal


class _StreamCapture:
    """Retain a bounded prefix for one stream without cross-stream races."""

    def __init__(self, limit: int, overflow: threading.Event) -> None:
        self._limit = limit
        self._retained = bytearray()
        self._overflow = overflow
        self.max_retained = 0
        self.truncated = False

    def add(self, chunk: bytes) -> None:
        if not chunk:
            return
        remaining = self._limit - len(self._retained)
        if remaining > 0:
            self._retained.extend(chunk[:remaining])
            self.max_retained = max(self.max_retained, len(self._retained))
        if len(chunk) > remaining:
            self.truncated = True
            self._overflow.set()

    def take(self) -> bytearray:
        retained = self._retained
        self._retained = bytearray()
        return retained


class _SpoolCapture:
    """Drain one stream to a temporary file without retaining it in memory."""

    def __init__(self, spool: Any, limit: int, overflow: threading.Event) -> None:
        self._spool = spool
        self._limit = limit
        self._overflow = overflow
        self._written = 0
        self.size = 0
        self.truncated = False

    def add(self, chunk: bytes) -> None:
        if not chunk:
            return
        remaining = max(0, self._limit - self._written)
        if remaining:
            retained = chunk[:remaining]
            self._spool.write(retained)
            self._written += len(retained)
        self.size += len(chunk)
        if len(chunk) > remaining:
            self.truncated = True
            self._overflow.set()

    def read_prefix(self, limit: int) -> bytes:
        self._spool.flush()
        self._spool.seek(0)
        return self._spool.read(limit)


def _drain_pipe(
    pipe: Any,
    capture: Any,
    errors: queue.SimpleQueue[Exception],
    failed: threading.Event,
    closing: threading.Event,
) -> None:
    try:
        while True:
            chunk = pipe.read(PROBE_READ_CHUNK_BYTES)
            if not chunk:
                break
            if isinstance(chunk, str):
                chunk = chunk.encode("utf-8", errors="replace")
            capture.add(chunk)
    except Exception as error:
        if not closing.is_set():
            errors.put(error)
            failed.set()


def _wait_for_process(
    process: Any,
    overflow: threading.Event,
    io_failed: threading.Event,
    *,
    timeout: float,
) -> tuple[str | None, float]:
    deadline = time.monotonic() + timeout
    while True:
        if io_failed.is_set():
            return "io_error", max(0.0, deadline - time.monotonic())
        if overflow.is_set():
            return "output_limit", max(0.0, deadline - time.monotonic())
        returncode = process.poll()
        if returncode is not None:
            return None, max(0.0, deadline - time.monotonic())
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return "timeout", 0.0
        time.sleep(min(_PROBE_POLL_SECONDS, remaining))


class _DirectProcessTree:
    """Fallback guard used by injected process doubles and unsupported hosts."""

    def __init__(self, process: Any) -> None:
        self._process = process

    def terminate(self) -> None:
        if self._process.poll() is None:
            self._process.terminate()

    def kill(self) -> None:
        if self._process.poll() is None:
            self._process.kill()

    def alive(self) -> bool:
        return self._process.poll() is None

    def close(self) -> None:
        return


class _PosixProcessTree:
    """A dedicated POSIX session whose process group is safe to signal."""

    def __init__(self, process: Any) -> None:
        self._pgid = int(process.pid)

    def _signal(self, signal_number: int) -> None:
        try:
            os.killpg(self._pgid, signal_number)
        except (ProcessLookupError, PermissionError):
            pass

    def terminate(self) -> None:
        self._signal(signal.SIGTERM)

    def kill(self) -> None:
        self._signal(signal.SIGKILL)

    def alive(self) -> bool:
        try:
            os.killpg(self._pgid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True

    def close(self) -> None:
        return


def _process_tree_guard(process: Any) -> Any:
    if os.name == "posix" and hasattr(process, "pid"):
        return _PosixProcessTree(process)
    return _DirectProcessTree(process)


def _wait_tree_exit(tree: Any, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while tree.alive():
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        time.sleep(min(_PROBE_POLL_SECONDS, remaining))
    return True


def _stop_and_reap(process: Any, tree: Any | None) -> None:
    guard = _DirectProcessTree(process) if tree is None else tree
    try:
        guard.terminate()
    except (OSError, ValueError):
        pass
    try:
        process.wait(timeout=_PROBE_TERMINATE_GRACE_SECONDS)
    except subprocess.TimeoutExpired:
        pass
    if not _wait_tree_exit(guard, _PROBE_TERMINATE_GRACE_SECONDS):
        try:
            guard.kill()
        except (OSError, ValueError):
            pass
    if process.poll() is None:
        try:
            process.kill()
        except OSError:
            pass
    try:
        process.wait(timeout=_PROBE_TERMINATE_GRACE_SECONDS)
    except subprocess.TimeoutExpired:
        pass
    guard.close()


def _close_probe_pipes(process: Any) -> None:
    for pipe in (getattr(process, "stdout", None), getattr(process, "stderr", None)):
        if pipe is None:
            continue
        try:
            pipe.close()
        except OSError:
            pass


def _join_readers(readers: Iterable[threading.Thread], timeout: float) -> None:
    deadline = time.monotonic() + timeout
    for reader in readers:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return
        reader.join(remaining)


def _combine_probe_output(
    stdout: _StreamCapture,
    stderr: _SpoolCapture,
    *,
    limit: int,
) -> tuple[str, bool]:
    combined = stdout.take()
    stderr_exists = stderr.size > 0
    if combined and stderr_exists and len(combined) < limit:
        combined.extend(b"\n")
    remaining = max(0, limit - len(combined))
    if remaining and stderr_exists:
        combined.extend(stderr.read_prefix(remaining))
    truncated = stdout.truncated or stderr.truncated or (
        stdout.max_retained + (1 if stdout.max_retained and stderr_exists else 0)
        + stderr.size
        > limit
    )
    decoded = bytes(combined[:limit]).decode("utf-8", errors="replace")
    sanitized = sanitize_text(decoded, max_length=limit)
    bounded = sanitized.encode("utf-8")[:limit]
    return bounded.decode("utf-8", errors="ignore"), truncated


def _popen_platform_options() -> dict[str, Any]:
    return {"start_new_session": True}


def _probe_diagnostic(
    code: str,
    message: str,
    *,
    details: Mapping[str, Any] | None = None,
) -> Diagnostic:
    return Diagnostic("warning", code, message, dict(details or {}))


def _validate_native_executable(value: str) -> None:
    """Require an absolute executable under the current host's path semantics."""

    if not os.path.isabs(value):
        raise ValueError(
            "executable must be an absolute path under current host semantics"
        )
    if os.name == "nt" and not os.path.splitdrive(value)[0]:
        raise ValueError(
            "executable must use native Windows drive or UNC absolute semantics"
        )
    try:
        file_stat = os.stat(value)
    except OSError as error:
        raise ValueError("executable exact path is not accessible") from error
    if not stat.S_ISREG(file_stat.st_mode):
        raise ValueError("executable exact path must identify a regular file")
    if not os.access(value, os.X_OK):
        raise ValueError("executable exact path is not executable")


def probe_cli_version(
    executable: str | os.PathLike[str],
    *,
    flags: Sequence[str] | None = None,
    path: str | None = None,
    environ: Mapping[str, str] | None = None,
    probe_platform: str | None = None,
    timeout: float = 2.0,
    output_limit: int = 4_096,
) -> CliVersionProbeResult:
    """Run one opt-in version probe from a caller-provided exact path.

    The default flag is the generic ``--version``. Callers may provide a
    different argv suffix explicitly; no command-specific flag table exists.
    Windows probing is disabled because standard-library ``Popen`` cannot
    atomically contain a suspended process in a Job Object before it runs.
    """

    executable_text = os.fspath(executable)
    if not executable_text or "\x00" in executable_text:
        raise ValueError("executable must be a non-empty exact path")
    current_probe_platform = (
        platform.system() if probe_platform is None else probe_platform
    )
    if os.name == "nt" or current_probe_platform.casefold().startswith(
        ("win", "nt")
    ):
        return CliVersionProbeResult(
            "error",
            diagnostics=(
                _probe_diagnostic(
                    "unsupported_secure_containment",
                    "Windows version probing is disabled because secure pre-execution process-tree containment is unavailable.",
                ),
            ),
        )
    _validate_native_executable(executable_text)
    if isinstance(flags, (str, bytes)):
        raise TypeError("flags must be a sequence of argument strings")
    probe_flags = ("--version",) if flags is None else tuple(flags)
    if any(not isinstance(flag, str) or "\x00" in flag for flag in probe_flags):
        raise ValueError("probe flags must be strings without NUL characters")
    if not isinstance(output_limit, int) or isinstance(output_limit, bool):
        raise TypeError("output_limit must be an integer")
    if output_limit <= 0:
        raise ValueError("output_limit must be positive")
    bounded_limit = min(output_limit, MAX_PROBE_OUTPUT_BYTES)
    try:
        requested_timeout = float(timeout)
    except (TypeError, ValueError) as error:
        raise ValueError("timeout must be a positive finite number") from error
    if not math.isfinite(requested_timeout) or requested_timeout <= 0:
        raise ValueError("timeout must be a positive finite number")
    bounded_timeout = min(requested_timeout, MAX_PROBE_TIMEOUT_SECONDS)
    source_environment = os.environ if environ is None else environ
    minimal_environment = _minimal_probe_environment(source_environment, path=path)
    argv = [executable_text, *probe_flags]

    try:
        process = subprocess.Popen(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
            env=minimal_environment,
            **_popen_platform_options(),
        )
    except Exception as error:
        return CliVersionProbeResult(
            "error",
            diagnostics=(
                _probe_diagnostic(
                    "version_probe_error",
                    "The version probe could not be completed.",
                    details={"error_type": type(error).__name__},
                ),
            ),
        )

    started_readers: list[threading.Thread] = []
    all_readers: list[threading.Thread] = []
    tree: Any | None = None
    stdout_capture: _StreamCapture | None = None
    stderr_capture: _SpoolCapture | None = None
    stderr_spool: Any | None = None
    stop_reason: str | None = None
    probe_error: Exception | None = None
    probe_io_error: Exception | None = None
    reader_errors: queue.SimpleQueue[Exception] = queue.SimpleQueue()
    reader_failed = threading.Event()
    readers_closing = threading.Event()
    try:
        tree = _process_tree_guard(process)
        overflow = threading.Event()
        stdout_capture = _StreamCapture(bounded_limit, overflow)
        stderr_spool = tempfile.TemporaryFile(mode="w+b")
        stderr_capture = _SpoolCapture(stderr_spool, bounded_limit, overflow)
        all_readers = [
            threading.Thread(
                target=_drain_pipe,
                args=(
                    pipe,
                    capture,
                    reader_errors,
                    reader_failed,
                    readers_closing,
                ),
                name=f"cli-version-{stream_name}",
                daemon=True,
            )
            for stream_name, pipe, capture in (
                ("stdout", process.stdout, stdout_capture),
                ("stderr", process.stderr, stderr_capture),
            )
            if pipe is not None
        ]
        for reader in all_readers:
            reader.start()
            started_readers.append(reader)
        stop_reason, remaining = _wait_for_process(
            process,
            overflow,
            reader_failed,
            timeout=bounded_timeout,
        )
        if stop_reason is None:
            process.wait(timeout=max(remaining, _PROBE_TERMINATE_GRACE_SECONDS))
        _stop_and_reap(process, tree)
        tree = None
        _join_readers(started_readers, _PROBE_THREAD_JOIN_SECONDS)
    except Exception as error:
        probe_error = error
        try:
            _stop_and_reap(process, tree)
            tree = None
        except Exception:
            pass
    finally:
        if tree is not None:
            try:
                _stop_and_reap(process, tree)
            except Exception:
                pass
        readers_closing.set()
        _close_probe_pipes(process)
        _join_readers(started_readers, _PROBE_THREAD_JOIN_SECONDS)

    try:
        probe_io_error = reader_errors.get_nowait()
    except queue.Empty:
        pass

    try:
        if stdout_capture is None or stderr_capture is None:
            output = ""
            truncated = False
        else:
            output, truncated = _combine_probe_output(
                stdout_capture,
                stderr_capture,
                limit=bounded_limit,
            )
    except (OSError, ValueError) as error:
        output = ""
        truncated = False
        if probe_io_error is None:
            probe_io_error = error
    except Exception as error:
        output = ""
        truncated = False
        if probe_error is None:
            probe_error = error
    finally:
        if stderr_spool is not None:
            try:
                stderr_spool.close()
            except (OSError, ValueError) as error:
                if probe_io_error is None:
                    probe_io_error = error
    if probe_io_error is not None:
        return CliVersionProbeResult(
            "error",
            output,
            process.returncode,
            diagnostics=(
                _probe_diagnostic(
                    "version_probe_io_error",
                    "Version probe output could not be collected safely.",
                    details={"error_type": type(probe_io_error).__name__},
                ),
            ),
        )
    if probe_error is not None:
        return CliVersionProbeResult(
            "error",
            output,
            process.returncode,
            diagnostics=(
                _probe_diagnostic(
                    "version_probe_error",
                    "The version probe could not be completed.",
                    details={"error_type": type(probe_error).__name__},
                ),
            ),
        )

    diagnostics: list[Diagnostic] = []
    if truncated or stop_reason == "output_limit":
        return CliVersionProbeResult(
            "output_limit",
            output,
            process.returncode,
            diagnostics=(
                _probe_diagnostic(
                    "version_probe_output_limit",
                    "Version probe output exceeded the configured limit.",
                    details={"output_limit": bounded_limit},
                ),
            ),
        )
    if stop_reason == "timeout":
        diagnostics.append(
            _probe_diagnostic(
                "version_probe_timeout",
                "The version probe timed out.",
                details={"timeout_seconds": bounded_timeout},
            )
        )
        return CliVersionProbeResult(
            "timeout",
            output,
            process.returncode,
            tuple(diagnostics),
        )
    if process.returncode != 0:
        diagnostics.append(
            _probe_diagnostic(
                "version_probe_nonzero",
                "The version probe returned a non-zero exit status.",
                details={"returncode": process.returncode},
            )
        )
        return CliVersionProbeResult(
            "nonzero",
            output,
            process.returncode,
            tuple(diagnostics),
        )
    if not output:
        diagnostics.append(
            _probe_diagnostic(
                "version_probe_no_output",
                "The version probe completed without output.",
            )
        )
        return CliVersionProbeResult(
            "no_output",
            returncode=process.returncode,
            diagnostics=tuple(diagnostics),
        )
    return CliVersionProbeResult(
        "success",
        output,
        process.returncode,
        tuple(diagnostics),
    )


__all__ = [
    "CliDiscoveryResult",
    "CliResolverRecord",
    "CliVersionProbeResult",
    "DEFAULT_WINDOWS_PATHEXT",
    "MAX_PROBE_OUTPUT_BYTES",
    "MAX_PROBE_TIMEOUT_SECONDS",
    "PROBE_READ_CHUNK_BYTES",
    "discover_clis",
    "probe_cli_version",
]

"""Complete PATH command discovery with an explicit, isolated version probe."""

from __future__ import annotations

import hashlib
import math
import os
import platform
import stat
import subprocess
import unicodedata
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path, PureWindowsPath
from typing import Any

from .models import (
    Capability,
    CapabilityStates,
    Diagnostic,
    ResolverRecord,
    SourceLocation,
)
from .sanitize import sanitize_text


DEFAULT_WINDOWS_PATHEXT = (".COM", ".EXE", ".BAT", ".CMD")
MAX_PROBE_TIMEOUT_SECONDS = 3.0
MAX_PROBE_OUTPUT_BYTES = 64 * 1024
_PROBE_STATUSES = frozenset({"success", "no_output", "nonzero", "timeout", "error"})
_MINIMAL_ENVIRONMENT_KEYS = ("PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP")


@dataclass(frozen=True)
class CliDiscoveryResult:
    """A complete public CLI inventory plus its private exact-path resolver."""

    capabilities: tuple[Capability, ...] | list[Capability] = field(
        default_factory=tuple
    )
    resolvers: tuple[ResolverRecord, ...] | list[ResolverRecord] = field(
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
        if any(not isinstance(item, ResolverRecord) for item in resolvers):
            raise TypeError("resolvers must contain ResolverRecord values")
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

    @property
    def probed_state(self) -> str:
        """Return the capability-state value represented by this attempt."""

        return "success" if self.status == "success" else self.status

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
    case_sensitive: bool | None = None,
) -> CliDiscoveryResult:
    """Enumerate every executable entry in an injected or environment PATH.

    Empty and relative PATH segments are considered only when ``cwd`` is
    explicitly injected. The function inspects directory metadata only; it
    never invokes a discovered command.
    """

    windows = _is_windows(platform_name, os_name)
    sensitive = not windows if case_sensitive is None else bool(case_sensitive)
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

    pairs: list[tuple[Capability, ResolverRecord]] = []
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

        display_name = _safe_display_name(effective.command_name, grouping_key)
        aliases = tuple(
            entry.command_name
            for entry in command_entries[1:]
            if entry.command_name != effective.command_name
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
        resolver = ResolverRecord(
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


def _bounded_probe_output(
    stdout: bytes | str | None,
    stderr: bytes | str | None,
    *,
    limit: int,
) -> tuple[str, bool]:
    def to_bytes(value: bytes | str | None) -> bytes:
        if value is None:
            return b""
        if isinstance(value, bytes):
            return value
        return value.encode("utf-8", errors="replace")

    stdout_bytes = to_bytes(stdout)
    stderr_bytes = to_bytes(stderr)
    separator = b"\n" if stdout_bytes and stderr_bytes else b""
    combined = stdout_bytes + separator + stderr_bytes
    truncated = len(combined) > limit
    bounded = combined[:limit]
    decoded = bounded.decode("utf-8", errors="replace")
    return sanitize_text(decoded, max_length=limit), truncated


def _probe_diagnostic(
    code: str,
    message: str,
    *,
    details: Mapping[str, Any] | None = None,
) -> Diagnostic:
    return Diagnostic("warning", code, message, dict(details or {}))


def _is_absolute_exact_path(value: str) -> bool:
    return Path(value).is_absolute() or PureWindowsPath(value).is_absolute()


def probe_cli_version(
    executable: str | os.PathLike[str],
    *,
    flags: Sequence[str] | None = None,
    path: str | None = None,
    environ: Mapping[str, str] | None = None,
    timeout: float = 2.0,
    output_limit: int = 4_096,
    runner: Callable[..., subprocess.CompletedProcess[Any]] | None = None,
) -> CliVersionProbeResult:
    """Run one opt-in version probe from a caller-provided exact path.

    The default flag is the generic ``--version``. Callers may provide a
    different argv suffix explicitly; no command-specific flag table exists.
    """

    executable_text = os.fspath(executable)
    if not executable_text or "\x00" in executable_text:
        raise ValueError("executable must be a non-empty exact path")
    if not _is_absolute_exact_path(executable_text):
        raise ValueError("executable must be an absolute path from a private resolver")
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
    run = subprocess.run if runner is None else runner
    argv = [executable_text, *probe_flags]

    try:
        completed = run(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
            env=minimal_environment,
            timeout=bounded_timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        output, truncated = _bounded_probe_output(
            error.output,
            error.stderr,
            limit=bounded_limit,
        )
        details: dict[str, Any] = {"timeout_seconds": bounded_timeout}
        if truncated:
            details["output_truncated"] = True
        return CliVersionProbeResult(
            "timeout",
            output,
            diagnostics=(
                _probe_diagnostic(
                    "version_probe_timeout",
                    "The version probe timed out.",
                    details=details,
                ),
            ),
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

    output, truncated = _bounded_probe_output(
        completed.stdout,
        completed.stderr,
        limit=bounded_limit,
    )
    diagnostics: list[Diagnostic] = []
    if truncated:
        diagnostics.append(
            _probe_diagnostic(
                "version_output_truncated",
                "Version probe output exceeded the configured limit and was truncated.",
                details={"output_limit": bounded_limit},
            )
        )
    if completed.returncode != 0:
        diagnostics.append(
            _probe_diagnostic(
                "version_probe_nonzero",
                "The version probe returned a non-zero exit status.",
                details={"returncode": completed.returncode},
            )
        )
        return CliVersionProbeResult(
            "nonzero",
            output,
            completed.returncode,
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
            returncode=completed.returncode,
            diagnostics=tuple(diagnostics),
        )
    return CliVersionProbeResult(
        "success",
        output,
        completed.returncode,
        tuple(diagnostics),
    )


__all__ = [
    "CliDiscoveryResult",
    "CliVersionProbeResult",
    "DEFAULT_WINDOWS_PATHEXT",
    "MAX_PROBE_OUTPUT_BYTES",
    "MAX_PROBE_TIMEOUT_SECONDS",
    "discover_clis",
    "probe_cli_version",
]

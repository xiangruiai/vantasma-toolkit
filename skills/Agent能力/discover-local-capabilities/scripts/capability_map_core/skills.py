"""Recursive, bounded, and failure-isolated local Agent Skill discovery."""

from __future__ import annotations

import errno
import hashlib
import json
import os
import re
import secrets
import stat
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

from .models import Capability, Diagnostic, ResolverRecord, SourceLocation
from .roots import RootSpec
from .sanitize import sanitize_text


MAX_FRONTMATTER_BYTES = 64 * 1024
_TOP_LEVEL_KEY_RE = re.compile(r"^([A-Za-z][A-Za-z0-9_-]*):(?:[ \t]*(.*))?$")
_METADATA_FIELDS = frozenset({"name", "description", "tags", "aliases"})
_SCOPE_PRIORITY = {"system": 0, "project": 1, "user": 2, "plugin": 3, "extra": 4}
_FD_WALK_SUPPORTED = (
    hasattr(os, "O_DIRECTORY")
    and os.open in os.supports_dir_fd
    and os.scandir in os.supports_fd
)


@dataclass(frozen=True)
class SkillDiscoveryResult:
    capabilities: tuple[Capability, ...] | list[Capability] = field(
        default_factory=tuple
    )
    resolvers: tuple[ResolverRecord, ...] | list[ResolverRecord] = field(
        default_factory=tuple
    )
    diagnostics: tuple[Diagnostic, ...] | list[Diagnostic] = field(
        default_factory=tuple
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "capabilities", tuple(self.capabilities))
        object.__setattr__(self, "resolvers", tuple(self.resolvers))
        object.__setattr__(self, "diagnostics", tuple(self.diagnostics))


@dataclass(frozen=True)
class _MetadataIssue:
    code: str
    message: str


@dataclass(frozen=True)
class _SkillMetadata:
    name: str
    description: str = ""
    tags: tuple[str, ...] = ()
    aliases: tuple[str, ...] = ()
    issues: tuple[_MetadataIssue, ...] = ()
    content_digest: str = ""


@dataclass(frozen=True)
class _Occurrence:
    visible_file: Path
    real_file: Path
    physical_key: tuple[str, ...]
    logical_parts: tuple[str, ...]
    source: SourceLocation
    origin_key: str
    via_symlink: bool
    expected_file_id: tuple[int, int] | None
    expected_stat: tuple[tuple[str, int], ...]
    frontmatter_payload: bytes
    frontmatter_truncated: bool
    read_issues: tuple[_MetadataIssue, ...]


@dataclass(frozen=True)
class _PreparedSkill:
    occurrences: tuple[_Occurrence, ...]
    representative: _Occurrence
    metadata: _SkillMetadata
    logical_identity: str
    weak_identity: bool


class _UnsupportedFrontmatter(ValueError):
    pass


class _EnvPathBlocked(Exception):
    pass


class _SourceChanged(Exception):
    pass


class _SafeOpenUnavailable(Exception):
    pass


def _symlink_failure_code(error: BaseException) -> str:
    if isinstance(error, RuntimeError) or getattr(error, "errno", None) == errno.ELOOP:
        return "symlink_loop"
    return "broken_symlink"


def _safe_location(prefix: str, parts: tuple[str, ...]) -> str:
    if not parts:
        return prefix
    if prefix.startswith("<"):
        return prefix + "::" + "::".join(parts)
    return prefix.rstrip("/") + "/" + "/".join(parts)


def _diagnostic(
    code: str,
    message: str,
    *,
    location: str,
    severity: str = "warning",
) -> Diagnostic:
    return Diagnostic(severity, code, message, {"location": location})


def _contained_by(path: Path, roots: tuple[Path, ...]) -> bool:
    for root in roots:
        try:
            path.relative_to(root)
        except ValueError:
            continue
        return True
    return False


def _is_env_segment(value: str) -> bool:
    return value.casefold() == ".env"


def _has_env_segment(path: Path) -> bool:
    return any(_is_env_segment(part) for part in path.parts)


def _resolve_symlink_chain(path: Path, *, max_links: int = 64) -> Path:
    """Resolve each link step while rejecting any case-insensitive .env segment."""

    absolute = path.absolute()
    resolved = Path(absolute.anchor)
    pending = deque(absolute.parts[1:])
    seen_links: set[tuple[Path, tuple[str, ...]]] = set()
    link_count = 0
    while pending:
        part = pending.popleft()
        if part in {"", "."}:
            continue
        if part == "..":
            resolved = resolved.parent
            continue
        if _is_env_segment(part):
            raise _EnvPathBlocked
        candidate = resolved / part
        entry_stat = os.lstat(candidate)
        if not stat.S_ISLNK(entry_stat.st_mode):
            resolved = candidate
            continue
        link_count += 1
        link_state = (candidate, tuple(pending))
        if link_count > max_links or link_state in seen_links:
            raise OSError(errno.ELOOP, "symbolic link loop")
        seen_links.add(link_state)
        target = Path(os.readlink(candidate))
        if _has_env_segment(target):
            raise _EnvPathBlocked
        target_parts = list(target.parts)
        if target.is_absolute():
            resolved = Path(target.anchor)
            target_parts = target_parts[1:]
        pending.extendleft(reversed(target_parts))
    return resolved


def _file_id(stat_result: os.stat_result) -> tuple[int, int] | None:
    inode = getattr(stat_result, "st_ino", 0)
    if not inode:
        return None
    return (getattr(stat_result, "st_dev", 0), inode)


def _root_file_id(stat_result: os.stat_result) -> tuple[int, int] | None:
    inode = getattr(stat_result, "st_ino", 0)
    if not inode:
        return None
    return (getattr(stat_result, "st_dev", 0), inode)


def _physical_key_from_stat(
    stat_result: os.stat_result, fallback_path: Path
) -> tuple[str, ...]:
    file_id = _file_id(stat_result)
    if file_id is not None:
        return ("inode", str(file_id[0]), str(file_id[1]))
    return ("realpath", os.path.normcase(str(fallback_path)))


def _fd_walk_supported() -> bool:
    return _FD_WALK_SUPPORTED


def _directory_open_flags() -> int:
    flags = os.O_RDONLY | os.O_DIRECTORY
    flags |= getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    return flags


def _file_open_flags() -> int:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    return flags


def _stat_evidence(stat_result: os.stat_result) -> tuple[tuple[str, int], ...]:
    return tuple(
        (field_name, int(getattr(stat_result, field_name)))
        for field_name in (
            "st_dev",
            "st_size",
            "st_mode",
            "st_nlink",
            "st_birthtime_ns",
            "st_ctime_ns",
            "st_mtime_ns",
        )
        if hasattr(stat_result, field_name)
    )


def _effective_scope(root: RootSpec, logical_parts: tuple[str, ...]) -> str:
    return "system" if ".system" in logical_parts else root.scope


def _walk_root(
    root: RootSpec,
    physical_root: Path,
    expected_root_id: tuple[int, int],
    allowed_roots: tuple[Path, ...],
    root_is_symlink: bool,
) -> tuple[list[_Occurrence], list[Diagnostic]]:
    occurrences: list[_Occurrence] = []
    diagnostics: list[Diagnostic] = []

    def open_verified_directory(
        path: str | Path,
        expected_id: tuple[int, int],
        *,
        directory_fd: int | None = None,
    ) -> int:
        if directory_fd is None:
            fd = os.open(path, _directory_open_flags())
        else:
            fd = os.open(
                path, _directory_open_flags(), dir_fd=directory_fd
            )
        try:
            opened = os.fstat(fd)
            if not stat.S_ISDIR(opened.st_mode) or _file_id(opened) != expected_id:
                raise _SourceChanged
            return fd
        except BaseException:
            os.close(fd)
            raise

    def read_opened_skill(
        fd: int, expected_stat: os.stat_result
    ) -> tuple[os.stat_result, bytes, bool, tuple[_MetadataIssue, ...]]:
        opened_stat = os.fstat(fd)
        if not stat.S_ISREG(opened_stat.st_mode) or not _opened_source_matches(
            opened_stat, _file_id(expected_stat), _stat_evidence(expected_stat)
        ):
            raise _SourceChanged
        try:
            payload, truncated = _read_frontmatter_fd(fd)
        except OSError:
            return (
                opened_stat,
                b"",
                False,
                (
                    _MetadataIssue(
                        "skill_read_error", "Skill frontmatter could not be read."
                    ),
                ),
            )
        return opened_stat, payload, truncated, ()

    def read_anchored_skill(
        directory_fd: int, name: str, expected_stat: os.stat_result
    ) -> tuple[os.stat_result, bytes, bool, tuple[_MetadataIssue, ...]]:
        if not getattr(os, "O_NOFOLLOW", 0) and _file_id(expected_stat) is None:
            raise _SafeOpenUnavailable
        try:
            fd = os.open(name, _file_open_flags(), dir_fd=directory_fd)
        except OSError as error:
            if error.errno in {errno.ELOOP, errno.ENOENT, errno.ENOTDIR}:
                raise _SourceChanged from error
            raise
        try:
            return read_opened_skill(fd, expected_stat)
        finally:
            os.close(fd)

    def read_verified_path_skill(
        path: Path, expected_stat: os.stat_result
    ) -> tuple[os.stat_result, bytes, bool, tuple[_MetadataIssue, ...]]:
        if not getattr(os, "O_NOFOLLOW", 0) and _file_id(expected_stat) is None:
            raise _SafeOpenUnavailable
        try:
            fd = os.open(path, _file_open_flags())
        except OSError as error:
            if error.errno in {errno.ELOOP, errno.ENOENT, errno.ENOTDIR}:
                raise _SourceChanged from error
            raise
        try:
            return read_opened_skill(fd, expected_stat)
        finally:
            os.close(fd)

    def add_occurrence(
        *,
        logical_parts: tuple[str, ...],
        visible_path: Path,
        real_file: Path,
        observed_stat: os.stat_result,
        payload: bytes,
        truncated: bool,
        read_issues: tuple[_MetadataIssue, ...],
        is_link: bool,
        reached_via_symlink: bool,
    ) -> None:
        skill_parts = logical_parts
        scope = _effective_scope(root, skill_parts)
        source = SourceLocation(
            _safe_location(root.public_prefix, skill_parts),
            scope,
            root.provider,
        )
        relative_key = "/".join(skill_parts) or "."
        occurrences.append(
            _Occurrence(
                visible_file=visible_path.absolute(),
                real_file=real_file,
                physical_key=_physical_key_from_stat(observed_stat, real_file),
                logical_parts=skill_parts,
                source=source,
                origin_key=f"{root.logical_key}:{relative_key}",
                via_symlink=reached_via_symlink or is_link,
                expected_file_id=_file_id(observed_stat),
                expected_stat=_stat_evidence(observed_stat),
                frontmatter_payload=payload,
                frontmatter_truncated=truncated,
                read_issues=read_issues,
            )
        )

    def walk(
        directory_fd: int,
        physical_directory: Path,
        logical_parts: tuple[str, ...],
        ancestors: frozenset[tuple[str, ...]],
        reached_via_symlink: bool,
    ) -> None:
        public_directory = _safe_location(root.public_prefix, logical_parts)
        try:
            directory_stat = os.fstat(directory_fd)
            directory_file_id = _file_id(directory_stat)
            if not stat.S_ISDIR(directory_stat.st_mode) or directory_file_id is None:
                diagnostics.append(
                    _diagnostic(
                        "directory_unverifiable",
                        "A Skill directory had no strong physical identity and was skipped.",
                        location=public_directory,
                    )
                )
                return
            directory_key = (
                "inode",
                str(directory_file_id[0]),
                str(directory_file_id[1]),
            )
            if directory_key in ancestors:
                diagnostics.append(
                    _diagnostic(
                        "symlink_loop",
                        "A directory link loop was skipped.",
                        location=public_directory,
                    )
                )
                return
            next_ancestors = ancestors | {directory_key}
            iterator = None
            try:
                iterator = os.scandir(directory_fd)
                names = sorted(entry.name for entry in iterator)
            finally:
                if iterator is not None:
                    iterator.close()
        except OSError:
            diagnostics.append(
                _diagnostic(
                    "directory_read_error",
                    "A Skill directory could not be read.",
                    location=public_directory,
                )
            )
            return
        finally:
            if 'names' not in locals():
                os.close(directory_fd)

        try:
            for name in names:
                if _is_env_segment(name):
                    diagnostics.append(
                        _diagnostic(
                            "env_path_blocked",
                            "A .env filesystem entry was skipped without reading it.",
                            location=_safe_location(
                                root.public_prefix, logical_parts + (name,)
                            ),
                        )
                    )
                    continue
                physical_path = physical_directory / name
                child_parts = logical_parts + (name,)
                visible_path = root.path.joinpath(*child_parts).absolute()
                public_child = _safe_location(root.public_prefix, child_parts)
                try:
                    entry_stat = os.stat(
                        name, dir_fd=directory_fd, follow_symlinks=False
                    )
                    is_link = stat.S_ISLNK(entry_stat.st_mode)
                    if is_link:
                        try:
                            anchored_target = Path(os.readlink(name, dir_fd=directory_fd))
                            if _has_env_segment(anchored_target):
                                raise _EnvPathBlocked
                            resolved = _resolve_symlink_chain(physical_path)
                        except _EnvPathBlocked:
                            diagnostics.append(
                                _diagnostic(
                                    "env_path_blocked",
                                    "A symbolic link chain passing through .env was skipped without reading it.",
                                    location=public_child,
                                )
                            )
                            continue
                        except PermissionError:
                            diagnostics.append(
                                _diagnostic(
                                    "permission_denied",
                                    "A symbolic link chain could not be inspected due to permissions.",
                                    location=public_child,
                                )
                            )
                            continue
                        except (OSError, RuntimeError) as error:
                            code = _symlink_failure_code(error)
                            diagnostics.append(
                                _diagnostic(
                                    code,
                                    (
                                        "A symbolic link loop was skipped."
                                        if code == "symlink_loop"
                                        else "A broken symbolic link was skipped."
                                    ),
                                    location=public_child,
                                )
                            )
                            continue
                        if _has_env_segment(resolved):
                            diagnostics.append(
                                _diagnostic(
                                    "env_path_blocked",
                                    "A symbolic link resolving through .env was skipped without reading it.",
                                    location=public_child,
                                )
                            )
                            continue
                        if not _contained_by(resolved, allowed_roots):
                            diagnostics.append(
                                _diagnostic(
                                    "symlink_outside_allowed_roots",
                                    "A symbolic link target outside allowed roots was skipped.",
                                    location=public_child,
                                )
                            )
                            continue
                        target_stat = os.stat(resolved, follow_symlinks=False)
                        if stat.S_ISDIR(target_stat.st_mode):
                            target_id = _file_id(target_stat)
                            if target_id is None:
                                diagnostics.append(
                                    _diagnostic(
                                        "directory_unverifiable",
                                        "A linked Skill directory had no strong physical identity and was skipped.",
                                        location=public_child,
                                    )
                                )
                                continue
                            target_fd = open_verified_directory(
                                resolved, target_id
                            )
                            walk(
                                target_fd,
                                resolved,
                                child_parts,
                                next_ancestors,
                                True,
                            )
                            continue
                        if name != "SKILL.md" or not stat.S_ISREG(
                            target_stat.st_mode
                        ):
                            continue
                        try:
                            observed_stat, payload, truncated, read_issues = (
                                read_verified_path_skill(resolved, target_stat)
                            )
                        except OSError:
                            observed_stat = target_stat
                            payload = b""
                            truncated = False
                            read_issues = (
                                _MetadataIssue(
                                    "skill_read_error",
                                    "Skill frontmatter could not be read.",
                                ),
                            )
                        real_file = resolved
                    elif stat.S_ISDIR(entry_stat.st_mode):
                        child_id = _file_id(entry_stat)
                        if child_id is None:
                            diagnostics.append(
                                _diagnostic(
                                    "directory_unverifiable",
                                    "A Skill directory had no strong physical identity and was skipped.",
                                    location=public_child,
                                )
                            )
                            continue
                        child_fd = open_verified_directory(
                            name, child_id, directory_fd=directory_fd
                        )
                        walk(
                            child_fd,
                            physical_path,
                            child_parts,
                            next_ancestors,
                            reached_via_symlink,
                        )
                        continue
                    elif name == "SKILL.md" and stat.S_ISREG(entry_stat.st_mode):
                        try:
                            observed_stat, payload, truncated, read_issues = (
                                read_anchored_skill(directory_fd, name, entry_stat)
                            )
                        except OSError:
                            observed_stat = entry_stat
                            payload = b""
                            truncated = False
                            read_issues = (
                                _MetadataIssue(
                                    "skill_read_error",
                                    "Skill frontmatter could not be read.",
                                ),
                            )
                        real_file = physical_path
                    else:
                        continue
                except _SafeOpenUnavailable:
                    diagnostics.append(
                        _diagnostic(
                            "safe_open_unavailable",
                            "This platform cannot safely open a Skill without symlink following or a stable file ID.",
                            location=public_child,
                        )
                    )
                    continue
                except _SourceChanged:
                    diagnostics.append(
                        _diagnostic(
                            "source_changed",
                            "A Skill source changed during discovery and was skipped without reading it.",
                            location=public_child,
                        )
                    )
                    continue
                except OSError:
                    diagnostics.append(
                        _diagnostic(
                            "entry_read_error",
                            "A filesystem entry could not be inspected.",
                            location=public_child,
                        )
                    )
                    continue

                add_occurrence(
                    logical_parts=logical_parts,
                    visible_path=visible_path,
                    real_file=real_file,
                    observed_stat=observed_stat,
                    payload=payload,
                    truncated=truncated,
                    read_issues=read_issues,
                    is_link=is_link,
                    reached_via_symlink=reached_via_symlink,
                )
        finally:
            os.close(directory_fd)

    try:
        root_fd = open_verified_directory(physical_root, expected_root_id)
    except _SourceChanged:
        diagnostics.append(
            _diagnostic(
                "root_changed",
                "A verified Skill root changed before its directory handle was opened.",
                location=root.public_prefix,
            )
        )
        return occurrences, diagnostics
    except OSError as error:
        code = (
            "root_changed"
            if error.errno in {errno.ELOOP, errno.ENOENT, errno.ENOTDIR}
            else "directory_read_error"
        )
        diagnostics.append(
            _diagnostic(
                code,
                "A verified Skill root could not be opened safely.",
                location=root.public_prefix,
            )
        )
        return occurrences, diagnostics
    walk(root_fd, physical_root, (), frozenset(), root_is_symlink)
    return occurrences, diagnostics


def _parse_quoted_scalar(value: str) -> str:
    if value.startswith('"'):
        if not value.endswith('"') or len(value) < 2:
            raise _UnsupportedFrontmatter("unterminated double-quoted scalar")
        try:
            parsed = json.loads(value)
        except (json.JSONDecodeError, TypeError) as error:
            raise _UnsupportedFrontmatter("unsupported double-quoted scalar") from error
        if not isinstance(parsed, str):
            raise _UnsupportedFrontmatter("quoted scalar is not text")
        return parsed
    if value.startswith("'"):
        if not value.endswith("'") or len(value) < 2:
            raise _UnsupportedFrontmatter("unterminated single-quoted scalar")
        return value[1:-1].replace("''", "'")
    if value.endswith(("'", '"')):
        raise _UnsupportedFrontmatter("mismatched scalar quotes")
    if value.startswith(("[", "{", "&", "*", "!")):
        raise _UnsupportedFrontmatter("unsupported scalar syntax")
    return value


def _strip_yaml_inline_comment(value: str) -> str:
    quote: str | None = None
    escaped = False
    index = 0
    while index < len(value):
        character = value[index]
        if quote == '"':
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == quote:
                quote = None
        elif quote == "'":
            if character == quote:
                if index + 1 < len(value) and value[index + 1] == quote:
                    index += 1
                else:
                    quote = None
        elif character in {"'", '"'}:
            quote = character
        elif character == "#" and (index == 0 or value[index - 1].isspace()):
            return value[:index].rstrip()
        index += 1
    return value


def _split_inline_list(value: str) -> tuple[str, ...]:
    if not value.endswith("]"):
        raise _UnsupportedFrontmatter("unterminated inline list")
    interior = value[1:-1].strip()
    if not interior:
        return ()
    items: list[str] = []
    current: list[str] = []
    quote: str | None = None
    escaped = False
    index = 0
    while index < len(interior):
        character = interior[index]
        if quote == '"':
            current.append(character)
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == quote:
                quote = None
        elif quote == "'":
            current.append(character)
            if character == quote:
                if index + 1 < len(interior) and interior[index + 1] == quote:
                    current.append(interior[index + 1])
                    index += 1
                else:
                    quote = None
        elif character in {"'", '"'}:
            quote = character
            current.append(character)
        elif character == ",":
            item = "".join(current).strip()
            if not item:
                raise _UnsupportedFrontmatter("empty inline-list item")
            items.append(_parse_quoted_scalar(item))
            current = []
        elif character in "[]{}":
            raise _UnsupportedFrontmatter("nested inline collections are unsupported")
        else:
            current.append(character)
        index += 1
    if quote is not None:
        raise _UnsupportedFrontmatter("unterminated quote in inline list")
    item = "".join(current).strip()
    if not item:
        raise _UnsupportedFrontmatter("empty inline-list item")
    items.append(_parse_quoted_scalar(item))
    return tuple(items)


def _indented_block(
    lines: list[str], start: int
) -> tuple[list[str], int]:
    block: list[str] = []
    index = start
    while index < len(lines):
        line = lines[index]
        if line and not line[0].isspace():
            break
        block.append(line)
        index += 1
    return block, index


def _strip_block_indentation(lines: list[str]) -> list[str]:
    nonempty = [line for line in lines if line.strip()]
    if not nonempty:
        return []
    indentation = min(len(line) - len(line.lstrip(" ")) for line in nonempty)
    if indentation == 0 or any("\t" in line[:indentation] for line in nonempty):
        raise _UnsupportedFrontmatter("multiline values must be space-indented")
    return [line[indentation:] if line.strip() else "" for line in lines]


def _parse_metadata_subset(frontmatter: str) -> dict[str, object]:
    lines = frontmatter.splitlines()
    values: dict[str, object] = {}
    index = 0
    while index < len(lines):
        line = lines[index]
        if not line.strip() or line.lstrip().startswith("#"):
            index += 1
            continue
        if line[0].isspace() or "\t" in line:
            raise _UnsupportedFrontmatter("unexpected indentation or tab")
        match = _TOP_LEVEL_KEY_RE.fullmatch(line)
        if match is None:
            raise _UnsupportedFrontmatter("unsupported top-level YAML syntax")
        key = match.group(1)
        raw_value = _strip_yaml_inline_comment(
            (match.group(2) or "").strip()
        )
        index += 1
        if key not in _METADATA_FIELDS:
            if not raw_value or raw_value in {"|", ">"}:
                _, index = _indented_block(lines, index)
            continue
        if key in values:
            raise _UnsupportedFrontmatter(f"duplicate metadata key: {key}")
        if raw_value in {"|", ">"}:
            if key not in {"name", "description"}:
                raise _UnsupportedFrontmatter("multiline list fields are unsupported")
            block, index = _indented_block(lines, index)
            normalized = _strip_block_indentation(block)
            values[key] = (
                "\n".join(normalized).strip()
                if raw_value == "|"
                else " ".join(part.strip() for part in normalized).strip()
            )
            continue
        if key in {"tags", "aliases"}:
            if raw_value.startswith("["):
                values[key] = _split_inline_list(raw_value)
            elif raw_value:
                values[key] = (_parse_quoted_scalar(raw_value),)
            else:
                block, index = _indented_block(lines, index)
                normalized = _strip_block_indentation(block)
                items: list[str] = []
                for item_line in normalized:
                    if not item_line.strip():
                        continue
                    if not item_line.startswith("- "):
                        raise _UnsupportedFrontmatter(
                            "block lists require simple dash-prefixed items"
                        )
                    item = _strip_yaml_inline_comment(item_line[2:].strip())
                    if not item:
                        raise _UnsupportedFrontmatter("empty block-list item")
                    items.append(_parse_quoted_scalar(item))
                values[key] = tuple(items)
            continue
        if not raw_value:
            values[key] = ""
        else:
            values[key] = _parse_quoted_scalar(raw_value)
    return values


def _opened_source_matches(
    stat_result: os.stat_result,
    expected_file_id: tuple[int, int] | None,
    expected_stat: tuple[tuple[str, int], ...],
) -> bool:
    opened_file_id = _file_id(stat_result)
    if expected_file_id is not None:
        return opened_file_id == expected_file_id
    return _stat_evidence(stat_result) == expected_stat


def _read_frontmatter_fd(fd: int) -> tuple[bytes, bool]:
    chunks: list[bytes] = []
    total = 0
    line_number = 0
    while total <= MAX_FRONTMATTER_BYTES:
        remaining = MAX_FRONTMATTER_BYTES - total
        line_chunks: list[bytes] = []
        while len(line_chunks) <= remaining:
            byte = os.read(fd, 1)
            if not byte:
                break
            line_chunks.append(byte)
            if byte == b"\n":
                break
        line = b"".join(line_chunks)
        if not line:
            return b"".join(chunks), False
        if len(line) > remaining:
            chunks.append(line[:remaining])
            return b"".join(chunks), True
        chunks.append(line)
        total += len(line)
        marker = line.rstrip(b"\r\n")
        if line_number == 0:
            marker = marker.removeprefix(b"\xef\xbb\xbf")
            if marker.strip() != b"---":
                return b"".join(chunks), False
        elif marker.strip() in {b"---", b"..."}:
            return b"".join(chunks), False
        line_number += 1
    return b"".join(chunks), True


def _skill_metadata(
    occurrence: _Occurrence, fallback_name: str
) -> _SkillMetadata:
    issues = list(occurrence.read_issues)
    if not sanitize_text(fallback_name, max_length=512):
        fallback_name = "unnamed-skill"
        issues.append(
            _MetadataIssue(
                "metadata_fallback_invalid",
                "Skill directory name was empty after sanitization; a neutral fallback was used.",
            )
        )
    if occurrence.read_issues:
        return _SkillMetadata(
            fallback_name,
            issues=tuple(issues),
        )
    payload = occurrence.frontmatter_payload
    truncated = occurrence.frontmatter_truncated
    content_digest = hashlib.sha256(payload).hexdigest()
    try:
        text = payload.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = payload.decode("utf-8-sig", errors="replace")
        issues.append(
            _MetadataIssue(
                "non_utf8_frontmatter",
                "Skill frontmatter contained non-UTF-8 bytes and was decoded with replacement.",
            )
        )
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        issues.append(
            _MetadataIssue(
                "invalid_frontmatter", "Skill frontmatter opening marker is missing."
            )
        )
        return _SkillMetadata(
            fallback_name, issues=tuple(issues), content_digest=content_digest
        )
    closing_index: int | None = None
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() in {"---", "..."}:
            closing_index = index
            break
    if closing_index is None:
        code = "frontmatter_too_large" if truncated else "invalid_frontmatter"
        issues.append(
            _MetadataIssue(code, "Skill frontmatter closing marker was not found.")
        )
        return _SkillMetadata(
            fallback_name, issues=tuple(issues), content_digest=content_digest
        )
    frontmatter = "\n".join(lines[1:closing_index])
    try:
        values = _parse_metadata_subset(frontmatter)
    except _UnsupportedFrontmatter:
        issues.append(
            _MetadataIssue(
                "invalid_frontmatter",
                "Skill frontmatter uses invalid or unsupported YAML syntax.",
            )
        )
        return _SkillMetadata(
            fallback_name, issues=tuple(issues), content_digest=content_digest
        )
    name = values.get("name", "")
    if not isinstance(name, str) or not name.strip():
        issues.append(
            _MetadataIssue(
                "metadata_name_missing",
                "Skill metadata has no usable name; the directory name was used.",
            )
        )
        name = fallback_name
    elif not sanitize_text(name, max_length=512):
        issues.append(
            _MetadataIssue(
                "metadata_name_invalid",
                "Skill metadata name was empty after sanitization; the directory name was used.",
            )
        )
        name = fallback_name
    description = values.get("description", "")
    tags = values.get("tags", ())
    aliases = values.get("aliases", ())
    if not isinstance(description, str):
        description = ""
    if not isinstance(tags, tuple):
        tags = ()
    if not isinstance(aliases, tuple):
        aliases = ()
    return _SkillMetadata(
        name.strip(),
        description.strip(),
        tags,
        aliases,
        tuple(issues),
        content_digest,
    )


def _occurrence_order(occurrence: _Occurrence) -> tuple[object, ...]:
    return (
        occurrence.via_symlink,
        _SCOPE_PRIORITY.get(occurrence.source.scope, 99),
        occurrence.source.provider.casefold(),
        occurrence.origin_key,
    )


def _logical_identity(
    occurrences: list[_Occurrence], canonical: _Occurrence, content_digest: str
) -> tuple[str, bool]:
    """Hash path-independent physical evidence, with a deterministic fallback.

    A non-symlink occurrence is canonical before aliases. File IDs make identity
    invariant to the visible entry set and distinguish byte-identical copies.
    Filesystems without file IDs use bounded content plus normalized non-path
    stat evidence and surface that weaker guarantee as a diagnostic.
    """

    physical_key = occurrences[0].physical_key
    if physical_key[0] == "inode":
        evidence: dict[str, object] = {
            "kind": "file-id",
            "device": physical_key[1],
            "file_id": physical_key[2],
        }
        weak = False
    else:
        evidence = {
            "kind": "content-stat-fallback",
            "content_digest": content_digest,
            "stat": dict(canonical.expected_stat),
        }
        weak = True
    encoded = json.dumps(
        evidence, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return "skill-physical-v2:" + hashlib.sha256(encoded).hexdigest(), weak


def _ambiguous_identity_nonce() -> str:
    return secrets.token_hex(16)


def discover_skills(roots: list[RootSpec] | tuple[RootSpec, ...]) -> SkillDiscoveryResult:
    """Discover physical Skills under allowed roots without reading Skill bodies."""

    root_specs = tuple(roots)
    global_diagnostics: list[Diagnostic] = []
    resolved_roots: list[tuple[RootSpec, Path, bool, tuple[int, int]]] = []
    for root in root_specs:
        if not _fd_walk_supported():
            global_diagnostics.append(
                _diagnostic(
                    "root_unverifiable",
                    "This platform cannot bind Skill traversal to directory handles.",
                    location=root.public_prefix,
                )
            )
            continue
        try:
            source_stat = os.lstat(root.path)
        except FileNotFoundError:
            continue
        except OSError:
            global_diagnostics.append(
                _diagnostic(
                    "root_stat_error",
                    "A configured Skill root could not be inspected.",
                    location=root.public_prefix,
                )
            )
            continue
        root_is_link = stat.S_ISLNK(source_stat.st_mode)
        try:
            real_root = _resolve_symlink_chain(root.path)
        except _EnvPathBlocked:
            global_diagnostics.append(
                _diagnostic(
                    "env_path_blocked",
                    "A configured Skill root chain passing through .env was skipped without reading it.",
                    location=root.public_prefix,
                )
            )
            continue
        except PermissionError:
            global_diagnostics.append(
                _diagnostic(
                    "permission_denied",
                    "A configured Skill root symlink chain could not be inspected due to permissions.",
                    location=root.public_prefix,
                )
            )
            continue
        except (OSError, RuntimeError) as error:
            if root_is_link and _symlink_failure_code(error) == "symlink_loop":
                code = "root_symlink_loop"
                message = "A configured Skill root contains a symbolic link loop."
            elif root_is_link and isinstance(error, FileNotFoundError):
                code = "broken_symlink"
                message = "A configured Skill root is a broken symbolic link."
            else:
                code = "root_resolve_error"
                message = "A configured Skill root could not be resolved."
            global_diagnostics.append(
                _diagnostic(code, message, location=root.public_prefix)
            )
            continue
        try:
            target_stat = real_root.stat()
        except OSError:
            global_diagnostics.append(
                _diagnostic(
                    "root_stat_error",
                    "A configured Skill root target could not be inspected.",
                    location=root.public_prefix,
                )
            )
            continue
        if not stat.S_ISDIR(target_stat.st_mode):
            global_diagnostics.append(
                _diagnostic(
                    "root_not_directory",
                    "A configured Skill root is not a directory.",
                    location=root.public_prefix,
                )
            )
            continue
        root_file_id = _root_file_id(target_stat)
        if root_file_id is None:
            global_diagnostics.append(
                _diagnostic(
                    "root_unverifiable",
                    "A configured Skill root had no strong physical identity and was skipped.",
                    location=root.public_prefix,
                )
            )
            continue
        if _has_env_segment(real_root):
            global_diagnostics.append(
                _diagnostic(
                    "env_path_blocked",
                    "A configured Skill root resolving through .env was skipped without reading it.",
                    location=root.public_prefix,
                )
            )
            continue
        resolved_roots.append((root, real_root, root_is_link, root_file_id))
    allowed_roots = tuple(
        sorted(
            {real for _, real, _, _ in resolved_roots}, key=lambda path: str(path)
        )
    )

    grouped: dict[tuple[str, ...], list[_Occurrence]] = {}
    for root, physical_root, root_is_link, root_file_id in resolved_roots:
        root_occurrences, root_diagnostics = _walk_root(
            root, physical_root, root_file_id, allowed_roots, root_is_link
        )
        global_diagnostics.extend(root_diagnostics)
        for occurrence in root_occurrences:
            grouped.setdefault(occurrence.physical_key, []).append(occurrence)

    prepared_skills: list[_PreparedSkill] = []
    for occurrences in grouped.values():
        ordered_occurrences = sorted(
            occurrences,
            key=_occurrence_order,
        )
        representative = ordered_occurrences[0]
        metadata = _skill_metadata(
            representative, representative.real_file.parent.name
        )
        logical_identity, weak_identity = _logical_identity(
            occurrences, representative, metadata.content_digest
        )
        prepared_skills.append(
            _PreparedSkill(
                tuple(occurrences),
                representative,
                metadata,
                logical_identity,
                weak_identity,
            )
        )

    ambiguous_nonces: dict[int, str] = {}
    weak_groups: dict[str, list[int]] = {}
    for index, prepared in enumerate(prepared_skills):
        if prepared.weak_identity:
            weak_groups.setdefault(prepared.logical_identity, []).append(index)
    for indexes in weak_groups.values():
        if len(indexes) < 2:
            continue
        for index in indexes:
            ambiguous_nonces[index] = _ambiguous_identity_nonce()

    capability_pairs: list[tuple[Capability, ResolverRecord]] = []
    for index, prepared in enumerate(prepared_skills):
        occurrences = prepared.occurrences
        representative = prepared.representative
        metadata = prepared.metadata
        logical_identity = prepared.logical_identity
        item_diagnostics = [
            _diagnostic(
                issue.code,
                issue.message,
                location=representative.source.location,
            )
            for issue in metadata.issues
        ]
        if prepared.weak_identity:
            item_diagnostics.append(
                _diagnostic(
                    "weak_physical_identity",
                    "No stable file ID was available; identity uses bounded content and non-path stat evidence.",
                    location=representative.source.location,
                    severity="info",
                )
            )
        ambiguous_nonce = ambiguous_nonces.get(index)
        if ambiguous_nonce is not None:
            logical_identity += f":ambiguous-nonce:{ambiguous_nonce}"
            item_diagnostics.append(
                _diagnostic(
                    "unstable_ambiguous_identity",
                    "Multiple physical Skills had indistinguishable fallback evidence; random path-independent identities were assigned for this scan only.",
                    location=representative.source.location,
                )
            )
        immutable_item_diagnostics = tuple(item_diagnostics)
        global_diagnostics.extend(immutable_item_diagnostics)
        sources = tuple(
            sorted(
                {occurrence.source for occurrence in occurrences},
                key=lambda source: (
                    source.location.casefold(),
                    source.scope,
                    source.provider.casefold(),
                ),
            )
        )
        capability = Capability(
            kind="skill",
            name=metadata.name,
            description=metadata.description,
            aliases=metadata.aliases,
            tags=metadata.tags,
            source_locations=sources,
            scope="extra",
            provider="local-skill",
            diagnostics=immutable_item_diagnostics,
            logical_identity=logical_identity,
        )
        exact_locations = {
            str(occurrence.visible_file) for occurrence in occurrences
        }
        exact_locations.update(str(occurrence.real_file) for occurrence in occurrences)
        resolver = ResolverRecord(capability.resolver_id, sorted(exact_locations))
        capability_pairs.append((capability, resolver))

    capability_pairs.sort(
        key=lambda pair: (pair[0].name.casefold(), pair[0].name, pair[0].id)
    )
    diagnostics = tuple(
        sorted(
            global_diagnostics,
            key=lambda item: (
                item.code,
                item.message,
                json.dumps(item.to_public_dict(), ensure_ascii=False, sort_keys=True),
            ),
        )
    )
    return SkillDiscoveryResult(
        capabilities=tuple(pair[0] for pair in capability_pairs),
        resolvers=tuple(pair[1] for pair in capability_pairs),
        diagnostics=diagnostics,
    )


__all__ = ["MAX_FRONTMATTER_BYTES", "SkillDiscoveryResult", "discover_skills"]

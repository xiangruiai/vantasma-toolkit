"""Recursive, bounded, and failure-isolated local Agent Skill discovery."""

from __future__ import annotations

import errno
import hashlib
import json
import os
import re
import stat
from dataclasses import dataclass, field
from pathlib import Path

from .models import Capability, Diagnostic, ResolverRecord, SourceLocation
from .roots import RootSpec
from .sanitize import sanitize_text


MAX_FRONTMATTER_BYTES = 64 * 1024
_TOP_LEVEL_KEY_RE = re.compile(r"^([A-Za-z][A-Za-z0-9_-]*):(?:[ \t]*(.*))?$")
_METADATA_FIELDS = frozenset({"name", "description", "tags", "aliases"})
_SCOPE_PRIORITY = {"system": 0, "project": 1, "user": 2, "plugin": 3, "extra": 4}


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


@dataclass(frozen=True)
class _Occurrence:
    visible_file: Path
    real_file: Path
    physical_key: tuple[str, ...]
    logical_parts: tuple[str, ...]
    source: SourceLocation
    origin_key: str
    via_symlink: bool


class _UnsupportedFrontmatter(ValueError):
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


def _has_env_segment(path: Path) -> bool:
    return ".env" in path.parts


def _physical_key(path: Path) -> tuple[str, ...]:
    stat_result = path.stat()
    inode = getattr(stat_result, "st_ino", 0)
    device = getattr(stat_result, "st_dev", 0)
    if inode:
        return ("inode", str(device), str(inode))
    return ("realpath", os.path.normcase(str(path.resolve(strict=True))))


def _effective_scope(root: RootSpec, logical_parts: tuple[str, ...]) -> str:
    return "system" if ".system" in logical_parts else root.scope


def _walk_root(
    root: RootSpec,
    allowed_roots: tuple[Path, ...],
    root_is_symlink: bool,
) -> tuple[list[_Occurrence], list[Diagnostic]]:
    occurrences: list[_Occurrence] = []
    diagnostics: list[Diagnostic] = []

    def walk(
        visible_directory: Path,
        logical_parts: tuple[str, ...],
        ancestors: frozenset[tuple[str, ...]],
        reached_via_symlink: bool,
    ) -> None:
        public_directory = _safe_location(root.public_prefix, logical_parts)
        try:
            real_directory = visible_directory.resolve(strict=True)
            directory_key = _physical_key(real_directory)
        except OSError:
            diagnostics.append(
                _diagnostic(
                    "directory_read_error",
                    "Could not resolve a directory while scanning Skills.",
                    location=public_directory,
                )
            )
            return
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
        try:
            with os.scandir(visible_directory) as iterator:
                entries = sorted(iterator, key=lambda entry: entry.name)
        except OSError:
            diagnostics.append(
                _diagnostic(
                    "directory_read_error",
                    "A Skill directory could not be read.",
                    location=public_directory,
                )
            )
            return

        for entry in entries:
            if entry.name == ".env":
                continue
            visible_path = Path(entry.path)
            child_parts = logical_parts + (entry.name,)
            public_child = _safe_location(root.public_prefix, child_parts)
            try:
                is_link = entry.is_symlink()
                if is_link:
                    try:
                        resolved = visible_path.resolve(strict=True)
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
                    if resolved.is_dir():
                        walk(visible_path, child_parts, next_ancestors, True)
                        continue
                    if entry.name != "SKILL.md" or not resolved.is_file():
                        continue
                    real_file = resolved
                elif entry.is_dir(follow_symlinks=False):
                    walk(
                        visible_path,
                        child_parts,
                        next_ancestors,
                        reached_via_symlink,
                    )
                    continue
                elif entry.name == "SKILL.md" and entry.is_file(
                    follow_symlinks=False
                ):
                    real_file = visible_path.resolve(strict=True)
                else:
                    continue
                file_key = _physical_key(real_file)
            except OSError:
                diagnostics.append(
                    _diagnostic(
                        "entry_read_error",
                        "A filesystem entry could not be inspected.",
                        location=public_child,
                    )
                )
                continue

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
                    physical_key=file_key,
                    logical_parts=skill_parts,
                    source=source,
                    origin_key=f"{root.logical_key}:{relative_key}",
                    via_symlink=reached_via_symlink or is_link,
                )
            )

    walk(root.path, (), frozenset(), root_is_symlink)
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
                    item = item_line[2:].strip()
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


def _read_frontmatter_prefix(path: Path) -> tuple[bytes, bool]:
    with open(path, "rb") as handle:
        chunks: list[bytes] = []
        total = 0
        line_number = 0
        while total <= MAX_FRONTMATTER_BYTES:
            remaining = MAX_FRONTMATTER_BYTES - total
            line = handle.readline(remaining + 1)
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


def _skill_metadata(path: Path, fallback_name: str) -> _SkillMetadata:
    issues: list[_MetadataIssue] = []
    if not sanitize_text(fallback_name, max_length=512):
        fallback_name = "unnamed-skill"
        issues.append(
            _MetadataIssue(
                "metadata_fallback_invalid",
                "Skill directory name was empty after sanitization; a neutral fallback was used.",
            )
        )
    try:
        payload, truncated = _read_frontmatter_prefix(path)
    except OSError:
        issues.append(
            _MetadataIssue(
                "skill_read_error", "Skill frontmatter could not be read."
            )
        )
        return _SkillMetadata(
            fallback_name,
            issues=tuple(issues),
        )
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
        return _SkillMetadata(fallback_name, issues=tuple(issues))
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
        return _SkillMetadata(fallback_name, issues=tuple(issues))
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
        return _SkillMetadata(fallback_name, issues=tuple(issues))
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
    )


def _occurrence_order(occurrence: _Occurrence) -> tuple[object, ...]:
    return (
        occurrence.via_symlink,
        _SCOPE_PRIORITY.get(occurrence.source.scope, 99),
        occurrence.source.provider.casefold(),
        occurrence.origin_key,
    )


def _logical_identity(
    occurrences: list[_Occurrence], canonical: _Occurrence
) -> str:
    """Hash path-independent physical evidence, with a deterministic fallback.

    A non-symlink occurrence is canonical before aliases. File IDs make identity
    invariant to the visible entry set and distinguish byte-identical copies.
    Filesystems without file IDs fall back to a canonical logical origin plus
    non-sensitive stat evidence, never a real or absolute path.
    """

    physical_key = occurrences[0].physical_key
    if physical_key[0] == "inode":
        evidence: dict[str, object] = {
            "kind": "file-id",
            "device": physical_key[1],
            "file_id": physical_key[2],
        }
    else:
        stat_result = canonical.real_file.stat()
        evidence = {
            "kind": "logical-stat-fallback",
            "origin": canonical.origin_key,
            "device": str(getattr(stat_result, "st_dev", 0)),
            "size": stat_result.st_size,
            "modified_ns": getattr(stat_result, "st_mtime_ns", 0),
            "changed_ns": getattr(stat_result, "st_ctime_ns", 0),
        }
    encoded = json.dumps(
        evidence, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return "skill-origin-v1:" + hashlib.sha256(encoded).hexdigest()


def discover_skills(roots: list[RootSpec] | tuple[RootSpec, ...]) -> SkillDiscoveryResult:
    """Discover physical Skills under allowed roots without reading Skill bodies."""

    root_specs = tuple(roots)
    global_diagnostics: list[Diagnostic] = []
    resolved_roots: list[tuple[RootSpec, Path, bool]] = []
    for root in root_specs:
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
            real_root = root.path.resolve(strict=True)
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
        if _has_env_segment(real_root):
            global_diagnostics.append(
                _diagnostic(
                    "env_path_blocked",
                    "A configured Skill root resolving through .env was skipped without reading it.",
                    location=root.public_prefix,
                )
            )
            continue
        resolved_roots.append((root, real_root, root_is_link))
    allowed_roots = tuple(
        sorted({real for _, real, _ in resolved_roots}, key=lambda path: str(path))
    )

    grouped: dict[tuple[str, ...], list[_Occurrence]] = {}
    for root, _, root_is_link in resolved_roots:
        root_occurrences, root_diagnostics = _walk_root(
            root, allowed_roots, root_is_link
        )
        global_diagnostics.extend(root_diagnostics)
        for occurrence in root_occurrences:
            grouped.setdefault(occurrence.physical_key, []).append(occurrence)

    capability_pairs: list[tuple[Capability, ResolverRecord]] = []
    for occurrences in grouped.values():
        ordered_occurrences = sorted(
            occurrences,
            key=_occurrence_order,
        )
        representative = ordered_occurrences[0]
        metadata = _skill_metadata(
            representative.visible_file, representative.real_file.parent.name
        )
        item_diagnostics = tuple(
            _diagnostic(
                issue.code,
                issue.message,
                location=representative.source.location,
            )
            for issue in metadata.issues
        )
        global_diagnostics.extend(item_diagnostics)
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
            scope=representative.source.scope,
            provider=representative.source.provider,
            diagnostics=item_diagnostics,
            logical_identity=_logical_identity(occurrences, representative),
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

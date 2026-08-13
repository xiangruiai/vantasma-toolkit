"""Resolve and manage private, runtime-only Agent instruction targets."""

from __future__ import annotations

import os
import hashlib
import hmac
import json
import re
import stat
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable


MAX_INSTRUCTION_BYTES = 8 * 1024 * 1024
_READ_CHUNK_BYTES = 64 * 1024
_VALID_AGENTS = frozenset({"codex", "claude"})
_VALID_SCOPES = frozenset({"user", "project"})
_INSTALLATION_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_START_PREFIX = b"<!-- vantasma:discover-local-capabilities:start"
_END_MARKER = b"<!-- vantasma:discover-local-capabilities:end -->"
_START_RE = re.compile(
    rb"^<!-- vantasma:discover-local-capabilities:start "
    rb"id=([A-Za-z0-9][A-Za-z0-9._-]{0,127}) schema=([0-9]+) -->$"
)


@dataclass(frozen=True)
class InstructionTarget:
    """One exact runtime instruction target; never a public-map record."""

    agent: str
    scope: str
    path: Path
    effectiveness: str

    def __post_init__(self) -> None:
        agent = self.agent.casefold().strip()
        scope = self.scope.casefold().strip()
        if agent not in _VALID_AGENTS:
            raise ValueError(f"unsupported Agent instruction target: {self.agent!r}")
        if scope not in _VALID_SCOPES:
            raise ValueError(f"unsupported instruction scope: {self.scope!r}")
        object.__setattr__(self, "agent", agent)
        object.__setattr__(self, "scope", scope)
        object.__setattr__(self, "path", Path(self.path))
        if not self.effectiveness.strip():
            raise ValueError("effectiveness must not be empty")


@dataclass(frozen=True)
class InstructionOperation:
    """One hash-bound file transition in a private instruction plan."""

    target: InstructionTarget
    operation: str
    original_exists: bool
    expected_original_sha256: str | None
    target_sha256: str | None
    original_mode: int | None
    newline: str
    original_bytes: bytes = field(repr=False, compare=False)
    target_bytes: bytes = field(repr=False, compare=False)
    parent_evidence: tuple[str, int, int] | None = field(
        default=None, repr=False, compare=False
    )
    diagnostics: tuple[str, ...] = field(default_factory=tuple)

    @property
    def applicable(self) -> bool:
        return self.operation != "conflict"

    def to_private_dict(self) -> dict[str, Any]:
        return {
            "agent": self.target.agent,
            "scope": self.target.scope,
            "path": str(self.target.path),
            "effectiveness": self.target.effectiveness,
            "operation": self.operation,
            "original_exists": self.original_exists,
            "expected_original_sha256": self.expected_original_sha256,
            "target_sha256": self.target_sha256,
            "original_mode": self.original_mode,
            "newline": self.newline,
            "parent_evidence": (
                None
                if self.parent_evidence is None
                else {
                    "path": self.parent_evidence[0],
                    "device": self.parent_evidence[1],
                    "inode": self.parent_evidence[2],
                }
            ),
            "diagnostics": list(self.diagnostics),
        }


@dataclass(frozen=True)
class InstructionPlan:
    """Deterministic, dry-run-only description of instruction mutations."""

    action: str
    installation_id: str
    operations: tuple[InstructionOperation, ...]
    backup_root: Path
    plan_hash: str
    map_path: Path | None = field(default=None, repr=False)
    resolver_path: Path | None = field(default=None, repr=False)
    diagnostics: tuple[str, ...] = field(default_factory=tuple)

    @property
    def applicable(self) -> bool:
        return not self.diagnostics and all(item.applicable for item in self.operations)

    @property
    def changed_operations(self) -> tuple[InstructionOperation, ...]:
        return tuple(
            item
            for item in self.operations
            if item.operation in {"install", "update", "uninstall"}
        )

    def to_private_dict(self, *, include_hash: bool = True) -> dict[str, Any]:
        document: dict[str, Any] = {
            "schema_version": 1,
            "action": self.action,
            "installation_id": self.installation_id,
            "map_path": None if self.map_path is None else str(self.map_path),
            "resolver_path": (
                None if self.resolver_path is None else str(self.resolver_path)
            ),
            "backup_root": str(self.backup_root),
            "applicable": self.applicable,
            "operations": [item.to_private_dict() for item in self.operations],
            "diagnostics": list(self.diagnostics),
        }
        if include_hash:
            document["plan_hash"] = self.plan_hash
        return document

    def to_json(self) -> str:
        return json.dumps(
            self.to_private_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )


@dataclass(frozen=True)
class _InstructionSnapshot:
    existed: bool
    payload: bytes | None
    mode: int | None
    device: int | None = None
    inode: int | None = None
    size: int | None = None
    mtime_ns: int | None = None
    ctime_ns: int | None = None


@dataclass(frozen=True)
class _ManagedBlock:
    installation_id: str
    start: int
    end: int
    terminator: bytes


def _safe_nonempty_regular_file(path: Path) -> bool:
    """Return existence/content state without following or blocking on special files."""

    try:
        before = os.lstat(path)
    except FileNotFoundError:
        return False
    except OSError as error:
        raise ValueError("instruction target could not be inspected") from error
    if stat.S_ISLNK(before.st_mode):
        raise ValueError("refusing symbolic-link instruction target")
    if not stat.S_ISREG(before.st_mode):
        raise ValueError("instruction target is not a regular file")
    if before.st_size > MAX_INSTRUCTION_BYTES:
        raise ValueError("instruction target exceeds the read limit")
    flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NONBLOCK", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise ValueError("instruction target changed before opening") from error
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
            raise ValueError("instruction target changed while opening")
        return opened.st_size > 0
    finally:
        os.close(descriptor)


def _snapshot_target(path: Path) -> _InstructionSnapshot:
    try:
        before = os.lstat(path)
    except FileNotFoundError:
        return _InstructionSnapshot(False, None, None)
    except OSError as error:
        raise ValueError("instruction target could not be inspected") from error
    if stat.S_ISLNK(before.st_mode):
        raise ValueError("refusing symbolic-link instruction target")
    if not stat.S_ISREG(before.st_mode):
        raise ValueError("instruction target is not a regular file")
    if before.st_size > MAX_INSTRUCTION_BYTES:
        raise ValueError("instruction target exceeds the read limit")
    flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NONBLOCK", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise ValueError("instruction target changed before opening") from error
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
            raise ValueError("instruction target changed while opening")
        chunks: list[bytes] = []
        total = 0
        while total <= MAX_INSTRUCTION_BYTES:
            chunk = os.read(
                descriptor,
                min(_READ_CHUNK_BYTES, MAX_INSTRUCTION_BYTES + 1 - total),
            )
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
        after = os.fstat(descriptor)
        after_state = (
            after.st_dev,
            after.st_ino,
            after.st_mode,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        )
        if total > MAX_INSTRUCTION_BYTES:
            raise ValueError("instruction target exceeds the read limit")
        if after_state != actual or total != opened.st_size:
            raise ValueError("instruction target changed while reading")
        return _InstructionSnapshot(
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


def _parent_evidence(path: Path) -> tuple[str, int, int] | None:
    current = path.parent
    while True:
        try:
            metadata = os.lstat(current)
        except FileNotFoundError:
            if current == current.parent:
                return None
            current = current.parent
            continue
        except OSError as error:
            raise ValueError("instruction parent could not be inspected") from error
        if stat.S_ISLNK(metadata.st_mode):
            raise ValueError("refusing symbolic-link instruction parent")
        if not stat.S_ISDIR(metadata.st_mode):
            raise ValueError("instruction parent is not a directory")
        return (str(current), metadata.st_dev, metadata.st_ino)


def _validate_installation_id(installation_id: str) -> str:
    if not isinstance(installation_id, str) or not _INSTALLATION_ID_RE.fullmatch(
        installation_id
    ):
        raise ValueError("installation_id must be an opaque safe identifier")
    return installation_id


def _absolute_private_path(value: Path, label: str) -> Path:
    path = Path(value)
    if not path.is_absolute():
        raise ValueError(f"{label} must be an absolute runtime path")
    if any(character in str(path) for character in ("\x00", "\r", "\n")):
        raise ValueError(f"{label} contains unsafe control characters")
    return path


def render_managed_block(
    *, installation_id: str, map_path: Path, resolver_path: Path
) -> str:
    """Render the stable Chinese routing block with exact private runtime paths."""

    safe_id = _validate_installation_id(installation_id)
    exact_map = _absolute_private_path(map_path, "map_path")
    exact_resolver = _absolute_private_path(resolver_path, "resolver_path")
    map_literal = json.dumps(str(exact_map), ensure_ascii=False)
    resolver_literal = json.dumps(str(exact_resolver), ensure_ascii=False)
    return "\n".join(
        (
            "<!-- vantasma:discover-local-capabilities:start "
            f"id={safe_id} schema=1 -->",
            "## 本机能力路由",
            "",
            f"处理需要本机工具或本机能力的任务前，先读取 {map_literal}。",
            f"仅在需要解析真实位置时读取 {resolver_literal}。",
            "如果候选是 Skill，完整读取其 SKILL.md。",
            "已发现不等于已授权或已验证；执行前检查权限、依赖和当前任务中的可用性。",
            "刷新、迁移、求助或卸载请求交给 discover-local-capabilities Skill。",
            "<!-- vantasma:discover-local-capabilities:end -->",
        )
    )


def _newline_style(payload: bytes) -> tuple[bytes, str]:
    if b"\r\n" in payload:
        return b"\r\n", "CRLF"
    return b"\n", "LF"


def _line_content(line: bytes) -> bytes:
    if line.endswith(b"\r\n"):
        return line[:-2]
    if line.endswith((b"\r", b"\n")):
        return line[:-1]
    return line


def _managed_blocks(payload: bytes) -> tuple[tuple[_ManagedBlock, ...], tuple[str, ...]]:
    blocks: list[_ManagedBlock] = []
    diagnostics: list[str] = []
    active: tuple[str, int] | None = None
    seen_ids: set[str] = set()
    offset = 0
    for line in payload.splitlines(keepends=True):
        content = _line_content(line)
        line_start = offset
        terminator = line[len(content) :]
        offset += len(line)
        start_match = _START_RE.fullmatch(content)
        marker_namespace = b"vantasma:discover-local-capabilities:" in content
        if start_match is not None:
            identifier = start_match.group(1).decode("ascii")
            if active is not None:
                diagnostics.append("nested managed instruction markers")
            else:
                active = (identifier, line_start)
            continue
        if content == _END_MARKER:
            if active is None:
                diagnostics.append("unmatched managed instruction end marker")
            else:
                identifier, start = active
                if identifier in seen_ids:
                    diagnostics.append(f"duplicate managed block id: {identifier}")
                seen_ids.add(identifier)
                blocks.append(_ManagedBlock(identifier, start, offset, terminator))
                active = None
            continue
        if marker_namespace:
            diagnostics.append("corrupt managed instruction marker")
    if active is not None:
        diagnostics.append("managed instruction block is missing its end marker")
    return tuple(blocks), tuple(dict.fromkeys(diagnostics))


def _append_block(payload: bytes, block: bytes, newline: bytes) -> bytes:
    if not payload:
        return block + newline
    separator = b"" if payload.endswith((b"\n", b"\r")) else newline
    return payload + separator + block + newline


def _operation_for_target(
    target: InstructionTarget,
    *,
    action: str,
    installation_id: str,
    rendered_block: str | None,
) -> InstructionOperation:
    if not target.path.is_absolute():
        raise ValueError("instruction target paths must be absolute")
    snapshot = _snapshot_target(target.path)
    payload = snapshot.payload or b""
    newline, newline_label = _newline_style(payload)
    blocks, diagnostics = _managed_blocks(payload)
    matching = tuple(
        block for block in blocks if block.installation_id == installation_id
    )
    if len(matching) > 1:
        diagnostics += (f"duplicate managed block id: {installation_id}",)
    original_hash = hashlib.sha256(payload).hexdigest() if snapshot.existed else None
    parent = _parent_evidence(target.path)
    if diagnostics:
        return InstructionOperation(
            target,
            "conflict",
            snapshot.existed,
            original_hash,
            None,
            snapshot.mode,
            newline_label,
            payload,
            payload,
            parent,
            tuple(dict.fromkeys(diagnostics)),
        )
    if action == "install":
        if rendered_block is None:  # pragma: no cover - internal contract
            raise ValueError("rendered_block is required for installation")
        block_bytes = rendered_block.replace("\n", newline.decode("ascii")).encode(
            "utf-8"
        )
        if matching:
            block = matching[0]
            desired = (
                payload[: block.start]
                + block_bytes
                + block.terminator
                + payload[block.end :]
            )
            operation = "noop" if desired == payload else "update"
        else:
            desired = _append_block(payload, block_bytes, newline)
            operation = "install"
    else:
        if matching:
            block = matching[0]
            desired = payload[: block.start] + payload[block.end :]
            operation = "uninstall"
        else:
            desired = payload
            operation = "noop"
    target_hash = hashlib.sha256(desired).hexdigest()
    return InstructionOperation(
        target,
        operation,
        snapshot.existed,
        original_hash,
        target_hash,
        snapshot.mode,
        newline_label,
        payload,
        desired,
        parent,
    )


def _sorted_targets(targets: Iterable[InstructionTarget]) -> tuple[InstructionTarget, ...]:
    values = tuple(targets)
    if not values:
        raise ValueError("at least one instruction target is required")
    if not all(isinstance(item, InstructionTarget) for item in values):
        raise TypeError("targets must contain InstructionTarget values")
    ordered = tuple(sorted(values, key=lambda item: (item.agent, item.scope, str(item.path))))
    paths = [item.path for item in ordered]
    if len(set(paths)) != len(paths):
        raise ValueError("instruction target paths must be unique")
    return ordered


def _make_plan(
    *,
    action: str,
    installation_id: str,
    operations: tuple[InstructionOperation, ...],
    backup_root: Path,
    map_path: Path | None,
    resolver_path: Path | None,
) -> InstructionPlan:
    diagnostics = tuple(
        diagnostic for operation in operations for diagnostic in operation.diagnostics
    )
    provisional = InstructionPlan(
        action,
        installation_id,
        operations,
        backup_root,
        "",
        map_path,
        resolver_path,
        diagnostics,
    )
    canonical = json.dumps(
        provisional.to_private_dict(include_hash=False),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return InstructionPlan(
        action,
        installation_id,
        operations,
        backup_root,
        hashlib.sha256(canonical).hexdigest(),
        map_path,
        resolver_path,
        diagnostics,
    )


def build_instruction_plan(
    targets: Iterable[InstructionTarget],
    installation_id: str,
    map_path: Path,
    resolver_path: Path,
    backup_root: Path | None = None,
) -> InstructionPlan:
    """Build a deterministic install/update plan without any filesystem writes."""

    safe_id = _validate_installation_id(installation_id)
    exact_map = _absolute_private_path(map_path, "map_path")
    exact_resolver = _absolute_private_path(resolver_path, "resolver_path")
    private_backup = (
        exact_resolver.parent / "instruction-backups"
        if backup_root is None
        else _absolute_private_path(backup_root, "backup_root")
    )
    rendered = render_managed_block(
        installation_id=safe_id,
        map_path=exact_map,
        resolver_path=exact_resolver,
    )
    operations = tuple(
        _operation_for_target(
            target,
            action="install",
            installation_id=safe_id,
            rendered_block=rendered,
        )
        for target in _sorted_targets(targets)
    )
    return _make_plan(
        action="install",
        installation_id=safe_id,
        operations=operations,
        backup_root=private_backup,
        map_path=exact_map,
        resolver_path=exact_resolver,
    )


def build_uninstall_plan(
    targets: Iterable[InstructionTarget],
    installation_id: str,
    backup_root: Path | None = None,
) -> InstructionPlan:
    """Build a block-only uninstall plan; capability data is deliberately untouched."""

    safe_id = _validate_installation_id(installation_id)
    ordered = _sorted_targets(targets)
    private_backup = (
        Path.home()
        / ".local"
        / "share"
        / "vantasma"
        / "agent-capabilities"
        / ".private"
        / "instruction-backups"
        if backup_root is None
        else _absolute_private_path(backup_root, "backup_root")
    )
    operations = tuple(
        _operation_for_target(
            target,
            action="uninstall",
            installation_id=safe_id,
            rendered_block=None,
        )
        for target in ordered
    )
    return _make_plan(
        action="uninstall",
        installation_id=safe_id,
        operations=operations,
        backup_root=private_backup,
        map_path=None,
        resolver_path=None,
    )


def apply_instruction_plan(
    plan: InstructionPlan,
    *,
    confirmed: bool,
    expected_plan_hash: str,
    failure_injector: Any = None,
):
    """Re-plan against current state, then atomically apply a confirmed plan."""

    if not isinstance(plan, InstructionPlan):
        raise TypeError("plan must be an InstructionPlan value")
    if confirmed is not True:
        raise ValueError("confirmed=True is required before instruction writes")
    if not isinstance(expected_plan_hash, str) or not hmac.compare_digest(
        expected_plan_hash, plan.plan_hash
    ):
        raise ValueError("expected plan hash does not match the proposed plan")
    targets = tuple(operation.target for operation in plan.operations)
    if plan.action == "install":
        if plan.map_path is None or plan.resolver_path is None:  # pragma: no cover
            raise ValueError("install plan is missing private runtime paths")
        current = build_instruction_plan(
            targets,
            installation_id=plan.installation_id,
            map_path=plan.map_path,
            resolver_path=plan.resolver_path,
            backup_root=plan.backup_root,
        )
    elif plan.action == "uninstall":
        current = build_uninstall_plan(
            targets,
            installation_id=plan.installation_id,
            backup_root=plan.backup_root,
        )
    else:  # pragma: no cover - constructed plans constrain this
        raise ValueError("unsupported instruction plan action")
    if not hmac.compare_digest(current.plan_hash, plan.plan_hash):
        from .transactions import TransactionError

        raise TransactionError("stale instruction plan; current state changed")
    if not current.applicable:
        raise ValueError("instruction plan is not applicable: " + "; ".join(current.diagnostics))

    from .transactions import FileMutation, apply_file_transaction

    mutations = tuple(
        FileMutation(
            path=operation.target.path,
            operation=operation.operation,
            expected_exists=operation.original_exists,
            expected_original_sha256=operation.expected_original_sha256,
            original_bytes=operation.original_bytes,
            target_bytes=operation.target_bytes,
            mode=(
                operation.original_mode
                if operation.original_mode is not None
                else 0o644
            ),
            newline=operation.newline,
            parent_evidence=operation.parent_evidence,
        )
        for operation in current.changed_operations
    )
    return apply_file_transaction(
        mutations,
        backup_root=current.backup_root,
        plan_hash=current.plan_hash,
        failure_injector=failure_injector,
    )


def _selection(values: Iterable[str] | None, allowed: frozenset[str], label: str) -> tuple[str, ...]:
    if values is None:
        return tuple(value for value in ("codex", "claude", "user", "project") if value in allowed)
    selected: list[str] = []
    for raw in values:
        value = raw.casefold().strip()
        if value not in allowed:
            raise ValueError(f"unsupported {label}: {raw!r}")
        if value not in selected:
            selected.append(value)
    return tuple(selected)


def resolve_instruction_targets(
    *,
    home: Path,
    project_root: Path | None = None,
    codex_home: Path | None = None,
    agents: Iterable[str] | None = None,
    scopes: Iterable[str] | None = None,
) -> tuple[InstructionTarget, ...]:
    """Resolve the effective, fully injected Codex and Claude instruction files."""

    home_path = Path(home).absolute()
    project_path = None if project_root is None else Path(project_root).absolute()
    codex_path = (
        home_path / ".codex" if codex_home is None else Path(codex_home).absolute()
    )
    selected_agents = _selection(agents, _VALID_AGENTS, "agent")
    selected_scopes = _selection(scopes, _VALID_SCOPES, "scope")
    targets: list[InstructionTarget] = []
    for agent in ("codex", "claude"):
        if agent not in selected_agents:
            continue
        for scope in ("user", "project"):
            if scope not in selected_scopes:
                continue
            if scope == "project" and project_path is None:
                raise ValueError("project_root is required for project targets")
            if agent == "codex" and scope == "user":
                override = codex_path / "AGENTS.override.md"
                if _safe_nonempty_regular_file(override):
                    path = override
                    effectiveness = "effective; non-empty AGENTS.override.md shadows AGENTS.md"
                else:
                    path = codex_path / "AGENTS.md"
                    effectiveness = "effective; empty or absent override does not shadow AGENTS.md"
            elif agent == "codex":
                path = project_path / "AGENTS.md"  # type: ignore[operator]
                effectiveness = "effective project instruction target"
            elif scope == "user":
                path = home_path / ".claude" / "CLAUDE.md"
                effectiveness = "effective user instruction target"
            else:
                path = project_path / "CLAUDE.md"  # type: ignore[operator]
                effectiveness = "effective project instruction target"
            targets.append(InstructionTarget(agent, scope, path, effectiveness))
    return tuple(targets)


__all__ = [
    "InstructionOperation",
    "InstructionPlan",
    "InstructionTarget",
    "MAX_INSTRUCTION_BYTES",
    "apply_instruction_plan",
    "build_instruction_plan",
    "build_uninstall_plan",
    "render_managed_block",
    "resolve_instruction_targets",
]

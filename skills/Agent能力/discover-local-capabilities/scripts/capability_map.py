#!/usr/bin/env python3
"""Discover and manage a private, local Agent capability map.

All host inputs and streams are injectable so callers can run the complete
workflow in an isolated home.  Discovery is read-only and never executes a
discovered command unless ``--probe-versions explicit`` is supplied.
"""

from __future__ import annotations

import argparse
import contextlib
import dataclasses
import hashlib
import hmac
import json
import os
import stat
import sys
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TextIO

from capability_map_core.classify import (
    classify_capabilities,
    route_query,
)
from capability_map_core.clis import discover_clis, probe_cli_version
from capability_map_core.connectors import discover_connectors
from capability_map_core.instructions import (
    InstructionPlan,
    InstructionTargetRequest,
    apply_instruction_plan,
    build_instruction_plan,
    build_uninstall_plan,
)
from capability_map_core.models import (
    Capability,
    CapabilityStates,
    Diagnostic,
    InventoryMetadata,
    SourceLocation,
)
from capability_map_core.render import (
    render_capability_map_markdown,
    render_inventory_json,
)
from capability_map_core.roots import RootSpec, skill_root_specs
from capability_map_core.sanitize import sanitize_text
from capability_map_core.skills import discover_skills
from capability_map_core.storage import (
    PublicArtifacts,
    StorageExpectedSnapshot,
    StoragePaths,
    _exact_values,
    _json_bytes,
    _parse_public_json,
    _sanitize_markdown_document,
    build_private_resolver_document,
    capture_storage_expected_state,
    default_storage_paths,
    write_storage_bundle,
)
from capability_map_core.transactions import (
    FileMutation,
    TransactionReceipt,
    apply_file_transaction,
    capture_directory_evidence,
)


MAX_WORKFLOW_DOCUMENT_BYTES = 64 * 1024 * 1024
_ARTIFACT_LABELS = ("map", "inventory", "config", "receipt", "resolver")
_STATE_FILENAME = "installation-state.json"
_PRIVATE_INSTALLATIONS = "installations"


class RefusedError(ValueError):
    """A safe, expected refusal that maps to exit code 2."""


class WorkflowError(RuntimeError):
    """An operational failure that maps to exit code 3."""


@dataclass(frozen=True)
class ScanResult:
    capabilities: tuple[Capability, ...]
    resolvers: tuple[Any, ...]
    diagnostics: tuple[Diagnostic, ...]
    inventory_text: str
    map_markdown: str


@dataclass(frozen=True)
class FileSnapshot:
    existed: bool
    payload: bytes | None
    mode: int | None
    device: int | None = None
    inode: int | None = None
    size: int | None = None
    ctime_ns: int | None = None

    @property
    def sha256(self) -> str | None:
        return None if self.payload is None else _digest(self.payload)


@dataclass(frozen=True)
class StateWritePlan:
    path: Path
    desired_bytes: bytes
    before: FileSnapshot
    plan_hash: str

    @property
    def changed(self) -> bool:
        return self.before.payload != self.desired_bytes or self.before.mode != 0o600


@dataclass(frozen=True)
class SetupWorkflowPlan:
    public: dict[str, Any]
    plan_hash: str
    paths: StoragePaths
    scan: ScanResult
    artifacts: PublicArtifacts
    instruction_plan: InstructionPlan
    target_request: InstructionTargetRequest
    installation_id: str
    state_id: str
    state_document: dict[str, Any]
    state_plan: StateWritePlan
    storage_expected: dict[str, StorageExpectedSnapshot]


@dataclass(frozen=True)
class RuntimeContext:
    paths: StoragePaths
    state_path: Path
    config: dict[str, Any]
    state: dict[str, Any]
    target_request: InstructionTargetRequest
    project_root: Path


def interpret_capability_map_intent(query: str) -> str:
    """Map common Chinese help requests to stable workflow operations."""

    if not isinstance(query, str):
        raise TypeError("query must be text")
    normalized = "".join(query.casefold().split())
    if any(word in normalized for word in ("卸载", "移除能力地图")):
        return "uninstall"
    if any(word in normalized for word in ("迁移", "换位置")):
        return "migrate"
    if any(word in normalized for word in ("刷新", "更新能力地图")):
        return "refresh"
    if any(word in normalized for word in ("在哪", "路径", "位置")):
        return "paths"
    return "usage"


def _absolute(value: str | os.PathLike[str], *, cwd: Path, home: Path) -> Path:
    raw = os.fspath(value)
    if raw == "~":
        return home.absolute()
    if raw.startswith(("~/", "~\\")):
        return (home / raw[2:]).absolute()
    path = Path(raw)
    return path.absolute() if path.is_absolute() else (cwd / path).absolute()


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _digest(value: bytes | str | Mapping[str, Any] | Sequence[Any]) -> str:
    if isinstance(value, bytes):
        payload = value
    elif isinstance(value, str):
        payload = value.encode("utf-8")
    else:
        payload = _canonical(value)
    return hashlib.sha256(payload).hexdigest()


def _write_json(stream: TextIO, value: Mapping[str, Any]) -> None:
    stream.write(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    )


def _safe_error(error: BaseException) -> str:
    message = sanitize_text(str(error), max_length=768).strip()
    return message or type(error).__name__


def _read_regular(path: Path, *, limit: int = MAX_WORKFLOW_DOCUMENT_BYTES) -> bytes:
    """Read one bounded, non-blocking, no-follow regular file."""

    candidate = Path(path)
    if any(part.casefold() == ".env" for part in candidate.parts):
        raise ValueError("workflow documents must not traverse .env")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NONBLOCK", 0)
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(candidate, flags)
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise ValueError("workflow document must be a regular file")
        if before.st_size > limit:
            raise ValueError("workflow document exceeds the read limit")
        chunks: list[bytes] = []
        remaining = limit + 1
        while remaining > 0:
            chunk = os.read(descriptor, min(64 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        payload = b"".join(chunks)
        after = os.fstat(descriptor)
        if len(payload) > limit:
            raise ValueError("workflow document exceeds the read limit")
        if (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
        ) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        ):
            raise ValueError("workflow document changed while reading")
        return payload
    finally:
        os.close(descriptor)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(_read_regular(path).decode("utf-8"))
    except FileNotFoundError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("workflow JSON is invalid") from error
    if not isinstance(value, dict):
        raise ValueError("workflow JSON must contain an object")
    return value


def _snapshot(path: Path) -> FileSnapshot:
    try:
        before = os.lstat(path)
        if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
            raise ValueError("workflow target must be a physical regular file")
        payload = _read_regular(path)
        after = os.lstat(path)
        if (
            before.st_dev,
            before.st_ino,
            before.st_mode,
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
        ) != (
            after.st_dev,
            after.st_ino,
            after.st_mode,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        ):
            raise ValueError("workflow target changed while snapshotting")
        return FileSnapshot(
            True,
            payload,
            stat.S_IMODE(after.st_mode),
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_ctime_ns,
        )
    except FileNotFoundError:
        return FileSnapshot(False, None, None)


def _artifact_paths(paths: StoragePaths) -> dict[str, Path]:
    return {
        "map": paths.map_path,
        "inventory": paths.inventory_path,
        "config": paths.config_path,
        "receipt": paths.receipt_path,
        "resolver": paths.resolver_path,
    }


def _snapshots(
    paths: StoragePaths, *, state_path: Path | None = None
) -> dict[Path, FileSnapshot]:
    targets = list(_artifact_paths(paths).values())
    if state_path is not None:
        targets.append(state_path)
    return {path: _snapshot(path) for path in targets}


def _atomic_restore(path: Path, payload: bytes, mode: int) -> None:
    temporary = path.parent / f".vantasma-restore-{_digest(str(path))[:20]}"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0)
    descriptor = os.open(temporary, flags, mode)
    try:
        view = memoryview(payload)
        while view:
            written = os.write(descriptor, view)
            view = view[written:]
        os.fchmod(descriptor, mode)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    try:
        os.link(temporary, path, follow_symlinks=False)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def _matches_committed(current: FileSnapshot, committed: FileSnapshot) -> bool:
    return bool(
        current.existed
        and committed.existed
        and current.device == committed.device
        and current.inode == committed.inode
        and current.size == committed.size
        and current.ctime_ns == committed.ctime_ns
        and current.mode == committed.mode
        and current.sha256 == committed.sha256
    )


def _matches_claimed(current: FileSnapshot, committed: FileSnapshot) -> bool:
    """Verify the claimed inode while allowing rename to advance ctime."""

    return bool(
        current.existed
        and committed.existed
        and current.device == committed.device
        and current.inode == committed.inode
        and current.size == committed.size
        and current.mode == committed.mode
        and current.sha256 == committed.sha256
    )


def _restore_after_failure(
    snapshots: Mapping[Path, FileSnapshot],
    committed: Mapping[Path, FileSnapshot],
    *,
    recovery_key: str,
) -> tuple[tuple[Path, ...], tuple[Path, ...]]:
    """Restore only transaction-owned files and preserve external replacements."""

    recovery_directories: set[Path] = set()
    conflicts: list[Path] = []
    for target, previous in snapshots.items():
        installed = committed.get(target)
        if installed is None:
            continue
        try:
            current = _snapshot(target)
        except (OSError, ValueError):
            conflicts.append(target)
            continue
        if not _matches_committed(current, installed):
            conflicts.append(target)
            continue
        recovery = target.parent / ".vantasma-workflow-recovery" / recovery_key
        recovery.mkdir(parents=True, exist_ok=True)
        destination = recovery / target.name
        index = 1
        while destination.exists():
            destination = recovery / f"{target.name}.{index}"
            index += 1
        try:
            os.replace(target, destination)
            claimed = _snapshot(destination)
        except (OSError, ValueError):
            conflicts.append(target)
            continue
        if not _matches_claimed(claimed, installed):
            conflicts.append(target)
            if not target.exists():
                try:
                    os.link(destination, target, follow_symlinks=False)
                except OSError:
                    pass
            continue
        recovery_directories.add(recovery)
        if previous.existed and previous.payload is not None:
            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                _atomic_restore(target, previous.payload, previous.mode or 0o600)
            except OSError:
                conflicts.append(target)
    return (
        tuple(sorted(recovery_directories, key=str)),
        tuple(sorted(set(conflicts), key=str)),
    )


def _selected_agents(value: str) -> tuple[str, ...]:
    if value == "both":
        return ("codex", "claude")
    return (value,)


def _storage_paths(
    *,
    storage: str | None,
    vault: str | None,
    home: Path,
    cwd: Path,
    environ: Mapping[str, str],
) -> StoragePaths:
    if storage is not None and vault is not None:
        raise RefusedError("choose either --storage or --vault")
    local_root = None if storage is None else _absolute(storage, cwd=cwd, home=home)
    selected_vault = None if vault is None else _absolute(vault, cwd=cwd, home=home)
    return default_storage_paths(
        home=home,
        environ=environ,
        local_root=local_root,
        selected_vault=selected_vault,
    )


def _private_namespace_id(public_root: Path, installation_id: str) -> str:
    return _digest(
        {
            "namespace": "capability-installation-v1",
            "public_root": str(public_root),
            "installation_id": installation_id,
        }
    )[:32]


def _namespaced_paths(
    base_paths: StoragePaths,
    *,
    installation_id: str,
    home: Path,
    environ: Mapping[str, str],
) -> StoragePaths:
    namespace = (
        base_paths.private_root
        / _PRIVATE_INSTALLATIONS
        / _private_namespace_id(base_paths.public_root, installation_id)
    )
    return default_storage_paths(
        home=home,
        environ=environ,
        local_root=base_paths.public_root,
        private_root=namespace,
    )


def _state_path(paths: StoragePaths) -> Path:
    return paths.private_root / _STATE_FILENAME


def _state_id(paths: StoragePaths, installation_id: str) -> str:
    return "state_" + _private_namespace_id(paths.public_root, installation_id)


def _codex_home(environ: Mapping[str, str], *, home: Path) -> Path:
    raw = environ.get("CODEX_HOME")
    if not raw:
        return (home / ".codex").absolute()
    return _absolute(raw, cwd=home, home=home)


def _scan(
    *,
    home: Path,
    project: Path | None,
    cwd: Path,
    environ: Mapping[str, str],
    extra_skill_roots: Iterable[Path] = (),
    probe_versions: bool = False,
) -> ScanResult:
    roots = skill_root_specs(
        home=home,
        project=project,
        extra_roots=extra_skill_roots,
        environ=environ,
    )
    plugin_roots = tuple(root for root in roots if root.scope in {"plugin", "extra"})
    connectors = discover_connectors(
        home=home,
        project=project,
        plugin_roots=plugin_roots,
        environ=environ,
    )
    skill_roots: list[RootSpec] = list(roots)
    skill_roots.extend(connectors.skill_roots)
    skills = discover_skills(tuple(skill_roots))
    clis = discover_clis(environ=environ, cwd=cwd)

    cli_capabilities = list(clis.capabilities)
    probe_diagnostics: list[Diagnostic] = []
    if probe_versions:
        by_resolver = {item.resolver_id: item for item in clis.resolvers}
        probed: list[Capability] = []
        for capability in cli_capabilities:
            resolver = by_resolver.get(capability.resolver_id)
            if resolver is None or not resolver.exact_locations:
                probed.append(capability)
                continue
            result = probe_cli_version(
                resolver.exact_locations[0],
                path=environ.get("PATH"),
                environ=environ,
            )
            probe_diagnostics.extend(result.diagnostics)
            version = result.output.splitlines()[0] if result.output else None
            states = dataclasses.replace(capability.states, probed=result.status)
            probed.append(dataclasses.replace(capability, states=states, version=version))
        cli_capabilities = probed

    all_capabilities = (
        *skills.capabilities,
        *cli_capabilities,
        *connectors.capabilities,
    )
    classified = classify_capabilities(all_capabilities)
    diagnostics = (
        *skills.diagnostics,
        *clis.diagnostics,
        *connectors.diagnostics,
        *probe_diagnostics,
    )
    metadata = InventoryMetadata("", len(classified), tuple(diagnostics))
    inventory_text = render_inventory_json(classified, metadata, diagnostics)
    map_markdown = render_capability_map_markdown(classified, metadata, diagnostics)
    return ScanResult(
        tuple(classified),
        tuple((*skills.resolvers, *clis.resolvers, *connectors.resolvers)),
        tuple(diagnostics),
        inventory_text,
        map_markdown,
    )


def _installation_id(
    paths: StoragePaths, request: InstructionTargetRequest, provided: str | None
) -> str:
    if provided is not None:
        try:
            return _validate_opaque_identifier(provided, "inst_")
        except ValueError as error:
            raise RefusedError("installation id is invalid") from error
    evidence = {
        "public_root": str(paths.public_root),
        "agents": list(request.agents),
        "scopes": list(request.scopes),
        "project": None if request.project_root is None else str(request.project_root),
    }
    return _validate_opaque_identifier("inst_" + _digest(evidence)[:24], "inst_")


def _configuration(
    *, installation_id: str, state_id: str, mode: str = "setup"
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "mode": mode,
        "installation_id": installation_id,
        "state_id": state_id,
    }


def _capability_counts(scan: ScanResult) -> dict[str, int]:
    counts = {"skills": 0, "clis": 0, "mcp": 0, "plugins": 0}
    labels = {"skill": "skills", "cli": "clis", "mcp": "mcp", "plugin": "plugins"}
    for capability in scan.capabilities:
        counts[labels[capability.kind]] += 1
    counts["unclassified"] = sum(
        1 for capability in scan.capabilities if not capability.scenes
    )
    counts["diagnostics"] = len(scan.diagnostics)
    counts["capabilities"] = len(scan.capabilities)
    return counts


def _receipt_markdown(
    installation_id: str,
    state_id: str,
    scan: ScanResult,
    instruction_plan: InstructionPlan,
) -> str:
    counts = _capability_counts(scan)
    lines = [
        "# Capability map setup receipt",
        "",
        "## Public artifacts",
        "",
        "Selected location: `<selected-public-storage>`.",
        "- map: `本机能力地图.md`",
        "- inventory: `capability-inventory.json`",
        "- config: `capability-map.config.json`",
        "- receipt: `setup-receipt.md`",
        "",
        "## Private runtime state",
        "",
        f"- installation: `{installation_id}`",
        f"- state: `{state_id}`",
        "- resolver and installation state are private 0600 files in an opaque namespace.",
        "- exact private paths are returned only by the confirmed apply command.",
        "",
        "## Counts",
        "",
    ]
    for label in (
        "skills",
        "clis",
        "mcp",
        "plugins",
        "unclassified",
        "diagnostics",
    ):
        lines.append(f"- {label}: {counts[label]}")
    lines.extend(["", "## Agent instruction targets", ""])
    for operation in instruction_plan.operations:
        lines.append(
            f"- {operation.target.agent}/{operation.target.scope}: "
            f"`{sanitize_text(operation.target.path.name, max_length=128)}`"
        )
    lines.extend(
        [
            "- backup manifest: private transaction backup; exact location is returned by apply.",
            "",
            "## Next steps",
            "",
            "Start a new session after setup so Agent instructions are reloaded.",
            "Natural language examples:",
            "- “能力地图怎么用”",
            "- “刷新能力地图”",
            "- “迁移能力地图”",
            "- “卸载能力地图”",
            "",
        ]
    )
    return "\n".join(lines)


def _artifacts(
    *,
    scan: ScanResult,
    installation_id: str,
    state_id: str,
    instruction_plan: InstructionPlan,
    mode: str = "setup",
) -> PublicArtifacts:
    return PublicArtifacts(
        scan.map_markdown,
        scan.inventory_text,
        _configuration(
            installation_id=installation_id,
            state_id=state_id,
            mode=mode,
        ),
        _receipt_markdown(installation_id, state_id, scan, instruction_plan),
    )


def _current_storage_state(
    paths: StoragePaths, *, state_path: Path | None = None
) -> dict[str, dict[str, Any]]:
    state: dict[str, dict[str, Any]] = {}
    targets = _artifact_paths(paths)
    if state_path is not None:
        targets = {**targets, "state": state_path}
    for label, path in targets.items():
        snapshot = _snapshot(path)
        state[label] = {
            "exists": snapshot.existed,
            "sha256": snapshot.sha256,
            "mode": snapshot.mode,
        }
    return state


def _desired_storage_bytes(
    paths: StoragePaths, artifacts: PublicArtifacts, scan: ScanResult
) -> dict[str, bytes]:
    records = tuple(scan.resolvers)
    exact_values = _exact_values(paths, records)
    return {
        "map": _sanitize_markdown_document(
            artifacts.map_markdown, exact_values=exact_values
        ).encode("utf-8"),
        "inventory": _json_bytes(_parse_public_json(artifacts.inventory, "inventory")),
        "config": _json_bytes(_parse_public_json(artifacts.config, "config")),
        "receipt": _sanitize_markdown_document(
            artifacts.receipt_markdown, exact_values=exact_values
        ).encode("utf-8"),
        "resolver": _json_bytes(build_private_resolver_document(paths, records)),
    }


def _storage_expected_transition(
    expected: Mapping[str, StorageExpectedSnapshot],
) -> dict[str, Any]:
    return {
        label: {
            "target": str(item.target),
            "exists": item.existed,
            "sha256": item.sha256,
            "mode": item.mode,
            "parent": {
                "resolved_path": str(item.parent_evidence.resolved_path),
                "existing_ancestors": [
                    {
                        "path": str(ancestor.path),
                        "device": ancestor.device,
                        "inode": ancestor.inode,
                        "mode": ancestor.mode,
                    }
                    for ancestor in item.parent_evidence.existing_ancestors
                ],
            },
        }
        for label, item in sorted(expected.items())
    }


def _runtime_state_document(
    *,
    paths: StoragePaths,
    installation_id: str,
    state_id: str,
    project_root: Path,
    request: InstructionTargetRequest,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "status": "active",
        "active": True,
        "installation_id": installation_id,
        "state_id": state_id,
        "public_root": str(paths.public_root),
        "project_root": str(project_root),
        "home": str(request.home),
        "codex_home": str(request.codex_home),
        "agents": list(request.agents),
        "scope": request.scopes[0],
        "target_request": request.to_private_dict(),
    }


def _state_write_plan(path: Path, document: Mapping[str, Any]) -> StateWritePlan:
    desired = _json_bytes(document)
    before = _snapshot(path)
    plan_hash = _digest(
        {
            "path": str(path),
            "before": {
                "exists": before.existed,
                "sha256": before.sha256,
                "mode": before.mode,
            },
            "desired_sha256": _digest(desired),
            "desired_mode": 0o600,
        }
    )
    return StateWritePlan(path, desired, before, plan_hash)


def _state_transition(plan: StateWritePlan) -> tuple[Any, ...]:
    return (
        str(plan.path),
        plan.before.existed,
        plan.before.sha256,
        plan.before.mode,
        _digest(plan.desired_bytes),
    )


def _apply_state_plan(plan: StateWritePlan) -> TransactionReceipt:
    current = _state_write_plan(plan.path, json.loads(plan.desired_bytes))
    if _state_transition(current) != _state_transition(plan):
        raise WorkflowError("stale private installation state")
    if not current.changed:
        return TransactionReceipt(current.plan_hash, (), None, None)
    before = current.before
    mutation = FileMutation(
        path=current.path,
        operation="update" if before.existed else "install",
        expected_exists=before.existed,
        expected_original_sha256=before.sha256,
        original_bytes=before.payload or b"",
        target_bytes=current.desired_bytes,
        mode=0o600,
        newline="LF",
        parent_evidence=capture_directory_evidence(current.path.parent),
    )
    backup_root = current.path.parent / "state-backups"
    return apply_file_transaction(
        (mutation,),
        backup_root=backup_root,
        backup_root_evidence=capture_directory_evidence(backup_root),
        plan_hash=current.plan_hash,
    )


def _build_setup_plan(
    *,
    args: argparse.Namespace,
    home: Path,
    cwd: Path,
    environ: Mapping[str, str],
) -> SetupWorkflowPlan:
    base_paths = _storage_paths(
        storage=args.storage,
        vault=args.vault,
        home=home,
        cwd=cwd,
        environ=environ,
    )
    project = _absolute(args.project, cwd=cwd, home=home).resolve(strict=False)
    agents = _selected_agents(args.agents)
    request = InstructionTargetRequest(
        home=home.resolve(strict=False),
        project_root=project if args.scope == "project" else None,
        codex_home=_codex_home(environ, home=home).resolve(strict=False),
        agents=agents,
        scopes=(args.scope,),
    )
    installation_id = _installation_id(base_paths, request, args.installation_id)
    paths = _namespaced_paths(
        base_paths,
        installation_id=installation_id,
        home=home,
        environ=environ,
    )
    storage_expected = capture_storage_expected_state(paths)
    state_id = _state_id(paths, installation_id)
    scan = _scan(
        home=home,
        project=project,
        cwd=cwd,
        environ=environ,
    )
    instruction_plan = build_instruction_plan(
        request,
        installation_id,
        paths.map_path,
        paths.resolver_path,
        backup_root=paths.private_root / "instruction-backups",
    )
    artifacts = _artifacts(
        scan=scan,
        installation_id=installation_id,
        state_id=state_id,
        instruction_plan=instruction_plan,
    )
    state_document = _runtime_state_document(
        paths=paths,
        installation_id=installation_id,
        state_id=state_id,
        project_root=project,
        request=request,
    )
    state_plan = _state_write_plan(_state_path(paths), state_document)
    current = _current_storage_state(paths, state_path=state_plan.path)
    desired_bytes = _desired_storage_bytes(paths, artifacts, scan)
    desired = {
        **{label: _digest(payload) for label, payload in desired_bytes.items()},
        "state": _digest(state_plan.desired_bytes),
    }
    changes = [
        label
        for label in _ARTIFACT_LABELS
        if current[label]["sha256"] != desired[label]
        or (label == "resolver" and current[label]["mode"] != 0o600)
    ]
    if state_plan.changed:
        changes.append("state")
    exact_paths = {label: str(path) for label, path in _artifact_paths(paths).items()}
    exact_paths["state"] = str(state_plan.path)
    hash_input = {
        "schema_version": 1,
        "installation_id": installation_id,
        "paths": exact_paths,
        "desired_hashes": desired,
        "current": current,
        "storage_expected": _storage_expected_transition(storage_expected),
        "instruction_plan_hash": instruction_plan.plan_hash,
        "state_plan_hash": state_plan.plan_hash,
    }
    plan_hash = _digest(hash_input)
    counts = _capability_counts(scan)
    counts.update(
        {
            "storage_changes": len(
                [label for label in changes if label in _ARTIFACT_LABELS]
            ),
            "state_changes": int("state" in changes),
            "instruction_changes": len(instruction_plan.changed_operations),
        }
    )
    public = {
        "schema_version": 1,
        "action": "setup",
        "installation_id": installation_id,
        "paths": exact_paths,
        "state_id": state_id,
        "counts": counts,
        "changes": changes,
        "desired_hashes": desired,
        "backups": [str(instruction_plan.backup_root)],
        "instruction_operations": [
            {
                "agent": operation.target.agent,
                "scope": operation.target.scope,
                "path": str(operation.target.path),
                "operation": operation.operation,
            }
            for operation in instruction_plan.operations
        ],
        "warnings": list(instruction_plan.diagnostics),
        "plan_hash": plan_hash,
    }
    return SetupWorkflowPlan(
        public,
        plan_hash,
        paths,
        scan,
        artifacts,
        instruction_plan,
        request,
        installation_id,
        state_id,
        state_document,
        state_plan,
        storage_expected,
    )


def _apply_storage_then_instructions(plan: SetupWorkflowPlan) -> dict[str, Any]:
    before = _snapshots(plan.paths, state_path=plan.state_plan.path)
    committed: dict[Path, FileSnapshot] = {}
    try:
        storage_result = write_storage_bundle(
            plan.paths,
            plan.artifacts,
            plan.scan.resolvers,
            expected_state=plan.storage_expected,
        )
        committed.update(_snapshots(plan.paths))
        current_state_plan = _state_write_plan(
            plan.state_plan.path, plan.state_document
        )
        if _state_transition(current_state_plan) != _state_transition(plan.state_plan):
            raise WorkflowError("private installation state changed after storage preparation")
        state_result = _apply_state_plan(current_state_plan)
        committed[plan.state_plan.path] = _snapshot(plan.state_plan.path)
        current_instruction_plan = build_instruction_plan(
            plan.target_request,
            plan.installation_id,
            plan.paths.map_path,
            plan.paths.resolver_path,
            backup_root=plan.paths.private_root / "instruction-backups",
        )
        if _instruction_transition(current_instruction_plan) != _instruction_transition(
            plan.instruction_plan
        ):
            raise WorkflowError("instruction targets changed after storage preparation")
        instruction_result = apply_instruction_plan(
            current_instruction_plan,
            confirmed=True,
            expected_plan_hash=current_instruction_plan.plan_hash,
        )
    except BaseException as error:
        _, conflicts = _restore_after_failure(
            before,
            committed,
            recovery_key=plan.plan_hash[:24],
        )
        if conflicts:
            raise WorkflowError(
                f"{error}; compensation_conflict: "
                + ", ".join(path.name for path in conflicts)
            ) from error
        raise
    hashes = dict(sorted(storage_result.hashes.items()))
    return {
        "status": "installed",
        "installation_id": plan.installation_id,
        "plan_hash": plan.plan_hash,
        "generation_id": storage_result.generation_id,
        "hashes": hashes,
        "paths": {
            **{label: str(path) for label, path in _artifact_paths(plan.paths).items()},
            "state": str(plan.state_plan.path),
            "instruction_targets": [
                str(operation.target.path)
                for operation in plan.instruction_plan.operations
            ],
            "instruction_manifest": (
                None
                if instruction_result.manifest_path is None
                else str(instruction_result.manifest_path)
            ),
            "instruction_backup": str(
                instruction_result.backup_directory or current_instruction_plan.backup_root
            ),
            "state_manifest": (
                None if state_result.manifest_path is None else str(state_result.manifest_path)
            ),
            "state_backup": str(
                state_result.backup_directory
                or plan.state_plan.path.parent / "state-backups"
            ),
        },
        "counts": plan.public["counts"],
    }


def _instruction_transition(plan: InstructionPlan) -> tuple[tuple[Any, ...], ...]:
    """Compare target transitions while excluding backup ancestry evidence."""

    return tuple(
        (
            str(item.target.path),
            item.operation,
            item.original_exists,
            item.expected_original_sha256,
            item.target_sha256,
            item.original_mode,
            item.newline,
            item.diagnostics,
        )
        for item in plan.operations
    )


def _validate_opaque_identifier(value: Any, prefix: str) -> str:
    allowed = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"
    if (
        not isinstance(value, str)
        or not value.startswith(prefix)
        or len(value) <= len(prefix)
        or len(value) > 128
        or any(character not in allowed for character in value)
    ):
        raise ValueError("invalid opaque identifier")
    return value


def _opaque_identifier(value: Any, prefix: str) -> str:
    try:
        return _validate_opaque_identifier(value, prefix)
    except ValueError as error:
        raise WorkflowError(
            "capability map contains an invalid opaque identifier"
        ) from error


def _config_for(paths: StoragePaths) -> dict[str, Any]:
    try:
        config = _read_json(paths.config_path)
    except FileNotFoundError as error:
        raise WorkflowError("capability map is not installed at the selected storage") from error
    if (
        config.get("schema_version") != 1
        or config.get("mode") != "setup"
        or set(config)
        != {"schema_version", "mode", "installation_id", "state_id"}
    ):
        raise WorkflowError("capability map config is invalid")
    _opaque_identifier(config.get("installation_id"), "inst_")
    _opaque_identifier(config.get("state_id"), "state_")
    return config


def _runtime_context(
    base_paths: StoragePaths,
    *,
    home: Path,
    environ: Mapping[str, str],
    require_active: bool = True,
) -> RuntimeContext:
    config = _config_for(base_paths)
    installation_id = str(config["installation_id"])
    paths = _namespaced_paths(
        base_paths,
        installation_id=installation_id,
        home=home,
        environ=environ,
    )
    expected_state_id = _state_id(paths, installation_id)
    if not hmac.compare_digest(str(config["state_id"]), expected_state_id):
        raise WorkflowError("capability map state reference does not match storage")
    state_path = _state_path(paths)
    state = _read_json(state_path)
    if stat.S_IMODE(os.stat(state_path, follow_symlinks=False).st_mode) != 0o600:
        raise WorkflowError("private installation state must use mode 0600")
    request_raw = state.get("target_request")
    if (
        state.get("schema_version") != 1
        or state.get("installation_id") != installation_id
        or state.get("state_id") != expected_state_id
        or state.get("public_root") != str(paths.public_root)
        or not isinstance(request_raw, dict)
    ):
        raise WorkflowError("private installation state is invalid")
    lifecycle = state.get("status")
    active = state.get("active")
    if lifecycle not in {"active", "migrated"} or active is not (
        lifecycle == "active"
    ):
        raise WorkflowError("private installation lifecycle is invalid")
    if lifecycle == "migrated":
        _opaque_identifier(state.get("migrated_to_state_id"), "state_")
        namespace = state.get("migrated_to_namespace")
        if (
            not isinstance(namespace, str)
            or len(namespace) != 32
            or any(character not in "0123456789abcdef" for character in namespace)
        ):
            raise WorkflowError("private migration namespace is invalid")
        if require_active:
            raise RefusedError("capability map installation has migrated")
    try:
        request = InstructionTargetRequest(
            home=Path(request_raw["home"]),
            project_root=(
                None
                if request_raw.get("project_root") is None
                else Path(request_raw["project_root"])
            ),
            codex_home=Path(request_raw["codex_home"]),
            agents=tuple(request_raw["agents"]),
            scopes=tuple(request_raw["scopes"]),
        )
        project_root = Path(state["project_root"])
    except (KeyError, TypeError, ValueError) as error:
        raise WorkflowError("private installation state target request is invalid") from error
    if (
        str(request.home) != state.get("home")
        or str(request.codex_home) != state.get("codex_home")
        or list(request.agents) != state.get("agents")
        or request.scopes[0] != state.get("scope")
        or not project_root.is_absolute()
    ):
        raise WorkflowError("private installation state target request does not match")
    return RuntimeContext(paths, state_path, config, state, request, project_root)


def _capability_from_public(raw: Any) -> Capability:
    if not isinstance(raw, dict):
        raise ValueError("inventory capability must be an object")
    required = {"id", "kind", "name", "resolver_id", "scope", "states"}
    if not required <= set(raw):
        raise ValueError("inventory capability is missing required fields")
    states_raw = raw["states"]
    if not isinstance(states_raw, dict):
        raise ValueError("inventory capability states are invalid")
    states = CapabilityStates(
        discovered=str(states_raw.get("discovered", "unknown")),
        probed=str(states_raw.get("probed", "unknown")),
        authenticated=str(states_raw.get("authenticated", "unknown")),
        verified=str(states_raw.get("verified", "unknown")),
    )
    sources_raw = raw.get("source_locations", [])
    diagnostics_raw = raw.get("diagnostics", [])
    if not isinstance(sources_raw, list) or not isinstance(diagnostics_raw, list):
        raise ValueError("inventory capability collections are invalid")
    sources = tuple(
        SourceLocation(
            str(item.get("location", "")),
            str(item.get("scope", "extra")),
            str(item.get("provider", "")),
        )
        for item in sources_raw
        if isinstance(item, dict)
    )
    diagnostics = tuple(
        Diagnostic(
            str(item.get("severity", "warning")),
            str(item.get("code", "inventory")),
            str(item.get("message", "")),
            item.get("details", {}) if isinstance(item.get("details", {}), dict) else {},
        )
        for item in diagnostics_raw
        if isinstance(item, dict)
    )
    capability = Capability(
        kind=str(raw["kind"]),
        name=str(raw["name"]),
        description=str(raw.get("description", "")),
        aliases=tuple(str(item) for item in raw.get("aliases", [])),
        tags=tuple(str(item) for item in raw.get("tags", [])),
        scenes=tuple(str(item) for item in raw.get("scenes", [])),
        source_locations=sources,
        scope=str(raw["scope"]),
        provider=str(raw.get("provider", "")),
        version=None if raw.get("version") is None else str(raw["version"]),
        states=states,
        classification_confidence=float(raw.get("classification_confidence", 0.0)),
        diagnostics=diagnostics,
    )
    public_id = str(raw["id"])
    resolver_id = str(raw["resolver_id"])
    if not public_id.startswith("cap_") or not resolver_id.startswith("res_"):
        raise ValueError("inventory capability IDs are invalid")
    object.__setattr__(capability, "id", public_id)
    object.__setattr__(capability, "resolver_id", resolver_id)
    return capability


def _inventory_capabilities(paths: StoragePaths) -> tuple[Capability, ...]:
    inventory = _read_json(paths.inventory_path)
    raw = inventory.get("capabilities")
    if not isinstance(raw, list) or len(raw) > 100_000:
        raise WorkflowError("capability inventory is invalid")
    try:
        return tuple(_capability_from_public(item) for item in raw)
    except (TypeError, ValueError) as error:
        raise WorkflowError("capability inventory is invalid") from error


def _handle_scan(
    args: argparse.Namespace,
    *, home: Path,
    cwd: Path,
    environ: Mapping[str, str],
) -> dict[str, Any]:
    project = _absolute(args.project, cwd=cwd, home=home)
    extras = tuple(_absolute(item, cwd=cwd, home=home) for item in args.skill_root)
    result = _scan(
        home=home,
        project=project,
        cwd=cwd,
        environ=environ,
        extra_skill_roots=extras,
        probe_versions=args.probe_versions == "explicit",
    )
    inventory = json.loads(result.inventory_text)
    if args.output_dir is not None:
        if args.confirmed is not True:
            raise RefusedError("--confirmed is required with --output-dir")
        base_paths = default_storage_paths(
            home=home,
            environ=environ,
            local_root=_absolute(args.output_dir, cwd=cwd, home=home),
        )
        installation_id = "scan_" + _digest(str(base_paths.public_root))[:24]
        paths = _namespaced_paths(
            base_paths,
            installation_id=installation_id,
            home=home,
            environ=environ,
        )
        state_id = _state_id(paths, installation_id)
        artifacts = PublicArtifacts(
            result.map_markdown,
            result.inventory_text,
            _configuration(
                installation_id=installation_id,
                state_id=state_id,
                mode="scan",
            ),
            "# Capability map scan receipt\n\n"
            f"- installation: `{installation_id}`\n"
            f"- private namespace: `{state_id}`\n",
        )
        expected = capture_storage_expected_state(paths)
        written = write_storage_bundle(
            paths, artifacts, result.resolvers, expected_state=expected
        )
        inventory["written"] = {
            "generation_id": written.generation_id,
            "paths": {label: str(path) for label, path in _artifact_paths(paths).items()},
        }
    return inventory


def _handle_setup(
    args: argparse.Namespace,
    *, home: Path,
    cwd: Path,
    environ: Mapping[str, str],
) -> dict[str, Any]:
    plan = _build_setup_plan(args=args, home=home, cwd=cwd, environ=environ)
    if args.setup_action == "plan":
        return plan.public
    if args.confirmed is not True:
        raise RefusedError("--confirmed is required before setup apply")
    expected = args.expected_plan_hash
    if not isinstance(expected, str) or not hmac.compare_digest(expected, plan.plan_hash):
        raise RefusedError("expected plan hash does not match the current plan")
    if not plan.instruction_plan.applicable:
        raise RefusedError("instruction plan contains conflicts")
    return _apply_storage_then_instructions(plan)


def _status_payload(
    base_paths: StoragePaths,
    *,
    home: Path,
    environ: Mapping[str, str],
) -> dict[str, Any]:
    context: RuntimeContext | None = None
    health_errors: list[str] = []
    lifecycle = "missing"
    try:
        context = _runtime_context(
            base_paths, home=home, environ=environ, require_active=False
        )
        paths = context.paths
        lifecycle = str(context.state["status"])
    except (FileNotFoundError, OSError, WorkflowError, ValueError) as error:
        if base_paths.config_path.exists():
            lifecycle = "invalid"
            health_errors.append("config/state: " + _safe_error(error))
        paths = base_paths
    path_map = _artifact_paths(paths)
    if context is not None:
        path_map["state"] = context.state_path
    files: dict[str, dict[str, Any]] = {}
    for label, path in path_map.items():
        try:
            payload = _read_regular(path)
        except FileNotFoundError:
            files[label] = {"exists": False, "sha256": None}
            health_errors.append(f"{label}: missing")
        except (OSError, ValueError):
            files[label] = {"exists": False, "sha256": None, "invalid": True}
            health_errors.append(f"{label}: invalid")
        else:
            files[label] = {"exists": True, "sha256": _digest(payload)}
            if label in {"map", "receipt"}:
                try:
                    text = payload.decode("utf-8")
                except UnicodeDecodeError:
                    text = ""
                if not text.strip():
                    health_errors.append(f"{label}: invalid markdown")
    all_artifacts_exist = all(
        files.get(label, {}).get("exists") for label in _ARTIFACT_LABELS
    )
    if context is not None:
        try:
            _inventory_capabilities(context.paths)
        except (FileNotFoundError, OSError, RuntimeError, TypeError, ValueError):
            health_errors.append("inventory: invalid JSON or schema")
        try:
            resolver = _read_json(context.paths.resolver_path)
            storage = resolver.get("storage")
            records = resolver.get("records")
            expected_storage = build_private_resolver_document(
                context.paths, ()
            )["storage"]
            if (
                set(resolver) != {"schema_version", "storage", "records"}
                or resolver.get("schema_version") != 1
                or not isinstance(storage, dict)
                or not isinstance(records, list)
                or len(records) > 100_000
                or storage != expected_storage
                or any(
                    not isinstance(record, dict)
                    or set(record) != {"resolver_id", "exact_locations"}
                    or not isinstance(record.get("resolver_id"), str)
                    or not record["resolver_id"].startswith("res_")
                    or len(record["resolver_id"]) > 128
                    or any(
                        character
                        not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"
                        for character in record["resolver_id"]
                    )
                    or not isinstance(record.get("exact_locations"), list)
                    or any(
                        not isinstance(location, str)
                        for location in record["exact_locations"]
                    )
                    for record in records
                )
                or len({record["resolver_id"] for record in records}) != len(records)
            ):
                raise ValueError("resolver schema mismatch")
            if os.name != "nt" and stat.S_IMODE(
                os.stat(context.paths.resolver_path, follow_symlinks=False).st_mode
            ) != 0o600:
                raise ValueError("resolver mode mismatch")
        except (FileNotFoundError, OSError, TypeError, ValueError):
            health_errors.append("resolver: invalid JSON, schema, or mode")
        if lifecycle == "active":
            try:
                instruction = build_instruction_plan(
                    context.target_request,
                    str(context.config["installation_id"]),
                    context.paths.map_path,
                    context.paths.resolver_path,
                    backup_root=context.paths.private_root / "instruction-backups",
                )
                if not instruction.applicable or instruction.changed_operations:
                    raise ValueError("managed instruction block is not current")
            except (FileNotFoundError, OSError, RuntimeError, TypeError, ValueError):
                health_errors.append("instructions: managed block is not current")
    health_errors = sorted(set(health_errors))
    installed = bool(
        context is not None
        and lifecycle == "active"
        and all_artifacts_exist
        and files.get("state", {}).get("exists")
    )
    return {
        "installed": installed,
        "healthy": installed and not health_errors,
        "health_errors": health_errors,
        "lifecycle": lifecycle,
        "installation_id": (
            None if context is None else context.config["installation_id"]
        ),
        "files": files,
    }


def _handle_refresh(
    args: argparse.Namespace,
    *, home: Path,
    cwd: Path,
    environ: Mapping[str, str],
) -> dict[str, Any]:
    if not args.dry_run and not args.confirmed:
        raise RefusedError("refresh requires --dry-run or --confirmed")
    base_paths = _storage_paths(
        storage=args.storage,
        vault=args.vault,
        home=home,
        cwd=cwd,
        environ=environ,
    )
    context = _runtime_context(base_paths, home=home, environ=environ)
    paths = context.paths
    storage_expected = capture_storage_expected_state(paths)
    installation_id = str(context.config["installation_id"])
    scan = _scan(
        home=home,
        project=context.project_root,
        cwd=context.project_root,
        environ=environ,
    )
    instruction_plan = build_instruction_plan(
        context.target_request,
        installation_id,
        paths.map_path,
        paths.resolver_path,
        backup_root=paths.private_root / "instruction-backups",
    )
    artifacts = _artifacts(
        scan=scan,
        installation_id=installation_id,
        state_id=str(context.config["state_id"]),
        instruction_plan=instruction_plan,
    )
    current = _current_storage_state(paths)
    desired = {
        label: _digest(payload)
        for label, payload in _desired_storage_bytes(paths, artifacts, scan).items()
    }
    changes = [
        label
        for label in _ARTIFACT_LABELS
        if current[label]["sha256"] != desired[label]
    ]
    plan_hash = _digest(
        {
            "action": "refresh",
            "installation_id": installation_id,
            "current": current,
            "desired": desired,
            "storage_expected": _storage_expected_transition(storage_expected),
        }
    )
    payload = {
        "status": "dry-run" if args.dry_run else "refreshed",
        "plan_hash": plan_hash,
        "changes": changes,
        "counts": {**_capability_counts(scan), "storage_changes": len(changes)},
    }
    if args.dry_run:
        return payload
    result = write_storage_bundle(
        paths, artifacts, scan.resolvers, expected_state=storage_expected
    )
    payload["generation_id"] = result.generation_id
    payload["paths"] = {
        label: str(path) for label, path in _artifact_paths(paths).items()
    }
    payload["paths"]["state"] = str(context.state_path)
    return payload


def _handle_migrate(
    args: argparse.Namespace,
    *, home: Path,
    cwd: Path,
    environ: Mapping[str, str],
) -> dict[str, Any]:
    if not args.dry_run and not args.confirmed:
        raise RefusedError("migrate requires --dry-run or --confirmed")
    old_base_paths = _storage_paths(
        storage=args.storage,
        vault=args.vault,
        home=home,
        cwd=cwd,
        environ=environ,
    )
    context = _runtime_context(old_base_paths, home=home, environ=environ)
    old_paths = context.paths
    new_base_paths = default_storage_paths(
        home=home,
        environ=environ,
        local_root=_absolute(args.to, cwd=cwd, home=home),
    )
    installation_id = str(context.config["installation_id"])
    new_paths = _namespaced_paths(
        new_base_paths,
        installation_id=installation_id,
        home=home,
        environ=environ,
    )
    storage_expected = capture_storage_expected_state(new_paths)
    if new_paths.public_root == old_paths.public_root:
        raise RefusedError("migration destination must differ from current storage")
    request = context.target_request
    scan = _scan(
        home=home,
        project=context.project_root,
        cwd=context.project_root,
        environ=environ,
    )
    new_state_id = _state_id(new_paths, installation_id)
    instruction_plan = build_instruction_plan(
        request,
        installation_id,
        new_paths.map_path,
        new_paths.resolver_path,
        backup_root=new_paths.private_root / "instruction-backups",
    )
    artifacts = _artifacts(
        scan=scan,
        installation_id=installation_id,
        state_id=new_state_id,
        instruction_plan=instruction_plan,
    )
    state_document = _runtime_state_document(
        paths=new_paths,
        installation_id=installation_id,
        state_id=new_state_id,
        project_root=context.project_root,
        request=request,
    )
    state_plan = _state_write_plan(_state_path(new_paths), state_document)
    migrated_state_document = {
        **context.state,
        "status": "migrated",
        "active": False,
        "migrated_to_state_id": new_state_id,
        "migrated_to_namespace": new_paths.private_root.name,
    }
    migrated_state_plan = _state_write_plan(
        context.state_path, migrated_state_document
    )
    current = _current_storage_state(new_paths, state_path=state_plan.path)
    desired = {
        **{
            label: _digest(payload)
            for label, payload in _desired_storage_bytes(
                new_paths, artifacts, scan
            ).items()
        },
        "state": _digest(state_plan.desired_bytes),
    }
    plan_hash = _digest(
        {
            "action": "migrate",
            "from": str(old_paths.public_root),
            "to": str(new_paths.public_root),
            "current": current,
            "desired": desired,
            "storage_expected": _storage_expected_transition(storage_expected),
            "instruction_plan_hash": instruction_plan.plan_hash,
            "state_plan_hash": state_plan.plan_hash,
            "source_state_plan_hash": migrated_state_plan.plan_hash,
        }
    )
    payload = {
        "status": "dry-run" if args.dry_run else "migrated",
        "from": str(old_paths.public_root),
        "to": str(new_paths.public_root),
        "old_data_preserved": True,
        "plan_hash": plan_hash,
        "changes": [
            label
            for label in (*_ARTIFACT_LABELS, "state")
            if current[label]["sha256"] != desired[label]
        ],
        "instruction_operations": [
            {
                "path": str(item.target.path),
                "operation": item.operation,
            }
            for item in instruction_plan.operations
        ],
    }
    if args.dry_run:
        return payload
    before = _snapshots(new_paths, state_path=state_plan.path)
    committed: dict[Path, FileSnapshot] = {}
    instruction_applied = False
    try:
        storage_result = write_storage_bundle(
            new_paths,
            artifacts,
            scan.resolvers,
            expected_state=storage_expected,
        )
        committed.update(_snapshots(new_paths))
        current_state_plan = _state_write_plan(state_plan.path, state_document)
        if _state_transition(current_state_plan) != _state_transition(state_plan):
            raise WorkflowError("migration state changed after storage preparation")
        state_result = _apply_state_plan(current_state_plan)
        committed[state_plan.path] = _snapshot(state_plan.path)
        current_instruction_plan = build_instruction_plan(
            request,
            installation_id,
            new_paths.map_path,
            new_paths.resolver_path,
            backup_root=new_paths.private_root / "instruction-backups",
        )
        if _instruction_transition(current_instruction_plan) != _instruction_transition(
            instruction_plan
        ):
            raise WorkflowError("instruction targets changed after migration preparation")
        apply_instruction_plan(
            current_instruction_plan,
            confirmed=True,
            expected_plan_hash=current_instruction_plan.plan_hash,
        )
        instruction_applied = True
        current_migrated_state_plan = _state_write_plan(
            context.state_path, migrated_state_document
        )
        if _state_transition(current_migrated_state_plan) != _state_transition(
            migrated_state_plan
        ):
            raise WorkflowError("source installation state changed during migration")
        migrated_state_result = _apply_state_plan(current_migrated_state_plan)
    except BaseException as error:
        instruction_compensation_error: BaseException | None = None
        if instruction_applied:
            try:
                restore_instruction = build_instruction_plan(
                    request,
                    installation_id,
                    old_paths.map_path,
                    old_paths.resolver_path,
                    backup_root=old_paths.private_root / "instruction-backups",
                )
                apply_instruction_plan(
                    restore_instruction,
                    confirmed=True,
                    expected_plan_hash=restore_instruction.plan_hash,
                )
            except BaseException as compensation_error:
                instruction_compensation_error = compensation_error
        _, conflicts = _restore_after_failure(
            before, committed, recovery_key=plan_hash[:24]
        )
        if conflicts or instruction_compensation_error is not None:
            details = [path.name for path in conflicts]
            if instruction_compensation_error is not None:
                details.append("instructions")
            raise WorkflowError(
                f"{error}; compensation_conflict: "
                + ", ".join(details)
            ) from error
        raise
    payload["generation_id"] = storage_result.generation_id
    payload["paths"] = {
        label: str(path) for label, path in _artifact_paths(new_paths).items()
    }
    payload["paths"].update(
        {
            "state": str(state_plan.path),
            "state_backup": str(
                state_result.backup_directory or state_plan.path.parent / "state-backups"
            ),
            "instruction_backup": str(current_instruction_plan.backup_root),
            "source_state_backup": str(
                migrated_state_result.backup_directory
                or context.state_path.parent / "state-backups"
            ),
        }
    )
    return payload


def _purge_data(
    paths: StoragePaths, installation_id: str, *, state_path: Path
) -> Path:
    recovery = paths.private_root / "purge-recovery" / (
        installation_id
        + "-"
        + _digest(_current_storage_state(paths, state_path=state_path))[:16]
    )
    moved: list[tuple[Path, Path]] = []
    try:
        recovery.mkdir(parents=True, exist_ok=False)
        targets = {**_artifact_paths(paths), "state": state_path}
        for label, source in targets.items():
            if not source.exists():
                continue
            destination = recovery / f"{label}-{source.name}"
            os.replace(source, destination)
            moved.append((source, destination))
    except BaseException:
        for source, destination in reversed(moved):
            if destination.exists() and not source.exists():
                source.parent.mkdir(parents=True, exist_ok=True)
                os.replace(destination, source)
        raise
    return recovery


def _handle_uninstall(
    args: argparse.Namespace,
    *, home: Path,
    cwd: Path,
    environ: Mapping[str, str],
) -> dict[str, Any]:
    if not args.dry_run and not args.confirmed:
        raise RefusedError("uninstall requires --dry-run or --confirmed")
    base_paths = _storage_paths(
        storage=args.storage,
        vault=args.vault,
        home=home,
        cwd=cwd,
        environ=environ,
    )
    context = _runtime_context(base_paths, home=home, environ=environ)
    paths = context.paths
    request = context.target_request
    installation_id = str(context.config["installation_id"])
    instruction_plan = build_uninstall_plan(
        request,
        installation_id,
        backup_root=paths.private_root / "instruction-backups",
    )
    payload = {
        "status": "dry-run" if args.dry_run else "uninstalled",
        "installation_id": installation_id,
        "purge_data": bool(args.purge_data),
        "plan_hash": instruction_plan.plan_hash,
        "instruction_operations": [
            {
                "path": str(item.target.path),
                "operation": item.operation,
            }
            for item in instruction_plan.operations
        ],
        "data_preserved": not args.purge_data,
    }
    if args.dry_run:
        return payload
    if instruction_plan.operations:
        apply_instruction_plan(
            instruction_plan,
            confirmed=True,
            expected_plan_hash=instruction_plan.plan_hash,
        )
    if args.purge_data:
        try:
            recovery = _purge_data(
                paths, installation_id, state_path=context.state_path
            )
        except BaseException:
            reinstall = build_instruction_plan(
                request,
                installation_id,
                paths.map_path,
                paths.resolver_path,
                backup_root=paths.private_root / "instruction-backups",
            )
            apply_instruction_plan(
                reinstall,
                confirmed=True,
                expected_plan_hash=reinstall.plan_hash,
            )
            raise
        payload["status"] = "purged"
        payload["recovery_directory"] = str(recovery)
        payload["data_preserved"] = False
    return payload


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="capability_map.py")
    commands = parser.add_subparsers(dest="command", required=True)

    scan = commands.add_parser("scan")
    scan.add_argument("--project", default=".")
    scan.add_argument("--skill-root", action="append", default=[])
    scan.add_argument("--output-dir")
    scan.add_argument("--confirmed", action="store_true")
    scan.add_argument(
        "--probe-versions",
        nargs="?",
        const="explicit",
        choices=("explicit",),
    )

    setup = commands.add_parser("setup")
    setup_actions = setup.add_subparsers(dest="setup_action", required=True)
    for action in ("plan", "apply"):
        child = setup_actions.add_parser(action)
        storage = child.add_mutually_exclusive_group()
        storage.add_argument("--storage")
        storage.add_argument("--vault")
        child.add_argument("--agents", choices=("codex", "claude", "both"), default="both")
        child.add_argument("--scope", choices=("user", "project"), default="user")
        child.add_argument("--project", default=".")
        child.add_argument("--installation-id")
        child.add_argument("--confirmed", action="store_true")
        child.add_argument("--expected-plan-hash")

    for name in ("status", "paths"):
        command = commands.add_parser(name)
        storage = command.add_mutually_exclusive_group()
        storage.add_argument("--storage")
        storage.add_argument("--vault")

    refresh = commands.add_parser("refresh")
    storage = refresh.add_mutually_exclusive_group()
    storage.add_argument("--storage")
    storage.add_argument("--vault")
    refresh_mode = refresh.add_mutually_exclusive_group()
    refresh_mode.add_argument("--dry-run", action="store_true")
    refresh_mode.add_argument("--confirmed", action="store_true")

    route = commands.add_parser("route")
    storage = route.add_mutually_exclusive_group()
    storage.add_argument("--storage")
    storage.add_argument("--vault")
    route.add_argument("--query", required=True)
    route.add_argument("--json", action="store_true")

    migrate = commands.add_parser("migrate")
    storage = migrate.add_mutually_exclusive_group()
    storage.add_argument("--storage")
    storage.add_argument("--vault")
    migrate.add_argument("--to", required=True)
    migrate_mode = migrate.add_mutually_exclusive_group()
    migrate_mode.add_argument("--dry-run", action="store_true")
    migrate_mode.add_argument("--confirmed", action="store_true")

    uninstall = commands.add_parser("uninstall")
    storage = uninstall.add_mutually_exclusive_group()
    storage.add_argument("--storage")
    storage.add_argument("--vault")
    uninstall_mode = uninstall.add_mutually_exclusive_group()
    uninstall_mode.add_argument("--dry-run", action="store_true")
    uninstall_mode.add_argument("--confirmed", action="store_true")
    uninstall.add_argument("--purge-data", action="store_true")

    intent = commands.add_parser("help-intent")
    intent.add_argument("--query", required=True)
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    home: Path | None = None,
    cwd: Path | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    """Run one command with fully injectable machine context and streams."""

    environment = dict(os.environ if environ is None else environ)
    injected_home = Path.home() if home is None else Path(home).absolute()
    injected_cwd = Path.cwd() if cwd is None else Path(cwd).absolute()
    output = sys.stdout if stdout is None else stdout
    errors = sys.stderr if stderr is None else stderr
    parser = _parser()
    try:
        with contextlib.redirect_stderr(errors), contextlib.redirect_stdout(output):
            try:
                args = parser.parse_args(None if argv is None else list(argv))
            except SystemExit as error:
                return int(error.code)

        if args.command == "scan":
            payload = _handle_scan(
                args,
                home=injected_home,
                cwd=injected_cwd,
                environ=environment,
            )
        elif args.command == "setup":
            payload = _handle_setup(
                args,
                home=injected_home,
                cwd=injected_cwd,
                environ=environment,
            )
        elif args.command in {"status", "paths"}:
            base_paths = _storage_paths(
                storage=args.storage,
                vault=args.vault,
                home=injected_home,
                cwd=injected_cwd,
                environ=environment,
            )
            if args.command == "status":
                payload = _status_payload(
                    base_paths, home=injected_home, environ=environment
                )
            else:
                context = _runtime_context(
                    base_paths, home=injected_home, environ=environment
                )
                payload = {
                    "paths": {
                        label: str(path)
                        for label, path in _artifact_paths(context.paths).items()
                    },
                    **_status_payload(
                        base_paths, home=injected_home, environ=environment
                    ),
                }
                payload["paths"]["state"] = str(context.state_path)
        elif args.command == "refresh":
            payload = _handle_refresh(
                args,
                home=injected_home,
                cwd=injected_cwd,
                environ=environment,
            )
        elif args.command == "route":
            base_paths = _storage_paths(
                storage=args.storage,
                vault=args.vault,
                home=injected_home,
                cwd=injected_cwd,
                environ=environment,
            )
            context = _runtime_context(
                base_paths, home=injected_home, environ=environment
            )
            intent = interpret_capability_map_intent(args.query)
            if intent != "usage" or any(
                marker in args.query for marker in ("怎么用", "帮助")
            ):
                payload = {
                    "query": sanitize_text(args.query, max_length=1024),
                    "intent": intent,
                    "matches": [],
                }
            else:
                payload = route_query(
                    args.query,
                    _inventory_capabilities(context.paths),
                ).to_public_dict()
        elif args.command == "migrate":
            payload = _handle_migrate(
                args,
                home=injected_home,
                cwd=injected_cwd,
                environ=environment,
            )
        elif args.command == "uninstall":
            payload = _handle_uninstall(
                args,
                home=injected_home,
                cwd=injected_cwd,
                environ=environment,
            )
        else:
            payload = {
                "query": sanitize_text(args.query, max_length=1024),
                "intent": interpret_capability_map_intent(args.query),
            }
        _write_json(output, payload)
        return 0
    except RefusedError as error:
        errors.write(_safe_error(error) + "\n")
        return 2
    except (FileNotFoundError, OSError, RuntimeError, TypeError, ValueError) as error:
        errors.write(_safe_error(error) + "\n")
        return 3


if __name__ == "__main__":
    raise SystemExit(main())

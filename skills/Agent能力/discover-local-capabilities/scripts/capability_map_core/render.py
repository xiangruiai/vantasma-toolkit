"""Deterministic public JSON and concise Markdown capability reports."""

from __future__ import annotations

import json
import re
import unicodedata
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from .classify import SceneDefinition, load_taxonomy
from .models import Capability, Diagnostic, InventoryMetadata
from .sanitize import REDACTED, sanitize, sanitize_text


DEFAULT_PRESENTATION_CAP = 6
_MARKDOWN_META_RE = re.compile(r"([`*_\[\]<>#+.!()])")


def _sensitive_public_key(value: str) -> bool:
    expanded = re.sub(
        r"(?<=[a-z0-9])(?=[A-Z])",
        "_",
        unicodedata.normalize("NFKC", value),
    ).casefold()
    parts = tuple(re.findall(r"[a-z0-9]+", expanded))
    sensitive_parts = {
        "authorization",
        "cookie",
        "credential",
        "credentials",
        "password",
        "secret",
        "token",
    }
    if any(part in sensitive_parts for part in parts):
        return True
    pairs = set(zip(parts, parts[1:]))
    return bool(
        pairs.intersection(
            {
                ("api", "key"),
                ("auth", "header"),
                ("private", "key"),
            }
        )
    )


def _strict_public_sanitize(value: Any) -> Any:
    """Sanitize recursively, then redact values for broad secret-key families."""

    safe = sanitize(value)

    def redact_keyed_values(item: Any) -> Any:
        if isinstance(item, dict):
            return {
                key: (
                    REDACTED
                    if _sensitive_public_key(key)
                    else redact_keyed_values(child)
                )
                for key, child in item.items()
            }
        if isinstance(item, list):
            return [redact_keyed_values(child) for child in item]
        return item

    return redact_keyed_values(safe)


def _capabilities(values: Iterable[Capability]) -> tuple[Capability, ...]:
    if isinstance(values, (str, bytes, bytearray)) or isinstance(values, Mapping):
        raise TypeError("capabilities must be a collection of Capability values")
    result = tuple(values)
    if any(not isinstance(item, Capability) for item in result):
        raise TypeError("capabilities must contain Capability values")
    return tuple(
        sorted(
            result,
            key=lambda item: (
                item.kind,
                item.name.casefold(),
                item.name,
                item.id,
                json.dumps(
                    item.to_public_dict(),
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
            ),
        )
    )


def _diagnostics(values: Iterable[Diagnostic]) -> tuple[Diagnostic, ...]:
    if isinstance(values, (str, bytes, bytearray)) or isinstance(values, Mapping):
        raise TypeError("diagnostics must be a collection of Diagnostic values")
    result = tuple(values)
    if any(not isinstance(item, Diagnostic) for item in result):
        raise TypeError("diagnostics must contain Diagnostic values")
    return tuple(
        sorted(
            result,
            key=lambda item: json.dumps(
                item.to_public_dict(), ensure_ascii=False, sort_keys=True
            ),
        )
    )


def _public_metadata(
    metadata: InventoryMetadata | Mapping[str, Any], capability_count: int
) -> tuple[dict[str, Any], tuple[Diagnostic, ...]]:
    if isinstance(metadata, InventoryMetadata):
        public = metadata.to_public_dict()
        embedded = tuple(metadata.diagnostics)
    elif isinstance(metadata, Mapping):
        allowed = {"schema_version", "generated_at", "capability_count", "diagnostics"}
        selected = {key: metadata[key] for key in allowed if key in metadata}
        raw_diagnostics = selected.pop("diagnostics", ())
        if raw_diagnostics is None:
            raw_diagnostics = ()
        embedded = _diagnostics(raw_diagnostics)
        public = {
            "schema_version": selected.get("schema_version", 2),
            "generated_at": selected.get("generated_at", ""),
            "capability_count": selected.get("capability_count", capability_count),
            "diagnostics": [item.to_public_dict() for item in embedded],
        }
    else:
        raise TypeError("metadata must be InventoryMetadata or a mapping")
    schema_version = public.get("schema_version", 2)
    if isinstance(schema_version, bool) or not isinstance(schema_version, int):
        raise TypeError("metadata schema_version must be an integer")
    generated_at = public.get("generated_at", "")
    if not isinstance(generated_at, str):
        raise TypeError("metadata generated_at must be a string")
    return (
        {
            "schema_version": schema_version,
            "generated_at": sanitize_text(generated_at, max_length=128),
            "capability_count": capability_count,
            "diagnostics": [item.to_public_dict() for item in embedded],
        },
        embedded,
    )


def _deduplicate_diagnostics(
    values: Iterable[Diagnostic],
) -> tuple[Diagnostic, ...]:
    """Deduplicate identical strict-public diagnostics by canonical JSON."""

    unique: dict[str, Diagnostic] = {}
    for item in values:
        key = json.dumps(
            _strict_public_sanitize(item.to_public_dict()),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        unique[key] = item
    return tuple(unique[key] for key in sorted(unique))


def _diagnostic_summary(diagnostics: Sequence[Diagnostic]) -> dict[str, Any]:
    by_severity = Counter(item.severity for item in diagnostics)
    by_code = Counter(item.code for item in diagnostics)
    return {
        "total": len(diagnostics),
        "by_severity": dict(sorted(by_severity.items())),
        "by_code": dict(sorted(by_code.items())),
    }


def _inventory_payload(
    capabilities: Iterable[Capability],
    metadata: InventoryMetadata | Mapping[str, Any],
    diagnostics: Iterable[Diagnostic],
) -> dict[str, Any]:
    ordered = _capabilities(capabilities)
    public_metadata, embedded = _public_metadata(metadata, len(ordered))
    capability_diagnostics = tuple(
        diagnostic
        for capability in ordered
        for diagnostic in capability.diagnostics
    )
    global_diagnostics = _deduplicate_diagnostics(
        (*embedded, *_diagnostics(diagnostics), *capability_diagnostics)
    )
    public_capabilities = [item.to_public_dict() for item in ordered]
    unclassified = [
        item.to_public_dict() for item in ordered if not item.scenes
    ]
    by_kind = Counter(item.kind for item in ordered)
    by_scene = Counter(scene for item in ordered for scene in item.scenes)
    return {
        "metadata": public_metadata,
        "summary": {
            "total": len(ordered),
            "by_kind": dict(sorted(by_kind.items())),
            "by_scene": dict(sorted(by_scene.items())),
            "unclassified": len(unclassified),
            "diagnostics": _diagnostic_summary(global_diagnostics),
        },
        "capabilities": public_capabilities,
        "unclassified": unclassified,
        "diagnostics": [item.to_public_dict() for item in global_diagnostics],
    }


def render_inventory_json(
    capabilities: Iterable[Capability],
    metadata: InventoryMetadata | Mapping[str, Any],
    diagnostics: Iterable[Diagnostic] = (),
) -> str:
    """Render the complete sanitized inventory; presentation caps never apply."""

    payload = _strict_public_sanitize(
        _inventory_payload(capabilities, metadata, diagnostics)
    )
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        indent=2,
    ) + "\n"


def _markdown_text(value: str, *, max_length: int = 512) -> str:
    safe = sanitize_text(value, max_length=max_length)
    pipe_marker = "\x00markdown-pipe\x00"
    safe = safe.replace("\\|", pipe_marker)
    safe = safe.replace("\\", "\\\\")
    safe = _MARKDOWN_META_RE.sub(r"\\\1", safe)
    return safe.replace(pipe_marker, "\\|")


def _taxonomy(
    taxonomy: Sequence[SceneDefinition] | str | Path | None,
    taxonomy_path: str | Path | None,
) -> tuple[SceneDefinition, ...]:
    if taxonomy is not None and taxonomy_path is not None:
        raise ValueError("Pass taxonomy or taxonomy_path, not both")
    if isinstance(taxonomy, (str, Path)):
        return load_taxonomy(taxonomy)
    if taxonomy is None:
        return load_taxonomy(taxonomy_path)
    result = tuple(taxonomy)
    if any(not isinstance(item, SceneDefinition) for item in result):
        raise TypeError("taxonomy must contain SceneDefinition values")
    return result


def _specificity(capability: Capability) -> tuple[int, int, int]:
    description = int(bool(capability.description))
    semantic_fields = len(capability.tags) + len(capability.aliases) + description
    kind_rank = {"skill": 4, "plugin": 3, "mcp": 2, "cli": 1}.get(
        capability.kind, 0
    )
    return semantic_fields, kind_rank, len(capability.description)


def _scene_candidates(
    capabilities: Sequence[Capability], scene_id: str
) -> tuple[Capability, ...]:
    candidates = [item for item in capabilities if scene_id in item.scenes]
    candidates.sort(
        key=lambda item: (
            -item.classification_confidence,
            tuple(-value for value in _specificity(item)),
            item.name.casefold(),
            item.name,
            item.id,
        )
    )
    return tuple(candidates)


def render_capability_map_markdown(
    capabilities: Iterable[Capability],
    metadata: InventoryMetadata | Mapping[str, Any],
    diagnostics: Iterable[Diagnostic] = (),
    taxonomy: Sequence[SceneDefinition] | str | Path | None = None,
    *,
    taxonomy_path: str | Path | None = None,
    presentation_cap: int = DEFAULT_PRESENTATION_CAP,
) -> str:
    """Render a bounded route map while leaving the JSON inventory complete."""

    if (
        isinstance(presentation_cap, bool)
        or not isinstance(presentation_cap, int)
        or presentation_cap < 1
    ):
        raise ValueError("presentation_cap must be a positive integer")
    ordered = _capabilities(capabilities)
    scenes = _taxonomy(taxonomy, taxonomy_path)
    public_metadata, embedded = _public_metadata(metadata, len(ordered))
    capability_diagnostics = tuple(
        diagnostic
        for capability in ordered
        for diagnostic in capability.diagnostics
    )
    global_diagnostics = _deduplicate_diagnostics(
        (*embedded, *_diagnostics(diagnostics), *capability_diagnostics)
    )
    diagnostic_counts = _diagnostic_summary(global_diagnostics)
    unclassified = tuple(item for item in ordered if not item.scenes)

    lines = [
        "# 本机能力地图",
        "",
    ]
    if public_metadata["generated_at"]:
        lines.extend(
            [
                f"> 清单元数据时间：{_markdown_text(public_metadata['generated_at'], max_length=128)}",
                "",
            ]
        )
    lines.extend(
        [
            "## 使用方式",
            "",
            "先用自然语言描述任务，再按下方场景选择有本机证据的候选。执行前通过 `resolver_id` 在私有解析索引中定位真实入口，Skill 候选应先完整读取其 `SKILL.md`。",
            "",
            "## 状态边界",
            "",
            "- `discovered` 只说明扫描时存在。",
            "- `probed` 只说明完成了可选探测。",
            "- `authenticated` 与 `verified` 必须在实际任务前检查，未知状态不能当作可用证明。",
            "",
            "## 场景 → 候选能力",
            "",
        ]
    )
    for scene in scenes:
        candidates = _scene_candidates(ordered, scene.id)
        lines.append(
            f"### {_markdown_text(scene.label_zh, max_length=128)} / "
            f"{_markdown_text(scene.label_en, max_length=128)}"
        )
        lines.append("")
        if not candidates:
            lines.extend(["暂无可靠候选。", ""])
            continue
        for candidate in candidates[:presentation_cap]:
            lines.append(
                "- "
                f"{_markdown_text(candidate.name)} "
                f"({candidate.kind}, confidence={candidate.classification_confidence:.3f}, "
                f"resolver_id={_markdown_text(candidate.resolver_id, max_length=128)})"
            )
        hidden = len(candidates) - min(len(candidates), presentation_cap)
        if hidden:
            lines.append(f"- 另有 {hidden} 项仅保留在完整 JSON 清单中。")
        lines.append("")

    lines.extend(
        [
            "## 待人工归类",
            "",
            f"共 {len(unclassified)} 项缺少可靠通用语义证据。以下只展示最多 {presentation_cap} 项，完整记录保留在 JSON 清单中。",
            "",
        ]
    )
    for item in unclassified[:presentation_cap]:
        lines.append(
            f"- {_markdown_text(item.name)} ({item.kind}, "
            f"resolver_id={_markdown_text(item.resolver_id, max_length=128)})"
        )
    if not unclassified:
        lines.append("- 无。")

    severity_parts = [
        f"{_markdown_text(name, max_length=32)}={count}"
        for name, count in diagnostic_counts["by_severity"].items()
    ]
    lines.extend(
        [
            "",
            "## 扫描诊断",
            "",
            f"共 {diagnostic_counts['total']} 条诊断"
            + (f"，按级别：{'，'.join(severity_parts)}。" if severity_parts else "。"),
            "",
            "## 刷新、迁移、卸载与帮助",
            "",
            "- 刚安装或移除能力后，请刷新能力地图。",
            "- 更换存储位置时使用迁移流程，并先检查 dry-run 计划。",
            "- 卸载默认只移除 Agent 路由托管块，保留地图数据。",
            "- 需要帮助时询问“能力地图怎么用”或查看命令帮助。",
            "",
        ]
    )
    return "\n".join(lines)


__all__ = [
    "DEFAULT_PRESENTATION_CAP",
    "render_capability_map_markdown",
    "render_inventory_json",
]

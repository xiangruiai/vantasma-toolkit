"""Neutral scene classification and deterministic natural-language routing."""

from __future__ import annotations

import json
import math
import re
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from functools import lru_cache
from pathlib import Path
from typing import Any

from .models import CAPABILITY_KINDS, Capability
from .sanitize import sanitize, sanitize_text


DEFAULT_TAXONOMY_PATH = (
    Path(__file__).resolve().parents[2] / "references" / "scene-taxonomy.json"
)
DEFAULT_MIN_CONFIDENCE = 0.34
DEFAULT_ROUTE_LIMIT = 8
UNRESOLVED_SAMPLE_LIMIT = 25

_SCENE_ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_SEGMENT_RE = re.compile(r"[a-z0-9]+|[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]+")
_ASCII_WORD_RE = re.compile(r"^[a-z0-9]+$")
_GENERIC_DESCRIPTIONS = frozenset(
    {
        "command discovered in path.",
        "command discovered in path",
    }
)
_LOW_INFORMATION_TOKENS = frozenset(
    {
        "a",
        "about",
        "am",
        "an",
        "and",
        "application",
        "are",
        "as",
        "at",
        "be",
        "been",
        "being",
        "by",
        "can",
        "cli",
        "command",
        "could",
        "did",
        "do",
        "does",
        "doing",
        "for",
        "from",
        "help",
        "in",
        "is",
        "it",
        "just",
        "make",
        "made",
        "makes",
        "making",
        "me",
        "my",
        "of",
        "on",
        "open",
        "or",
        "our",
        "please",
        "plugin",
        "run",
        "runner",
        "service",
        "should",
        "skill",
        "that",
        "the",
        "their",
        "these",
        "this",
        "those",
        "to",
        "tool",
        "tools",
        "use",
        "using",
        "utility",
        "was",
        "we",
        "were",
        "will",
        "with",
        "would",
        "you",
        "your",
    }
)


def _require_string_collection(
    values: Iterable[str], field_name: str
) -> tuple[str, ...]:
    if isinstance(values, (str, bytes, bytearray)) or isinstance(values, Mapping):
        raise TypeError(f"{field_name} must be a collection of strings")
    try:
        collected = tuple(values)
    except TypeError as error:
        raise TypeError(f"{field_name} must be a collection of strings") from error
    if any(not isinstance(value, str) for value in collected):
        raise TypeError(f"{field_name} must contain only strings")
    return collected


def _stable_strings(
    values: Iterable[str], field_name: str = "values"
) -> tuple[str, ...]:
    collected = _require_string_collection(values, field_name)
    normalized = {
        unicodedata.normalize("NFKC", sanitize_text(value, max_length=512)).casefold()
        for value in collected
        if sanitize_text(value, max_length=512)
    }
    return tuple(sorted(normalized))


def _stable_public_strings(
    values: Iterable[str], field_name: str = "values"
) -> tuple[str, ...]:
    collected = _require_string_collection(values, field_name)
    normalized = {
        unicodedata.normalize("NFC", sanitize_text(value, max_length=512))
        for value in collected
        if sanitize_text(value, max_length=512)
    }
    return tuple(sorted(normalized, key=lambda value: (value.casefold(), value)))


@dataclass(frozen=True)
class SceneDefinition:
    """One generic scene with bilingual semantic evidence."""

    id: str
    label_zh: str
    label_en: str
    keywords: tuple[str, ...] | list[str] = field(default_factory=tuple)
    phrases: tuple[str, ...] | list[str] = field(default_factory=tuple)
    kind_boosts: Mapping[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        scene_id = sanitize_text(self.id, max_length=128).casefold()
        if not _SCENE_ID_RE.fullmatch(scene_id) or scene_id == "unclassified":
            raise ValueError(f"Invalid scene id: {self.id!r}")
        label_zh = sanitize_text(self.label_zh, max_length=128)
        label_en = sanitize_text(self.label_en, max_length=128)
        if not label_zh or not label_en:
            raise ValueError("Scene labels must not be empty")
        if not isinstance(self.kind_boosts, Mapping):
            raise TypeError("kind_boosts must be a mapping")
        boosts: dict[str, float] = {}
        for kind, raw_boost in self.kind_boosts.items():
            normalized_kind = sanitize_text(kind, max_length=32).casefold()
            if normalized_kind not in CAPABILITY_KINDS:
                raise ValueError(f"Unsupported kind boost: {kind!r}")
            if isinstance(raw_boost, bool) or not isinstance(raw_boost, (int, float)):
                raise TypeError("kind boosts must be finite numbers")
            boost = float(raw_boost)
            if not math.isfinite(boost) or boost < 0.0 or boost > 2.0:
                raise ValueError("kind boosts must be between 0.0 and 2.0")
            boosts[normalized_kind] = boost
        keywords = _stable_strings(self.keywords, "keywords")
        phrases = _stable_strings(self.phrases, "phrases")
        if not keywords and not phrases:
            raise ValueError("A scene must contain generic semantic evidence")
        object.__setattr__(self, "id", scene_id)
        object.__setattr__(self, "label_zh", label_zh)
        object.__setattr__(self, "label_en", label_en)
        object.__setattr__(self, "keywords", keywords)
        object.__setattr__(self, "phrases", phrases)
        object.__setattr__(
            self,
            "kind_boosts",
            {kind: boosts[kind] for kind in sorted(boosts)},
        )


@dataclass(frozen=True)
class RouteMatch:
    """A public, explainable match for one locally discovered capability."""

    id: str
    name: str
    kind: str
    score: float
    evidence: tuple[str, ...] | list[str]
    scenes: tuple[str, ...] | list[str]
    resolver_id: str
    state_warning: str

    def __post_init__(self) -> None:
        if not math.isfinite(self.score) or self.score < 0.0:
            raise ValueError("route score must be a non-negative finite number")
        object.__setattr__(self, "id", sanitize_text(self.id, max_length=128))
        object.__setattr__(self, "name", sanitize_text(self.name, max_length=512))
        object.__setattr__(self, "kind", sanitize_text(self.kind, max_length=32))
        object.__setattr__(self, "score", round(float(self.score), 6))
        object.__setattr__(
            self, "evidence", _stable_strings(self.evidence, "evidence")
        )
        object.__setattr__(self, "scenes", _stable_strings(self.scenes, "scenes"))
        object.__setattr__(
            self,
            "resolver_id",
            sanitize_text(self.resolver_id, max_length=128),
        )
        object.__setattr__(
            self,
            "state_warning",
            sanitize_text(self.state_warning, max_length=512),
        )

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "kind": self.kind,
            "score": self.score,
            "evidence": list(self.evidence),
            "scenes": list(self.scenes),
            "resolver_id": self.resolver_id,
            "state_warning": self.state_warning,
        }


@dataclass(frozen=True)
class UnresolvedSummary:
    """A bounded summary of capabilities with no reliable scene evidence."""

    count: int
    capability_ids: tuple[str, ...] | list[str] = field(default_factory=tuple)
    names: tuple[str, ...] | list[str] = field(default_factory=tuple)
    truncated: bool = False

    def __post_init__(self) -> None:
        if self.count < 0:
            raise ValueError("unresolved count must not be negative")
        object.__setattr__(
            self, "capability_ids", _stable_public_strings(self.capability_ids)
        )
        object.__setattr__(
            self, "names", _stable_public_strings(self.names, "names")
        )

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "count": self.count,
            "capability_ids": list(self.capability_ids),
            "names": list(self.names),
            "truncated": self.truncated,
        }


@dataclass(frozen=True)
class RouteResult:
    """Typed route response suitable for deterministic JSON output."""

    query: str
    matches: tuple[RouteMatch, ...] | list[RouteMatch] = field(default_factory=tuple)
    unresolved: UnresolvedSummary = field(default_factory=lambda: UnresolvedSummary(0))

    def __post_init__(self) -> None:
        matches = _require_collection(self.matches, "matches")
        if any(not isinstance(item, RouteMatch) for item in matches):
            raise TypeError("matches must contain RouteMatch values")
        if not isinstance(self.unresolved, UnresolvedSummary):
            raise TypeError("unresolved must be an UnresolvedSummary")
        object.__setattr__(self, "query", sanitize_text(self.query, max_length=1_024))
        object.__setattr__(self, "matches", matches)

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "matches": [item.to_public_dict() for item in self.matches],
            "unresolved": self.unresolved.to_public_dict(),
        }


def _require_collection(values: Iterable[Any], field_name: str) -> tuple[Any, ...]:
    if isinstance(values, (str, bytes, bytearray)) or isinstance(values, Mapping):
        raise TypeError(f"{field_name} must be a collection")
    try:
        return tuple(values)
    except TypeError as error:
        raise TypeError(f"{field_name} must be a collection") from error


def _scene_from_mapping(raw: Any) -> SceneDefinition:
    if not isinstance(raw, Mapping):
        raise TypeError("taxonomy scenes must be mappings")
    expected = {
        "id",
        "label_zh",
        "label_en",
        "keywords",
        "phrases",
        "kind_boosts",
    }
    if set(raw) != expected:
        raise ValueError("taxonomy scene fields do not match the public schema")
    return SceneDefinition(
        id=raw["id"],
        label_zh=raw["label_zh"],
        label_en=raw["label_en"],
        keywords=raw["keywords"],
        phrases=raw["phrases"],
        kind_boosts=raw["kind_boosts"],
    )


@lru_cache(maxsize=32)
def _load_taxonomy_cached(path_text: str) -> tuple[SceneDefinition, ...]:
    path = Path(path_text)
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, Mapping) or raw.get("schema_version") != 1:
        raise ValueError("Unsupported scene taxonomy schema")
    unclassified = raw.get("unclassified")
    if not isinstance(unclassified, Mapping) or unclassified.get("id") != "unclassified":
        raise ValueError("Taxonomy must define the unclassified boundary")
    raw_scenes = raw.get("scenes")
    if not isinstance(raw_scenes, list):
        raise TypeError("taxonomy scenes must be a list")
    scenes = tuple(_scene_from_mapping(item) for item in raw_scenes)
    if len({scene.id for scene in scenes}) != len(scenes):
        raise ValueError("taxonomy scene ids must be unique")
    return scenes


def load_taxonomy(path: str | Path | None = None) -> tuple[SceneDefinition, ...]:
    """Load and validate the generic packaged taxonomy."""

    selected = DEFAULT_TAXONOMY_PATH if path is None else Path(path)
    return _load_taxonomy_cached(str(selected.resolve()))


def _resolve_taxonomy(
    taxonomy: Sequence[SceneDefinition] | str | Path | None,
    taxonomy_path: str | Path | None,
) -> tuple[SceneDefinition, ...]:
    if taxonomy is not None and taxonomy_path is not None:
        raise ValueError("Pass taxonomy or taxonomy_path, not both")
    if isinstance(taxonomy, (str, Path)):
        return load_taxonomy(taxonomy)
    if taxonomy is None:
        return load_taxonomy(taxonomy_path)
    if isinstance(taxonomy, (bytes, bytearray)) or isinstance(taxonomy, Mapping):
        raise TypeError("taxonomy must be a collection of SceneDefinition values")
    scenes = tuple(taxonomy)
    if any(not isinstance(scene, SceneDefinition) for scene in scenes):
        raise TypeError("taxonomy must contain SceneDefinition values")
    if len({scene.id for scene in scenes}) != len(scenes):
        raise ValueError("taxonomy scene ids must be unique")
    return scenes


@lru_cache(maxsize=65_536)
def _tokens(value: str) -> frozenset[str]:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    result: set[str] = set()
    for segment in _SEGMENT_RE.findall(normalized):
        if _ASCII_WORD_RE.fullmatch(segment):
            if len(segment) <= 1 or segment in _LOW_INFORMATION_TOKENS:
                continue
            result.add(segment)
            if (
                len(segment) > 3
                and segment.endswith("s")
                and not segment.endswith(("is", "ss", "us"))
            ):
                result.add(segment[:-1])
            continue
        if len(segment) <= 1:
            continue
        result.add(segment)
        result.update(segment[index : index + 2] for index in range(len(segment) - 1))
    return frozenset(result)


def _public_record_fingerprint(capability: Capability) -> str:
    """Return a collision-free canonical key for one complete public record."""

    return json.dumps(
        capability.to_public_dict(),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _term_matches(term: str, text_tokens: frozenset[str]) -> bool:
    term_tokens = _tokens(term)
    return bool(term_tokens) and term_tokens.issubset(text_tokens)


def _phrase_matches(phrase: str, value: str, text_tokens: frozenset[str]) -> bool:
    normalized_phrase = unicodedata.normalize("NFKC", phrase).casefold()
    normalized_value = unicodedata.normalize("NFKC", value).casefold()
    if any("\u3400" <= character <= "\ufaff" for character in normalized_phrase):
        return normalized_phrase in normalized_value
    phrase_tokens = _tokens(normalized_phrase)
    if len(phrase_tokens) <= 1:
        return bool(phrase_tokens) and phrase_tokens.issubset(text_tokens)
    words = re.findall(r"[a-z0-9]+", normalized_phrase)
    if not words:
        return False
    pattern = r"(?<![a-z0-9])" + r"[^a-z0-9]+".join(
        re.escape(word) for word in words
    ) + r"(?![a-z0-9])"
    return re.search(pattern, normalized_value) is not None


def _cjk_query_phrase_matches(term: str, value: str) -> bool:
    """Match multi-character CJK scene terms without enabling single-char noise."""

    normalized_term = unicodedata.normalize("NFKC", term).casefold()
    if len(normalized_term) < 2:
        return False
    if not any("\u3400" <= character <= "\ufaff" for character in normalized_term):
        return False
    normalized_value = unicodedata.normalize("NFKC", value).casefold()
    return normalized_term in normalized_value


def _contains_cjk(value: str) -> bool:
    normalized = unicodedata.normalize("NFKC", value)
    return any("\u3400" <= character <= "\ufaff" for character in normalized)


def _field_match(
    value: str,
    scene: SceneDefinition,
    *,
    field_name: str,
    weight: float,
) -> tuple[float, tuple[str, ...]]:
    if not value or weight <= 0.0:
        return 0.0, ()
    text_tokens = _tokens(value)
    matched: list[str] = []
    phrase_evidence: set[str] = set()
    for term in scene.keywords:
        if field_name == "query" and _contains_cjk(term):
            if _cjk_query_phrase_matches(term, value):
                matched.append(term)
                phrase_evidence.add(term)
            continue
        if _term_matches(term, text_tokens):
            matched.append(term)
    for phrase in scene.phrases:
        if field_name == "query" and _contains_cjk(phrase):
            phrase_matched = _cjk_query_phrase_matches(phrase, value)
        else:
            phrase_matched = _phrase_matches(phrase, value, text_tokens)
        if phrase_matched:
            matched.append(phrase)
            if field_name == "query":
                phrase_evidence.add(phrase)
    distinct = tuple(sorted(set(matched)))
    if not distinct:
        return 0.0, ()
    strength = min(2.5, 1.0 + 0.35 * (len(distinct) - 1))
    evidence = tuple(
        (
            f"{field_name}:phrase:{term}"
            if term in phrase_evidence
            else f"{field_name}:{term}"
        )
        for term in distinct[:8]
    )
    return weight * strength, evidence


def _field_weights(capability: Capability) -> tuple[tuple[str, tuple[str, ...], float], ...]:
    if capability.kind == "skill":
        weights = {"tag": 6.0, "name": 5.0, "alias": 4.5, "description": 4.0}
    elif capability.kind == "plugin":
        weights = {"tag": 4.5, "name": 2.5, "alias": 2.25, "description": 3.5}
    elif capability.kind == "mcp":
        weights = {"tag": 1.0, "name": 2.0, "alias": 1.75, "description": 1.5}
    else:
        weights = {"tag": 0.25, "name": 1.5, "alias": 1.25, "description": 0.0}
    description = capability.description
    if description.casefold() in _GENERIC_DESCRIPTIONS:
        description = ""
    return (
        ("tag", tuple(capability.tags), weights["tag"]),
        ("name", (capability.name,), weights["name"]),
        ("alias", tuple(capability.aliases), weights["alias"]),
        ("description", (description,) if description else (), weights["description"]),
    )


def _score_capability_scene(
    capability: Capability, scene: SceneDefinition
) -> tuple[float, tuple[str, ...]]:
    score = 0.0
    evidence: list[str] = []
    for field_name, values, weight in _field_weights(capability):
        for value in values:
            field_score, field_evidence = _field_match(
                value,
                scene,
                field_name=field_name,
                weight=weight,
            )
            score += field_score
            evidence.extend(field_evidence)
    if score > 0.0:
        score += scene.kind_boosts.get(capability.kind, 0.0)
    return score, tuple(sorted(set(evidence)))


def _override_for(
    capability: Capability,
    overrides: Mapping[str, Iterable[str] | str] | None,
) -> Iterable[str] | str | None:
    if overrides is None:
        return None
    fingerprint = _public_record_fingerprint(capability)
    if fingerprint in overrides:
        return overrides[fingerprint]
    if capability.id in overrides:
        return overrides[capability.id]
    if capability.name in overrides:
        return overrides[capability.name]
    folded_name = capability.name.casefold()
    for key, value in overrides.items():
        if isinstance(key, str) and key.casefold() == folded_name:
            return value
    return None


def classify_capabilities(
    capabilities: Iterable[Capability],
    taxonomy: Sequence[SceneDefinition] | str | Path | None = None,
    *,
    taxonomy_path: str | Path | None = None,
    overrides: Mapping[str, Iterable[str] | str] | None = None,
    min_confidence: float = DEFAULT_MIN_CONFIDENCE,
) -> tuple[Capability, ...]:
    """Classify immutable capabilities solely from taxonomy and local evidence."""

    if not 0.0 <= min_confidence <= 1.0:
        raise ValueError("min_confidence must be between 0.0 and 1.0")
    if isinstance(capabilities, (str, bytes, bytearray)) or isinstance(
        capabilities, Mapping
    ):
        raise TypeError("capabilities must be a collection of Capability values")
    if overrides is not None and not isinstance(overrides, Mapping):
        raise TypeError("overrides must be a mapping")
    scenes = _resolve_taxonomy(taxonomy, taxonomy_path)
    scene_ids = {scene.id for scene in scenes}
    result: list[Capability] = []
    for capability in capabilities:
        if not isinstance(capability, Capability):
            raise TypeError("capabilities must contain Capability values")
        override = _override_for(capability, overrides)
        if override is not None:
            selected = (
                (override,)
                if isinstance(override, str)
                else _require_string_collection(override, "override scenes")
            )
            normalized = tuple(
                sorted(
                    {
                        sanitize_text(value, max_length=128).casefold()
                        for value in selected
                        if sanitize_text(value, max_length=128)
                    }
                )
            )
            unknown = set(normalized) - scene_ids
            if unknown:
                raise ValueError(f"Unknown override scene ids: {sorted(unknown)!r}")
            result.append(
                replace(
                    capability,
                    scenes=normalized,
                    classification_confidence=1.0 if normalized else 0.0,
                )
            )
            continue

        scored = []
        for scene in scenes:
            raw_score, _ = _score_capability_scene(capability, scene)
            if raw_score > 0.0:
                confidence = raw_score / (raw_score + 2.5)
                scored.append((scene.id, raw_score, confidence))
        if not scored:
            result.append(
                replace(capability, scenes=(), classification_confidence=0.0)
            )
            continue
        best_raw = max(item[1] for item in scored)
        selected_scenes = tuple(
            scene_id
            for scene_id, raw_score, confidence in sorted(scored)
            if confidence >= min_confidence and raw_score >= best_raw * 0.62
        )
        if not selected_scenes:
            result.append(
                replace(capability, scenes=(), classification_confidence=0.0)
            )
            continue
        best_confidence = max(
            confidence
            for scene_id, _, confidence in scored
            if scene_id in selected_scenes
        )
        result.append(
            replace(
                capability,
                scenes=selected_scenes,
                classification_confidence=round(best_confidence, 6),
            )
        )
    return tuple(sorted(result, key=_public_record_fingerprint))


def _score_query_scene(
    query: str, scene: SceneDefinition
) -> tuple[float, tuple[str, ...]]:
    return _field_match(
        query,
        scene,
        field_name="query",
        weight=1.0,
    )


def _direct_query_evidence(
    query_tokens: frozenset[str], capability: Capability
) -> tuple[float, tuple[str, ...]]:
    if capability.kind == "skill":
        weights = {"tag": 4.0, "name": 3.5, "alias": 3.0, "description": 2.5}
    elif capability.kind == "plugin":
        weights = {"tag": 3.25, "name": 2.75, "alias": 2.5, "description": 2.25}
    elif capability.kind == "mcp":
        weights = {"tag": 0.75, "name": 2.5, "alias": 2.25, "description": 1.5}
    else:
        weights = {"tag": 0.0, "name": 2.25, "alias": 2.0, "description": 0.0}
    score = 0.0
    evidence: list[str] = []
    description = capability.description
    if description.casefold() in _GENERIC_DESCRIPTIONS:
        description = ""
    fields = (
        ("tag", capability.tags),
        ("name", (capability.name,)),
        ("alias", capability.aliases),
        ("description", (description,) if description else ()),
    )
    for field_name, values in fields:
        weight = weights[field_name]
        if weight <= 0.0:
            continue
        for value in values:
            overlap = sorted(query_tokens.intersection(_tokens(value)))
            if not overlap:
                continue
            score += weight * min(2.0, 1.0 + 0.2 * (len(overlap) - 1))
            evidence.extend(f"query:{field_name}:{token}" for token in overlap[:6])
    return score, tuple(sorted(set(evidence)))


def _state_warning(capability: Capability) -> str:
    states = capability.states
    if all(
        value == "success"
        for value in (
            states.discovered,
            states.probed,
            states.authenticated,
            states.verified,
        )
    ):
        return "All reported states are success; verify task-specific suitability before use."
    return (
        f"discovered={states.discovered}; probed={states.probed}; "
        f"authenticated={states.authenticated}; verified={states.verified}. "
        "Discovery alone is not runtime verification."
    )


def route_query(
    query: str | Iterable[Capability],
    capabilities: Iterable[Capability] | str,
    taxonomy: Sequence[SceneDefinition] | str | Path | None = None,
    *,
    taxonomy_path: str | Path | None = None,
    overrides: Mapping[str, Iterable[str] | str] | None = None,
    limit: int = DEFAULT_ROUTE_LIMIT,
) -> RouteResult:
    """Rank installed candidates for a query without inventing capabilities."""

    if not isinstance(query, str) and isinstance(capabilities, str):
        query, capabilities = capabilities, query
    if not isinstance(query, str) or isinstance(capabilities, str):
        raise TypeError("route_query requires a string query and capabilities")
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 0:
        raise ValueError("limit must be a non-negative integer")
    if isinstance(capabilities, (str, bytes, bytearray)) or isinstance(
        capabilities, Mapping
    ):
        raise TypeError("capabilities must be a collection of Capability values")
    if overrides is not None and not isinstance(overrides, Mapping):
        raise TypeError("overrides must be a mapping")
    safe_query = sanitize_text(query, max_length=1_024)
    scenes = _resolve_taxonomy(taxonomy, taxonomy_path)
    original = tuple(capabilities)
    if any(not isinstance(item, Capability) for item in original):
        raise TypeError("capabilities must contain Capability values")
    classified_records: list[Capability] = []
    for item in original:
        if overrides is None and item.scenes:
            classified_records.append(item)
        else:
            classified_records.extend(
                classify_capabilities((item,), scenes, overrides=overrides)
            )
    classified = tuple(
        sorted(classified_records, key=_public_record_fingerprint)
    )

    query_tokens = _tokens(safe_query)
    query_scene_matches = {
        scene.id: _score_query_scene(safe_query, scene) for scene in scenes
    }
    query_scene_matches = {
        scene_id: match
        for scene_id, match in query_scene_matches.items()
        if match[0] > 0.0
    }
    scene_by_id = {scene.id: scene for scene in scenes}
    ranked: list[tuple[RouteMatch, str]] = []
    for capability in classified:
        direct_score, direct_evidence = _direct_query_evidence(
            query_tokens, capability
        )
        relevant_scenes = tuple(
            sorted(set(capability.scenes).intersection(query_scene_matches))
        )
        if not relevant_scenes and direct_score < 2.0:
            continue
        score = direct_score
        evidence = list(direct_evidence)
        for scene_id in relevant_scenes:
            scene_score, query_evidence = query_scene_matches[scene_id]
            affinity = min(1.5, 0.75 + scene_score / 2.0)
            score += 6.0 * capability.classification_confidence * affinity
            evidence.append(f"scene:{scene_id}")
            evidence.extend(query_evidence)
            _, capability_evidence = _score_capability_scene(
                capability, scene_by_id[scene_id]
            )
            evidence.extend(f"capability:{item}" for item in capability_evidence[:6])
        if score <= 0.0:
            continue
        kind_bonus = {"skill": 0.6, "plugin": 0.35, "mcp": 0.2, "cli": 0.0}
        score += capability.classification_confidence * 1.5
        score += kind_bonus.get(capability.kind, 0.0)
        match = RouteMatch(
            id=capability.id,
            name=capability.name,
            kind=capability.kind,
            score=score,
            evidence=evidence,
            scenes=capability.scenes,
            resolver_id=capability.resolver_id,
            state_warning=_state_warning(capability),
        )
        ranked.append(
            (match, _public_record_fingerprint(capability))
        )
    ranked.sort(
        key=lambda pair: (
            -pair[0].score,
            pair[0].evidence,
            pair[0].scenes,
            pair[1],
        )
    )
    unresolved_items = sorted(
        (item for item in classified if not item.scenes),
        key=lambda item: (
            item.name.casefold(),
            item.name,
            item.id,
            _public_record_fingerprint(item),
        ),
    )
    unresolved_sample = unresolved_items[:UNRESOLVED_SAMPLE_LIMIT]
    unresolved = UnresolvedSummary(
        count=len(unresolved_items),
        capability_ids=tuple(item.id for item in unresolved_sample),
        names=tuple(item.name for item in unresolved_sample),
        truncated=len(unresolved_items) > len(unresolved_sample),
    )
    return RouteResult(
        query=safe_query,
        matches=tuple(pair[0] for pair in ranked[:limit]),
        unresolved=unresolved,
    )


def route_result_json(result: RouteResult) -> str:
    """Serialize a typed route result without adding runtime metadata."""

    if not isinstance(result, RouteResult):
        raise TypeError("result must be a RouteResult")
    return json.dumps(
        sanitize(result.to_public_dict()),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ) + "\n"


__all__ = [
    "DEFAULT_MIN_CONFIDENCE",
    "DEFAULT_ROUTE_LIMIT",
    "DEFAULT_TAXONOMY_PATH",
    "RouteMatch",
    "RouteResult",
    "SceneDefinition",
    "UnresolvedSummary",
    "classify_capabilities",
    "load_taxonomy",
    "route_query",
    "route_result_json",
]

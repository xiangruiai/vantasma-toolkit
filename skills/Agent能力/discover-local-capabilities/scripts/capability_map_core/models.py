"""Public capability schema and private resolver records."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import InitVar, dataclass, field
from typing import Any

from .sanitize import REDACTED, REDACTED_PATH, sanitize, sanitize_text


CAPABILITY_KINDS = frozenset({"skill", "cli", "mcp", "plugin"})
CAPABILITY_SCOPES = frozenset({"user", "project", "system", "plugin", "extra"})


class _FrozenDict(dict[str, Any]):
    """A JSON-serializable mapping that rejects normal mutation APIs."""

    @staticmethod
    def _immutable(*args: object, **kwargs: object) -> None:
        raise TypeError("public diagnostic details are immutable")

    __setitem__ = _immutable
    __delitem__ = _immutable
    clear = _immutable
    pop = _immutable
    popitem = _immutable
    setdefault = _immutable
    update = _immutable
    __ior__ = _immutable


def _freeze_json(value: Any) -> Any:
    if isinstance(value, dict):
        return _FrozenDict((key, _freeze_json(item)) for key, item in value.items())
    if isinstance(value, list):
        return tuple(_freeze_json(item) for item in value)
    return value


def _require_instances(
    values: list[Any] | tuple[Any, ...], expected_type: type[Any], field_name: str
) -> tuple[Any, ...]:
    immutable_values = tuple(values)
    if any(not isinstance(value, expected_type) for value in immutable_values):
        raise TypeError(f"{field_name} must contain {expected_type.__name__} values")
    return immutable_values


def _stable_unique(values: list[str] | tuple[str, ...]) -> tuple[str, ...]:
    sanitized = {_normalize_public_text(value) for value in values}
    return tuple(sorted(sanitized, key=lambda value: (value.casefold(), value)))


def _normalize_public_text(value: str, *, max_length: int = 2_048) -> str:
    return unicodedata.normalize("NFC", sanitize_text(value, max_length=max_length))


def _normalize_identity_text(value: str, *, max_length: int) -> str:
    return unicodedata.normalize(
        "NFC", _normalize_public_text(value, max_length=max_length)
    )


def _normalize_logical_identity(value: str) -> str:
    normalized = _normalize_identity_text(value, max_length=512)
    if (
        REDACTED in normalized
        or REDACTED_PATH in normalized
        or normalized == "~"
        or normalized.startswith(("~/", "~\\"))
    ):
        raise ValueError("logical_identity must be non-sensitive and path-independent")
    return normalized


def _opaque_digest(namespace: str, evidence: dict[str, str]) -> str:
    payload = json.dumps(
        {"namespace": namespace, "evidence": evidence},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:24]


def _identity_evidence_digest(value: str) -> str:
    payload = json.dumps(
        {"namespace": "logical-identity-v1", "evidence": value},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True)
class CapabilityStates:
    """Evidence states; discovery establishes no runtime guarantees."""

    discovered: str = "success"
    probed: str = "unknown"
    authenticated: str = "unknown"
    verified: str = "unknown"

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "discovered", _normalize_public_text(self.discovered, max_length=32)
        )
        object.__setattr__(
            self, "probed", _normalize_public_text(self.probed, max_length=32)
        )
        object.__setattr__(
            self,
            "authenticated",
            _normalize_public_text(self.authenticated, max_length=32),
        )
        object.__setattr__(
            self, "verified", _normalize_public_text(self.verified, max_length=32)
        )

    def to_public_dict(self) -> dict[str, str]:
        return {
            "discovered": sanitize_text(self.discovered, max_length=32),
            "probed": sanitize_text(self.probed, max_length=32),
            "authenticated": sanitize_text(self.authenticated, max_length=32),
            "verified": sanitize_text(self.verified, max_length=32),
        }


@dataclass(frozen=True)
class SourceLocation:
    """A sanitized visible location; exact paths belong in ResolverRecord."""

    location: str
    scope: str = "extra"
    provider: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "location", _normalize_public_text(self.location, max_length=1_024)
        )
        object.__setattr__(
            self, "scope", _normalize_public_text(self.scope, max_length=64)
        )
        object.__setattr__(
            self, "provider", _normalize_public_text(self.provider, max_length=128)
        )

    def to_public_dict(self) -> dict[str, str]:
        return {
            "location": sanitize_text(self.location, max_length=1_024),
            "scope": sanitize_text(self.scope, max_length=64),
            "provider": sanitize_text(self.provider, max_length=128),
        }


@dataclass(frozen=True)
class Diagnostic:
    """A non-fatal discovery or classification diagnostic."""

    severity: str
    code: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "severity", _normalize_public_text(self.severity, max_length=32)
        )
        object.__setattr__(
            self, "code", _normalize_public_text(self.code, max_length=128)
        )
        object.__setattr__(
            self, "message", _normalize_public_text(self.message, max_length=1_024)
        )
        object.__setattr__(
            self,
            "details",
            _freeze_json(sanitize(self.details, max_length=1_024)),
        )

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "severity": sanitize_text(self.severity, max_length=32),
            "code": sanitize_text(self.code, max_length=128),
            "message": sanitize_text(self.message, max_length=1_024),
            "details": sanitize(self.details, max_length=1_024),
        }


@dataclass(frozen=True)
class Capability:
    """A capability whose public serializer cannot expose resolver paths."""

    kind: str
    name: str
    description: str = ""
    aliases: tuple[str, ...] | list[str] = field(default_factory=tuple)
    tags: tuple[str, ...] | list[str] = field(default_factory=tuple)
    scenes: tuple[str, ...] | list[str] = field(default_factory=tuple)
    source_locations: tuple[SourceLocation, ...] | list[SourceLocation] = field(
        default_factory=tuple
    )
    scope: str = "extra"
    provider: str = ""
    version: str | None = None
    states: CapabilityStates = field(default_factory=CapabilityStates)
    classification_confidence: float = 0.0
    diagnostics: tuple[Diagnostic, ...] | list[Diagnostic] = field(default_factory=tuple)
    _logical_identity_digest: str = field(default="", repr=False, compare=False)
    logical_identity: InitVar[str | None] = None
    id: str = field(init=False)
    resolver_id: str = field(init=False)

    def __post_init__(self, logical_identity: str | None) -> None:
        normalized_kind = self.kind.casefold().strip()
        normalized_scope = self.scope.casefold().strip()
        if normalized_kind not in CAPABILITY_KINDS:
            raise ValueError(f"Unsupported capability kind: {self.kind!r}")
        if normalized_scope not in CAPABILITY_SCOPES:
            raise ValueError(f"Unsupported capability scope: {self.scope!r}")
        if not self.name.strip():
            raise ValueError("Capability name must not be empty")
        if not 0.0 <= self.classification_confidence <= 1.0:
            raise ValueError("classification_confidence must be between 0.0 and 1.0")

        normalized_name = _normalize_public_text(self.name, max_length=512)
        if not normalized_name:
            raise ValueError("Capability name must not be empty after sanitization")
        normalized_provider = _normalize_public_text(self.provider, max_length=256)
        normalized_version = (
            None
            if self.version is None
            else _normalize_public_text(self.version, max_length=256)
        )
        if not isinstance(self.states, CapabilityStates):
            raise TypeError("states must be a CapabilityStates value")
        normalized_sources = _require_instances(
            self.source_locations, SourceLocation, "source_locations"
        )
        normalized_diagnostics = _require_instances(
            self.diagnostics, Diagnostic, "diagnostics"
        )
        object.__setattr__(self, "kind", normalized_kind)
        object.__setattr__(self, "scope", normalized_scope)
        object.__setattr__(self, "name", normalized_name)
        object.__setattr__(
            self,
            "description",
            _normalize_public_text(self.description, max_length=2_048),
        )
        object.__setattr__(self, "aliases", _stable_unique(self.aliases))
        object.__setattr__(self, "tags", _stable_unique(self.tags))
        object.__setattr__(self, "scenes", _stable_unique(self.scenes))
        object.__setattr__(self, "source_locations", normalized_sources)
        object.__setattr__(self, "provider", normalized_provider)
        object.__setattr__(self, "version", normalized_version)
        object.__setattr__(self, "diagnostics", normalized_diagnostics)
        identity = {
            "kind": normalized_kind,
            "name": _normalize_identity_text(normalized_name, max_length=512),
            "provider": _normalize_identity_text(normalized_provider, max_length=256),
            "scope": normalized_scope,
        }
        if logical_identity is None:
            logical_identity_digest = self._logical_identity_digest
            if logical_identity_digest and not re.fullmatch(
                r"[0-9a-f]{64}", logical_identity_digest
            ):
                raise ValueError("_logical_identity_digest must be a SHA-256 digest")
        else:
            normalized_logical_identity = _normalize_logical_identity(logical_identity)
            logical_identity_digest = (
                ""
                if not normalized_logical_identity
                else _identity_evidence_digest(normalized_logical_identity)
            )
        object.__setattr__(
            self, "_logical_identity_digest", logical_identity_digest
        )
        if logical_identity_digest:
            identity["logical_identity_digest"] = logical_identity_digest
        object.__setattr__(
            self, "id", f"cap_{_opaque_digest('capability-v2', identity)}"
        )
        object.__setattr__(
            self, "resolver_id", f"res_{_opaque_digest('resolver-v2', identity)}"
        )

    def to_public_dict(self) -> dict[str, Any]:
        sources = sorted(
            (source.to_public_dict() for source in self.source_locations),
            key=lambda item: json.dumps(item, ensure_ascii=False, sort_keys=True),
        )
        diagnostics = sorted(
            (diagnostic.to_public_dict() for diagnostic in self.diagnostics),
            key=lambda item: json.dumps(item, ensure_ascii=False, sort_keys=True),
        )
        return {
            "id": self.id,
            "kind": self.kind,
            "name": sanitize_text(self.name, max_length=512),
            "description": sanitize_text(self.description, max_length=2_048),
            "aliases": list(_stable_unique(self.aliases)),
            "tags": list(_stable_unique(self.tags)),
            "scenes": list(_stable_unique(self.scenes)),
            "source_locations": sources,
            "resolver_id": self.resolver_id,
            "scope": self.scope,
            "provider": sanitize_text(self.provider, max_length=256),
            "version": None if self.version is None else sanitize_text(self.version, max_length=256),
            "states": self.states.to_public_dict(),
            "classification_confidence": self.classification_confidence,
            "diagnostics": diagnostics,
        }


@dataclass(frozen=True)
class ResolverRecord:
    """Private exact locations keyed by a public opaque resolver ID."""

    resolver_id: str
    exact_locations: tuple[str, ...] | list[str] = field(repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "exact_locations", tuple(self.exact_locations))

    def to_private_dict(self) -> dict[str, Any]:
        return {
            "resolver_id": self.resolver_id,
            "exact_locations": sorted(set(self.exact_locations)),
        }


@dataclass(frozen=True)
class InventoryMetadata:
    """Public metadata for a complete capability inventory."""

    generated_at: str
    capability_count: int = 0
    diagnostics: tuple[Diagnostic, ...] | list[Diagnostic] = field(default_factory=tuple)
    schema_version: int = 2

    def __post_init__(self) -> None:
        normalized_diagnostics = _require_instances(
            self.diagnostics, Diagnostic, "diagnostics"
        )
        object.__setattr__(
            self,
            "generated_at",
            _normalize_public_text(self.generated_at, max_length=128),
        )
        object.__setattr__(self, "diagnostics", normalized_diagnostics)

    def to_public_dict(self) -> dict[str, Any]:
        diagnostics = sorted(
            (diagnostic.to_public_dict() for diagnostic in self.diagnostics),
            key=lambda item: json.dumps(item, ensure_ascii=False, sort_keys=True),
        )
        return {
            "schema_version": self.schema_version,
            "generated_at": sanitize_text(self.generated_at, max_length=128),
            "capability_count": self.capability_count,
            "diagnostics": diagnostics,
        }

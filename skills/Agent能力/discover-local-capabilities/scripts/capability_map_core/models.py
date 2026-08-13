"""Public capability schema and private resolver records."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

from .sanitize import sanitize, sanitize_text


CAPABILITY_KINDS = frozenset({"skill", "cli", "mcp", "plugin"})
CAPABILITY_SCOPES = frozenset({"user", "project", "system", "plugin", "extra"})


def _stable_unique(values: list[str]) -> list[str]:
    sanitized = {sanitize_text(value) for value in values}
    return sorted(sanitized, key=lambda value: (value.casefold(), value))


def _opaque_digest(namespace: str, evidence: dict[str, str]) -> str:
    payload = json.dumps(
        {"namespace": namespace, "evidence": evidence},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:24]


@dataclass
class CapabilityStates:
    """Evidence states; discovery establishes no runtime guarantees."""

    discovered: str = "success"
    probed: str = "unknown"
    authenticated: str = "unknown"
    verified: str = "unknown"

    def to_public_dict(self) -> dict[str, str]:
        return {
            "discovered": sanitize_text(self.discovered, max_length=32),
            "probed": sanitize_text(self.probed, max_length=32),
            "authenticated": sanitize_text(self.authenticated, max_length=32),
            "verified": sanitize_text(self.verified, max_length=32),
        }


@dataclass
class SourceLocation:
    """A sanitized visible location; exact paths belong in ResolverRecord."""

    location: str
    scope: str = "extra"
    provider: str = ""

    def to_public_dict(self) -> dict[str, str]:
        return {
            "location": sanitize_text(self.location, max_length=1_024),
            "scope": sanitize_text(self.scope, max_length=64),
            "provider": sanitize_text(self.provider, max_length=128),
        }


@dataclass
class Diagnostic:
    """A non-fatal discovery or classification diagnostic."""

    severity: str
    code: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "severity": sanitize_text(self.severity, max_length=32),
            "code": sanitize_text(self.code, max_length=128),
            "message": sanitize_text(self.message, max_length=1_024),
            "details": sanitize(self.details, max_length=1_024),
        }


@dataclass
class Capability:
    """A capability whose public serializer cannot expose resolver paths."""

    kind: str
    name: str
    description: str = ""
    aliases: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    scenes: list[str] = field(default_factory=list)
    source_locations: list[SourceLocation] = field(default_factory=list)
    scope: str = "extra"
    provider: str = ""
    version: str | None = None
    states: CapabilityStates = field(default_factory=CapabilityStates)
    classification_confidence: float = 0.0
    diagnostics: list[Diagnostic] = field(default_factory=list)
    id: str = field(init=False)
    resolver_id: str = field(init=False)

    def __post_init__(self) -> None:
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

        self.kind = normalized_kind
        self.scope = normalized_scope
        identity = {
            "kind": normalized_kind,
            "name": sanitize_text(self.name, max_length=512).casefold(),
            "provider": sanitize_text(self.provider, max_length=256).casefold(),
            "scope": normalized_scope,
        }
        self.id = f"cap_{_opaque_digest('capability-v2', identity)}"
        self.resolver_id = f"res_{_opaque_digest('resolver-v2', identity)}"

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
            "aliases": _stable_unique(self.aliases),
            "tags": _stable_unique(self.tags),
            "scenes": _stable_unique(self.scenes),
            "source_locations": sources,
            "resolver_id": self.resolver_id,
            "scope": self.scope,
            "provider": sanitize_text(self.provider, max_length=256),
            "version": None if self.version is None else sanitize_text(self.version, max_length=256),
            "states": self.states.to_public_dict(),
            "classification_confidence": self.classification_confidence,
            "diagnostics": diagnostics,
        }


@dataclass
class ResolverRecord:
    """Private exact locations keyed by a public opaque resolver ID."""

    resolver_id: str
    exact_locations: list[str]

    def to_private_dict(self) -> dict[str, Any]:
        return {
            "resolver_id": self.resolver_id,
            "exact_locations": sorted(set(self.exact_locations)),
        }


@dataclass
class InventoryMetadata:
    """Public metadata for a complete capability inventory."""

    generated_at: str
    capability_count: int = 0
    diagnostics: list[Diagnostic] = field(default_factory=list)
    schema_version: int = 2

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

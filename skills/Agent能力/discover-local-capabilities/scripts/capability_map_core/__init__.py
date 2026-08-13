"""Core primitives for the discover-local-capabilities scanner."""

from .models import (
    Capability,
    CapabilityStates,
    Diagnostic,
    InventoryMetadata,
    ResolverRecord,
    SourceLocation,
)
from .sanitize import sanitize, sanitize_text

__all__ = [
    "Capability",
    "CapabilityStates",
    "Diagnostic",
    "InventoryMetadata",
    "ResolverRecord",
    "SourceLocation",
    "sanitize",
    "sanitize_text",
]

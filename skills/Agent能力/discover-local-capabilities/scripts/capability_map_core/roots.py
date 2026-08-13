"""Cross-platform, injectable root providers for local Agent Skills."""

from __future__ import annotations

import os
import platform
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath

from .models import CAPABILITY_SCOPES


_SENSITIVE_IDENTITY_RE = re.compile(
    r"(?i)(?:token|secret|password|api[_-]?key)\s*[:=]"
)


@dataclass(frozen=True)
class RootSpec:
    """A physical search root plus non-sensitive logical source evidence."""

    path: Path
    scope: str
    provider: str
    logical_key: str
    public_prefix: str

    def __post_init__(self) -> None:
        path = Path(self.path)
        scope = self.scope.casefold().strip()
        provider = self.provider.strip()
        logical_key = self.logical_key.strip()
        public_prefix = self.public_prefix.strip().rstrip("/\\")
        if scope not in CAPABILITY_SCOPES:
            raise ValueError(f"Unsupported root scope: {self.scope!r}")
        if not provider:
            raise ValueError("Root provider must not be empty")
        if not logical_key:
            raise ValueError("Root logical_key must not be empty")
        if (
            path_like_identity(logical_key)
            or _SENSITIVE_IDENTITY_RE.search(logical_key)
        ):
            raise ValueError(
                "Root logical_key must be non-sensitive and path-independent"
            )
        if not public_prefix:
            raise ValueError("Root public_prefix must not be empty")
        object.__setattr__(self, "path", path)
        object.__setattr__(self, "scope", scope)
        object.__setattr__(self, "provider", provider)
        object.__setattr__(self, "logical_key", logical_key)
        object.__setattr__(self, "public_prefix", public_prefix)


def path_like_identity(value: str) -> bool:
    """Return whether an identity is an absolute Unix or Windows path."""

    return Path(value).is_absolute() or PureWindowsPath(value).is_absolute()


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


def _expand_injected_home(value: str | os.PathLike[str], home: Path) -> Path:
    raw = os.fspath(value)
    if raw == "~":
        return home
    if raw.startswith(("~/", "~\\")):
        return home / raw[2:]
    return Path(raw)


def skill_root_specs(
    *,
    home: Path,
    project: Path | None = None,
    extra_roots: Iterable[Path] = (),
    environ: Mapping[str, str] | None = None,
    platform_name: str | None = None,
) -> tuple[RootSpec, ...]:
    """Return known Skill roots using only explicitly injectable host inputs.

    ``platform_name`` controls Windows environment-key case handling. Codex and
    Claude keep the same default home-relative directories across supported OSes.
    """

    injected_home = Path(home)
    environment = os.environ if environ is None else environ
    operating_system = platform.system() if platform_name is None else platform_name
    windows = operating_system.casefold().startswith("win")
    codex_override = _environment_value(
        environment, "CODEX_HOME", case_insensitive=windows
    )
    claude_override = _environment_value(
        environment, "CLAUDE_CONFIG_DIR", case_insensitive=windows
    )
    codex_home = (
        _expand_injected_home(codex_override, injected_home)
        if codex_override
        else injected_home / ".codex"
    )
    claude_home = (
        _expand_injected_home(claude_override, injected_home)
        if claude_override
        else injected_home / ".claude"
    )
    codex_public_home = "<codex-home>" if codex_override else "~/.codex"
    claude_public_home = "<claude-home>" if claude_override else "~/.claude"
    roots: list[RootSpec] = [
        RootSpec(
            codex_home / "skills",
            "user",
            "codex",
            "user:codex",
            f"{codex_public_home}/skills",
        ),
        RootSpec(
            injected_home / ".agents" / "skills",
            "user",
            "shared",
            "user:shared",
            "~/.agents/skills",
        ),
        RootSpec(
            claude_home / "skills",
            "user",
            "claude",
            "user:claude",
            f"{claude_public_home}/skills",
        ),
        RootSpec(
            codex_home / "plugins",
            "plugin",
            "codex-plugin",
            "plugin:codex",
            f"{codex_public_home}/plugins",
        ),
        RootSpec(
            claude_home / "plugins",
            "plugin",
            "claude-plugin",
            "plugin:claude",
            f"{claude_public_home}/plugins",
        ),
    ]
    if project is not None:
        project_root = Path(project)
        roots.extend(
            (
                RootSpec(
                    project_root / ".codex" / "skills",
                    "project",
                    "codex",
                    "project:codex",
                    "<project>/.codex/skills",
                ),
                RootSpec(
                    project_root / ".agents" / "skills",
                    "project",
                    "shared",
                    "project:shared",
                    "<project>/.agents/skills",
                ),
                RootSpec(
                    project_root / ".claude" / "skills",
                    "project",
                    "claude",
                    "project:claude",
                    "<project>/.claude/skills",
                ),
            )
        )
    for index, extra_root in enumerate(extra_roots, start=1):
        roots.append(
            RootSpec(
                _expand_injected_home(extra_root, injected_home),
                "extra",
                "extra",
                f"extra:{index}",
                f"<extra:{index}>",
            )
        )
    return tuple(roots)


__all__ = ["RootSpec", "skill_root_specs"]

"""Test helpers for isolated local-capability discovery fixtures."""

from __future__ import annotations

from pathlib import Path


def write_skill(
    directory: Path,
    *,
    frontmatter: str | None = None,
    body: str = "# Body\n",
    encoding: str = "utf-8",
    bom: bool = False,
) -> Path:
    """Create a SKILL.md fixture without touching any real user Skill root."""

    directory.mkdir(parents=True, exist_ok=True)
    metadata = frontmatter
    if metadata is None:
        metadata = f"name: {directory.name}\ndescription: Fixture skill"
    text = f"---\n{metadata}\n---\n{body}"
    payload = text.encode(encoding)
    if bom:
        payload = b"\xef\xbb\xbf" + payload
    skill_md = directory / "SKILL.md"
    skill_md.write_bytes(payload)
    return skill_md


def write_raw_skill(directory: Path, payload: bytes) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    skill_md = directory / "SKILL.md"
    skill_md.write_bytes(payload)
    return skill_md

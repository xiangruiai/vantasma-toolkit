"""Tests for root resolution and recursive, bounded Skill discovery."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from capability_map_core.roots import RootSpec, skill_root_specs  # noqa: E402
from capability_map_core.skills import (  # noqa: E402
    MAX_FRONTMATTER_BYTES,
    SkillDiscoveryResult,
    discover_skills,
)

from support import write_raw_skill, write_skill  # noqa: E402


class RootProviderTests(unittest.TestCase):
    def test_roots_are_home_project_plugin_and_extra_aware_with_injected_inputs(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            home = base / "home"
            project = base / "project"
            codex_home = base / "portable-codex"
            claude_home = base / "portable-claude"
            extra = base / "额外 能力"
            environment = {
                "CODEX_HOME": str(codex_home),
                "CLAUDE_CONFIG_DIR": str(claude_home),
            }

            roots = skill_root_specs(
                home=home,
                project=project,
                extra_roots=[extra],
                environ=environment,
                platform_name="Windows",
            )

            by_key = {root.logical_key: root for root in roots}
            self.assertEqual(by_key["user:codex"].path, codex_home / "skills")
            self.assertEqual(by_key["user:claude"].path, claude_home / "skills")
            self.assertEqual(by_key["user:shared"].path, home / ".agents" / "skills")
            self.assertEqual(
                by_key["project:codex"].path, project / ".codex" / "skills"
            )
            self.assertEqual(
                by_key["project:claude"].path, project / ".claude" / "skills"
            )
            self.assertEqual(
                by_key["project:shared"].path, project / ".agents" / "skills"
            )
            self.assertEqual(by_key["plugin:codex"].path, codex_home / "plugins")
            self.assertEqual(by_key["plugin:claude"].path, claude_home / "plugins")
            self.assertEqual(by_key["extra:1"].path, extra)
            self.assertEqual(by_key["extra:1"].scope, "extra")
            self.assertTrue(all(not root.public_prefix.startswith(str(base)) for root in roots))

    def test_root_spec_rejects_absolute_or_sensitive_logical_keys(self) -> None:
        with self.assertRaises(ValueError):
            RootSpec(Path("/tmp/example"), "extra", "custom", "/tmp/example", "extra")
        with self.assertRaises(ValueError):
            RootSpec(Path("/tmp/example"), "extra", "custom", "token=secret", "extra")


class SkillDiscoveryTests(unittest.TestCase):
    def test_recurses_all_sources_and_parses_supported_frontmatter_subset(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            home = base / "home"
            project = base / "project"
            extra = base / "额外"
            write_skill(
                home / ".codex" / "skills" / ".system" / "工具箱",
                bom=True,
                frontmatter=(
                    'name: "系统工具"\n'
                    "description: |\n"
                    "  第一行\n"
                    "  第二行\n"
                    "tags: [automation, \"中文\"]\n"
                    "aliases:\n"
                    "  - 工具箱\n"
                    "  - 'Tool Box'"
                ),
            )
            write_skill(
                home
                / ".claude"
                / "skills"
                / "one"
                / "two"
                / "three"
                / "deep",
                frontmatter=(
                    "name: deep-skill\n"
                    "description: >\n"
                    "  folded\n"
                    "  description\n"
                    "tags:\n"
                    "  - nested"
                ),
            )
            write_skill(home / ".agents" / "skills" / "shared")
            write_skill(project / ".codex" / "skills" / "project-skill")
            write_skill(
                home
                / ".codex"
                / "plugins"
                / "cache"
                / "publisher"
                / "plugin"
                / "1.0"
                / "skills"
                / "embedded"
            )
            write_skill(extra / "嵌套" / "能力")

            result = discover_skills(
                skill_root_specs(home=home, project=project, extra_roots=[extra])
            )

            self.assertIsInstance(result, SkillDiscoveryResult)
            self.assertEqual(len(result.capabilities), 6)
            by_name = {capability.name: capability for capability in result.capabilities}
            system = by_name["系统工具"]
            self.assertEqual(system.description, "第一行 第二行")
            self.assertEqual(system.tags, ("automation", "中文"))
            self.assertEqual(system.aliases, ("Tool Box", "工具箱"))
            self.assertEqual(system.scope, "system")
            self.assertEqual(system.source_locations[0].scope, "system")
            self.assertEqual(by_name["deep-skill"].description, "folded description")
            self.assertEqual(by_name["embedded"].scope, "plugin")
            self.assertEqual(by_name["能力"].provider, "extra")
            self.assertEqual(len(result.resolvers), 6)

    def test_invalid_and_non_utf8_frontmatter_falls_back_without_stopping(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "skills"
            write_raw_skill(
                root / "invalid-directory-name",
                b"---\nname: [unterminated\ndescription: nope\n---\nbody",
            )
            write_raw_skill(
                root / "binary-directory-name",
                b"---\nname: bad\xffname\ndescription: usable\n---\nbody",
            )
            write_skill(
                root / "empty-sanitized-name",
                frontmatter='name: "\\u0000"\ndescription: control-only name',
            )
            write_raw_skill(
                root / "\x01",
                b"---\nname: [unterminated\n---\nbody",
            )
            write_skill(root / "healthy", frontmatter="name: healthy")

            result = discover_skills(
                [RootSpec(root, "extra", "fixtures", "extra:fixtures", "<extra>")]
            )

            self.assertEqual(
                {capability.name for capability in result.capabilities},
                {
                    "invalid-directory-name",
                    "bad�name",
                    "empty-sanitized-name",
                    "healthy",
                    "unnamed-skill",
                },
            )
            codes = {diagnostic.code for diagnostic in result.diagnostics}
            self.assertIn("invalid_frontmatter", codes)
            self.assertIn("non_utf8_frontmatter", codes)
            self.assertIn("metadata_name_invalid", codes)
            self.assertIn("metadata_fallback_invalid", codes)
            invalid = next(
                capability
                for capability in result.capabilities
                if capability.name == "invalid-directory-name"
            )
            self.assertIn(
                "invalid_frontmatter",
                {diagnostic.code for diagnostic in invalid.diagnostics},
            )

    def test_reads_only_a_bounded_skill_frontmatter_prefix_and_never_env(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "skills"
            skill = write_skill(
                root / "bounded",
                frontmatter="name: bounded\ndescription: short",
                body="x" * (MAX_FRONTMATTER_BYTES * 3),
            )
            env_file = root / ".env"
            env_file.parent.mkdir(parents=True, exist_ok=True)
            env_file.write_text("name: must-not-be-read", encoding="utf-8")
            env_directory = root / "nested" / ".env"
            write_skill(env_directory / "hidden-skill", frontmatter="name: forbidden")
            real_open = open
            reads: list[tuple[Path, int, int]] = []
            payload = skill.read_bytes()
            body_start = payload.index(b"\n---\n") + len(b"\n---\n")

            class RecordingReader:
                def __init__(self, handle: object, opened_path: Path) -> None:
                    self._handle = handle
                    self._path = opened_path

                def __enter__(self) -> "RecordingReader":
                    self._handle.__enter__()
                    return self

                def __exit__(self, *args: object) -> object:
                    return self._handle.__exit__(*args)

                def read(self, size: int = -1) -> bytes:
                    chunk = self._handle.read(size)
                    reads.append((self._path, size, self._handle.tell()))
                    return chunk

                def readline(self, size: int = -1) -> bytes:
                    line = self._handle.readline(size)
                    reads.append((self._path, size, self._handle.tell()))
                    return line

            def recording_open(path: object, mode: str = "r", *args: object, **kwargs: object) -> object:
                opened_path = Path(path)  # type: ignore[arg-type]
                if opened_path.name == ".env" or ".env" in opened_path.parts:
                    raise AssertionError("discovery attempted to read .env")
                handle = real_open(path, mode, *args, **kwargs)
                if "b" in mode:
                    return RecordingReader(handle, opened_path)
                return handle

            with mock.patch("capability_map_core.skills.open", recording_open):
                result = discover_skills(
                    [RootSpec(root, "extra", "fixtures", "extra:fixtures", "<extra>")]
                )

            self.assertEqual([capability.name for capability in result.capabilities], ["bounded"])
            self.assertTrue(reads)
            self.assertTrue(
                all(0 < size <= MAX_FRONTMATTER_BYTES + 1 for _, size, _ in reads)
            )
            self.assertEqual({path for path, _, _ in reads}, {skill})
            self.assertLessEqual(max(position for _, _, position in reads), body_start)

    @unittest.skipUnless(hasattr(os, "symlink"), "symlinks are required")
    def test_physical_dedupe_keeps_all_visible_sources_and_one_resolver(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            physical = write_skill(
                base / "physical" / "same",
                frontmatter="name: shared-physical\ndescription: one file",
            )
            user_root = base / "home" / ".codex" / "skills"
            project_root = base / "project" / ".agents" / "skills"
            extra_root = base / "extra"
            for directory in (user_root, project_root, extra_root):
                directory.mkdir(parents=True, exist_ok=True)
            (user_root / "first-visible").symlink_to(physical.parent, target_is_directory=True)
            (project_root / "second-visible").symlink_to(
                physical.parent, target_is_directory=True
            )
            (extra_root / "third-visible").symlink_to(
                physical.parent, target_is_directory=True
            )
            roots = [
                RootSpec(user_root, "user", "codex", "user:codex", "~/.codex/skills"),
                RootSpec(
                    project_root,
                    "project",
                    "shared",
                    "project:shared",
                    "<project>/.agents/skills",
                ),
                RootSpec(extra_root, "extra", "extra", "extra:1", "<extra:1>"),
                RootSpec(physical.parent.parent, "extra", "physical", "extra:2", "<extra:2>"),
            ]

            result = discover_skills(roots)

            self.assertEqual(len(result.capabilities), 1)
            self.assertEqual(len(result.resolvers), 1)
            capability = result.capabilities[0]
            sources = capability.source_locations
            self.assertEqual(len(sources), 4)
            self.assertEqual({source.scope for source in sources}, {"user", "project", "extra"})
            self.assertEqual(
                {source.provider for source in sources},
                {"codex", "shared", "extra", "physical"},
            )
            resolver = result.resolvers[0]
            self.assertEqual(resolver.resolver_id, capability.resolver_id)
            self.assertIn(str(physical.resolve()), resolver.exact_locations)
            public_json = json.dumps(capability.to_public_dict(), ensure_ascii=False)
            self.assertNotIn(str(base), public_json)

    def test_same_metadata_on_distinct_physical_skills_has_distinct_ids(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            first = base / "one"
            second = base / "two"
            write_skill(first / "same", frontmatter="name: duplicate\ndescription: same")
            write_skill(second / "same", frontmatter="name: duplicate\ndescription: same")

            result = discover_skills(
                [
                    RootSpec(first, "extra", "first", "extra:first", "<first>"),
                    RootSpec(second, "extra", "second", "extra:second", "<second>"),
                ]
            )

            self.assertEqual(len(result.capabilities), 2)
            self.assertEqual(len({item.id for item in result.capabilities}), 2)
            self.assertEqual(len({item.resolver_id for item in result.capabilities}), 2)

    @unittest.skipUnless(hasattr(os, "symlink"), "symlinks are required")
    def test_symlinks_follow_allowed_roots_but_report_loops_breakage_and_escape(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            first_root = base / "first"
            second_root = base / "second"
            outside = base / "outside"
            first_root.mkdir()
            second_root.mkdir()
            write_skill(second_root / "allowed-target", frontmatter="name: allowed")
            write_skill(outside / "escaped-target", frontmatter="name: escaped")
            (first_root / "allowed-link").symlink_to(
                second_root / "allowed-target", target_is_directory=True
            )
            (first_root / "escaped-link").symlink_to(
                outside / "escaped-target", target_is_directory=True
            )
            (first_root / "loop").symlink_to(first_root, target_is_directory=True)
            (first_root / "broken-directory").symlink_to(
                base / "missing-directory", target_is_directory=True
            )
            (first_root / "broken-file").mkdir()
            (first_root / "broken-file" / "SKILL.md").symlink_to(
                base / "missing-SKILL.md"
            )
            (first_root / "file-loop").mkdir()
            (first_root / "file-loop" / "SKILL.md").symlink_to("SKILL.md")

            result = discover_skills(
                [
                    RootSpec(first_root, "extra", "first", "extra:first", "<first>"),
                    RootSpec(second_root, "extra", "second", "extra:second", "<second>"),
                ]
            )

            self.assertEqual({item.name for item in result.capabilities}, {"allowed"})
            codes = [diagnostic.code for diagnostic in result.diagnostics]
            self.assertIn("symlink_outside_allowed_roots", codes)
            self.assertGreaterEqual(codes.count("symlink_loop"), 2)
            self.assertGreaterEqual(codes.count("broken_symlink"), 2)

    def test_permission_and_read_errors_are_diagnostic_and_other_roots_continue(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = base / "root"
            blocked = root / "blocked"
            unreadable = root / "unreadable"
            healthy = root / "healthy"
            write_skill(blocked / "nested", frontmatter="name: blocked")
            unreadable_file = write_skill(unreadable, frontmatter="name: unreadable")
            write_skill(healthy, frontmatter="name: healthy")
            real_scandir = os.scandir
            real_open = open

            def guarded_scandir(path: object) -> object:
                if Path(path) == blocked:
                    raise PermissionError("synthetic traversal denial")
                return real_scandir(path)

            def guarded_open(path: object, *args: object, **kwargs: object) -> object:
                if Path(path) == unreadable_file:
                    raise PermissionError("synthetic read denial")
                return real_open(path, *args, **kwargs)

            with mock.patch("capability_map_core.skills.os.scandir", guarded_scandir), mock.patch(
                "capability_map_core.skills.open", guarded_open
            ):
                result = discover_skills(
                    [RootSpec(root, "extra", "fixtures", "extra:fixtures", "<extra>")]
                )

            self.assertEqual(
                {capability.name for capability in result.capabilities},
                {"healthy", "unreadable"},
            )
            codes = {diagnostic.code for diagnostic in result.diagnostics}
            self.assertIn("directory_read_error", codes)
            self.assertIn("skill_read_error", codes)
            unreadable_capability = next(
                item for item in result.capabilities if item.name == "unreadable"
            )
            self.assertIn(
                "skill_read_error",
                {diagnostic.code for diagnostic in unreadable_capability.diagnostics},
            )


if __name__ == "__main__":
    unittest.main()

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
            self.assertEqual(system.scope, "extra")
            self.assertEqual(system.provider, "local-skill")
            self.assertEqual(system.source_locations[0].scope, "system")
            self.assertEqual(by_name["deep-skill"].description, "folded description")
            self.assertEqual(by_name["embedded"].source_locations[0].scope, "plugin")
            self.assertEqual(by_name["能力"].source_locations[0].provider, "extra")
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

    def test_yaml_comments_are_removed_only_outside_quoted_scalars(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "skills"
            write_skill(
                root / "plain",
                frontmatter=(
                    "name: alpha # unquoted comment\n"
                    "description: plain description # another comment"
                ),
            )
            write_skill(
                root / "quoted",
                frontmatter=(
                    'name: "alpha # literal" # trailing comment\n'
                    "description: 'quoted # literal' # trailing comment"
                ),
            )

            result = discover_skills(
                [RootSpec(root, "extra", "fixtures", "extra:fixtures", "<extra>")]
            )

            by_name = {capability.name: capability for capability in result.capabilities}
            self.assertEqual(set(by_name), {"alpha", "alpha # literal"})
            self.assertEqual(by_name["alpha"].description, "plain description")
            self.assertEqual(
                by_name["alpha # literal"].description, "quoted # literal"
            )

    def test_yaml_block_list_comments_preserve_quoted_literals(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "skills"
            write_skill(
                root / "list-comments",
                frontmatter=(
                    "name: list-comments\n"
                    "aliases:\n"
                    "  - first # unquoted comment\n"
                    '  - "first # literal" # trailing comment'
                ),
            )
            write_skill(
                root / "ambiguous-list",
                frontmatter="name: ignored\ntags:\n  - [nested] # unsupported",
            )

            result = discover_skills(
                [RootSpec(root, "extra", "fixtures", "extra:fixtures", "<extra>")]
            )

            by_name = {capability.name: capability for capability in result.capabilities}
            self.assertEqual(
                by_name["list-comments"].aliases,
                ("first", "first # literal"),
            )
            fallback = by_name["ambiguous-list"]
            self.assertIn(
                "invalid_frontmatter",
                {diagnostic.code for diagnostic in fallback.diagnostics},
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
            real_os_open = os.open
            real_os_read = os.read
            reads: list[tuple[Path, int, int]] = []
            payload = skill.read_bytes()
            body_start = payload.index(b"\n---\n") + len(b"\n---\n")
            opened_paths: dict[int, Path] = {}

            def recording_open(
                path: object, flags: int, *args: object, **kwargs: object
            ) -> int:
                opened_path = Path(path)  # type: ignore[arg-type]
                if ".env" in {part.casefold() for part in opened_path.parts}:
                    raise AssertionError("discovery attempted to read .env")
                fd = real_os_open(path, flags, *args, **kwargs)
                opened_paths[fd] = opened_path
                return fd

            def recording_read(fd: int, size: int) -> bytes:
                chunk = real_os_read(fd, size)
                reads.append((opened_paths[fd], size, os.lseek(fd, 0, os.SEEK_CUR)))
                return chunk

            with mock.patch(
                "capability_map_core.skills.os.open", recording_open
            ), mock.patch("capability_map_core.skills.os.read", recording_read):
                result = discover_skills(
                    [RootSpec(root, "extra", "fixtures", "extra:fixtures", "<extra>")]
                )

            self.assertEqual([capability.name for capability in result.capabilities], ["bounded"])
            self.assertTrue(reads)
            self.assertTrue(
                all(0 < size <= MAX_FRONTMATTER_BYTES + 1 for _, size, _ in reads)
            )
            self.assertEqual(
                {path.resolve() for path, _, _ in reads},
                {skill.resolve()},
            )
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

    @unittest.skipUnless(hasattr(os, "symlink"), "symlinks are required")
    def test_symlink_targets_with_env_segments_are_never_read_or_traversed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = base / "skills"
            allowed_targets = base / "allowed-targets"
            allowed_targets.mkdir()
            file_case = root / "file-case"
            file_case.mkdir(parents=True)
            payload_canary = b"forbidden-chain-payload"
            payload_file = allowed_targets / "payload.md"
            payload_file.write_bytes(
                b"---\nname: " + payload_canary + b"\n---\nprivate target bytes"
            )
            (file_case / ".env").symlink_to(payload_file)
            (file_case / "middle").symlink_to(".env")
            linked_skill = file_case / "skill"
            linked_skill.mkdir()
            (linked_skill / "SKILL.md").symlink_to("../middle")

            directory_case = root / "directory-case"
            directory_case.mkdir()
            payload_directory = allowed_targets / "payload-directory"
            write_skill(
                payload_directory / "nested" / "skill",
                frontmatter="name: forbidden-directory-target",
            )
            (directory_case / ".ENV").symlink_to(
                payload_directory, target_is_directory=True
            )
            (directory_case / "middle").symlink_to(".ENV", target_is_directory=True)
            (directory_case / "exposed").symlink_to(
                "middle", target_is_directory=True
            )
            write_skill(root / "healthy", frontmatter="name: healthy")
            real_os_read = os.read
            real_scandir = os.scandir
            real_readlink = os.readlink
            read_chunks: list[bytes] = []
            payload_scans: list[Path] = []
            readlink_steps: list[tuple[Path, str]] = []
            payload_directory_id = (
                payload_directory.stat().st_dev,
                payload_directory.stat().st_ino,
            )

            def recording_read(fd: int, size: int) -> bytes:
                chunk = real_os_read(fd, size)
                read_chunks.append(chunk)
                return chunk

            def recording_scandir(path: object) -> object:
                if Path(path).name == allowed_targets.name:
                    raise PermissionError("keep the allowed target root unscanned")
                target_stat = os.stat(path)
                if (target_stat.st_dev, target_stat.st_ino) == payload_directory_id:
                    payload_scans.append(Path(path))  # type: ignore[arg-type]
                return real_scandir(path)

            def recording_readlink(
                path: object, *args: object, **kwargs: object
            ) -> str:
                target = real_readlink(path, *args, **kwargs)
                readlink_steps.append((Path(path), os.fsdecode(target)))
                return target

            with mock.patch(
                "capability_map_core.skills.os.read", recording_read
            ), mock.patch(
                "capability_map_core.skills.os.scandir", recording_scandir
            ), mock.patch(
                "capability_map_core.skills.os.readlink", recording_readlink
            ):
                result = discover_skills(
                    [
                        RootSpec(
                            root,
                            "extra",
                            "fixtures",
                            "extra:fixtures",
                            "<extra>",
                        ),
                        RootSpec(
                            allowed_targets,
                            "extra",
                            "targets",
                            "extra:targets",
                            "<targets>",
                        ),
                    ]
                )

            self.assertEqual([item.name for item in result.capabilities], ["healthy"])
            self.assertNotIn(payload_canary, b"".join(read_chunks))
            self.assertEqual(payload_scans, [])
            self.assertTrue(readlink_steps)
            self.assertGreaterEqual(
                [item.code for item in result.diagnostics].count("env_path_blocked"),
                2,
            )

    @unittest.skipUnless(hasattr(os, "symlink"), "symlinks are required")
    def test_source_replaced_after_scan_is_rejected_before_reading(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = base / "skills"
            skill_file = write_skill(
                root / "raced", frontmatter="name: original-safe-skill"
            )
            secret_canary = b"toctou-secret-canary"
            secret_file = base / "outside-secret"
            secret_file.write_bytes(
                b"---\nname: " + secret_canary + b"\n---\nprivate bytes"
            )
            original_backup = base / "original-SKILL.md"
            real_os_open = os.open
            real_os_read = os.read
            raced = False
            read_chunks: list[bytes] = []

            def racing_open(
                path: object, flags: int, *args: object, **kwargs: object
            ) -> int:
                nonlocal raced
                opened_path = Path(path)  # type: ignore[arg-type]
                if opened_path.name == "SKILL.md" and not raced:
                    skill_file.rename(original_backup)
                    skill_file.symlink_to(secret_file)
                    raced = True
                return real_os_open(path, flags, *args, **kwargs)

            def recording_read(fd: int, size: int) -> bytes:
                chunk = real_os_read(fd, size)
                read_chunks.append(chunk)
                return chunk

            with mock.patch(
                "capability_map_core.skills.os.open", racing_open
            ), mock.patch("capability_map_core.skills.os.read", recording_read):
                result = discover_skills(
                    [RootSpec(root, "extra", "fixtures", "extra:fixtures", "<extra>")]
                )

            self.assertTrue(raced)
            self.assertEqual(result.capabilities, ())
            self.assertNotIn(secret_canary, b"".join(read_chunks))
            self.assertIn(
                "source_changed",
                {diagnostic.code for diagnostic in result.diagnostics},
            )

    def test_without_nofollow_or_file_id_double_swap_is_never_opened(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = base / "skills"
            skill_file = write_skill(root / "unverifiable", frontmatter="name: safe")
            backup = base / "original-SKILL.md"
            secret_canary = b"double-swap-secret-canary"
            secret_file = base / "secret"
            secret_file.write_bytes(
                b"---\nname: " + secret_canary + b"\n---\nprivate bytes"
            )
            real_os_open = os.open
            real_os_read = os.read
            open_attempts: list[Path] = []
            read_chunks: list[bytes] = []

            def double_swap_open(
                path: object, flags: int, *args: object, **kwargs: object
            ) -> int:
                opened_path = Path(path)  # type: ignore[arg-type]
                if (
                    opened_path.name == skill_file.name
                    and opened_path.parent.name == skill_file.parent.name
                ):
                    open_attempts.append(opened_path)
                    skill_file.rename(backup)
                    skill_file.symlink_to(secret_file)
                    fd = real_os_open(path, flags, *args, **kwargs)
                    skill_file.unlink()
                    backup.rename(skill_file)
                    return fd
                return real_os_open(path, flags, *args, **kwargs)

            def recording_read(fd: int, size: int) -> bytes:
                chunk = real_os_read(fd, size)
                read_chunks.append(chunk)
                return chunk

            uniform_evidence = (("st_mode", 33188), ("st_size", 123))
            with mock.patch.object(
                os, "O_NOFOLLOW", 0, create=True
            ), mock.patch(
                "capability_map_core.skills._file_id", return_value=None
            ), mock.patch(
                "capability_map_core.skills._stat_evidence",
                return_value=uniform_evidence,
            ), mock.patch(
                "capability_map_core.skills.os.open", double_swap_open
            ), mock.patch(
                "capability_map_core.skills.os.read", recording_read
            ):
                result = discover_skills(
                    [RootSpec(root, "extra", "fixtures", "extra:fixtures", "<extra>")]
                )

            self.assertEqual(open_attempts, [])
            self.assertEqual(result.capabilities, ())
            self.assertNotIn(secret_canary, b"".join(read_chunks))
            self.assertIn(
                "safe_open_unavailable",
                {diagnostic.code for diagnostic in result.diagnostics},
            )

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
    def test_adding_an_earlier_alias_does_not_change_physical_skill_ids(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "skills"
            physical_directory = root / "z-canonical"
            write_skill(
                physical_directory,
                frontmatter="name: stable-physical\ndescription: stable",
            )
            roots = [
                RootSpec(root, "extra", "fixtures", "root:fixtures", "<root>")
            ]

            before = discover_skills(roots)
            (root / "a-earlier-alias").symlink_to(
                physical_directory, target_is_directory=True
            )
            after = discover_skills(roots)

            self.assertEqual(len(before.capabilities), 1)
            self.assertEqual(len(after.capabilities), 1)
            self.assertEqual(before.capabilities[0].id, after.capabilities[0].id)
            self.assertEqual(
                before.capabilities[0].resolver_id,
                after.capabilities[0].resolver_id,
            )
            self.assertEqual(len(after.capabilities[0].source_locations), 2)

    @unittest.skipUnless(hasattr(os, "symlink"), "symlinks are required")
    def test_higher_priority_project_alias_does_not_change_ids(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            physical_root = base / "physical"
            physical_skill = physical_root / "skill"
            write_skill(physical_skill, frontmatter="name: cross-scope-alias")
            user_root = base / "user"
            project_root = base / "project"
            user_root.mkdir()
            project_root.mkdir()
            (user_root / "visible").symlink_to(
                physical_skill, target_is_directory=True
            )
            user_spec = RootSpec(
                user_root, "user", "codex", "user:codex", "<user>"
            )
            project_spec = RootSpec(
                project_root,
                "project",
                "shared",
                "project:shared",
                "<project>",
            )
            physical_spec = RootSpec(
                physical_root,
                "extra",
                "physical",
                "extra:physical",
                "<physical>",
            )
            real_scandir = os.scandir

            def hide_direct_root(path: object) -> object:
                if Path(path).name == physical_root.name:
                    raise PermissionError("keep physical root available but hidden")
                return real_scandir(path)

            with mock.patch(
                "capability_map_core.skills.os.scandir", hide_direct_root
            ):
                before = discover_skills([user_spec, physical_spec])
                (project_root / "visible").symlink_to(
                    physical_skill, target_is_directory=True
                )
                after = discover_skills(
                    [project_spec, user_spec, physical_spec]
                )

            before_capability = before.capabilities[0]
            after_capability = after.capabilities[0]
            self.assertEqual(before_capability.id, after_capability.id)
            self.assertEqual(
                before_capability.resolver_id, after_capability.resolver_id
            )
            self.assertEqual(after_capability.scope, "extra")
            self.assertEqual(after_capability.provider, "local-skill")
            self.assertEqual(
                {(source.scope, source.provider) for source in after_capability.source_locations},
                {("user", "codex"), ("project", "shared")},
            )

    def test_identical_physical_copies_never_collide_across_root_namespaces(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            first_root = base / "first"
            second_root = base / "second"
            metadata = "name: identical-copy\ndescription: byte-for-byte identical"
            write_skill(first_root / "same-relative", frontmatter=metadata)
            write_skill(second_root / "same-relative", frontmatter=metadata)

            distinct_namespaces = discover_skills(
                [
                    RootSpec(
                        first_root,
                        "extra",
                        "same-provider",
                        "extra:one",
                        "<one>",
                    ),
                    RootSpec(
                        second_root,
                        "extra",
                        "same-provider",
                        "extra:two",
                        "<two>",
                    ),
                ]
            )
            same_namespace_evidence = discover_skills(
                [
                    RootSpec(
                        first_root,
                        "extra",
                        "same-provider",
                        "extra:duplicate",
                        "<one>",
                    ),
                    RootSpec(
                        second_root,
                        "extra",
                        "same-provider",
                        "extra:duplicate",
                        "<two>",
                    ),
                ]
            )

            self.assertEqual(len(distinct_namespaces.capabilities), 2)
            self.assertEqual(
                len({item.id for item in distinct_namespaces.capabilities}), 2
            )
            self.assertEqual(len(same_namespace_evidence.capabilities), 2)
            self.assertEqual(
                len({item.id for item in same_namespace_evidence.capabilities}), 2
            )

    def test_no_file_id_fallback_is_path_independent_and_marks_weak_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            moving_root = base / "moving"
            original = write_skill(
                moving_root / "z-origin",
                frontmatter="name: fallback-identity\ndescription: stable",
            )
            moving_spec = RootSpec(
                moving_root,
                "extra",
                "fixtures",
                "extra:moving",
                "<moving>",
            )
            first_root = base / "copy-one"
            second_root = base / "copy-two"
            metadata = "name: fallback-copy\ndescription: identical"
            first_copy = write_skill(first_root / "same-relative", frontmatter=metadata)
            second_copy = write_skill(second_root / "same-relative", frontmatter=metadata)
            os.utime(first_copy, ns=(1_700_000_000_000_000_001,) * 2)
            os.utime(second_copy, ns=(1_700_000_000_000_000_002,) * 2)

            def no_file_id(path: Path) -> tuple[str, ...]:
                return ("realpath", os.path.normcase(str(path.resolve(strict=True))))

            with mock.patch(
                "capability_map_core.skills._physical_key", no_file_id
            ):
                before_move = discover_skills([moving_spec])
                original.parent.rename(moving_root / "a-new-origin")
                after_move = discover_skills([moving_spec])
                copies = discover_skills(
                    [
                        RootSpec(
                            first_root,
                            "extra",
                            "same-provider",
                            "extra:duplicate",
                            "<one>",
                        ),
                        RootSpec(
                            second_root,
                            "extra",
                            "same-provider",
                            "extra:duplicate",
                            "<two>",
                        ),
                    ]
                )

            self.assertEqual(before_move.capabilities[0].id, after_move.capabilities[0].id)
            self.assertEqual(
                before_move.capabilities[0].resolver_id,
                after_move.capabilities[0].resolver_id,
            )
            self.assertEqual(len({item.id for item in copies.capabilities}), 2)
            self.assertIn(
                "weak_physical_identity",
                {item.code for item in after_move.diagnostics},
            )

    def test_exact_fallback_collisions_use_unstable_opaque_nonces(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            first_root = base / "copy-one"
            second_root = base / "copy-two"
            metadata = "name: exact-copy\ndescription: identical fallback evidence"
            write_skill(first_root / "same-relative", frontmatter=metadata)
            write_skill(second_root / "same-relative", frontmatter=metadata)

            def no_file_id(path: Path) -> tuple[str, ...]:
                return ("realpath", os.path.normcase(str(path.resolve(strict=True))))

            uniform_evidence = (
                ("st_dev", 7),
                ("st_size", 123),
                ("st_mode", 33188),
                ("st_nlink", 1),
                ("st_birthtime_ns", 11),
                ("st_ctime_ns", 11),
                ("st_mtime_ns", 11),
            )
            with mock.patch(
                "capability_map_core.skills._physical_key", no_file_id
            ), mock.patch(
                "capability_map_core.skills._file_id", return_value=None
            ), mock.patch(
                "capability_map_core.skills._stat_evidence",
                return_value=uniform_evidence,
            ), mock.patch(
                "capability_map_core.skills._ambiguous_identity_nonce",
                side_effect=("opaque-first", "opaque-second"),
                create=True,
            ) as nonce_mock:
                result = discover_skills(
                    [
                        RootSpec(
                            first_root,
                            "extra",
                            "same-provider",
                            "extra:duplicate",
                            "<one>",
                        ),
                        RootSpec(
                            second_root,
                            "extra",
                            "same-provider",
                            "extra:duplicate",
                            "<two>",
                        ),
                    ]
                )

            self.assertEqual(len(result.capabilities), 2)
            self.assertEqual(len({item.id for item in result.capabilities}), 2)
            self.assertEqual(len({item.resolver_id for item in result.resolvers}), 2)
            self.assertEqual(nonce_mock.call_count, 2)
            self.assertGreaterEqual(
                [item.code for item in result.diagnostics].count(
                    "unstable_ambiguous_identity"
                ),
                2,
            )
            public_json = json.dumps(
                [item.to_public_dict() for item in result.capabilities],
                ensure_ascii=False,
            )
            self.assertNotIn(str(first_root), public_json)
            self.assertNotIn(str(second_root), public_json)

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
            real_os_open = os.open

            def guarded_scandir(path: object) -> object:
                if Path(path).name == blocked.name:
                    raise PermissionError("synthetic traversal denial")
                return real_scandir(path)

            def guarded_open(
                path: object, flags: int, *args: object, **kwargs: object
            ) -> int:
                opened_path = Path(path)  # type: ignore[arg-type]
                if (
                    opened_path.name == unreadable_file.name
                    and opened_path.parent.name == unreadable_file.parent.name
                ):
                    raise PermissionError("synthetic read denial")
                return real_os_open(path, flags, *args, **kwargs)

            with mock.patch("capability_map_core.skills.os.scandir", guarded_scandir), mock.patch(
                "capability_map_core.skills.os.open", guarded_open
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

    @unittest.skipUnless(hasattr(os, "symlink"), "symlinks are required")
    def test_root_stat_readlink_and_scandir_errors_are_diagnostic(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            stat_denied = base / "stat-denied"
            resolve_denied = base / "resolve-denied"
            readlink_target = base / "readlink-target"
            readlink_denied = base / "readlink-denied"
            scandir_denied = base / "scandir-denied"
            healthy = base / "healthy"
            for directory in (
                stat_denied,
                resolve_denied,
                readlink_target,
                scandir_denied,
            ):
                directory.mkdir()
            readlink_denied.symlink_to(readlink_target, target_is_directory=True)
            write_skill(healthy / "skill", frontmatter="name: healthy-root")
            roots = [
                RootSpec(stat_denied, "extra", "stat", "root:stat", "<stat>"),
                RootSpec(
                    resolve_denied,
                    "extra",
                    "resolve",
                    "root:resolve",
                    "<resolve>",
                ),
                RootSpec(
                    readlink_denied,
                    "extra",
                    "readlink",
                    "root:readlink",
                    "<readlink>",
                ),
                RootSpec(
                    scandir_denied,
                    "extra",
                    "scandir",
                    "root:scandir",
                    "<scandir>",
                ),
                RootSpec(healthy, "extra", "healthy", "root:healthy", "<healthy>"),
            ]
            real_lstat = os.lstat
            real_scandir = os.scandir

            def guarded_lstat(path: object, *args: object, **kwargs: object) -> object:
                if Path(path).name == stat_denied.name:
                    raise PermissionError("synthetic root stat denial")
                return real_lstat(path, *args, **kwargs)

            real_readlink = os.readlink

            def guarded_readlink(
                path: object, *args: object, **kwargs: object
            ) -> str:
                if Path(path).name == readlink_denied.name:
                    raise PermissionError("synthetic root readlink denial")
                return real_readlink(path, *args, **kwargs)

            def guarded_scandir(path: object) -> object:
                if Path(path).name == scandir_denied.name:
                    raise PermissionError("synthetic root scandir denial")
                return real_scandir(path)

            with mock.patch(
                "capability_map_core.skills.os.lstat", guarded_lstat
            ), mock.patch(
                "capability_map_core.skills.os.readlink", guarded_readlink
            ), mock.patch(
                "capability_map_core.skills.os.scandir", guarded_scandir
            ):
                result = discover_skills(roots)

            self.assertEqual(
                [capability.name for capability in result.capabilities],
                ["healthy-root"],
            )
            codes = [diagnostic.code for diagnostic in result.diagnostics]
            self.assertIn("root_stat_error", codes)
            self.assertIn("permission_denied", codes)
            self.assertIn("directory_read_error", codes)
            self.assertNotIn("broken_symlink", codes)

    @unittest.skipUnless(hasattr(os, "symlink"), "symlinks are required")
    def test_root_symlink_loop_is_diagnostic_and_does_not_stop_other_roots(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            first_link = base / "loop-a"
            second_link = base / "loop-b"
            first_link.symlink_to(second_link, target_is_directory=True)
            second_link.symlink_to(first_link, target_is_directory=True)
            healthy = base / "healthy"
            write_skill(healthy / "skill", frontmatter="name: healthy-root")

            result = discover_skills(
                [
                    RootSpec(
                        first_link,
                        "extra",
                        "loop",
                        "root:loop",
                        "<loop>",
                    ),
                    RootSpec(
                        healthy,
                        "extra",
                        "healthy",
                        "root:healthy",
                        "<healthy>",
                    ),
                ]
            )

            self.assertEqual(
                [capability.name for capability in result.capabilities],
                ["healthy-root"],
            )
            codes = [diagnostic.code for diagnostic in result.diagnostics]
            self.assertIn("root_symlink_loop", codes)
            self.assertNotIn("broken_symlink", codes)

    @unittest.skipUnless(hasattr(os, "symlink"), "symlinks are required")
    def test_configured_root_env_chain_is_rejected_before_scandir(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            payload_root = base / "payload-root"
            payload_canary = b"configured-root-secret-canary"
            write_raw_skill(
                payload_root / "secret",
                b"---\nname: " + payload_canary + b"\n---\nprivate bytes",
            )
            root_alias = base / "root-alias"
            middle = base / "middle"
            env_hop = base / ".ENV"
            env_hop.symlink_to(payload_root, target_is_directory=True)
            middle.symlink_to(env_hop, target_is_directory=True)
            root_alias.symlink_to(middle, target_is_directory=True)
            healthy_root = base / "healthy"
            write_skill(healthy_root / "skill", frontmatter="name: healthy-root")
            payload_id = (payload_root.stat().st_dev, payload_root.stat().st_ino)
            real_scandir = os.scandir
            real_os_read = os.read
            payload_scans: list[Path] = []
            read_chunks: list[bytes] = []

            def recording_scandir(path: object) -> object:
                opened_stat = os.stat(path)
                if (opened_stat.st_dev, opened_stat.st_ino) == payload_id:
                    payload_scans.append(Path(path))  # type: ignore[arg-type]
                return real_scandir(path)

            def recording_read(fd: int, size: int) -> bytes:
                chunk = real_os_read(fd, size)
                read_chunks.append(chunk)
                return chunk

            with mock.patch(
                "capability_map_core.skills.os.scandir", recording_scandir
            ), mock.patch(
                "capability_map_core.skills.os.read", recording_read
            ):
                result = discover_skills(
                    [
                        RootSpec(
                            root_alias,
                            "extra",
                            "blocked",
                            "root:blocked",
                            "<blocked>",
                        ),
                        RootSpec(
                            healthy_root,
                            "extra",
                            "healthy",
                            "root:healthy",
                            "<healthy>",
                        ),
                    ]
                )

            self.assertEqual(
                [capability.name for capability in result.capabilities],
                ["healthy-root"],
            )
            self.assertEqual(payload_scans, [])
            self.assertNotIn(payload_canary, b"".join(read_chunks))
            self.assertIn(
                "env_path_blocked",
                {diagnostic.code for diagnostic in result.diagnostics},
            )

    @unittest.skipUnless(hasattr(os, "symlink"), "symlinks are required")
    def test_root_alias_redirect_after_verification_cannot_change_walk_target(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            verified_root = base / "verified-root"
            write_skill(verified_root / "original", frontmatter="name: original-root")
            forbidden_root = base / ".ENV"
            secret_canary = b"root-alias-secret-canary"
            write_raw_skill(
                forbidden_root / "secret",
                b"---\nname: " + secret_canary + b"\n---\nprivate bytes",
            )
            root_alias = base / "root-alias"
            root_alias.symlink_to(verified_root, target_is_directory=True)
            forbidden_id = (
                forbidden_root.stat().st_dev,
                forbidden_root.stat().st_ino,
            )
            real_resolve_chain = sys.modules[
                "capability_map_core.skills"
            ]._resolve_symlink_chain
            real_scandir = os.scandir
            real_os_read = os.read
            redirected = False
            forbidden_scans: list[Path] = []
            read_chunks: list[bytes] = []

            def redirect_after_resolve(path: Path) -> Path:
                nonlocal redirected
                resolved = real_resolve_chain(path)
                if path.absolute() == root_alias.absolute() and not redirected:
                    root_alias.unlink()
                    root_alias.symlink_to(forbidden_root, target_is_directory=True)
                    redirected = True
                return resolved

            def recording_scandir(path: object) -> object:
                target_stat = os.stat(path)
                if (target_stat.st_dev, target_stat.st_ino) == forbidden_id:
                    forbidden_scans.append(Path(path))  # type: ignore[arg-type]
                return real_scandir(path)

            def recording_read(fd: int, size: int) -> bytes:
                chunk = real_os_read(fd, size)
                read_chunks.append(chunk)
                return chunk

            with mock.patch(
                "capability_map_core.skills._resolve_symlink_chain",
                redirect_after_resolve,
            ), mock.patch(
                "capability_map_core.skills.os.scandir", recording_scandir
            ), mock.patch(
                "capability_map_core.skills.os.read", recording_read
            ):
                result = discover_skills(
                    [
                        RootSpec(
                            root_alias,
                            "extra",
                            "alias",
                            "root:alias",
                            "<alias>",
                        )
                    ]
                )

            self.assertTrue(redirected)
            self.assertEqual(
                [capability.name for capability in result.capabilities],
                ["original-root"],
            )
            self.assertEqual(forbidden_scans, [])
            self.assertNotIn(secret_canary, b"".join(read_chunks))

    @unittest.skipUnless(hasattr(os, "symlink"), "symlinks are required")
    def test_symlink_hop_permission_errors_are_not_reported_as_broken(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            target = base / "target"
            target.mkdir()
            lstat_hop = base / "lstat-hop"
            lstat_root = base / "lstat-root"
            lstat_hop.symlink_to(target, target_is_directory=True)
            lstat_root.symlink_to(lstat_hop, target_is_directory=True)
            readlink_root = base / "readlink-root"
            readlink_root.symlink_to(target, target_is_directory=True)
            healthy_root = base / "healthy"
            write_skill(healthy_root / "skill", frontmatter="name: healthy-root")
            real_lstat = os.lstat
            real_readlink = os.readlink

            def guarded_lstat(path: object, *args: object, **kwargs: object) -> object:
                if Path(path).name == lstat_hop.name:
                    raise PermissionError("synthetic symlink-hop lstat denial")
                return real_lstat(path, *args, **kwargs)

            def guarded_readlink(
                path: object, *args: object, **kwargs: object
            ) -> str:
                if Path(path).name == readlink_root.name:
                    raise PermissionError("synthetic symlink-hop readlink denial")
                return real_readlink(path, *args, **kwargs)

            with mock.patch(
                "capability_map_core.skills.os.lstat", guarded_lstat
            ), mock.patch(
                "capability_map_core.skills.os.readlink", guarded_readlink
            ):
                result = discover_skills(
                    [
                        RootSpec(
                            lstat_root,
                            "extra",
                            "lstat",
                            "root:lstat-hop",
                            "<lstat>",
                        ),
                        RootSpec(
                            readlink_root,
                            "extra",
                            "readlink",
                            "root:readlink-hop",
                            "<readlink>",
                        ),
                        RootSpec(
                            healthy_root,
                            "extra",
                            "healthy",
                            "root:healthy",
                            "<healthy>",
                        ),
                    ]
                )

            self.assertEqual(
                [capability.name for capability in result.capabilities],
                ["healthy-root"],
            )
            codes = [diagnostic.code for diagnostic in result.diagnostics]
            self.assertGreaterEqual(codes.count("permission_denied"), 2)
            self.assertNotIn("broken_symlink", codes)


if __name__ == "__main__":
    unittest.main()

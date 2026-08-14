"""Tests for local/Obsidian storage and the private resolver bundle."""

from __future__ import annotations

import json
import os
import stat
import sys
import tempfile
import time
import unittest
from pathlib import Path, PureWindowsPath
from unittest import mock


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import capability_map_core.storage as storage_module  # noqa: E402
from capability_map_core.clis import discover_clis  # noqa: E402
from capability_map_core.models import ResolverRecord  # noqa: E402
from capability_map_core.storage import (  # noqa: E402
    PublicArtifacts,
    RootEvidence,
    StoragePaths,
    build_private_resolver_document,
    capture_storage_expected_state,
    default_storage_paths,
    discover_obsidian_vaults,
    write_storage_bundle,
)


def _artifacts(marker: str, exact_path: str | None = None) -> PublicArtifacts:
    path_text = "" if exact_path is None else f"\nsource: {exact_path}"
    return PublicArtifacts(
        map_markdown=f"# Map {marker}{path_text}\n",
        inventory={"schema_version": 2, "marker": marker, "source": exact_path},
        config={"schema_version": 1, "marker": marker, "source": exact_path},
        receipt_markdown=f"# Receipt {marker}{path_text}\n",
    )


def _bundle_bytes(paths: StoragePaths) -> dict[Path, bytes]:
    return {
        path: path.read_bytes()
        for path in (
            paths.map_path,
            paths.inventory_path,
            paths.config_path,
            paths.receipt_path,
            paths.resolver_path,
        )
    }


class DefaultStoragePathTests(unittest.TestCase):
    def test_storage_paths_capture_private_root_evidence_without_repr_leak(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            public_parent = base / "public-parent"
            private_parent = base / "private-parent"
            public_parent.mkdir()
            private_parent.mkdir()

            paths = default_storage_paths(
                home=base / "home",
                local_root=public_parent / "map",
                private_root=private_parent / "data",
            )

            self.assertIsInstance(paths.public_root_evidence, RootEvidence)
            self.assertIsInstance(paths.private_root_evidence, RootEvidence)
            self.assertEqual(
                paths.public_root_evidence.resolved_path, paths.public_root
            )
            self.assertEqual(
                paths.private_root_evidence.resolved_path, paths.private_root
            )
            self.assertTrue(paths.public_root_evidence.existing_ancestors)
            self.assertTrue(paths.private_root_evidence.existing_ancestors)
            self.assertIn("RootEvidence", storage_module.__all__)
            self.assertNotIn("public_root_evidence", repr(paths))
            self.assertNotIn("private_root_evidence", repr(paths))

    def test_platform_defaults_are_fully_injected(self) -> None:
        home = Path("/fixture/home")
        cases = (
            (
                "Darwin",
                {},
                home / "Library" / "Application Support" / "Vantasma" / "Agent能力地图",
            ),
            (
                "Linux",
                {},
                home / ".local" / "share" / "vantasma" / "agent-capabilities",
            ),
            (
                "Linux",
                {"XDG_DATA_HOME": "/fixture/数据 根"},
                Path("/fixture/数据 根/vantasma/agent-capabilities"),
            ),
            (
                "Windows",
                {"localappdata": "/fixture/Local Data"},
                Path("/fixture/Local Data/Vantasma/Agent能力地图"),
            ),
        )
        for platform_name, environment, expected in cases:
            with self.subTest(platform_name=platform_name, environment=environment):
                if platform_name == "Windows" and os.name != "nt":
                    self.assertEqual(
                        storage_module.default_storage_root_text(
                            platform_name=platform_name,
                            environ=environment,
                            home=home,
                        ),
                        str(
                            PureWindowsPath(environment["localappdata"])
                            / "Vantasma"
                            / "Agent能力地图"
                        ),
                    )
                    continue
                paths = default_storage_paths(
                    platform_name=platform_name,
                    environ=environment,
                    home=home,
                )
                self.assertIsInstance(paths, StoragePaths)
                self.assertEqual(paths.public_root, expected)
                self.assertEqual(paths.private_root, expected / ".private")
                self.assertEqual(paths.map_path, expected / "本机能力地图.md")
                self.assertEqual(
                    paths.inventory_path, expected / "capability-inventory.json"
                )
                self.assertEqual(
                    paths.config_path, expected / "capability-map.config.json"
                )
                self.assertEqual(paths.receipt_path, expected / "setup-receipt.md")
                self.assertEqual(
                    paths.resolver_path,
                    expected / ".private" / "capability-resolver.json",
                )

    def test_windows_falls_back_to_injected_home_and_expands_tilde(self) -> None:
        home = Path("/fixture/Windows User")
        if os.name != "nt":
            self.assertEqual(
                storage_module.default_storage_root_text(
                    platform_name="win32", environ={}, home=home
                ),
                r"\fixture\Windows User\AppData\Local\Vantasma\Agent能力地图",
            )
            return
        paths = default_storage_paths(
            platform_name="win32",
            environ={},
            home=home,
            local_root="~/显式 地图",
        )

        self.assertEqual(paths.public_root, home / "显式 地图")
        self.assertEqual(
            paths.private_root,
            home / "AppData" / "Local" / "Vantasma" / "Agent能力地图" / ".private",
        )

    def test_cross_host_windows_path_semantics_fail_closed(self) -> None:
        if os.name == "nt":
            self.skipTest("this test requires a non-Windows host")
        with self.assertRaisesRegex(ValueError, "path_semantics_unavailable"):
            default_storage_paths(
                platform_name="Windows",
                environ={"LOCALAPPDATA": r"C:\Fixture\Local Data"},
                home=Path("/fixture/non-windows-home"),
            )

    def test_windows_default_root_text_needs_no_host_path_resolution(self) -> None:
        helper = getattr(storage_module, "default_storage_root_text", None)
        self.assertIsNotNone(helper)
        self.assertEqual(
            helper(
                platform_name="Windows",
                environ={"localappdata": r"C:\Fixture\Local Data"},
                home=r"C:\Fixture\Home",
            ),
            r"C:\Fixture\Local Data\Vantasma\Agent能力地图",
        )
        self.assertEqual(
            helper(
                platform_name="Windows",
                environ={},
                home=r"C:\Fixture\Home",
            ),
            r"C:\Fixture\Home\AppData\Local\Vantasma\Agent能力地图",
        )

    def test_explicit_local_and_obsidian_roots_are_distinct_modes(self) -> None:
        home = Path("/fixture/home")
        local = Path("/fixture/Local Maps/中文")
        vault = Path("/fixture/iCloud Drive/知识 Vault")

        local_paths = default_storage_paths(home=home, local_root=local)
        vault_paths = default_storage_paths(
            home=home,
            selected_vault=vault,
            vault_subdirectory="Agent/定制 地图",
        )

        self.assertEqual(local_paths.public_root, local)
        self.assertEqual(vault_paths.public_root, vault / "Agent" / "定制 地图")
        self.assertFalse(vault_paths.private_root.is_relative_to(vault))
        with self.assertRaises(ValueError):
            default_storage_paths(
                home=home, local_root=local, selected_vault=vault
            )
        with self.assertRaises(ValueError):
            default_storage_paths(
                home=home,
                selected_vault=vault,
                private_root=vault / "private",
            )

    def test_custom_vault_subdirectory_cannot_escape_or_be_absolute(self) -> None:
        vault = Path("/fixture/vault")
        for unsafe in ("../outside", "Agent/../../outside", "/absolute"):
            with self.subTest(unsafe=unsafe):
                with self.assertRaises(ValueError):
                    default_storage_paths(
                        home=Path("/fixture/home"),
                        selected_vault=vault,
                        vault_subdirectory=unsafe,
                    )

    def test_staging_root_accepts_only_safe_public_relative_components(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            public_root = base / "public"
            for unsafe in (".", "../outside", base / "absolute-stage"):
                with self.subTest(unsafe=unsafe), self.assertRaises(ValueError):
                    default_storage_paths(
                        home=base / "home",
                        local_root=public_root,
                        private_root=base / "private",
                        staging_root=unsafe,
                    )

    def test_staging_root_is_created_via_public_handle_without_following_symlink(self) -> None:
        if not hasattr(os, "symlink"):
            self.skipTest("symlinks unsupported")
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            public_root = base / "public"
            outside = base / "outside"
            public_root.mkdir()
            outside.mkdir()
            (public_root / "redirect").symlink_to(
                outside, target_is_directory=True
            )
            paths = default_storage_paths(
                home=base / "home",
                local_root=public_root,
                private_root=base / "private",
                staging_root="redirect/nested",
            )

            self.assertEqual(
                paths.staging_root, paths.public_root / "redirect" / "nested"
            )
            with self.assertRaises((OSError, ValueError)):
                write_storage_bundle(paths, _artifacts("must-not-write"), ())

            self.assertFalse((outside / "nested").exists())
            self.assertEqual(list(outside.glob(".capability-stage-*")), [])
            self.assertEqual(list(public_root.glob(".capability-stage-*")), [])
            self.assertTrue(
                all(
                    not path.exists()
                    for path in (
                        paths.map_path,
                        paths.inventory_path,
                        paths.config_path,
                        paths.receipt_path,
                        paths.resolver_path,
                    )
                )
            )

    def test_storage_paths_reject_wrong_filenames_and_escape_paths(self) -> None:
        root = Path("/fixture/root")
        private = Path("/fixture/private")
        valid = {
            "public_root": root,
            "map_path": root / "本机能力地图.md",
            "inventory_path": root / "capability-inventory.json",
            "config_path": root / "capability-map.config.json",
            "receipt_path": root / "setup-receipt.md",
            "private_root": private,
            "resolver_path": private / "capability-resolver.json",
        }
        with self.assertRaises(ValueError):
            StoragePaths(**{**valid, "map_path": root.parent / "escaped.md"})
        with self.assertRaises(ValueError):
            StoragePaths(**{**valid, "inventory_path": root / "other.json"})
        with self.assertRaises(ValueError):
            StoragePaths(**{**valid, "resolver_path": private.parent / "resolver.json"})

    def test_private_ancestor_symlink_into_selected_vault_is_rejected(self) -> None:
        if not hasattr(os, "symlink"):
            self.skipTest("symlinks unsupported")
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            vault = base / "vault"
            hidden_private = vault / "hidden-private"
            hidden_private.mkdir(parents=True)
            private_alias = base / "private-alias"
            private_alias.symlink_to(hidden_private, target_is_directory=True)

            with self.assertRaises(ValueError):
                default_storage_paths(
                    home=base / "home",
                    selected_vault=vault,
                    private_root=private_alias / "resolver-data",
                )

    def test_output_root_symlinks_are_rejected_during_path_resolution(self) -> None:
        if not hasattr(os, "symlink"):
            self.skipTest("symlinks unsupported")
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            real_public = base / "real-public"
            real_public.mkdir()
            public_alias = base / "public-alias"
            public_alias.symlink_to(real_public, target_is_directory=True)

            with self.assertRaises(ValueError):
                default_storage_paths(
                    home=base / "home",
                    local_root=public_alias,
                    private_root=base / "private",
                )

    def test_storage_roots_reject_env_segments_and_symlink_loops(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            with self.assertRaises(ValueError):
                default_storage_paths(
                    home=base / "home",
                    selected_vault=base / ".env" / "vault",
                    private_root=base / "private",
                )

            if hasattr(os, "symlink"):
                loop = base / "loop"
                loop.symlink_to(loop, target_is_directory=True)
                with self.assertRaises(ValueError):
                    default_storage_paths(
                        home=base / "home",
                        selected_vault=base / "vault",
                        private_root=loop / "resolver-data",
                    )


class ObsidianVaultDiscoveryTests(unittest.TestCase):
    def test_discovers_multiple_vaults_without_walking_notes_and_deduplicates(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            config_one = base / "config one" / "obsidian.json"
            config_two = base / "config two" / "obsidian.json"
            chinese = base / "iCloud 云盘" / "知识 Vault"
            spaced = base / "外接 磁盘" / "Project Notes"
            long_vault = base / ("很长的名称" * 30)
            for vault in (chinese, spaced, long_vault):
                vault.mkdir(parents=True)
                (vault / "private note.md").write_text("must not be read", encoding="utf-8")
            config_one.parent.mkdir(parents=True)
            config_two.parent.mkdir(parents=True)
            config_one.write_text(
                json.dumps(
                    {
                        "vaults": {
                            "one": {"path": str(chinese), "open": True},
                            "two": {"path": str(spaced), "open": False},
                            "long": {"path": str(long_vault)},
                        }
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8-sig",
            )
            config_two.write_text(
                json.dumps(
                    {
                        "vaults": {
                            "duplicate": {
                                "path": str(chinese / ".." / chinese.name),
                                "open": False,
                            },
                            "network": {
                                "path": "//server.example/share/团队 Vault",
                                "open": True,
                            },
                        }
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            with mock.patch.object(Path, "rglob", side_effect=AssertionError("note walk")), mock.patch(
                "os.walk", side_effect=AssertionError("note walk")
            ):
                forward = discover_obsidian_vaults((config_two, config_one))
                reverse = discover_obsidian_vaults((config_one, config_two))

            self.assertEqual(forward, reverse)
            self.assertEqual(len(forward.candidates), 4)
            self.assertEqual(sum(item.path == chinese for item in forward.candidates), 1)
            self.assertTrue(next(item for item in forward.candidates if item.path == chinese).open)
            self.assertTrue(any(str(item.path).startswith("//server.example") for item in forward.candidates))
            self.assertTrue(all(str(base) not in item.display_label for item in forward.candidates))
            self.assertTrue(all(len(item.display_label) <= 128 for item in forward.candidates))
            self.assertEqual(forward.diagnostics, ())

    def test_missing_configs_are_normal_but_broken_inputs_have_diagnostics(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            missing = base / "missing" / "obsidian.json"
            invalid = base / "invalid.json"
            invalid.write_text("{broken", encoding="utf-8")
            directory = base / "directory.json"
            directory.mkdir()
            real = base / "real.json"
            real.write_text('{"vaults": {}}', encoding="utf-8")
            linked = base / "linked.json"
            linked.symlink_to(real)
            env_config = base / ".env" / "obsidian.json"
            env_config.parent.mkdir()
            env_config.write_text('{"vaults": {}}', encoding="utf-8")
            oversized = base / "oversized.json"
            oversized.write_bytes(b" " * (storage_module.MAX_OBSIDIAN_CONFIG_BYTES + 1))

            result = discover_obsidian_vaults(
                (missing, invalid, directory, linked, env_config, oversized)
            )

            codes = {item.code for item in result.diagnostics}
            self.assertNotIn("missing_config", codes)
            self.assertIn("invalid_obsidian_config", codes)
            self.assertIn("obsidian_config_not_regular", codes)
            self.assertIn("obsidian_config_symlink", codes)
            self.assertIn("obsidian_config_env_blocked", codes)
            self.assertIn("obsidian_config_too_large", codes)
            public_diagnostics = json.dumps(
                [item.to_public_dict() for item in result.diagnostics],
                ensure_ascii=False,
            )
            self.assertNotIn(str(base), public_diagnostics)

    @unittest.skipUnless(hasattr(os, "mkfifo"), "FIFO is POSIX-only")
    def test_fifo_is_rejected_without_blocking(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fifo = Path(temporary) / "obsidian.json"
            os.mkfifo(fifo)

            started = time.monotonic()
            result = discover_obsidian_vaults((fifo,))
            elapsed = time.monotonic() - started

            self.assertLess(elapsed, 1.0)
            self.assertIn(
                "obsidian_config_not_regular",
                {item.code for item in result.diagnostics},
            )

    def test_permission_errors_are_diagnostics(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config = Path(temporary) / "obsidian.json"
            config.write_text('{"vaults": {}}', encoding="utf-8")
            original_open = storage_module.os.open

            def denied(path: object, *args: object, **kwargs: object) -> int:
                if os.fspath(path) == os.fspath(config):
                    raise PermissionError("fixture denied")
                return original_open(path, *args, **kwargs)

            with mock.patch.object(storage_module.os, "open", side_effect=denied):
                result = discover_obsidian_vaults((config,))

            self.assertIn(
                "obsidian_config_permission_denied",
                {item.code for item in result.diagnostics},
            )


class ResolverDocumentTests(unittest.TestCase):
    def test_private_document_is_deterministic_and_contains_all_exact_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            paths = default_storage_paths(
                home=base / "home",
                local_root=base / "公开 地图",
                private_root=base / "系统 私有",
            )
            exact_one = str(base / "home" / "技能" / "SKILL.md")
            exact_two = str(base / ("长目录" * 40) / "tool")
            records = (
                ResolverRecord("res_b", [exact_two, exact_one, exact_two]),
                ResolverRecord("res_a", ["//server/share/能力"]),
            )

            forward = build_private_resolver_document(paths, records)
            reverse = build_private_resolver_document(paths, tuple(reversed(records)))

            self.assertEqual(forward, reverse)
            self.assertEqual(forward["schema_version"], 1)
            self.assertEqual(
                [item["resolver_id"] for item in forward["records"]],
                ["res_a", "res_b"],
            )
            self.assertEqual(
                forward["records"][1]["exact_locations"],
                [exact_two, exact_one, exact_two],
            )
            serialized = json.dumps(forward, ensure_ascii=False, sort_keys=True)
            for exact in (
                exact_one,
                exact_two,
                "//server/share/能力",
                str(paths.public_root),
                str(paths.map_path),
                str(paths.private_root),
                str(paths.resolver_path),
            ):
                self.assertIn(exact, serialized)

    def test_duplicate_resolver_ids_with_different_records_are_rejected(self) -> None:
        paths = default_storage_paths(home=Path("/fixture/home"))
        with self.assertRaises(ValueError):
            build_private_resolver_document(
                paths,
                (
                    ResolverRecord("res_same", ["/one"]),
                    ResolverRecord("res_same", ["/two", "/one"]),
                ),
            )

    def test_cli_four_entry_shadow_chain_serializes_without_adapter(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            directories = tuple(base / f"bin {index}" for index in range(3))
            for directory in directories:
                executable = directory / "same-tool"
                executable.parent.mkdir(parents=True)
                executable.write_text("#!/bin/sh\n", encoding="utf-8")
                executable.chmod(0o755)
            path_value = os.pathsep.join(
                [str(directories[0]), str(directories[1]), str(directories[2]), str(directories[0])]
            )
            cli_result = discover_clis(
                path=path_value,
                cwd=base,
                platform_name="Linux",
                os_name="posix",
            )
            paths = default_storage_paths(
                home=base / "home", local_root=base / "map"
            )

            write_storage_bundle(paths, _artifacts("cli"), cli_result.resolvers)

            private = json.loads(paths.resolver_path.read_text(encoding="utf-8"))
            self.assertEqual(len(private["records"]), 1)
            self.assertEqual(
                private["records"][0]["exact_locations"],
                [
                    str(directories[0] / "same-tool"),
                    str(directories[1] / "same-tool"),
                    str(directories[2] / "same-tool"),
                    str(directories[0] / "same-tool"),
                ],
            )


class AtomicStorageWriterTests(unittest.TestCase):
    def test_plan_expected_state_refuses_later_create_and_modify(self) -> None:
        cases = ("create", "modify")
        if os.name != "nt":
            cases += ("chmod",)
        for mutation in cases:
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as temporary:
                base = Path(temporary)
                paths = default_storage_paths(
                    home=base / "home",
                    local_root=base / "map",
                    private_root=base / "private",
                )
                if mutation != "create":
                    write_storage_bundle(paths, _artifacts("old"), ())
                expected = capture_storage_expected_state(paths)
                paths.public_root.mkdir(parents=True, exist_ok=True)
                if mutation == "chmod":
                    concurrent = paths.map_path.read_bytes()
                    paths.map_path.chmod(0o600)
                else:
                    concurrent = b"external plan-race owner\n"
                    paths.map_path.write_bytes(concurrent)

                with self.assertRaisesRegex(RuntimeError, "stale storage plan"):
                    write_storage_bundle(
                        paths,
                        _artifacts("new"),
                        (),
                        expected_state=expected,
                    )

                self.assertEqual(paths.map_path.read_bytes(), concurrent)
                if mutation == "chmod":
                    self.assertEqual(stat.S_IMODE(paths.map_path.stat().st_mode), 0o600)

    @staticmethod
    def _file_evidence(path: Path) -> tuple[int, int, int, int, int, bytes]:
        metadata = os.lstat(path)
        return (
            metadata.st_dev,
            metadata.st_ino,
            metadata.st_mtime_ns,
            metadata.st_size,
            stat.S_IMODE(metadata.st_mode),
            path.read_bytes(),
        )

    def test_target_snapshot_uses_nofollow_nonblock_and_bounded_reads(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "target"
            target.write_bytes(b"four")
            real_open = os.open

            with mock.patch.object(storage_module.os, "open", wraps=real_open) as opened:
                snapshot = storage_module._target_snapshot(target)

            target_calls = [
                call
                for call in opened.call_args_list
                if os.fspath(call.args[0]) == os.fspath(target)
            ]
            self.assertEqual(len(target_calls), 1)
            flags = target_calls[0].args[1]
            self.assertTrue(flags & getattr(os, "O_NONBLOCK", 0))
            if getattr(os, "O_NOFOLLOW", 0):
                self.assertTrue(flags & os.O_NOFOLLOW)
            self.assertEqual(snapshot.payload, b"four")

            with mock.patch.object(
                storage_module, "MAX_STORAGE_TARGET_BYTES", 3, create=True
            ):
                with self.assertRaises(ValueError):
                    storage_module._target_snapshot(target)

    @unittest.skipUnless(hasattr(os, "mkfifo"), "FIFO race is POSIX-only")
    def test_target_swap_from_regular_file_to_fifo_is_rejected_without_blocking(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            paths = default_storage_paths(home=base / "home", local_root=base / "map")
            write_storage_bundle(paths, _artifacts("old"), ())
            target = paths.map_path
            parked = base / "parked-map"
            original_lstat = storage_module.os.lstat
            swapped = False

            def swap_after_lstat(path: object, *args: object, **kwargs: object):
                nonlocal swapped
                metadata = original_lstat(path, *args, **kwargs)
                if os.fspath(path) == os.fspath(target) and not swapped:
                    swapped = True
                    target.rename(parked)
                    os.mkfifo(target)
                return metadata

            started = time.monotonic()
            with mock.patch.object(
                storage_module.os, "lstat", side_effect=swap_after_lstat
            ), mock.patch.object(
                Path,
                "read_bytes",
                side_effect=AssertionError("path-based read followed raced target"),
            ):
                with self.assertRaises(ValueError):
                    write_storage_bundle(paths, _artifacts("new"), ())

            self.assertLess(time.monotonic() - started, 1.0)

    def test_target_swap_from_regular_file_to_symlink_is_rejected(self) -> None:
        if not hasattr(os, "symlink") or not getattr(os, "O_NOFOLLOW", 0):
            self.skipTest("secure no-follow opens unsupported")
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            paths = default_storage_paths(home=base / "home", local_root=base / "map")
            write_storage_bundle(paths, _artifacts("old"), ())
            target = paths.map_path
            parked = base / "parked-map"
            outside = base / "outside"
            outside.write_bytes(b"do not read")
            original_lstat = storage_module.os.lstat
            swapped = False

            def swap_after_lstat(path: object, *args: object, **kwargs: object):
                nonlocal swapped
                metadata = original_lstat(path, *args, **kwargs)
                if os.fspath(path) == os.fspath(target) and not swapped:
                    swapped = True
                    target.rename(parked)
                    target.symlink_to(outside)
                return metadata

            with mock.patch.object(
                storage_module.os, "lstat", side_effect=swap_after_lstat
            ), mock.patch.object(
                Path,
                "read_bytes",
                side_effect=AssertionError("path-based read followed raced target"),
            ):
                with self.assertRaises(ValueError):
                    write_storage_bundle(paths, _artifacts("new"), ())

            self.assertEqual(outside.read_bytes(), b"do not read")

    def test_first_write_creates_complete_sanitized_bundle_and_private_resolver(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            home = base / "home canary"
            paths = default_storage_paths(
                home=home,
                local_root=base / "公开 地图",
                private_root=base / "系统 私有",
            )
            exact = str(home / "外部 能力" / "secret-tool")
            records = (ResolverRecord("res_fixture", [exact]),)

            result = write_storage_bundle(paths, _artifacts("first", exact), records)

            bundle = _bundle_bytes(paths)
            self.assertTrue(all(bundle.values()))
            self.assertEqual(set(result.hashes), {"map", "inventory", "config", "receipt", "resolver"})
            self.assertEqual(len(result.changed_paths), 5)
            self.assertTrue(result.generation_id.startswith("gen_"))
            self.assertEqual(result.receipt_info["generation_id"], result.generation_id)
            json.loads(paths.inventory_path.read_text(encoding="utf-8"))
            json.loads(paths.config_path.read_text(encoding="utf-8"))
            private = json.loads(paths.resolver_path.read_text(encoding="utf-8"))
            self.assertIn(exact, json.dumps(private, ensure_ascii=False))
            public = b"\n".join(
                bundle[path]
                for path in (
                    paths.map_path,
                    paths.inventory_path,
                    paths.config_path,
                    paths.receipt_path,
                )
            ).decode("utf-8")
            for private_value in (
                exact,
                str(home),
                str(paths.resolver_path),
                str(paths.private_root),
            ):
                self.assertNotIn(private_value, public)
            if os.name != "nt":
                self.assertEqual(stat.S_IMODE(paths.resolver_path.stat().st_mode), 0o600)

    def test_documents_and_repeated_writes_are_deterministic_and_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            paths = default_storage_paths(home=base / "home", local_root=base / "map")
            records = (ResolverRecord("res_b", ["/two"]), ResolverRecord("res_a", ["/one"]))

            first = write_storage_bundle(paths, _artifacts("same"), records)
            before = _bundle_bytes(paths)
            mtimes = {path: path.stat().st_mtime_ns for path in before}
            with mock.patch.object(storage_module.os, "replace", wraps=os.replace) as replace:
                second = write_storage_bundle(paths, _artifacts("same"), tuple(reversed(records)))

            self.assertEqual(first.hashes, second.hashes)
            self.assertEqual(first.generation_id, second.generation_id)
            self.assertEqual(second.changed_paths, ())
            self.assertEqual(replace.call_count, 0)
            self.assertEqual(before, _bundle_bytes(paths))
            self.assertEqual(mtimes, {path: path.stat().st_mtime_ns for path in before})

    def test_normal_commit_is_no_replace_and_handle_bound(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            paths = default_storage_paths(
                home=base / "home",
                local_root=base / "map",
                private_root=base / "private",
            )
            write_storage_bundle(
                paths,
                _artifacts("old"),
                (ResolverRecord("res_old", ["/old"]),),
            )

            with mock.patch.object(
                storage_module.os, "replace", wraps=os.replace
            ) as replaced, mock.patch.object(
                storage_module.os, "link", wraps=os.link
            ) as linked, mock.patch.object(
                storage_module.os, "rename", wraps=os.rename
            ) as renamed, mock.patch.object(
                storage_module.os, "open", wraps=os.open
            ) as opened, mock.patch.object(
                storage_module.os,
                "chmod",
                side_effect=AssertionError("path-based chmod is forbidden"),
            ):
                write_storage_bundle(
                    paths,
                    _artifacts("secure"),
                    (ResolverRecord("res_new", ["/new"]),),
                )

            self.assertEqual(replaced.call_count, 0)
            self.assertEqual(linked.call_count, 5)
            self.assertEqual(renamed.call_count, 5)
            for call in linked.call_args_list:
                self.assertEqual(Path(call.args[0]).name, call.args[0])
                self.assertEqual(Path(call.args[1]).name, call.args[1])
                self.assertIsInstance(call.kwargs.get("src_dir_fd"), int)
                self.assertIsInstance(call.kwargs.get("dst_dir_fd"), int)
                self.assertFalse(call.kwargs.get("follow_symlinks"))
            for call in renamed.call_args_list:
                self.assertIsInstance(call.kwargs.get("src_dir_fd"), int)
                self.assertIsInstance(call.kwargs.get("dst_dir_fd"), int)
            stable_names = {
                paths.map_path.name,
                paths.inventory_path.name,
                paths.config_path.name,
                paths.receipt_path.name,
                paths.resolver_path.name,
            }
            stable_opens = [
                call for call in opened.call_args_list if call.args[0] in stable_names
            ]
            self.assertTrue(stable_opens)
            for call in stable_opens:
                self.assertIsInstance(call.kwargs.get("dir_fd"), int)
                self.assertTrue(call.args[1] & os.O_NOFOLLOW)

    def test_missing_secure_storage_backend_fails_before_creating_roots(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            paths = default_storage_paths(
                home=base / "home",
                local_root=base / "map",
                private_root=base / "private",
            )

            with mock.patch.object(storage_module.os, "fchmod", None):
                with self.assertRaisesRegex(
                    RuntimeError, "secure_storage_backend_unavailable"
                ):
                    write_storage_bundle(paths, _artifacts("must-not-write"), ())

            self.assertFalse(paths.public_root.exists())
            self.assertFalse(paths.private_root.exists())

    def test_root_and_stage_swap_during_link_cannot_write_attacker_artifact(self) -> None:
        if not hasattr(os, "symlink"):
            self.skipTest("symlinks unsupported")
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            public_root = base / "public-map"
            parked_public = base / "parked-public-map"
            attacker_root = base / "attacker-map"
            attacker_root.mkdir()
            paths = default_storage_paths(
                home=base / "home",
                local_root=public_root,
                private_root=base / "private",
            )
            real_link = os.link
            swapped = False

            def swap_before_link(
                source: object, destination: object, *args: object, **kwargs: object
            ) -> None:
                nonlocal swapped
                destination_name = os.fspath(destination)
                if Path(destination_name).name == paths.map_path.name and not swapped:
                    swapped = True
                    original_stage = next(public_root.glob(".capability-stage-*"))
                    public_root.rename(parked_public)
                    public_root.symlink_to(attacker_root, target_is_directory=True)
                real_link(source, destination, *args, **kwargs)

            with mock.patch.object(
                storage_module.os, "link", side_effect=swap_before_link
            ):
                with self.assertRaises((ValueError, RuntimeError)):
                    write_storage_bundle(paths, _artifacts("raced"), ())

            public_names = {
                paths.map_path.name,
                paths.inventory_path.name,
                paths.config_path.name,
                paths.receipt_path.name,
            }
            self.assertTrue(swapped)
            self.assertTrue(
                all(not (attacker_root / name).exists() for name in public_names)
            )
            self.assertTrue(
                all(not (parked_public / name).exists() for name in public_names)
            )
            self.assertFalse(paths.resolver_path.exists())

    def test_successful_update_preserves_existing_public_modes(self) -> None:
        if os.name == "nt":
            self.skipTest("POSIX mode semantics")
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            paths = default_storage_paths(home=base / "home", local_root=base / "map")
            records = (ResolverRecord("res_fixture", ["/exact"]),)
            write_storage_bundle(paths, _artifacts("old"), records)
            modes = {
                paths.map_path: 0o640,
                paths.inventory_path: 0o604,
                paths.config_path: 0o644,
                paths.receipt_path: 0o600,
            }
            for path, mode in modes.items():
                path.chmod(mode)

            write_storage_bundle(paths, _artifacts("new"), records)

            self.assertEqual(
                {path: stat.S_IMODE(path.stat().st_mode) for path in modes}, modes
            )
            self.assertEqual(stat.S_IMODE(paths.resolver_path.stat().st_mode), 0o600)

    def test_failure_at_every_replace_restores_previous_bundle_exactly(self) -> None:
        labels = ("map", "inventory", "config", "receipt", "resolver")
        for failing_label in labels:
            with self.subTest(failing_label=failing_label), tempfile.TemporaryDirectory() as temporary:
                base = Path(temporary)
                paths = default_storage_paths(
                    home=base / "home",
                    local_root=base / "map",
                    private_root=base / "private",
                )
                records = (ResolverRecord("res_fixture", [str(base / "old exact")]),)
                write_storage_bundle(paths, _artifacts("old"), records)
                if os.name != "nt":
                    paths.map_path.chmod(0o640)
                before = _bundle_bytes(paths)
                modes = {
                    path: stat.S_IMODE(path.stat().st_mode) for path in before
                }

                def fail(label: str, target: Path) -> None:
                    self.assertEqual(target.name, {
                        "map": "本机能力地图.md",
                        "inventory": "capability-inventory.json",
                        "config": "capability-map.config.json",
                        "receipt": "setup-receipt.md",
                        "resolver": "capability-resolver.json",
                    }[label])
                    if label == failing_label:
                        raise OSError("injected replace failure")

                with self.assertRaises(OSError):
                    write_storage_bundle(
                        paths,
                        _artifacts("new"),
                        (ResolverRecord("res_fixture", [str(base / "new exact")]),),
                        failure_injector=fail,
                    )

                self.assertEqual(_bundle_bytes(paths), before)
                self.assertEqual(
                    {path: stat.S_IMODE(path.stat().st_mode) for path in before},
                    modes,
                )
                self.assertEqual(
                    list(paths.public_root.glob(".capability-stage-*")), []
                )
                self.assertEqual(
                    list(paths.private_root.glob(".capability-stage-*")), []
                )

    def test_failure_at_every_replace_leaves_no_partial_first_install(self) -> None:
        labels = ("map", "inventory", "config", "receipt", "resolver")
        for failing_label in labels:
            with self.subTest(failing_label=failing_label), tempfile.TemporaryDirectory() as temporary:
                base = Path(temporary)
                paths = default_storage_paths(
                    home=base / "home",
                    local_root=base / "map",
                    private_root=base / "private",
                )

                def fail(label: str, _target: Path) -> None:
                    if label == failing_label:
                        raise RuntimeError("injected")

                with self.assertRaises(RuntimeError):
                    write_storage_bundle(
                        paths,
                        _artifacts("first"),
                        (ResolverRecord("res_fixture", ["/exact"]),),
                        failure_injector=fail,
                    )

                self.assertTrue(
                    all(
                        not path.exists()
                        for path in (
                            paths.map_path,
                            paths.inventory_path,
                            paths.config_path,
                            paths.receipt_path,
                            paths.resolver_path,
                        )
                    )
                )

    def test_rollback_never_touches_targets_that_were_not_replaced(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            paths = default_storage_paths(
                home=base / "home",
                local_root=base / "map",
                private_root=base / "private",
            )
            records = (ResolverRecord("res_fixture", ["/old"]),)
            write_storage_bundle(paths, _artifacts("old"), records)
            untouched = (paths.receipt_path, paths.resolver_path)
            untouched_before = {
                path: self._file_evidence(path) for path in untouched
            }
            concurrent_config = b'{"owner": "concurrent"}\n'

            def fail_after_first_replace(label: str, _target: Path) -> None:
                if label == "inventory":
                    paths.config_path.write_bytes(concurrent_config)
                    raise OSError("injected after concurrent change")

            with self.assertRaises(OSError):
                write_storage_bundle(
                    paths,
                    _artifacts("new"),
                    (ResolverRecord("res_fixture", ["/new"]),),
                    failure_injector=fail_after_first_replace,
                )

            self.assertEqual(paths.config_path.read_bytes(), concurrent_config)
            self.assertEqual(
                {path: self._file_evidence(path) for path in untouched},
                untouched_before,
            )

    def test_rollback_preserves_concurrent_overwrite_of_replaced_target(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            paths = default_storage_paths(
                home=base / "home",
                local_root=base / "map",
                private_root=base / "private",
            )
            records = (ResolverRecord("res_fixture", ["/old"]),)
            write_storage_bundle(paths, _artifacts("old"), records)
            old_inventory = self._file_evidence(paths.inventory_path)
            concurrent_payload = b"concurrent map owner\n"
            concurrent_evidence: tuple[int, int] | None = None

            def overwrite_map_then_fail(label: str, _target: Path) -> None:
                nonlocal concurrent_evidence
                if label != "config":
                    return
                replacement = paths.public_root / ".concurrent-map"
                replacement.write_bytes(concurrent_payload)
                os.replace(replacement, paths.map_path)
                metadata = os.lstat(paths.map_path)
                concurrent_evidence = (metadata.st_dev, metadata.st_ino)
                raise OSError("later target failed")

            with self.assertRaises(RuntimeError) as caught:
                write_storage_bundle(
                    paths,
                    _artifacts("new"),
                    (ResolverRecord("res_fixture", ["/new"]),),
                    failure_injector=overwrite_map_then_fail,
                )

            self.assertRegex(str(caught.exception), "rollback_conflict.*map")
            current = os.lstat(paths.map_path)
            self.assertEqual(paths.map_path.read_bytes(), concurrent_payload)
            self.assertEqual((current.st_dev, current.st_ino), concurrent_evidence)
            self.assertEqual(
                self._file_evidence(paths.inventory_path)[-2:], old_inventory[-2:]
            )

    def test_concurrent_target_change_aborts_before_replace_and_is_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            paths = default_storage_paths(
                home=base / "home",
                local_root=base / "map",
                private_root=base / "private",
            )
            records = (ResolverRecord("res_fixture", ["/old"]),)
            write_storage_bundle(paths, _artifacts("old"), records)
            old_map = self._file_evidence(paths.map_path)
            concurrent_inventory = b'{"owner": "concurrent"}\n'

            def change_current_target(label: str, target: Path) -> None:
                if label == "inventory":
                    target.write_bytes(concurrent_inventory)

            with self.assertRaises(RuntimeError):
                write_storage_bundle(
                    paths,
                    _artifacts("new"),
                    (ResolverRecord("res_fixture", ["/new"]),),
                    failure_injector=change_current_target,
                )

            self.assertEqual(paths.map_path.read_bytes(), old_map[-1])
            self.assertEqual(paths.inventory_path.read_bytes(), concurrent_inventory)

    def test_private_root_ancestor_swap_into_vault_is_rejected_before_public_write(self) -> None:
        if not hasattr(os, "symlink"):
            self.skipTest("symlinks unsupported")
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            vault = base / "vault"
            private_parent = base / "private-parent"
            vault.mkdir()
            private_parent.mkdir()
            paths = default_storage_paths(
                home=base / "home",
                selected_vault=vault,
                private_root=private_parent / "resolver-data",
            )
            parked_private = base / "parked-private-parent"
            private_parent.rename(parked_private)
            redirected = vault / "redirected-private"
            redirected.mkdir()
            private_parent.symlink_to(redirected, target_is_directory=True)

            with self.assertRaises(ValueError):
                write_storage_bundle(
                    paths,
                    _artifacts("must-not-write"),
                    (ResolverRecord("res_fixture", ["/exact"]),),
                )

            self.assertFalse(paths.public_root.exists())
            self.assertFalse((redirected / "resolver-data" / "capability-resolver.json").exists())
            self.assertEqual(list(parked_private.iterdir()), [])

    def test_public_root_swap_mid_update_rolls_back_via_original_physical_root(self) -> None:
        if not hasattr(os, "symlink"):
            self.skipTest("symlinks unsupported")
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            public_root = base / "public-map"
            attacker_root = base / "attacker-map"
            attacker_root.mkdir()
            paths = default_storage_paths(
                home=base / "home",
                local_root=public_root,
                private_root=base / "private",
            )
            records = (ResolverRecord("res_fixture", ["/old"]),)
            write_storage_bundle(paths, _artifacts("old"), records)
            before = _bundle_bytes(paths)
            parked_public = base / "parked-public-map"

            def swap_root_after_map(label: str, _target: Path) -> None:
                if label == "inventory":
                    public_root.rename(parked_public)
                    public_root.symlink_to(attacker_root, target_is_directory=True)

            with self.assertRaises((ValueError, RuntimeError)):
                write_storage_bundle(
                    paths,
                    _artifacts("new"),
                    (ResolverRecord("res_fixture", ["/new"]),),
                    failure_injector=swap_root_after_map,
                )

            parked_bundle = {
                parked_public / path.name: payload
                for path, payload in before.items()
                if path.parent == paths.public_root
            }
            self.assertEqual(
                {path: path.read_bytes() for path in parked_bundle}, parked_bundle
            )
            self.assertEqual(list(parked_public.glob(".capability-stage-*")), [])
            self.assertEqual(list(attacker_root.iterdir()), [])
            self.assertEqual(paths.resolver_path.read_bytes(), before[paths.resolver_path])

    def test_invalid_json_is_rejected_before_any_target_write(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            paths = default_storage_paths(home=base / "home", local_root=base / "map")
            artifacts = PublicArtifacts(
                map_markdown="# map\n",
                inventory="{invalid",
                config={},
                receipt_markdown="# receipt\n",
            )

            with self.assertRaises(ValueError):
                write_storage_bundle(paths, artifacts, ())

            self.assertFalse(paths.public_root.exists())
            self.assertFalse(paths.private_root.exists())

    def test_symlink_roots_and_targets_are_rejected_without_following(self) -> None:
        if not hasattr(os, "symlink"):
            self.skipTest("symlinks unsupported")
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            home = base / "home"
            real = base / "real"
            real.mkdir()
            linked = base / "linked"
            linked.symlink_to(real, target_is_directory=True)
            with self.assertRaises(ValueError):
                default_storage_paths(home=home, local_root=linked)
            self.assertEqual(list(real.iterdir()), [])

            paths = default_storage_paths(home=home, local_root=base / "map")
            paths.public_root.mkdir(parents=True)
            outside = base / "outside.md"
            outside.write_text("keep", encoding="utf-8")
            paths.map_path.symlink_to(outside)
            with self.assertRaises(ValueError):
                write_storage_bundle(paths, _artifacts("target"), ())
            self.assertEqual(outside.read_text(encoding="utf-8"), "keep")


if __name__ == "__main__":
    unittest.main()

"""Integration tests for the capability-map command workflow."""

from __future__ import annotations

import contextlib
import errno
import io
import json
import os
import shutil
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


PACKAGE_DIR = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = PACKAGE_DIR / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import capability_map  # noqa: E402


def _sha256(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_skill(path: Path, name: str, description: str) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "SKILL.md").write_text(
        "---\n"
        f"name: {name}\n"
        f"description: {description}\n"
        "tags: [fixture, automation]\n"
        "---\n# Fixture\n",
        encoding="utf-8",
    )


def _snapshot(root: Path) -> dict[str, tuple[str, bytes | None]]:
    if not root.exists():
        return {}
    result: dict[str, tuple[str, bytes | None]] = {}
    for item in sorted(root.rglob("*")):
        relative = str(item.relative_to(root))
        if item.is_symlink():
            result[relative] = ("symlink", os.readlink(item).encode())
        elif item.is_file():
            result[relative] = ("file", item.read_bytes())
        elif item.is_dir():
            result[relative] = ("dir", None)
    return result


class WorkflowFixture:
    def __init__(self, base: Path) -> None:
        self.base = base
        self.home = base / "home"
        self.project = base / "project"
        self.bin = base / "bin"
        self.storage = base / "能力 地图"
        self.migrated = base / "迁移 地图"
        self.extra_environ: dict[str, str] = {}
        self.home.mkdir()
        self.project.mkdir()
        self.bin.mkdir()
        (self.home / ".codex").mkdir()
        _write_skill(
            self.home / ".codex" / "skills" / "fixture-skill",
            "fixture-skill",
            "Fixture task automation and local workflow helper.",
        )
        executable = self.bin / "fixture-cli"
        executable.write_text("#!/bin/sh\necho fixture\n", encoding="utf-8")
        executable.chmod(executable.stat().st_mode | stat.S_IXUSR)
        (self.project / ".mcp.json").write_text(
            json.dumps(
                {
                    "mcpServers": {
                        "fixture-mcp": {
                            "command": "/synthetic/private/command",
                            "env": {"TOKEN": "never-public"},
                        }
                    }
                }
            ),
            encoding="utf-8",
        )
        plugin = self.home / ".codex" / "plugins" / "fixture-plugin"
        (plugin / ".codex-plugin").mkdir(parents=True)
        (plugin / ".codex-plugin" / "plugin.json").write_text(
            json.dumps(
                {
                    "name": "fixture-plugin",
                    "description": "Fixture local plugin",
                    "version": "1.0.0",
                }
            ),
            encoding="utf-8",
        )

    @property
    def environ(self) -> dict[str, str]:
        return {"PATH": str(self.bin), **self.extra_environ}

    def run(self, *argv: str) -> tuple[int, dict[str, object], str]:
        return self.run_from(self.project, *argv)

    def run_from(
        self, runtime_cwd: Path, *argv: str
    ) -> tuple[int, dict[str, object], str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        code = capability_map.main(
            list(argv),
            environ=self.environ,
            home=self.home,
            cwd=runtime_cwd,
            stdout=stdout,
            stderr=stderr,
        )
        output = stdout.getvalue()
        return code, json.loads(output) if output else {}, stderr.getvalue()

    def setup_args(self) -> tuple[str, ...]:
        return (
            "--storage",
            str(self.storage),
            "--agents",
            "both",
            "--scope",
            "project",
            "--project",
            str(self.project),
        )

    def install(self) -> dict[str, object]:
        code, plan, error = self.run("setup", "plan", *self.setup_args())
        if code != 0:
            raise AssertionError(error)
        code, receipt, error = self.run(
            "setup",
            "apply",
            *self.setup_args(),
            "--confirmed",
            "--expected-plan-hash",
            str(plan["plan_hash"]),
        )
        if code != 0:
            raise AssertionError(error)
        return receipt


class CapabilityMapEntrypointTests(unittest.TestCase):
    def test_capability_map_entrypoint_exists(self) -> None:
        self.assertTrue((SCRIPTS_DIR / "capability_map.py").is_file())

    def test_natural_language_intents_are_deterministic(self) -> None:
        cases = {
            "能力地图怎么用": "usage",
            "能力地图在哪": "paths",
            "请刷新能力地图": "refresh",
            "把能力地图迁移到新目录": "migrate",
            "卸载能力地图": "uninstall",
        }
        for query, expected in cases.items():
            with self.subTest(query=query):
                self.assertEqual(
                    capability_map.interpret_capability_map_intent(query), expected
                )


class CapabilityMapWorkflowTests(unittest.TestCase):
    def test_uninstall_refuses_corrupt_managed_block_without_mutation(self) -> None:
        for purge_data in (False, True):
            with self.subTest(purge_data=purge_data), tempfile.TemporaryDirectory() as temporary:
                fixture = WorkflowFixture(Path(temporary))
                fixture.install()
                instructions = fixture.project / "AGENTS.md"
                instructions.write_bytes(
                    instructions.read_bytes().replace(
                        b"<!-- vantasma:discover-local-capabilities:end -->", b""
                    )
                )
                before = _snapshot(fixture.base)
                dry_arguments = [
                    "uninstall",
                    "--storage",
                    str(fixture.storage),
                    "--dry-run",
                ]
                if purge_data:
                    dry_arguments.append("--purge-data")
                dry_code, dry_plan, dry_error = fixture.run(*dry_arguments)
                self.assertEqual((dry_code, dry_error), (0, ""))
                self.assertEqual(dry_plan["status"], "dry-run")
                self.assertEqual(_snapshot(fixture.base), before)

                arguments = [
                    "uninstall",
                    "--storage",
                    str(fixture.storage),
                    "--confirmed",
                ]
                if purge_data:
                    arguments.append("--purge-data")

                code, _, error = fixture.run(*arguments)

                self.assertEqual(code, 2)
                self.assertIn("instruction plan", error)
                self.assertEqual(_snapshot(fixture.base), before)

    def test_uninstall_purge_dry_run_reports_data_is_still_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = WorkflowFixture(Path(temporary))
            fixture.install()
            before = _snapshot(fixture.base)

            code, plan, error = fixture.run(
                "uninstall",
                "--storage",
                str(fixture.storage),
                "--dry-run",
                "--purge-data",
            )

            self.assertEqual((code, error), (0, ""))
            self.assertEqual(plan["status"], "dry-run")
            self.assertTrue(plan["data_preserved"])
            self.assertTrue(plan["would_purge_data"])
            self.assertEqual(_snapshot(fixture.base), before)

    def test_uninstall_lifecycle_never_reuses_an_installation_namespace(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = WorkflowFixture(Path(temporary))
            applied = fixture.install()
            old_state_path = Path(applied["paths"]["state"])
            old_installation_id = str(applied["installation_id"])

            code, uninstalled, error = fixture.run(
                "uninstall", "--storage", str(fixture.storage), "--confirmed"
            )
            self.assertEqual((code, error, uninstalled["status"]), (0, "", "uninstalled"))
            state = json.loads(old_state_path.read_text(encoding="utf-8"))
            self.assertEqual(state["status"], "uninstalled")
            self.assertFalse(state["active"])
            old_state_bytes = old_state_path.read_bytes()

            code, status, error = fixture.run(
                "status", "--storage", str(fixture.storage)
            )
            self.assertEqual((code, error), (0, ""))
            self.assertFalse(status["installed"])
            self.assertFalse(status["healthy"])
            self.assertEqual(status["lifecycle"], "uninstalled")
            self.assertEqual(status["health_errors"], [])

            for command in (
                ("refresh", "--confirmed"),
                ("migrate", "--to", str(fixture.migrated), "--confirmed"),
                ("uninstall", "--confirmed"),
            ):
                code, _, error = fixture.run(
                    command[0], "--storage", str(fixture.storage), *command[1:]
                )
                self.assertEqual(code, 2, command)
                self.assertIn("uninstalled", error)

            code, _, error = fixture.run(
                "setup",
                "plan",
                *fixture.setup_args(),
                "--installation-id",
                old_installation_id,
            )
            self.assertEqual(code, 2)
            self.assertIn("already exists", error)

            code, _, error = fixture.run("setup", "plan", *fixture.setup_args())
            self.assertEqual(code, 2)
            self.assertIn("explicit", error)
            code, plan, error = fixture.run(
                "setup",
                "plan",
                *fixture.setup_args(),
                "--installation-id",
                "inst_reinstall",
            )
            self.assertEqual((code, error), (0, ""))
            code, reinstalled, error = fixture.run(
                "setup",
                "apply",
                *fixture.setup_args(),
                "--installation-id",
                "inst_reinstall",
                "--confirmed",
                "--expected-plan-hash",
                str(plan["plan_hash"]),
            )
            self.assertEqual((code, error), (0, ""))
            self.assertNotEqual(reinstalled["installation_id"], old_installation_id)
            self.assertNotEqual(Path(reinstalled["paths"]["state"]), old_state_path)
            self.assertEqual(old_state_path.read_bytes(), old_state_bytes)

            code, _, error = fixture.run(
                "uninstall", "--storage", str(fixture.storage), "--confirmed"
            )
            self.assertEqual((code, error), (0, ""))
            code, _, error = fixture.run(
                "setup",
                "plan",
                *fixture.setup_args(),
                "--installation-id",
                old_installation_id,
            )
            self.assertEqual(code, 2)
            self.assertIn("already exists", error)
            self.assertEqual(old_state_path.read_bytes(), old_state_bytes)

    def test_purged_installation_id_history_is_never_reused(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = WorkflowFixture(Path(temporary))
            applied = fixture.install()
            old_installation_id = str(applied["installation_id"])

            code, purged, error = fixture.run(
                "uninstall",
                "--storage",
                str(fixture.storage),
                "--confirmed",
                "--purge-data",
            )
            self.assertEqual((code, error, purged["status"]), (0, "", "purged"))
            before = _snapshot(fixture.base)

            code, _, error = fixture.run(
                "setup",
                "plan",
                *fixture.setup_args(),
                "--installation-id",
                old_installation_id,
            )
            self.assertEqual(code, 2)
            self.assertIn("already", error)
            self.assertEqual(_snapshot(fixture.base), before)

            code, plan, error = fixture.run(
                "setup", "plan", *fixture.setup_args()
            )
            self.assertEqual((code, error), (0, ""))
            self.assertNotEqual(plan["installation_id"], old_installation_id)
            self.assertEqual(_snapshot(fixture.base), before)

    def test_recovery_history_matches_only_an_exact_installation_id(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = WorkflowFixture(Path(temporary))
            setup_args = (
                *fixture.setup_args(),
                "--installation-id",
                "inst_alpha-beta",
            )
            code, plan, error = fixture.run("setup", "plan", *setup_args)
            self.assertEqual((code, error), (0, ""))
            code, _, error = fixture.run(
                "setup",
                "apply",
                *setup_args,
                "--confirmed",
                "--expected-plan-hash",
                str(plan["plan_hash"]),
            )
            self.assertEqual((code, error), (0, ""))
            code, _, error = fixture.run(
                "uninstall",
                "--storage",
                str(fixture.storage),
                "--confirmed",
                "--purge-data",
            )
            self.assertEqual((code, error), (0, ""))
            before = _snapshot(fixture.base)

            code, plan, error = fixture.run(
                "setup",
                "plan",
                *fixture.setup_args(),
                "--installation-id",
                "inst_alpha",
            )

            self.assertEqual((code, error), (0, ""))
            self.assertEqual(plan["installation_id"], "inst_alpha")
            self.assertEqual(_snapshot(fixture.base), before)

    def test_installation_history_uses_storage_root_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = WorkflowFixture(Path(temporary))
            applied = fixture.install()
            code, _, error = fixture.run(
                "uninstall",
                "--storage",
                str(fixture.storage),
                "--confirmed",
                "--purge-data",
            )
            self.assertEqual((code, error), (0, ""))
            private_base = Path(applied["paths"]["state"]).parent.parent.parent
            parked_base = private_base.parent / "parked-history-root"
            real_installation_id = capability_map._installation_id
            swapped: dict[str, object] = {}

            def swap_then_select(*args: object, **kwargs: object) -> str:
                if not swapped:
                    os.rename(private_base, parked_base)
                    shutil.copytree(parked_base, private_base)
                    swapped["parked"] = _snapshot(parked_base)
                    swapped["replacement"] = _snapshot(private_base)
                    swapped["parked_inode"] = os.lstat(parked_base).st_ino
                    swapped["replacement_inode"] = os.lstat(private_base).st_ino
                return real_installation_id(*args, **kwargs)

            with mock.patch(
                "capability_map._installation_id", side_effect=swap_then_select
            ):
                code, _, error = fixture.run(
                    "setup", "plan", *fixture.setup_args()
                )

            self.assertEqual(code, 2)
            self.assertIn("history", error)
            self.assertEqual(os.lstat(parked_base).st_ino, swapped["parked_inode"])
            self.assertEqual(
                os.lstat(private_base).st_ino, swapped["replacement_inode"]
            )
            self.assertEqual(_snapshot(parked_base), swapped["parked"])
            self.assertEqual(_snapshot(private_base), swapped["replacement"])

    def test_installation_history_refuses_root_restored_after_missing_capture(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = WorkflowFixture(Path(temporary))
            setup_args = (
                *fixture.setup_args(),
                "--installation-id",
                "inst_restored_history",
            )
            code, plan, error = fixture.run("setup", "plan", *setup_args)
            self.assertEqual((code, error), (0, ""))
            code, applied, error = fixture.run(
                "setup",
                "apply",
                *setup_args,
                "--confirmed",
                "--expected-plan-hash",
                str(plan["plan_hash"]),
            )
            self.assertEqual((code, error), (0, ""))
            code, _, error = fixture.run(
                "uninstall",
                "--storage",
                str(fixture.storage),
                "--confirmed",
                "--purge-data",
            )
            self.assertEqual((code, error), (0, ""))
            private_base = Path(applied["paths"]["state"]).parent.parent.parent
            parked_base = private_base.parent / "parked-before-storage-paths"
            original_inode = os.lstat(private_base).st_ino
            original_snapshot = _snapshot(private_base)
            real_storage_paths = capability_map._storage_paths
            captured_missing = False

            def storage_paths_while_parked(*args: object, **kwargs: object) -> object:
                nonlocal captured_missing
                if captured_missing:
                    return real_storage_paths(*args, **kwargs)
                captured_missing = True
                os.rename(private_base, parked_base)
                try:
                    paths = real_storage_paths(*args, **kwargs)
                finally:
                    os.rename(parked_base, private_base)
                return paths

            with mock.patch(
                "capability_map._storage_paths", side_effect=storage_paths_while_parked
            ):
                code, _, error = fixture.run(
                    "setup",
                    "plan",
                    *fixture.setup_args(),
                    "--installation-id",
                    "inst_restored_history",
                )

            self.assertEqual(code, 2)
            self.assertIn("history", error)
            self.assertEqual(os.lstat(private_base).st_ino, original_inode)
            self.assertEqual(_snapshot(private_base), original_snapshot)

    def test_installation_history_scan_is_bounded_and_closes_iterator(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = WorkflowFixture(Path(temporary))
            fixture.install()
            code, _, error = fixture.run(
                "uninstall",
                "--storage",
                str(fixture.storage),
                "--confirmed",
                "--purge-data",
            )
            self.assertEqual((code, error), (0, ""))
            real_scandir = os.scandir
            observed = {"yielded": 0, "closed": False}

            class Entry:
                def __init__(self, name: str) -> None:
                    self.name = name

            class Entries:
                def __enter__(self) -> "Entries":
                    return self

                def __exit__(self, *args: object) -> None:
                    observed["closed"] = True

                def __iter__(self) -> "Entries":
                    return self

                def __next__(self) -> Entry:
                    observed["yielded"] += 1
                    return Entry(f"history-{observed['yielded']}")

            def bounded_scandir(path: object) -> object:
                if isinstance(path, int):
                    return Entries()
                return real_scandir(path)

            fake_scandir = mock.Mock(side_effect=bounded_scandir)
            supported = set(os.supports_fd)
            supported.add(fake_scandir)
            before = _snapshot(fixture.base)
            with mock.patch("capability_map.os.scandir", fake_scandir), mock.patch.object(
                capability_map.os, "supports_fd", supported
            ), mock.patch(
                "capability_map._scan",
                side_effect=capability_map.WorkflowError(
                    "installation history scan did not fail closed"
                ),
            ):
                code, _, error = fixture.run(
                    "setup", "plan", *fixture.setup_args()
                )

            self.assertEqual(code, 2)
            self.assertIn("too large", error)
            self.assertEqual(observed["yielded"], 4097)
            self.assertTrue(observed["closed"])
            self.assertEqual(_snapshot(fixture.base), before)

    def test_setup_fails_closed_when_purge_history_is_a_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = WorkflowFixture(Path(temporary))
            applied = fixture.install()
            old_installation_id = str(applied["installation_id"])
            code, _, error = fixture.run(
                "uninstall",
                "--storage",
                str(fixture.storage),
                "--confirmed",
                "--purge-data",
            )
            self.assertEqual((code, error), (0, ""))
            private_base = Path(applied["paths"]["state"]).parent.parent.parent
            recovery = private_base / "purge-recovery"
            parked = private_base / "parked-purge-history"
            os.rename(recovery, parked)
            os.symlink(parked, recovery)
            before = _snapshot(fixture.base)

            code, _, error = fixture.run(
                "setup",
                "plan",
                *fixture.setup_args(),
                "--installation-id",
                old_installation_id,
            )

            self.assertEqual(code, 2)
            self.assertIn("history", error)
            self.assertEqual(_snapshot(fixture.base), before)

    def test_uninstalled_and_direct_purge_move_complete_owned_namespace(self) -> None:
        for direct in (False, True):
            with self.subTest(direct=direct), tempfile.TemporaryDirectory() as temporary:
                fixture = WorkflowFixture(Path(temporary))
                applied = fixture.install()
                paths = {key: Path(value) for key, value in applied["paths"].items()
                         if key in {"map", "inventory", "config", "receipt", "resolver", "state"}}
                namespace = paths["state"].parent
                unrelated_private = namespace.parent / "other-namespace"
                unrelated_private.mkdir()
                (unrelated_private / "keep.txt").write_text("keep", encoding="utf-8")
                user_public = fixture.storage / "user-note.txt"
                user_public.write_text("keep", encoding="utf-8")
                if not direct:
                    code, _, error = fixture.run(
                        "uninstall", "--storage", str(fixture.storage), "--confirmed"
                    )
                    self.assertEqual((code, error), (0, ""))

                code, purged, error = fixture.run(
                    "uninstall",
                    "--storage",
                    str(fixture.storage),
                    "--confirmed",
                    "--purge-data",
                )
                self.assertEqual((code, error, purged["status"]), (0, "", "purged"))
                recovery = Path(purged["recovery_directory"])
                self.assertTrue(recovery.is_dir())
                self.assertFalse(namespace.exists())
                self.assertTrue((unrelated_private / "keep.txt").is_file())
                self.assertEqual(user_public.read_text(encoding="utf-8"), "keep")
                for path in paths.values():
                    self.assertFalse(path.exists())
                recovered_names = {item.name for item in recovery.rglob("*")}
                for required in (
                    "本机能力地图.md",
                    "capability-inventory.json",
                    "capability-map.config.json",
                    "setup-receipt.md",
                    "capability-resolver.json",
                    "installation-state.json",
                    "instruction-backups",
                    "state-backups",
                ):
                    self.assertIn(required, recovered_names)

    def test_purge_preserves_external_public_overwrite_and_restores_install(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = WorkflowFixture(Path(temporary))
            applied = fixture.install()
            map_path = Path(applied["paths"]["map"])
            namespace = Path(applied["paths"]["state"]).parent
            real_purge = capability_map._purge_data

            def external_then_purge(*args: object, **kwargs: object) -> object:
                map_path.write_text("external purge owner\n", encoding="utf-8")
                return real_purge(*args, **kwargs)

            with mock.patch("capability_map._purge_data", side_effect=external_then_purge):
                code, _, error = fixture.run(
                    "uninstall",
                    "--storage",
                    str(fixture.storage),
                    "--confirmed",
                    "--purge-data",
                )
            self.assertEqual(code, 3)
            self.assertIn("purge_conflict", error)
            self.assertEqual(
                map_path.read_text(encoding="utf-8"), "external purge owner\n"
            )
            self.assertTrue(namespace.is_dir())
            self.assertIn(
                "vantasma:discover-local-capabilities:start",
                (fixture.project / "AGENTS.md").read_text(encoding="utf-8"),
            )

    def test_cross_filesystem_purge_is_explicit_and_fully_compensated(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = WorkflowFixture(Path(temporary))
            applied = fixture.install()
            owned_paths = {
                label: Path(path)
                for label, path in applied["paths"].items()
                if label in {"map", "inventory", "config", "receipt", "resolver", "state"}
            }
            owned_before = {
                label: (path.read_bytes(), stat.S_IMODE(os.lstat(path).st_mode))
                for label, path in owned_paths.items()
            }
            instruction_paths = tuple(
                Path(path) for path in applied["paths"]["instruction_targets"]
            )
            instructions_before = {
                path: (path.read_bytes(), stat.S_IMODE(os.lstat(path).st_mode))
                for path in instruction_paths
            }
            private_base = owned_paths["state"].parent.parent.parent
            real_purge = capability_map._purge_data
            real_link = capability_map.os.link
            link_calls = 0

            def purge_with_exdev(*args: object, **kwargs: object) -> object:
                def injected_link(
                    source: object,
                    destination: object,
                    *,
                    src_dir_fd: int | None = None,
                    dst_dir_fd: int | None = None,
                    follow_symlinks: bool = True,
                ) -> None:
                    nonlocal link_calls
                    link_calls += 1
                    if link_calls == 2:
                        raise OSError(
                            errno.EXDEV,
                            "synthetic cross-device failure",
                            str(fixture.base / "must-not-leak"),
                        )
                    real_link(
                        source,
                        destination,
                        src_dir_fd=src_dir_fd,
                        dst_dir_fd=dst_dir_fd,
                        follow_symlinks=follow_symlinks,
                    )

                with mock.patch("capability_map.os.link", side_effect=injected_link):
                    return real_purge(*args, **kwargs)

            with mock.patch(
                "capability_map._purge_data", side_effect=purge_with_exdev
            ):
                code, _, error = fixture.run(
                    "uninstall",
                    "--storage",
                    str(fixture.storage),
                    "--confirmed",
                    "--purge-data",
                )

            self.assertEqual(code, 3)
            self.assertEqual(
                error.strip(),
                "cross-filesystem purge is unsupported; migrate public storage "
                "to the private recovery filesystem before purge",
            )
            self.assertNotIn(str(fixture.base), error)
            self.assertEqual(link_calls, 3)
            for label, path in owned_paths.items():
                self.assertEqual(
                    (path.read_bytes(), stat.S_IMODE(os.lstat(path).st_mode)),
                    owned_before[label],
                )
            for path, expected in instructions_before.items():
                self.assertEqual(
                    (path.read_bytes(), stat.S_IMODE(os.lstat(path).st_mode)),
                    expected,
                )
            self.assertFalse((private_base / "purge-recovery").exists())

    def test_purge_preserves_external_namespace_replacement(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = WorkflowFixture(Path(temporary))
            applied = fixture.install()
            namespace = Path(applied["paths"]["state"]).parent
            real_rename = capability_map._rename_directory_no_replace
            replaced = False

            def replace_namespace(
                source: object,
                destination: object,
                *,
                src_dir_fd: int | None = None,
                dst_dir_fd: int | None = None,
            ) -> None:
                nonlocal replaced
                real_rename(
                    source,
                    destination,
                    src_dir_fd=src_dir_fd,
                    dst_dir_fd=dst_dir_fd,
                )
                if not replaced and Path(source).name == namespace.name:
                    replaced = True
                    os.symlink("external-owner", namespace)

            with mock.patch(
                "capability_map._rename_directory_no_replace",
                side_effect=replace_namespace,
            ):
                code, _, error = fixture.run(
                    "uninstall",
                    "--storage",
                    str(fixture.storage),
                    "--confirmed",
                    "--purge-data",
                )
            self.assertEqual(code, 3)
            self.assertIn("purge_conflict", error)
            self.assertTrue(namespace.is_symlink())
            self.assertEqual(os.readlink(namespace), "external-owner")

    def test_purge_compensation_preserves_raced_namespace_destination(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = WorkflowFixture(Path(temporary))
            applied = fixture.install()
            namespace = Path(applied["paths"]["state"]).parent
            real_rename = capability_map._rename_directory_no_replace
            replacement: dict[str, object] = {}

            def move_then_precreate(
                source: object,
                destination: object,
                *,
                src_dir_fd: int | None = None,
                dst_dir_fd: int | None = None,
            ) -> None:
                real_rename(
                    source,
                    destination,
                    src_dir_fd=src_dir_fd,
                    dst_dir_fd=dst_dir_fd,
                )
                if not replacement and Path(source).name == namespace.name:
                    namespace.mkdir(mode=0o700)
                    (namespace / "external.txt").write_text(
                        "external namespace owner", encoding="utf-8"
                    )
                    replacement["inode"] = os.lstat(namespace).st_ino
                    replacement["snapshot"] = _snapshot(namespace)

            with mock.patch(
                "capability_map._rename_directory_no_replace",
                side_effect=move_then_precreate,
            ):
                code, _, error = fixture.run(
                    "uninstall",
                    "--storage",
                    str(fixture.storage),
                    "--confirmed",
                    "--purge-data",
                )

            self.assertEqual(code, 3)
            self.assertIn("compensation_conflict: instructions", error)
            self.assertEqual(os.lstat(namespace).st_ino, replacement["inode"])
            self.assertEqual(_snapshot(namespace), replacement["snapshot"])
            self.assertNotIn(
                "vantasma:discover-local-capabilities:start",
                (fixture.project / "AGENTS.md").read_text(encoding="utf-8"),
            )

    def test_purge_recovery_ancestry_and_destination_are_no_clobber(self) -> None:
        for attack in (
            "symlink",
            "ancestor-swap",
            "pinned-ancestor-swap",
            "destination",
        ):
            with self.subTest(attack=attack), tempfile.TemporaryDirectory() as temporary:
                fixture = WorkflowFixture(Path(temporary))
                applied = fixture.install()
                state_path = Path(applied["paths"]["state"])
                namespace = state_path.parent
                private_base = namespace.parent.parent
                attacker = fixture.base / "attacker-recovery"
                attacker.mkdir()
                canary = attacker / "keep.txt"
                canary.write_text("external recovery owner", encoding="utf-8")
                attacker_before = _snapshot(attacker)
                attacker_inode = os.lstat(attacker).st_ino
                recovery_parent = private_base / "purge-recovery"
                patcher = contextlib.nullcontext()

                if attack == "symlink":
                    os.symlink(attacker, recovery_parent)
                elif attack == "destination":
                    context = capability_map._runtime_context(
                        capability_map._storage_paths(
                            storage=str(fixture.storage),
                            vault=None,
                            home=fixture.home,
                            cwd=fixture.project,
                            environ=fixture.environ,
                        ),
                        home=fixture.home,
                        environ=fixture.environ,
                    )
                    recovery_name = str(applied["installation_id"]) + "-" + capability_map._digest(
                        capability_map._current_storage_state(
                            context.paths, state_path=context.state_path
                        )
                    )[:16]
                    destination = recovery_parent / recovery_name
                    destination.mkdir(parents=True)
                    (destination / "external.txt").write_text(
                        "external destination owner", encoding="utf-8"
                    )
                else:
                    real_mkdir = os.mkdir
                    swapped = False
                    swap_trigger = (
                        "public"
                        if attack == "pinned-ancestor-swap"
                        else "purge-recovery"
                    )

                    def mkdir_then_swap(
                        path: object,
                        mode: int = 0o777,
                        *,
                        dir_fd: int | None = None,
                    ) -> None:
                        nonlocal swapped
                        real_mkdir(path, mode, dir_fd=dir_fd)
                        if not swapped and Path(path).name == swap_trigger:
                            swapped = True
                            os.rename(recovery_parent, private_base / "swapped-recovery")
                            os.symlink(attacker, recovery_parent)

                    patcher = mock.patch(
                        "capability_map.os.mkdir", side_effect=mkdir_then_swap
                    )

                with patcher:
                    code, _, error = fixture.run(
                        "uninstall",
                        "--storage",
                        str(fixture.storage),
                        "--confirmed",
                        "--purge-data",
                    )

                self.assertEqual(code, 3)
                self.assertIn("purge", error)
                self.assertEqual(os.lstat(attacker).st_ino, attacker_inode)
                self.assertEqual(_snapshot(attacker), attacker_before)
                self.assertTrue(state_path.is_file())

    def test_purge_rejects_private_base_swap_after_instruction_removal(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = WorkflowFixture(Path(temporary))
            applied = fixture.install()
            state_path = Path(applied["paths"]["state"])
            namespace = state_path.parent
            private_base = namespace.parent.parent
            parked_base = private_base.parent / "parked-private-base"
            original_state = state_path.read_bytes()
            real_apply = capability_map.apply_instruction_plan
            swap_evidence: dict[str, int] = {}
            replacement_snapshot: dict[str, tuple[str, bytes | None]] = {}

            def apply_then_swap(*args: object, **kwargs: object) -> object:
                result = real_apply(*args, **kwargs)
                plan = args[0]
                if getattr(plan, "action", None) == "uninstall" and not swap_evidence:
                    os.rename(private_base, parked_base)
                    shutil.copytree(parked_base, private_base)
                    parked_namespace = parked_base / "installations" / namespace.name
                    replacement_namespace = (
                        private_base / "installations" / namespace.name
                    )
                    swap_evidence["parked"] = os.lstat(parked_namespace).st_ino
                    swap_evidence["replacement"] = os.lstat(
                        replacement_namespace
                    ).st_ino
                    replacement_snapshot.update(_snapshot(replacement_namespace))
                return result

            with mock.patch(
                "capability_map.apply_instruction_plan", side_effect=apply_then_swap
            ):
                code, _, error = fixture.run(
                    "uninstall",
                    "--storage",
                    str(fixture.storage),
                    "--confirmed",
                    "--purge-data",
                )

            parked_namespace = parked_base / "installations" / namespace.name
            replacement_namespace = private_base / "installations" / namespace.name
            self.assertEqual(code, 3)
            self.assertIn("compensation_conflict: instructions", error)
            self.assertEqual(os.lstat(parked_namespace).st_ino, swap_evidence["parked"])
            self.assertEqual(
                os.lstat(replacement_namespace).st_ino,
                swap_evidence["replacement"],
            )
            self.assertEqual(
                (parked_namespace / "installation-state.json").read_bytes(),
                original_state,
            )
            self.assertEqual(
                (replacement_namespace / "installation-state.json").read_bytes(),
                original_state,
            )
            self.assertEqual(_snapshot(replacement_namespace), replacement_snapshot)
            self.assertNotIn(
                "vantasma:discover-local-capabilities:start",
                (fixture.project / "AGENTS.md").read_text(encoding="utf-8"),
            )

    def test_purge_rejects_namespace_only_swap_after_instruction_removal(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = WorkflowFixture(Path(temporary))
            applied = fixture.install()
            namespace = Path(applied["paths"]["state"]).parent
            parked_namespace = namespace.parent / "parked-installation-namespace"
            real_apply = capability_map.apply_instruction_plan
            swapped: dict[str, object] = {}

            def apply_then_swap(*args: object, **kwargs: object) -> object:
                result = real_apply(*args, **kwargs)
                plan = args[0]
                if getattr(plan, "action", None) == "uninstall" and not swapped:
                    os.rename(namespace, parked_namespace)
                    shutil.copytree(parked_namespace, namespace)
                    swapped["parked_inode"] = os.lstat(parked_namespace).st_ino
                    swapped["replacement_inode"] = os.lstat(namespace).st_ino
                    swapped["parked"] = _snapshot(parked_namespace)
                    swapped["replacement"] = _snapshot(namespace)
                return result

            with mock.patch(
                "capability_map.apply_instruction_plan", side_effect=apply_then_swap
            ):
                code, _, error = fixture.run(
                    "uninstall",
                    "--storage",
                    str(fixture.storage),
                    "--confirmed",
                    "--purge-data",
                )

            self.assertEqual(code, 3)
            self.assertIn("compensation_conflict: instructions", error)
            self.assertEqual(
                os.lstat(parked_namespace).st_ino, swapped["parked_inode"]
            )
            self.assertEqual(os.lstat(namespace).st_ino, swapped["replacement_inode"])
            self.assertEqual(_snapshot(parked_namespace), swapped["parked"])
            self.assertEqual(_snapshot(namespace), swapped["replacement"])
            self.assertNotIn(
                "vantasma:discover-local-capabilities:start",
                (fixture.project / "AGENTS.md").read_text(encoding="utf-8"),
            )

    def test_purge_rejects_namespace_swap_after_state_read(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = WorkflowFixture(Path(temporary))
            applied = fixture.install()
            namespace = Path(applied["paths"]["state"]).parent
            parked_namespace = namespace.parent / "parked-after-state-read"
            real_runtime = capability_map._runtime_context
            swapped: dict[str, object] = {}

            def runtime_then_swap(*args: object, **kwargs: object) -> object:
                context = real_runtime(*args, **kwargs)
                if not swapped:
                    os.rename(namespace, parked_namespace)
                    shutil.copytree(parked_namespace, namespace)
                    swapped["parked_inode"] = os.lstat(parked_namespace).st_ino
                    swapped["replacement_inode"] = os.lstat(namespace).st_ino
                    swapped["parked"] = _snapshot(parked_namespace)
                    swapped["replacement"] = _snapshot(namespace)
                return context

            with mock.patch(
                "capability_map._runtime_context", side_effect=runtime_then_swap
            ):
                code, _, error = fixture.run(
                    "uninstall",
                    "--storage",
                    str(fixture.storage),
                    "--confirmed",
                    "--purge-data",
                )

            self.assertEqual(code, 3)
            self.assertIn("namespace", error)
            self.assertEqual(
                os.lstat(parked_namespace).st_ino, swapped["parked_inode"]
            )
            self.assertEqual(os.lstat(namespace).st_ino, swapped["replacement_inode"])
            self.assertEqual(_snapshot(parked_namespace), swapped["parked"])
            self.assertEqual(_snapshot(namespace), swapped["replacement"])
            self.assertIn(
                "vantasma:discover-local-capabilities:start",
                (fixture.project / "AGENTS.md").read_text(encoding="utf-8"),
            )

    def test_purge_rolls_back_actual_substituted_namespace(self) -> None:
        for occupy_source in (False, True):
            with self.subTest(occupy_source=occupy_source), tempfile.TemporaryDirectory() as temporary:
                fixture = WorkflowFixture(Path(temporary))
                applied = fixture.install()
                namespace = Path(applied["paths"]["state"]).parent
                parked_namespace = namespace.parent / "parked-before-native-rename"
                real_rename = capability_map._rename_directory_no_replace
                moved: dict[str, object] = {}

                def substitute_then_rename(
                    source: object,
                    destination: object,
                    *,
                    src_dir_fd: int | None = None,
                    dst_dir_fd: int | None = None,
                ) -> None:
                    if not moved and Path(source).name == namespace.name:
                        os.rename(namespace, parked_namespace)
                        shutil.copytree(parked_namespace, namespace)
                        moved["parked_inode"] = os.lstat(parked_namespace).st_ino
                        moved["replacement_inode"] = os.lstat(namespace).st_ino
                        moved["parked"] = _snapshot(parked_namespace)
                        moved["replacement"] = _snapshot(namespace)
                        real_rename(
                            source,
                            destination,
                            src_dir_fd=src_dir_fd,
                            dst_dir_fd=dst_dir_fd,
                        )
                        if occupy_source:
                            namespace.mkdir(mode=0o700)
                            (namespace / "external.txt").write_text(
                                "external source owner", encoding="utf-8"
                            )
                            moved["external_inode"] = os.lstat(namespace).st_ino
                            moved["external"] = _snapshot(namespace)
                        return
                    real_rename(
                        source,
                        destination,
                        src_dir_fd=src_dir_fd,
                        dst_dir_fd=dst_dir_fd,
                    )

                with mock.patch(
                    "capability_map._rename_directory_no_replace",
                    side_effect=substitute_then_rename,
                ):
                    code, _, error = fixture.run(
                        "uninstall",
                        "--storage",
                        str(fixture.storage),
                        "--confirmed",
                        "--purge-data",
                    )

                self.assertEqual(code, 3)
                self.assertIn("purge_conflict", error)
                self.assertIn("compensation_conflict: instructions", error)
                self.assertEqual(
                    os.lstat(parked_namespace).st_ino, moved["parked_inode"]
                )
                self.assertEqual(_snapshot(parked_namespace), moved["parked"])
                if occupy_source:
                    self.assertIn("recovery", error)
                    self.assertEqual(
                        os.lstat(namespace).st_ino, moved["external_inode"]
                    )
                    self.assertEqual(_snapshot(namespace), moved["external"])
                    recovery_names = tuple(
                        namespace.parent.parent.glob(
                            "purge-recovery/*/private-namespace"
                        )
                    )
                    self.assertEqual(len(recovery_names), 1)
                    self.assertEqual(
                        os.lstat(recovery_names[0]).st_ino,
                        moved["replacement_inode"],
                    )
                    self.assertEqual(
                        _snapshot(recovery_names[0]), moved["replacement"]
                    )
                else:
                    self.assertEqual(
                        os.lstat(namespace).st_ino, moved["replacement_inode"]
                    )
                    self.assertEqual(_snapshot(namespace), moved["replacement"])
                    self.assertFalse(
                        tuple(
                            namespace.parent.parent.glob(
                                "purge-recovery/*/private-namespace"
                            )
                        )
                    )

    def test_compensation_builder_reuses_original_backup_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = WorkflowFixture(Path(temporary))
            applied = fixture.install()
            namespace = Path(applied["paths"]["state"]).parent
            parked_namespace = namespace.parent / "parked-before-compensation-build"
            real_build = capability_map.build_instruction_plan
            swapped: dict[str, object] = {}
            evidence_was_passed = False

            def fail_purge(*args: object, **kwargs: object) -> object:
                raise capability_map.WorkflowError("forced purge failure")

            def swap_then_build(*args: object, **kwargs: object) -> object:
                nonlocal evidence_was_passed
                evidence_was_passed = kwargs.get("backup_root_evidence") is not None
                if not swapped:
                    os.rename(namespace, parked_namespace)
                    shutil.copytree(parked_namespace, namespace)
                    swapped["parked_inode"] = os.lstat(parked_namespace).st_ino
                    swapped["replacement_inode"] = os.lstat(namespace).st_ino
                    swapped["parked"] = _snapshot(parked_namespace)
                    swapped["replacement"] = _snapshot(namespace)
                return real_build(*args, **kwargs)

            with mock.patch("capability_map._purge_data", side_effect=fail_purge), mock.patch(
                "capability_map.build_instruction_plan", side_effect=swap_then_build
            ):
                code, _, error = fixture.run(
                    "uninstall",
                    "--storage",
                    str(fixture.storage),
                    "--confirmed",
                    "--purge-data",
                )

            self.assertEqual(code, 3)
            self.assertIn("compensation_conflict: instructions", error)
            self.assertTrue(evidence_was_passed)
            self.assertEqual(
                os.lstat(parked_namespace).st_ino, swapped["parked_inode"]
            )
            self.assertEqual(os.lstat(namespace).st_ino, swapped["replacement_inode"])
            self.assertEqual(_snapshot(parked_namespace), swapped["parked"])
            self.assertEqual(_snapshot(namespace), swapped["replacement"])
            self.assertNotIn(
                "vantasma:discover-local-capabilities:start",
                (fixture.project / "AGENTS.md").read_text(encoding="utf-8"),
            )

    def test_purge_rejects_private_base_swap_after_state_read(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = WorkflowFixture(Path(temporary))
            applied = fixture.install()
            state_path = Path(applied["paths"]["state"])
            namespace = state_path.parent
            private_base = namespace.parent.parent
            parked_base = private_base.parent / "parked-after-state-read"
            real_runtime = capability_map._runtime_context
            swapped: dict[str, object] = {}

            def runtime_then_swap(*args: object, **kwargs: object) -> object:
                context = real_runtime(*args, **kwargs)
                if not swapped:
                    os.rename(private_base, parked_base)
                    shutil.copytree(parked_base, private_base)
                    parked_namespace = parked_base / "installations" / namespace.name
                    replacement_namespace = private_base / "installations" / namespace.name
                    swapped["parked_inode"] = os.lstat(parked_namespace).st_ino
                    swapped["replacement_inode"] = os.lstat(replacement_namespace).st_ino
                    swapped["parked"] = _snapshot(parked_namespace)
                    swapped["replacement"] = _snapshot(replacement_namespace)
                return context

            with mock.patch(
                "capability_map._runtime_context", side_effect=runtime_then_swap
            ):
                code, _, error = fixture.run(
                    "uninstall",
                    "--storage",
                    str(fixture.storage),
                    "--confirmed",
                    "--purge-data",
                )

            parked_namespace = parked_base / "installations" / namespace.name
            replacement_namespace = private_base / "installations" / namespace.name
            self.assertEqual(code, 3)
            self.assertIn("private base", error)
            self.assertEqual(
                os.lstat(parked_namespace).st_ino, swapped["parked_inode"]
            )
            self.assertEqual(
                os.lstat(replacement_namespace).st_ino,
                swapped["replacement_inode"],
            )
            self.assertEqual(_snapshot(parked_namespace), swapped["parked"])
            self.assertEqual(_snapshot(replacement_namespace), swapped["replacement"])
            self.assertIn(
                "vantasma:discover-local-capabilities:start",
                (fixture.project / "AGENTS.md").read_text(encoding="utf-8"),
            )

    def test_purge_namespace_move_is_atomic_no_clobber(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = WorkflowFixture(Path(temporary))
            applied = fixture.install()
            state_path = Path(applied["paths"]["state"])
            private_base = state_path.parent.parent.parent
            real_rename = capability_map._rename_directory_no_replace
            external_inode: list[int] = []

            def race_destination(
                source: str,
                destination: str,
                *,
                src_dir_fd: int,
                dst_dir_fd: int,
            ) -> None:
                if destination == "private-namespace" and not external_inode:
                    os.mkdir(destination, dir_fd=dst_dir_fd)
                    external_inode.append(
                        os.stat(
                            destination,
                            dir_fd=dst_dir_fd,
                            follow_symlinks=False,
                        ).st_ino
                    )
                real_rename(
                    source,
                    destination,
                    src_dir_fd=src_dir_fd,
                    dst_dir_fd=dst_dir_fd,
                )

            with mock.patch(
                "capability_map._rename_directory_no_replace",
                side_effect=race_destination,
            ):
                code, _, error = fixture.run(
                    "uninstall",
                    "--storage",
                    str(fixture.storage),
                    "--confirmed",
                    "--purge-data",
                )

            raced = tuple(
                (private_base / "purge-recovery").glob(
                    "*/private-namespace"
                )
            )
            self.assertEqual(code, 3)
            self.assertIn("purge", error)
            self.assertEqual(len(raced), 1)
            self.assertEqual(os.lstat(raced[0]).st_ino, external_inode[0])
            self.assertTrue(state_path.is_file())
            self.assertIn(
                "vantasma:discover-local-capabilities:start",
                (fixture.project / "AGENTS.md").read_text(encoding="utf-8"),
            )

    def test_purge_directory_open_closes_fd_when_fstat_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = WorkflowFixture(Path(temporary))
            applied = fixture.install()
            state_path = Path(applied["paths"]["state"])
            real_open = os.open
            real_fstat = os.fstat
            opened_recovery: list[int] = []

            def track_open(
                path: object,
                flags: int,
                mode: int = 0o777,
                *,
                dir_fd: int | None = None,
            ) -> int:
                descriptor = real_open(path, flags, mode, dir_fd=dir_fd)
                if Path(path).name == "purge-recovery":
                    opened_recovery.append(descriptor)
                return descriptor

            def fail_recovery_fstat(descriptor: int) -> os.stat_result:
                if opened_recovery and descriptor == opened_recovery[0]:
                    raise OSError("synthetic recovery fstat failure")
                return real_fstat(descriptor)

            with (
                mock.patch("capability_map.os.open", side_effect=track_open),
                mock.patch("capability_map.os.fstat", side_effect=fail_recovery_fstat),
            ):
                code, _, error = fixture.run(
                    "uninstall",
                    "--storage",
                    str(fixture.storage),
                    "--confirmed",
                    "--purge-data",
                )

            self.assertEqual(code, 3)
            self.assertIn("fstat", error)
            self.assertEqual(len(opened_recovery), 1)
            descriptor_closed = False
            try:
                real_fstat(opened_recovery[0])
            except OSError:
                descriptor_closed = True
            finally:
                if not descriptor_closed:
                    os.close(opened_recovery[0])
            self.assertTrue(descriptor_closed)
            self.assertTrue(state_path.is_file())
            self.assertIn(
                "vantasma:discover-local-capabilities:start",
                (fixture.project / "AGENTS.md").read_text(encoding="utf-8"),
            )

    def test_purge_failure_after_move_rolls_back_owned_data(self) -> None:
        for failure_target in ("map", "namespace"):
            with self.subTest(failure_target=failure_target), tempfile.TemporaryDirectory() as temporary:
                fixture = WorkflowFixture(Path(temporary))
                applied = fixture.install()
                paths = {
                    key: Path(value)
                    for key, value in applied["paths"].items()
                    if key
                    in {"map", "inventory", "config", "receipt", "resolver", "state"}
                }
                contents = {
                    label: path.read_bytes() for label, path in paths.items()
                }
                namespace = paths["state"].parent
                fail_source = paths["map"] if failure_target == "map" else namespace
                failed = False
                if failure_target == "map":
                    real_unlink = os.unlink

                    def move_then_fail(
                        source: object, *, dir_fd: int | None = None
                    ) -> None:
                        nonlocal failed
                        real_unlink(source, dir_fd=dir_fd)
                        if not failed and Path(source).name == fail_source.name:
                            failed = True
                            raise OSError("synthetic purge move failure")

                    patcher = mock.patch(
                        "capability_map.os.unlink", side_effect=move_then_fail
                    )
                else:
                    real_rename = capability_map._rename_directory_no_replace

                    def move_then_fail(
                        source: object,
                        destination: object,
                        *,
                        src_dir_fd: int | None = None,
                        dst_dir_fd: int | None = None,
                    ) -> None:
                        nonlocal failed
                        real_rename(
                            source,
                            destination,
                            src_dir_fd=src_dir_fd,
                            dst_dir_fd=dst_dir_fd,
                        )
                        if not failed and Path(source).name == fail_source.name:
                            failed = True
                            raise OSError("synthetic purge move failure")

                    patcher = mock.patch(
                        "capability_map._rename_directory_no_replace",
                        side_effect=move_then_fail,
                    )

                with patcher:
                    code, _, error = fixture.run(
                        "uninstall",
                        "--storage",
                        str(fixture.storage),
                        "--confirmed",
                        "--purge-data",
                    )
                self.assertEqual(code, 3)
                self.assertIn("synthetic purge move failure", error)
                for label, path in paths.items():
                    self.assertTrue(path.is_file(), label)
                    self.assertEqual(path.read_bytes(), contents[label], label)
                self.assertIn(
                    "vantasma:discover-local-capabilities:start",
                    (fixture.project / "AGENTS.md").read_text(encoding="utf-8"),
                )

    def test_explicit_installation_id_uses_runtime_validator_and_zero_writes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = WorkflowFixture(Path(temporary))
            before = _snapshot(fixture.base)
            code, _, error = fixture.run(
                "setup",
                "plan",
                *fixture.setup_args(),
                "--installation-id",
                "custom",
            )
            self.assertEqual(code, 2)
            self.assertIn("installation", error)
            self.assertEqual(before, _snapshot(fixture.base))

    def test_cli_apply_binds_plan_storage_state_across_writer_race(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = WorkflowFixture(Path(temporary))
            code, plan, error = fixture.run("setup", "plan", *fixture.setup_args())
            self.assertEqual((code, error), (0, ""))
            real_write = capability_map.write_storage_bundle
            map_path = Path(plan["paths"]["map"])

            def race(*args: object, **kwargs: object) -> object:
                map_path.parent.mkdir(parents=True, exist_ok=True)
                map_path.write_text("external plan-race owner\n", encoding="utf-8")
                return real_write(*args, **kwargs)

            with mock.patch("capability_map.write_storage_bundle", side_effect=race):
                code, _, error = fixture.run(
                    "setup",
                    "apply",
                    *fixture.setup_args(),
                    "--confirmed",
                    "--expected-plan-hash",
                    str(plan["plan_hash"]),
                )
            self.assertEqual(code, 3)
            self.assertIn("stale storage plan", error)
            self.assertEqual(
                map_path.read_text(encoding="utf-8"), "external plan-race owner\n"
            )

    def test_compensation_treats_external_chmod_as_conflict(self) -> None:
        if os.name == "nt":
            self.skipTest("POSIX mode semantics")
        with tempfile.TemporaryDirectory() as temporary:
            fixture = WorkflowFixture(Path(temporary))
            code, plan, error = fixture.run("setup", "plan", *fixture.setup_args())
            self.assertEqual((code, error), (0, ""))
            map_path = Path(plan["paths"]["map"])

            def chmod_then_fail(*_args: object, **_kwargs: object) -> None:
                map_path.chmod(0o600)
                raise RuntimeError("synthetic instruction failure")

            with mock.patch(
                "capability_map.apply_instruction_plan", side_effect=chmod_then_fail
            ):
                code, _, error = fixture.run(
                    "setup",
                    "apply",
                    *fixture.setup_args(),
                    "--confirmed",
                    "--expected-plan-hash",
                    str(plan["plan_hash"]),
                )
            self.assertEqual(code, 3)
            self.assertIn("compensation_conflict", error)
            self.assertTrue(map_path.is_file())
            self.assertEqual(stat.S_IMODE(map_path.stat().st_mode), 0o600)

    def test_status_reports_health_without_hiding_installed_corruption(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = WorkflowFixture(Path(temporary))
            applied = fixture.install()
            Path(applied["paths"]["inventory"]).write_text("{broken", encoding="utf-8")

            code, status, error = fixture.run(
                "status", "--storage", str(fixture.storage)
            )
            self.assertEqual((code, error), (0, ""))
            self.assertTrue(status["installed"])
            self.assertFalse(status["healthy"])
            self.assertEqual(status["lifecycle"], "active")
            self.assertTrue(
                any("inventory" in item for item in status["health_errors"])
            )

        cases = ["empty-map", "resolver-schema", "instruction-block"]
        if os.name != "nt":
            cases.append("resolver-mode")
        for case in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as temporary:
                fixture = WorkflowFixture(Path(temporary))
                applied = fixture.install()
                if case == "empty-map":
                    Path(applied["paths"]["map"]).write_bytes(b"")
                elif case == "resolver-schema":
                    resolver_path = Path(applied["paths"]["resolver"])
                    resolver = json.loads(resolver_path.read_text(encoding="utf-8"))
                    resolver["records"] = [{}]
                    resolver_path.write_text(json.dumps(resolver), encoding="utf-8")
                    resolver_path.chmod(0o600)
                elif case == "instruction-block":
                    (fixture.project / "AGENTS.md").write_text(
                        "external instructions\n", encoding="utf-8"
                    )
                else:
                    Path(applied["paths"]["resolver"]).chmod(0o644)
                code, status, error = fixture.run(
                    "status", "--storage", str(fixture.storage)
                )
                self.assertEqual((code, error), (0, ""))
                self.assertTrue(status["installed"])
                self.assertFalse(status["healthy"])
                self.assertTrue(status["health_errors"])

    def test_migrated_source_is_inactive_and_cannot_mutate_active_install(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = WorkflowFixture(Path(temporary))
            applied = fixture.install()
            old_state = Path(applied["paths"]["state"])
            code, migrated, error = fixture.run(
                "migrate",
                "--storage",
                str(fixture.storage),
                "--to",
                str(fixture.migrated),
                "--confirmed",
            )
            self.assertEqual((code, error), (0, ""))
            state = json.loads(old_state.read_text(encoding="utf-8"))
            self.assertEqual(state["status"], "migrated")
            self.assertFalse(state["active"])
            self.assertEqual(state["migrated_to_state_id"], json.loads(
                Path(migrated["paths"]["state"]).read_text(encoding="utf-8")
            )["state_id"])

            code, status, error = fixture.run(
                "status", "--storage", str(fixture.storage)
            )
            self.assertEqual((code, error), (0, ""))
            self.assertFalse(status["installed"])
            self.assertEqual(status["lifecycle"], "migrated")

            instructions_before = (fixture.project / "AGENTS.md").read_bytes()
            for command in (
                ("refresh", "--confirmed"),
                ("migrate", "--to", str(fixture.base / "third"), "--confirmed"),
                ("uninstall", "--confirmed"),
                ("uninstall", "--confirmed", "--purge-data"),
            ):
                code, _, error = fixture.run(
                    command[0], "--storage", str(fixture.storage), *command[1:]
                )
                self.assertEqual(code, 2, command)
                self.assertIn("migrated", error)
            self.assertEqual(
                (fixture.project / "AGENTS.md").read_bytes(), instructions_before
            )

        with tempfile.TemporaryDirectory() as temporary:
            fixture = WorkflowFixture(Path(temporary))
            applied = fixture.install()
            old_state_path = Path(applied["paths"]["state"])
            original_state = old_state_path.read_bytes()
            original_apply_state = capability_map._apply_state_plan

            def fail_source_state(plan: object) -> object:
                if getattr(plan, "path", None) == old_state_path:
                    raise RuntimeError("synthetic source-state failure")
                return original_apply_state(plan)

            with mock.patch(
                "capability_map._apply_state_plan", side_effect=fail_source_state
            ):
                code, _, error = fixture.run(
                    "migrate",
                    "--storage",
                    str(fixture.storage),
                    "--to",
                    str(fixture.migrated),
                    "--confirmed",
                )
            self.assertEqual(code, 3)
            self.assertIn("synthetic source-state failure", error)
            self.assertEqual(old_state_path.read_bytes(), original_state)
            self.assertTrue(json.loads(original_state)["active"])
            instructions = (fixture.project / "AGENTS.md").read_text(encoding="utf-8")
            self.assertIn(str(fixture.storage / "本机能力地图.md"), instructions)
            self.assertNotIn(str(fixture.migrated / "本机能力地图.md"), instructions)

    def test_private_runtime_state_uses_saved_targets_and_custom_codex_home(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = WorkflowFixture(Path(temporary))
            custom_codex = fixture.base / "custom codex"
            custom_codex.mkdir()
            fixture.extra_environ["CODEX_HOME"] = str(custom_codex)
            args = (
                "--storage",
                str(fixture.storage),
                "--agents",
                "codex",
                "--scope",
                "user",
                "--project",
                str(fixture.project),
            )
            code, plan, error = fixture.run("setup", "plan", *args)
            self.assertEqual((code, error), (0, ""))
            self.assertIn("state", plan["paths"])
            self.assertFalse(Path(plan["paths"]["state"]).exists())
            code, applied, error = fixture.run(
                "setup",
                "apply",
                *args,
                "--confirmed",
                "--expected-plan-hash",
                str(plan["plan_hash"]),
            )
            self.assertEqual((code, error), (0, ""))

            state_path = Path(applied["paths"]["state"])
            state = json.loads(state_path.read_text(encoding="utf-8"))
            config = json.loads(
                Path(applied["paths"]["config"]).read_text(encoding="utf-8")
            )
            self.assertEqual(stat.S_IMODE(state_path.stat().st_mode), 0o600)
            self.assertEqual(state["project_root"], str(fixture.project.resolve()))
            self.assertEqual(state["codex_home"], str(custom_codex.resolve()))
            self.assertEqual(state["public_root"], str(fixture.storage.resolve()))
            self.assertEqual(
                set(config),
                {"schema_version", "mode", "installation_id", "state_id"},
            )
            self.assertNotIn(str(fixture.project), json.dumps(config))
            self.assertTrue((custom_codex / "AGENTS.md").is_file())

            elsewhere = fixture.base / "elsewhere"
            elsewhere.mkdir()
            code, status, error = fixture.run_from(
                elsewhere, "status", "--storage", str(fixture.storage)
            )
            self.assertEqual((code, error), (0, ""))
            self.assertTrue(status["installed"])
            code, _, error = fixture.run_from(
                elsewhere,
                "uninstall",
                "--storage",
                str(fixture.storage),
                "--confirmed",
            )
            self.assertEqual((code, error), (0, ""))
            self.assertNotIn(
                "vantasma:discover-local-capabilities:start",
                (custom_codex / "AGENTS.md").read_text(encoding="utf-8"),
            )

    def test_private_namespaces_isolate_setup_scan_and_legacy_relative_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = WorkflowFixture(Path(temporary))
            installed = fixture.install()
            setup_resolver = Path(installed["paths"]["resolver"])
            setup_hash = _sha256(setup_resolver)
            scan_output = fixture.base / "scan-output"
            code, scan, error = fixture.run(
                "scan",
                "--project",
                str(fixture.project),
                "--output-dir",
                str(scan_output),
                "--confirmed",
            )
            self.assertEqual((code, error), (0, ""))
            scan_resolver = Path(scan["written"]["paths"]["resolver"])
            self.assertNotEqual(setup_resolver, scan_resolver)
            self.assertIn("installations", setup_resolver.parts)
            self.assertIn("installations", scan_resolver.parts)
            self.assertEqual(_sha256(setup_resolver), setup_hash)

        with tempfile.TemporaryDirectory() as temporary:
            fixture = WorkflowFixture(Path(temporary))
            stdout = io.StringIO()
            stderr = io.StringIO()
            import scan_capabilities

            code = scan_capabilities.main(
                ["--project", "project"],
                environ=fixture.environ,
                home=fixture.home,
                cwd=fixture.base,
                stdout=stdout,
                stderr=stderr,
            )
            self.assertEqual(code, 0, stderr.getvalue())
            written = json.loads(stdout.getvalue())["written"]["paths"]
            self.assertEqual(
                Path(written["map"]),
                (fixture.project / ".capability-map" / "本机能力地图.md").resolve(),
            )

    def test_planned_hashes_match_written_bytes_and_refresh_is_noop(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = WorkflowFixture(Path(temporary))
            code, plan, error = fixture.run("setup", "plan", *fixture.setup_args())
            self.assertEqual((code, error), (0, ""))
            code, applied, error = fixture.run(
                "setup",
                "apply",
                *fixture.setup_args(),
                "--confirmed",
                "--expected-plan-hash",
                str(plan["plan_hash"]),
            )
            self.assertEqual((code, error), (0, ""))
            for label, expected_hash in plan["desired_hashes"].items():
                self.assertEqual(_sha256(Path(plan["paths"][label])), expected_hash)

            before_repeat = _snapshot(fixture.base)
            code, _, error = fixture.run(
                "setup", "plan", *fixture.setup_args()
            )
            self.assertEqual(code, 2)
            self.assertIn("already installed", error)
            self.assertIn("refresh", error)
            code, _, error = fixture.run(
                "setup",
                "plan",
                *fixture.setup_args(),
                "--installation-id",
                "inst_second",
            )
            self.assertEqual(code, 2)
            self.assertIn("already installed", error)
            code, _, error = fixture.run(
                "setup",
                "apply",
                *fixture.setup_args(),
                "--confirmed",
                "--expected-plan-hash",
                str(plan["plan_hash"]),
            )
            self.assertEqual(code, 2)
            self.assertEqual(_snapshot(fixture.base), before_repeat)
            instructions = (fixture.project / "AGENTS.md").read_text(encoding="utf-8")
            self.assertEqual(
                instructions.count("vantasma:discover-local-capabilities:start"), 1
            )
            installation_states = tuple(
                Path(applied["paths"]["state"])
                .parent.parent.glob("*/installation-state.json")
            )
            self.assertEqual(len(installation_states), 1)

            before = _snapshot(fixture.base)
            code, refresh, error = fixture.run(
                "refresh", "--storage", str(fixture.storage), "--dry-run"
            )
            self.assertEqual((code, error), (0, ""))
            self.assertEqual(refresh["changes"], [])
            self.assertEqual(refresh["counts"]["storage_changes"], 0)
            self.assertEqual(before, _snapshot(fixture.base))
            self.assertEqual(applied["hashes"], {
                key: plan["desired_hashes"][key]
                for key in ("config", "inventory", "map", "receipt", "resolver")
            })

    def test_compensation_preserves_external_overwrite_and_reports_conflict(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = WorkflowFixture(Path(temporary))
            code, plan, error = fixture.run("setup", "plan", *fixture.setup_args())
            self.assertEqual((code, error), (0, ""))
            map_path = Path(plan["paths"]["map"])

            def external_then_fail(*_args: object, **_kwargs: object) -> None:
                map_path.write_text("external owner\n", encoding="utf-8")
                raise RuntimeError("synthetic instruction failure")

            with mock.patch(
                "capability_map.apply_instruction_plan",
                side_effect=external_then_fail,
            ):
                code, _, error = fixture.run(
                    "setup",
                    "apply",
                    *fixture.setup_args(),
                    "--confirmed",
                    "--expected-plan-hash",
                    str(plan["plan_hash"]),
                )
            self.assertEqual(code, 3)
            self.assertIn("compensation_conflict", error)
            self.assertEqual(map_path.read_text(encoding="utf-8"), "external owner\n")
            self.assertFalse((fixture.project / "AGENTS.md").exists())

    def test_public_receipt_is_complete_safe_and_apply_stdout_is_exact(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = WorkflowFixture(Path(temporary))
            applied = fixture.install()
            receipt = Path(applied["paths"]["receipt"]).read_text(encoding="utf-8")
            for fragment in (
                "本机能力地图.md",
                "capability-inventory.json",
                "capability-map.config.json",
                "setup-receipt.md",
                "skills",
                "clis",
                "mcp",
                "plugins",
                "unclassified",
                "diagnostics",
                "new session",
                "能力地图怎么用",
                "刷新能力地图",
                "迁移能力地图",
                "卸载能力地图",
                "private",
            ):
                self.assertIn(fragment, receipt)
            for exact in (
                str(fixture.base),
                str(applied["paths"]["resolver"]),
                str(applied["paths"]["state"]),
            ):
                self.assertNotIn(exact, receipt)
            self.assertTrue(Path(applied["paths"]["resolver"]).is_absolute())
            self.assertTrue(Path(applied["paths"]["state"]).is_absolute())
            self.assertIn("instruction_backup", applied["paths"])

    def test_scan_orchestrates_all_collectors_without_process_execution(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = WorkflowFixture(Path(temporary))
            with mock.patch(
                "capability_map_core.clis.subprocess.Popen",
                side_effect=AssertionError("default scan executed a CLI"),
            ), mock.patch(
                "socket.socket",
                side_effect=AssertionError("default scan opened a network socket"),
            ):
                code, payload, error = fixture.run(
                    "scan", "--project", str(fixture.project)
                )

            self.assertEqual((code, error), (0, ""))
            names = {item["name"] for item in payload["capabilities"]}
            self.assertTrue(
                {"fixture-skill", "fixture-cli", "fixture-mcp", "fixture-plugin"}
                <= names
            )
            serialized = json.dumps(payload, ensure_ascii=False)
            self.assertNotIn("never-public", serialized)
            self.assertNotIn("/synthetic/private/command", serialized)

    def test_setup_plan_is_zero_write_deterministic_and_apply_is_hash_bound(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = WorkflowFixture(Path(temporary))
            before = _snapshot(fixture.base)

            code, first, error = fixture.run(
                "setup", "plan", *fixture.setup_args()
            )
            middle = _snapshot(fixture.base)
            code2, second, error2 = fixture.run(
                "setup", "plan", *fixture.setup_args()
            )

            self.assertEqual((code, code2, error, error2), (0, 0, "", ""))
            self.assertEqual(before, middle)
            self.assertEqual(first, second)
            self.assertRegex(str(first["plan_hash"]), r"^[0-9a-f]{64}$")
            self.assertEqual(first["counts"]["capabilities"], 4)
            self.assertEqual(len(first["instruction_operations"]), 2)

            missing_code, _, missing_error = fixture.run(
                "setup",
                "apply",
                *fixture.setup_args(),
                "--expected-plan-hash",
                str(first["plan_hash"]),
            )
            stale_code, _, stale_error = fixture.run(
                "setup",
                "apply",
                *fixture.setup_args(),
                "--confirmed",
                "--expected-plan-hash",
                "0" * 64,
            )
            self.assertEqual((missing_code, stale_code), (2, 2))
            self.assertIn("confirmed", missing_error)
            self.assertIn("plan hash", stale_error)
            self.assertEqual(before, _snapshot(fixture.base))

            receipt = fixture.install()
            self.assertEqual(receipt["status"], "installed")
            paths = receipt["paths"]
            for name in ("map", "inventory", "config", "receipt", "resolver"):
                self.assertTrue(Path(paths[name]).is_file())
            self.assertIn(
                "vantasma:discover-local-capabilities:start",
                (fixture.project / "AGENTS.md").read_text(encoding="utf-8"),
            )
            self.assertIn(
                "vantasma:discover-local-capabilities:start",
                (fixture.project / "CLAUDE.md").read_text(encoding="utf-8"),
            )
            private = json.loads(Path(paths["resolver"]).read_text(encoding="utf-8"))
            self.assertEqual(len(private["records"]), 4)

    def test_lifecycle_route_refresh_migrate_uninstall_and_purge_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = WorkflowFixture(Path(temporary))
            receipt = fixture.install()
            original_map = Path(receipt["paths"]["map"])

            code, route, error = fixture.run(
                "route",
                "--storage",
                str(fixture.storage),
                "--query",
                "fixture task automation",
                "--json",
            )
            self.assertEqual((code, error), (0, ""))
            self.assertEqual(route["matches"][0]["name"], "fixture-skill")
            self.assertIn("resolver_id", route["matches"][0])
            self.assertIn("state_warning", route["matches"][0])

            _write_skill(
                fixture.home / ".codex" / "skills" / "second-skill",
                "second-skill",
                "Second fixture task automation helper.",
            )
            storage_before = _snapshot(fixture.storage)
            code, refresh_plan, error = fixture.run(
                "refresh",
                "--storage",
                str(fixture.storage),
                "--dry-run",
            )
            self.assertEqual((code, error), (0, ""))
            self.assertEqual(storage_before, _snapshot(fixture.storage))
            self.assertEqual(refresh_plan["counts"]["capabilities"], 5)
            code, refreshed, error = fixture.run(
                "refresh",
                "--storage",
                str(fixture.storage),
                "--confirmed",
            )
            self.assertEqual((code, error, refreshed["status"]), (0, "", "refreshed"))

            migrate_before = _snapshot(fixture.base)
            code, migration, error = fixture.run(
                "migrate",
                "--storage",
                str(fixture.storage),
                "--to",
                str(fixture.migrated),
                "--dry-run",
            )
            self.assertEqual((code, error), (0, ""))
            self.assertEqual(migrate_before, _snapshot(fixture.base))
            self.assertEqual(migration["from"], str(fixture.storage.resolve()))
            code, migrated, error = fixture.run(
                "migrate",
                "--storage",
                str(fixture.storage),
                "--to",
                str(fixture.migrated),
                "--confirmed",
            )
            self.assertEqual((code, error, migrated["status"]), (0, "", "migrated"))
            self.assertTrue(original_map.exists())
            self.assertIn(
                str(fixture.migrated / "本机能力地图.md"),
                (fixture.project / "AGENTS.md").read_text(encoding="utf-8"),
            )

            code, uninstall_plan, error = fixture.run(
                "uninstall",
                "--storage",
                str(fixture.migrated),
                "--dry-run",
            )
            self.assertEqual((code, error), (0, ""))
            self.assertEqual(uninstall_plan["purge_data"], False)
            code, uninstalled, error = fixture.run(
                "uninstall",
                "--storage",
                str(fixture.migrated),
                "--confirmed",
            )
            self.assertEqual(
                (code, error, uninstalled["status"]), (0, "", "uninstalled")
            )
            self.assertNotIn(
                "vantasma:discover-local-capabilities:start",
                (fixture.project / "AGENTS.md").read_text(encoding="utf-8"),
            )
            self.assertTrue((fixture.migrated / "本机能力地图.md").exists())

            fixture.storage = fixture.migrated
            reinstall_args = (
                *fixture.setup_args(),
                "--installation-id",
                "inst_after_uninstall",
            )
            code, reinstall_plan, error = fixture.run(
                "setup", "plan", *reinstall_args
            )
            self.assertEqual((code, error), (0, ""))
            code, _, error = fixture.run(
                "setup",
                "apply",
                *reinstall_args,
                "--confirmed",
                "--expected-plan-hash",
                str(reinstall_plan["plan_hash"]),
            )
            self.assertEqual((code, error), (0, ""))
            code, purged, error = fixture.run(
                "uninstall",
                "--storage",
                str(fixture.migrated),
                "--confirmed",
                "--purge-data",
            )
            self.assertEqual((code, error, purged["status"]), (0, "", "purged"))
            self.assertFalse((fixture.migrated / "本机能力地图.md").exists())
            self.assertTrue(Path(purged["recovery_directory"]).is_dir())

    def test_status_paths_legacy_wrapper_and_instruction_failure_compensation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = WorkflowFixture(Path(temporary))
            fixture.install()
            code, status, error = fixture.run(
                "status", "--storage", str(fixture.storage)
            )
            code2, paths, error2 = fixture.run(
                "paths", "--storage", str(fixture.storage)
            )
            self.assertEqual((code, code2, error, error2), (0, 0, "", ""))
            self.assertTrue(status["installed"])
            self.assertTrue(status["healthy"])
            self.assertEqual(status["health_errors"], [])
            self.assertEqual(status["lifecycle"], "active")
            self.assertEqual(
                paths["paths"]["map"],
                str((fixture.storage / "本机能力地图.md").resolve()),
            )

        with tempfile.TemporaryDirectory() as temporary:
            fixture = WorkflowFixture(Path(temporary))
            code, plan, error = fixture.run("setup", "plan", *fixture.setup_args())
            self.assertEqual((code, error), (0, ""))
            with mock.patch(
                "capability_map.apply_instruction_plan",
                side_effect=RuntimeError("synthetic instruction failure"),
            ):
                code, _, error = fixture.run(
                    "setup",
                    "apply",
                    *fixture.setup_args(),
                    "--confirmed",
                    "--expected-plan-hash",
                    str(plan["plan_hash"]),
                )
            self.assertEqual(code, 3)
            self.assertIn("synthetic instruction failure", error)
            self.assertFalse((fixture.storage / "本机能力地图.md").exists())
            self.assertFalse((fixture.project / "AGENTS.md").exists())

        with tempfile.TemporaryDirectory() as temporary:
            fixture = WorkflowFixture(Path(temporary))
            output = fixture.base / "legacy-output"
            stdout = io.StringIO()
            stderr = io.StringIO()
            import scan_capabilities

            code = scan_capabilities.main(
                [
                    "--project",
                    str(fixture.project),
                    "--output-dir",
                    str(output),
                    "--skill-root",
                    str(fixture.home / ".codex" / "skills"),
                    "--cli",
                    "fixture-cli",
                ],
                environ=fixture.environ,
                home=fixture.home,
                cwd=fixture.project,
                stdout=stdout,
                stderr=stderr,
            )
            self.assertEqual(code, 0, stderr.getvalue())
            self.assertTrue((output / "本机能力地图.md").is_file())
            self.assertTrue((output / "capability-inventory.json").is_file())
            self.assertIn("deprecated", stderr.getvalue().casefold())


if __name__ == "__main__":
    unittest.main()

"""Integration tests for the capability-map command workflow."""

from __future__ import annotations

import io
import json
import os
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
        return {"PATH": str(self.bin)}

    def run(self, *argv: str) -> tuple[int, dict[str, object], str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        code = capability_map.main(
            list(argv),
            environ=self.environ,
            home=self.home,
            cwd=self.project,
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
            fixture.install()
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

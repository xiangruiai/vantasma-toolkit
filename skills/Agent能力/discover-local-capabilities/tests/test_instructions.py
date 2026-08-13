"""Tests for managed Agent instruction target resolution and transactions."""

from __future__ import annotations

import sys
import tempfile
import unittest
import os
import json
import stat
from pathlib import Path
from unittest import mock


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from capability_map_core.instructions import (  # noqa: E402
    InstructionTarget,
    apply_instruction_plan,
    build_instruction_plan,
    build_uninstall_plan,
    render_managed_block,
    resolve_instruction_targets,
)
import capability_map_core.transactions as transactions_module  # noqa: E402
from capability_map_core.transactions import TransactionError  # noqa: E402


class InstructionTargetResolutionTests(unittest.TestCase):
    def test_resolves_all_effective_targets_and_nonempty_codex_override(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            home = base / "home"
            codex_home = base / "codex"
            project = base / "project"
            home.mkdir()
            codex_home.mkdir()
            project.mkdir()
            (codex_home / "AGENTS.md").write_text("base\n", encoding="utf-8")
            override = codex_home / "AGENTS.override.md"
            override.write_text("override\n", encoding="utf-8")

            targets = resolve_instruction_targets(
                home=home, project_root=project, codex_home=codex_home
            )

            self.assertTrue(all(isinstance(item, InstructionTarget) for item in targets))
            self.assertEqual(
                [(item.agent, item.scope, item.path) for item in targets],
                [
                    ("codex", "user", override),
                    ("codex", "project", project / "AGENTS.md"),
                    ("claude", "user", home / ".claude" / "CLAUDE.md"),
                    ("claude", "project", project / "CLAUDE.md"),
                ],
            )
            self.assertIn("shadows", targets[0].effectiveness)

    def test_empty_codex_override_does_not_shadow_agents_md(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            home = base / "home"
            codex_home = base / "codex"
            project = base / "project"
            home.mkdir()
            codex_home.mkdir()
            project.mkdir()
            (codex_home / "AGENTS.override.md").write_bytes(b"")

            target = resolve_instruction_targets(
                home=home,
                project_root=project,
                codex_home=codex_home,
                agents=("codex",),
                scopes=("user",),
            )[0]

            self.assertEqual(target.path, codex_home / "AGENTS.md")
            self.assertIn("does not shadow", target.effectiveness)

    def test_override_symlink_and_fifo_are_rejected_without_blocking(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            home = base / "home"
            codex_home = base / "codex"
            home.mkdir()
            codex_home.mkdir()
            actual = base / "actual.md"
            actual.write_text("outside\n", encoding="utf-8")
            override = codex_home / "AGENTS.override.md"
            if hasattr(os, "symlink"):
                override.symlink_to(actual)
                with self.assertRaisesRegex(ValueError, "symbolic-link"):
                    resolve_instruction_targets(
                        home=home,
                        codex_home=codex_home,
                        agents=("codex",),
                        scopes=("user",),
                    )
                override.unlink()
            if hasattr(os, "mkfifo"):
                os.mkfifo(override)
                with self.assertRaisesRegex(ValueError, "regular file"):
                    resolve_instruction_targets(
                        home=home,
                        codex_home=codex_home,
                        agents=("codex",),
                        scopes=("user",),
                    )


class InstructionPlanTests(unittest.TestCase):
    def _target(self, path: Path) -> InstructionTarget:
        return InstructionTarget("codex", "project", path, "effective")

    def test_plan_is_deterministic_and_makes_no_writes_including_directories(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            target_path = base / "missing-parent" / "AGENTS.md"
            map_path = (base / "public" / "本机能力地图.md").absolute()
            resolver_path = (base / "private" / "capability-resolver.json").absolute()
            backup_root = base / "private" / "backups"

            first = build_instruction_plan(
                (self._target(target_path),),
                installation_id="install_123",
                map_path=map_path,
                resolver_path=resolver_path,
                backup_root=backup_root,
            )
            second = build_instruction_plan(
                (self._target(target_path),),
                installation_id="install_123",
                map_path=map_path,
                resolver_path=resolver_path,
                backup_root=backup_root,
            )

            self.assertEqual(first.plan_hash, second.plan_hash)
            self.assertEqual(first.to_json(), second.to_json())
            self.assertEqual(first.operations[0].operation, "install")
            self.assertIsNone(first.operations[0].expected_original_sha256)
            self.assertFalse((base / "missing-parent").exists())
            self.assertFalse((base / "public").exists())
            self.assertFalse((base / "private").exists())

    def test_rendered_block_is_private_neutral_and_uses_exact_absolute_paths(self) -> None:
        block = render_managed_block(
            installation_id="opaque.1",
            map_path=Path("/fixture/地图/本机能力地图.md"),
            resolver_path=Path("/fixture/private/capability-resolver.json"),
        )

        self.assertTrue(
            block.startswith(
                "<!-- vantasma:discover-local-capabilities:start id=opaque.1 schema=1 -->"
            )
        )
        self.assertTrue(
            block.endswith("<!-- vantasma:discover-local-capabilities:end -->")
        )
        self.assertIn("/fixture/地图/本机能力地图.md", block)
        self.assertIn("/fixture/private/capability-resolver.json", block)
        self.assertIn("仅在需要", block)
        self.assertIn("SKILL.md", block)
        self.assertIn("已发现", block)
        self.assertIn("已授权", block)
        self.assertIn("刷新", block)
        self.assertNotIn("secret", block.casefold())

    def test_existing_matching_block_updates_and_other_user_bytes_are_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            target_path = base / "AGENTS.md"
            old = render_managed_block(
                installation_id="same-id",
                map_path=base / "old-map.md",
                resolver_path=base / "old-resolver.json",
            ).encode("utf-8")
            prefix = b"# User rules\nkeep exactly\n"
            suffix = b"\nlast user line\n"
            target_path.write_bytes(prefix + old + suffix)

            plan = build_instruction_plan(
                (self._target(target_path),),
                installation_id="same-id",
                map_path=base / "new-map.md",
                resolver_path=base / "new-resolver.json",
            )

            operation = plan.operations[0]
            self.assertEqual(operation.operation, "update")
            self.assertTrue(operation.target_bytes.startswith(prefix))
            self.assertTrue(operation.target_bytes.endswith(suffix))
            self.assertIn(bytes(str(base / "new-map.md"), "utf-8"), operation.target_bytes)
            self.assertNotIn(bytes(str(base / "old-map.md"), "utf-8"), operation.target_bytes)

    def test_idempotent_plan_is_noop_and_uninstall_removes_only_matching_block(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            target_path = base / "AGENTS.md"
            matching = render_managed_block(
                installation_id="mine",
                map_path=base / "map.md",
                resolver_path=base / "resolver.json",
            ).encode("utf-8")
            other = render_managed_block(
                installation_id="other",
                map_path=base / "other-map.md",
                resolver_path=base / "other-resolver.json",
            ).encode("utf-8")
            user = b"user-before\n"
            target_path.write_bytes(user + matching + b"\n" + other + b"\nuser-after\n")
            target = self._target(target_path)

            reinstall = build_instruction_plan(
                (target,),
                installation_id="mine",
                map_path=base / "map.md",
                resolver_path=base / "resolver.json",
            )
            uninstall = build_uninstall_plan((target,), installation_id="mine")

            self.assertEqual(reinstall.operations[0].operation, "noop")
            self.assertEqual(uninstall.operations[0].operation, "uninstall")
            self.assertNotIn(matching, uninstall.operations[0].target_bytes)
            self.assertIn(other, uninstall.operations[0].target_bytes)
            self.assertTrue(uninstall.operations[0].target_bytes.startswith(user))
            self.assertTrue(uninstall.operations[0].target_bytes.endswith(b"user-after\n"))

    def test_corrupt_nested_duplicate_and_unmatched_markers_make_plan_inapplicable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            target_path = base / "AGENTS.md"
            target = self._target(target_path)
            valid = render_managed_block(
                installation_id="duplicate",
                map_path=base / "map.md",
                resolver_path=base / "resolver.json",
            ).encode("utf-8")
            corruptions = {
                "duplicate": valid + b"\n" + valid,
                "missing-end": valid.rsplit(b"\n", 1)[0],
                "unmatched-end": b"<!-- vantasma:discover-local-capabilities:end -->\n",
                "nested": valid.replace(
                    "## 本机能力路由".encode("utf-8"),
                    (
                        "<!-- vantasma:discover-local-capabilities:start "
                        "id=nested schema=1 -->\n## 本机能力路由"
                    ).encode("utf-8"),
                ),
                "damaged": valid.replace(b" schema=1 -->", b" schema=1 -- >"),
            }
            for label, payload in corruptions.items():
                with self.subTest(label=label):
                    target_path.write_bytes(payload)
                    plan = build_instruction_plan(
                        (target,),
                        installation_id="duplicate",
                        map_path=base / "map.md",
                        resolver_path=base / "resolver.json",
                    )
                    self.assertFalse(plan.applicable)
                    self.assertEqual(plan.operations[0].operation, "conflict")
                    self.assertTrue(plan.diagnostics)

    def test_invalid_installation_ids_and_relative_private_paths_are_rejected(self) -> None:
        target = self._target(Path("/fixture/project/AGENTS.md"))
        for bad in ("", "white space", "line\nbreak", "../escape", "x" * 129):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                build_instruction_plan(
                    (target,),
                    installation_id=bad,
                    map_path=Path("/fixture/map.md"),
                    resolver_path=Path("/fixture/resolver.json"),
                )
        with self.assertRaises(ValueError):
            build_instruction_plan(
                (target,),
                installation_id="valid",
                map_path=Path("relative-map.md"),
                resolver_path=Path("/fixture/resolver.json"),
            )


class InstructionApplyTests(unittest.TestCase):
    def _target(self, agent: str, path: Path) -> InstructionTarget:
        return InstructionTarget(agent, "project", path, "effective")

    def _plan(
        self,
        targets: tuple[InstructionTarget, ...],
        base: Path,
        installation_id: str = "apply-test",
    ):
        return build_instruction_plan(
            targets,
            installation_id=installation_id,
            map_path=(base / "public" / "本机能力地图.md").absolute(),
            resolver_path=(base / "private" / "capability-resolver.json").absolute(),
            backup_root=(base / "private" / "instruction-backups").absolute(),
        )

    def test_first_install_preserves_lf_crlf_modes_and_writes_exact_backups(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            first = base / "one" / "AGENTS.md"
            second = base / "two" / "CLAUDE.md"
            first.parent.mkdir()
            second.parent.mkdir()
            first_original = b"# first\nuser rule\n"
            second_original = b"# second\r\nuser rule\r\n"
            first.write_bytes(first_original)
            second.write_bytes(second_original)
            first.chmod(0o640)
            second.chmod(0o600)
            plan = self._plan(
                (self._target("codex", first), self._target("claude", second)), base
            )

            receipt = apply_instruction_plan(
                plan, confirmed=True, expected_plan_hash=plan.plan_hash
            )

            self.assertEqual(set(receipt.changed_paths), {first, second})
            self.assertIsNotNone(receipt.manifest_path)
            self.assertEqual(stat.S_IMODE(first.stat().st_mode), 0o640)
            self.assertEqual(stat.S_IMODE(second.stat().st_mode), 0o600)
            self.assertNotIn(b"\r\n", first.read_bytes())
            self.assertIn(b"\r\n", second.read_bytes())
            self.assertNotIn(b"\n", second.read_bytes().replace(b"\r\n", b""))
            manifest = json.loads(receipt.manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["plan_hash"], plan.plan_hash)
            entries = {entry["path"]: entry for entry in manifest["entries"]}
            self.assertEqual(entries[str(first)]["newline"], "LF")
            self.assertEqual(entries[str(second)]["newline"], "CRLF")
            first_backup = receipt.manifest_path.parent / entries[str(first)]["backup_file"]
            second_backup = receipt.manifest_path.parent / entries[str(second)]["backup_file"]
            self.assertEqual(first_backup.read_bytes(), first_original)
            self.assertEqual(second_backup.read_bytes(), second_original)

    def test_confirmation_and_stale_plan_refuse_before_any_writes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            target_path = base / "AGENTS.md"
            target_path.write_bytes(b"original\n")
            target = self._target("codex", target_path)
            plan = self._plan((target,), base)

            with self.assertRaisesRegex(ValueError, "confirmed"):
                apply_instruction_plan(
                    plan, confirmed=False, expected_plan_hash=plan.plan_hash
                )
            with self.assertRaisesRegex(ValueError, "plan hash"):
                apply_instruction_plan(
                    plan, confirmed=True, expected_plan_hash="0" * 64
                )
            target_path.write_bytes(b"external change\n")
            with self.assertRaisesRegex(TransactionError, "stale"):
                apply_instruction_plan(
                    plan, confirmed=True, expected_plan_hash=plan.plan_hash
                )

            self.assertEqual(target_path.read_bytes(), b"external change\n")
            self.assertFalse(plan.backup_root.exists())

    def test_failure_after_one_commit_rolls_back_exact_bytes_and_mode(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            first = base / "a" / "AGENTS.md"
            second = base / "b" / "CLAUDE.md"
            first.parent.mkdir()
            second.parent.mkdir()
            first.write_bytes(b"alpha\n")
            second.write_bytes(b"beta\r\n")
            first.chmod(0o640)
            second.chmod(0o604)
            plan = self._plan(
                (self._target("codex", first), self._target("claude", second)), base
            )
            calls = 0

            def fail_after_first(event: str, path: Path) -> None:
                nonlocal calls
                if event == "after_replace":
                    calls += 1
                    if calls == 1:
                        raise OSError("injected failure")

            with self.assertRaises(TransactionError) as caught:
                apply_instruction_plan(
                    plan,
                    confirmed=True,
                    expected_plan_hash=plan.plan_hash,
                    failure_injector=fail_after_first,
                )

            self.assertEqual(first.read_bytes(), b"alpha\n")
            self.assertEqual(second.read_bytes(), b"beta\r\n")
            self.assertEqual(stat.S_IMODE(first.stat().st_mode), 0o640)
            self.assertEqual(stat.S_IMODE(second.stat().st_mode), 0o604)
            self.assertEqual(caught.exception.rollback_conflicts, ())
            self.assertTrue(caught.exception.manifest_path.is_file())

    def test_concurrent_change_after_commit_is_preserved_and_reported(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            target_path = base / "AGENTS.md"
            target_path.write_bytes(b"before\n")
            plan = self._plan((self._target("codex", target_path),), base)

            def concurrent_then_fail(event: str, path: Path) -> None:
                if event == "after_replace":
                    path.write_bytes(b"concurrent owner\n")
                    raise OSError("stop transaction")

            with self.assertRaises(TransactionError) as caught:
                apply_instruction_plan(
                    plan,
                    confirmed=True,
                    expected_plan_hash=plan.plan_hash,
                    failure_injector=concurrent_then_fail,
                )

            self.assertEqual(target_path.read_bytes(), b"concurrent owner\n")
            self.assertEqual(caught.exception.rollback_conflicts, (target_path,))

    def test_idempotent_reinstall_and_uninstall_only_change_managed_block(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            target_path = base / "AGENTS.md"
            original = b"# user\nkeep\n"
            target_path.write_bytes(original)
            target = self._target("codex", target_path)
            install = self._plan((target,), base, "roundtrip")
            apply_instruction_plan(
                install, confirmed=True, expected_plan_hash=install.plan_hash
            )

            reinstall = self._plan((target,), base, "roundtrip")
            receipt = apply_instruction_plan(
                reinstall,
                confirmed=True,
                expected_plan_hash=reinstall.plan_hash,
            )
            self.assertEqual(reinstall.operations[0].operation, "noop")
            self.assertEqual(receipt.changed_paths, ())
            self.assertIsNone(receipt.manifest_path)

            uninstall = build_uninstall_plan(
                (target,),
                installation_id="roundtrip",
                backup_root=base / "private" / "instruction-backups",
            )
            apply_instruction_plan(
                uninstall,
                confirmed=True,
                expected_plan_hash=uninstall.plan_hash,
            )
            remaining = target_path.read_bytes()
            self.assertEqual(remaining, original)
            self.assertNotIn(b"vantasma:discover-local-capabilities", remaining)

    def test_target_swap_to_symlink_between_plan_and_apply_is_refused(self) -> None:
        if not hasattr(os, "symlink"):
            self.skipTest("symlinks unsupported")
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            target_path = base / "AGENTS.md"
            outside = base / "outside.md"
            target_path.write_bytes(b"inside\n")
            outside.write_bytes(b"outside\n")
            plan = self._plan((self._target("codex", target_path),), base)
            target_path.unlink()
            target_path.symlink_to(outside)

            with self.assertRaises(ValueError):
                apply_instruction_plan(
                    plan, confirmed=True, expected_plan_hash=plan.plan_hash
                )

            self.assertEqual(outside.read_bytes(), b"outside\n")
            self.assertFalse(plan.backup_root.exists())

    def test_backend_without_dir_fd_support_fails_closed_before_writes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            target_path = base / "AGENTS.md"
            target_path.write_bytes(b"original\n")
            plan = self._plan((self._target("codex", target_path),), base)

            with mock.patch.object(
                transactions_module, "_DIR_FD_BACKEND_SUPPORTED", False
            ):
                with self.assertRaisesRegex(RuntimeError, "secure_transaction_backend"):
                    apply_instruction_plan(
                        plan, confirmed=True, expected_plan_hash=plan.plan_hash
                    )

            self.assertEqual(target_path.read_bytes(), b"original\n")
            self.assertFalse(plan.backup_root.exists())


if __name__ == "__main__":
    unittest.main()

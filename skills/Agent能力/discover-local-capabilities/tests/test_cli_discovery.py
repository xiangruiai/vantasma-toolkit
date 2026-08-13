"""Tests for complete, non-executing PATH command discovery."""

from __future__ import annotations

import json
import os
import socket
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from capability_map_core.clis import (  # noqa: E402
    CliDiscoveryResult,
    discover_clis,
    probe_cli_version,
)


def _write_file(path: Path, *, executable: bool = True) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("fixture\n", encoding="utf-8")
    path.chmod(0o755 if executable else 0o644)
    return path


def _capability_by_name(result: CliDiscoveryResult, name: str):
    return next(capability for capability in result.capabilities if capability.name == name)


def _resolver_for(result: CliDiscoveryResult, capability):
    return next(
        resolver
        for resolver in result.resolvers
        if resolver.resolver_id == capability.resolver_id
    )


class UnixCliDiscoveryTests(unittest.TestCase):
    def test_collects_every_regular_executable_and_rejects_other_entry_types(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / "all commands"
            _write_file(directory / "ordinary-tool")
            _write_file(directory / "工具 乙")
            _write_file(directory / "not-executable", executable=False)
            (directory / "directory-tool").mkdir()
            fifo = directory / "fifo-tool"
            os.mkfifo(fifo)
            socket_path = directory / "socket-tool"
            unix_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self.addCleanup(unix_socket.close)
            unix_socket.bind(str(socket_path))

            result = discover_clis(
                path=str(directory),
                cwd=Path(temporary),
                platform_name="Linux",
                os_name="posix",
            )

            self.assertEqual(
                [capability.name for capability in result.capabilities],
                ["ordinary-tool", "工具 乙"],
            )
            self.assertEqual(result.entry_count, 2)
            self.assertTrue(
                all(capability.states.discovered == "success" for capability in result.capabilities)
            )
            self.assertTrue(all(capability.states.probed == "unknown" for capability in result.capabilities))

    def test_preserves_path_order_duplicates_empty_relative_and_shadow_entries(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            cwd = base / "working"
            first = base / "first"
            relative = cwd / "relative-bin"
            for directory in (cwd, first, relative):
                _write_file(directory / "same")
            path_value = os.pathsep.join(
                [str(first), "", "relative-bin", str(first)]
            )

            result = discover_clis(
                path=path_value,
                cwd=cwd,
                platform_name="Linux",
                os_name="posix",
            )

            capability = _capability_by_name(result, "same")
            resolver = _resolver_for(result, capability)
            expected = (
                str(first / "same"),
                str(cwd / "same"),
                str(relative / "same"),
                str(first / "same"),
            )
            self.assertEqual(resolver.exact_locations, expected)
            self.assertEqual(len(capability.source_locations), 4)
            self.assertEqual(result.entry_count, 4)
            entry_details = [
                diagnostic.details
                for diagnostic in capability.diagnostics
                if diagnostic.code == "cli_path_entry"
            ]
            self.assertEqual([item["shadow_rank"] for item in entry_details], [0, 1, 2, 3])
            self.assertEqual([item["effective"] for item in entry_details], [True, False, False, False])

    def test_empty_and_relative_segments_never_fall_back_to_real_cwd(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            absolute = Path(temporary) / "absolute"
            _write_file(absolute / "safe-tool")

            result = discover_clis(
                path=os.pathsep.join(["", "relative-bin", str(absolute)]),
                cwd=None,
                platform_name="Linux",
                os_name="posix",
            )

            self.assertEqual([item.name for item in result.capabilities], ["safe-tool"])
            self.assertEqual(result.entry_count, 1)
            self.assertEqual(
                [item.code for item in result.diagnostics],
                ["cwd_not_injected", "cwd_not_injected"],
            )

    def test_shadowed_symlink_and_duplicate_physical_entry_remain_visible(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            first = base / "one"
            second = base / "two"
            executable = _write_file(first / "linked")
            second.mkdir()
            (second / "linked").symlink_to(executable)

            result = discover_clis(
                path=os.pathsep.join([str(first), str(second)]),
                cwd=base,
                platform_name="Linux",
                os_name="posix",
            )

            capability = _capability_by_name(result, "linked")
            self.assertEqual(len(capability.source_locations), 2)
            self.assertEqual(
                _resolver_for(result, capability).exact_locations,
                (str(first / "linked"), str(second / "linked")),
            )
            self.assertIn(
                "duplicate_physical_entry",
                [diagnostic.code for diagnostic in capability.diagnostics],
            )

    def test_directory_read_error_is_diagnostic_and_other_path_entries_continue(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            denied = base / "denied"
            usable = base / "usable"
            denied.mkdir()
            _write_file(usable / "still-found")
            real_scandir = os.scandir

            def selective_scandir(path):
                if Path(path) == denied:
                    raise PermissionError("synthetic denied directory")
                return real_scandir(path)

            with mock.patch(
                "capability_map_core.clis.os.scandir", side_effect=selective_scandir
            ):
                result = discover_clis(
                    path=os.pathsep.join([str(denied), str(usable)]),
                    cwd=base,
                    platform_name="Linux",
                    os_name="posix",
                )

            self.assertEqual([item.name for item in result.capabilities], ["still-found"])
            self.assertIn("path_directory_unreadable", [item.code for item in result.diagnostics])

    def test_default_inventory_never_executes_programs_and_has_no_allowlist(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / "bin"
            names = ["unknown-command-9381", "another arbitrary executable"]
            for name in names:
                _write_file(directory / name)

            with mock.patch(
                "capability_map_core.clis.subprocess.run",
                side_effect=AssertionError("default discovery executed a command"),
            ) as run:
                result = discover_clis(
                    path=str(directory),
                    cwd=Path(temporary),
                    platform_name="Linux",
                    os_name="posix",
                )

            run.assert_not_called()
            self.assertEqual(
                [capability.name for capability in result.capabilities],
                sorted(names, key=lambda value: (value.casefold(), value)),
            )

    def test_public_output_is_sanitized_while_only_resolver_has_exact_paths(self) -> None:
        with tempfile.TemporaryDirectory(prefix="private-user-segment-") as temporary:
            base = Path(temporary)
            directory = base / "private user" / "bin"
            _write_file(directory / "portable")

            first = discover_clis(
                path=str(directory), cwd=base, platform_name="Linux", os_name="posix"
            )
            public_payload = json.dumps(
                {
                    "capabilities": [item.to_public_dict() for item in first.capabilities],
                    "diagnostics": [item.to_public_dict() for item in first.diagnostics],
                },
                ensure_ascii=False,
            )

            self.assertNotIn(str(base), public_payload)
            self.assertNotIn("private-user-segment-", public_payload)
            capability = first.capabilities[0]
            self.assertEqual(
                _resolver_for(first, capability).exact_locations,
                (str(directory / "portable"),),
            )

            with tempfile.TemporaryDirectory(prefix="other-machine-") as other:
                other_dir = Path(other) / "bin"
                _write_file(other_dir / "portable")
                second = discover_clis(
                    path=str(other_dir),
                    cwd=Path(other),
                    platform_name="Linux",
                    os_name="posix",
                )
            self.assertEqual(capability.id, second.capabilities[0].id)
            self.assertEqual(capability.resolver_id, second.capabilities[0].resolver_id)


class WindowsCliDiscoveryTests(unittest.TestCase):
    def test_pathext_filtering_stripping_and_case_insensitive_shadow_chain(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            first = base / "Windows Bin One"
            second = base / "Windows Bin Two"
            _write_file(first / "Tool.EXE", executable=False)
            _write_file(first / "tool.CMD", executable=False)
            _write_file(first / "ignored.py", executable=True)
            (first / "fake.EXE").mkdir()
            _write_file(second / "TOOL.exe", executable=False)

            result = discover_clis(
                path=";".join([str(first), str(second)]),
                cwd=base,
                platform_name="Windows",
                os_name="nt",
                pathext=".EXE;.CMD",
                case_sensitive=False,
            )

            self.assertEqual(len(result.capabilities), 1)
            capability = result.capabilities[0]
            self.assertEqual(capability.name, "Tool")
            self.assertEqual(result.entry_count, 3)
            self.assertEqual(
                _resolver_for(result, capability).exact_locations,
                (
                    str(first / "Tool.EXE"),
                    str(first / "tool.CMD"),
                    str(second / "TOOL.exe"),
                ),
            )
            details = [
                item.details
                for item in capability.diagnostics
                if item.code == "cli_path_entry"
            ]
            self.assertEqual([item["path_rank"] for item in details], [0, 0, 1])
            self.assertEqual([item["effective"] for item in details], [True, False, False])

    def test_case_sensitive_override_keeps_distinct_windows_commands(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / "bin"
            _write_file(directory / "Case.EXE", executable=False)
            _write_file(directory / "case.CMD", executable=False)

            result = discover_clis(
                path=str(directory),
                cwd=Path(temporary),
                platform_name="Windows",
                os_name="nt",
                pathext=[".EXE", ".CMD"],
                case_sensitive=True,
            )

            self.assertEqual([item.name for item in result.capabilities], ["Case", "case"])
            self.assertEqual(result.entry_count, 2)


class CliVersionProbeTests(unittest.TestCase):
    def test_probe_uses_exact_argv_minimal_environment_limits_and_sanitizes_output(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            executable = Path(temporary) / "tool"
            secret = "gh" + "p_" + "syntheticvalue123456"
            stdout = f"tool 1.2.3 token={secret} {temporary} " + ("x" * 200)
            completed = subprocess.CompletedProcess(
                [str(executable), "version"], 0, stdout=stdout.encode(), stderr=b""
            )
            environment = {
                "PATH": "/minimal/bin",
                "SYSTEMROOT": "C:\\Windows",
                "TEMP": "/safe-temp",
                "TOKEN": secret,
                "UNRELATED": "do-not-copy",
            }

            with mock.patch(
                "capability_map_core.clis.subprocess.run", return_value=completed
            ) as run:
                result = probe_cli_version(
                    executable,
                    flags=("version",),
                    environ=environment,
                    timeout=99,
                    output_limit=80,
                )

            run.assert_called_once()
            args, kwargs = run.call_args
            self.assertEqual(args[0], [str(executable), "version"])
            self.assertIs(kwargs["stdin"], subprocess.DEVNULL)
            self.assertIs(kwargs["stdout"], subprocess.PIPE)
            self.assertIs(kwargs["stderr"], subprocess.PIPE)
            self.assertFalse(kwargs["shell"])
            self.assertLessEqual(kwargs["timeout"], 3)
            self.assertEqual(
                kwargs["env"],
                {
                    "PATH": "/minimal/bin",
                    "SYSTEMROOT": "C:\\Windows",
                    "TEMP": "/safe-temp",
                    "NO_COLOR": "1",
                },
            )
            self.assertEqual(result.status, "success")
            self.assertLessEqual(len(result.output), 80)
            self.assertNotIn(secret, result.output)
            self.assertNotIn(temporary, result.output)

    def test_probe_encodes_no_output_nonzero_timeout_and_error_distinctly(self) -> None:
        executable = Path("/private/resolver/tool")
        cases = (
            (subprocess.CompletedProcess([], 0, stdout=b"", stderr=b""), "no_output"),
            (
                subprocess.CompletedProcess([], 9, stdout=b"bad", stderr=b"failure"),
                "nonzero",
            ),
            (subprocess.TimeoutExpired([], 1, output=b"partial", stderr=b"late"), "timeout"),
            (OSError("cannot execute /private/resolver/tool"), "error"),
            (RuntimeError("synthetic runner failure"), "error"),
        )
        for outcome, expected in cases:
            with self.subTest(expected=expected):
                if isinstance(outcome, BaseException):
                    patch = mock.patch(
                        "capability_map_core.clis.subprocess.run", side_effect=outcome
                    )
                else:
                    patch = mock.patch(
                        "capability_map_core.clis.subprocess.run", return_value=outcome
                    )
                with patch:
                    result = probe_cli_version(executable, environ={"PATH": "/bin"})
                self.assertEqual(result.status, expected)
                self.assertNotEqual(result.status, "success")
                self.assertNotIn("/private/resolver", result.output)

    def test_probe_rejects_non_exact_command_name(self) -> None:
        with self.assertRaises(ValueError):
            probe_cli_version("untrusted-command-name")


if __name__ == "__main__":
    unittest.main()

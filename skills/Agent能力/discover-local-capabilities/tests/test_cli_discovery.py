"""Tests for complete, non-executing PATH command discovery."""

from __future__ import annotations

import inspect
import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import capability_map_core.clis as cli_module  # noqa: E402
from capability_map_core.clis import (  # noqa: E402
    CliDiscoveryResult,
    MAX_PROBE_TIMEOUT_SECONDS,
    discover_clis,
    probe_cli_version,
)

PROBE_READ_CHUNK_BYTES = getattr(cli_module, "PROBE_READ_CHUNK_BYTES", 0)


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


def _write_python_executable(path: Path, body: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"#!{sys.executable}\n{body}\n", encoding="utf-8")
    path.chmod(0o755)
    return path


def _pid_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _wait_pid_gone(pid: int, timeout: float = 1.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not _pid_exists(pid):
            return True
        time.sleep(0.02)
    return not _pid_exists(pid)


class _TrackingPipe:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload
        self._offset = 0
        self.read_sizes: list[int] = []
        self.closed = False
        self._lock = threading.Lock()

    def read(self, size: int = -1) -> bytes:
        if size <= 0:
            raise AssertionError("probe pipe reads must always be bounded")
        with self._lock:
            self.read_sizes.append(size)
            chunk = self._payload[self._offset : self._offset + size]
            self._offset += len(chunk)
            return chunk

    def close(self) -> None:
        self.closed = True


class _TrackingTemporaryFile:
    def __init__(self, wrapped) -> None:
        self._wrapped = wrapped
        self.bytes_written = 0

    def write(self, data: bytes) -> int:
        self.bytes_written += len(data)
        return self._wrapped.write(data)

    def __getattr__(self, name: str):
        return getattr(self._wrapped, name)


class _FakeDirEntry:
    def __init__(self, name: str, file_stat: os.stat_result) -> None:
        self.name = name
        self._file_stat = file_stat

    def stat(self, *, follow_symlinks: bool = True) -> os.stat_result:
        return self._file_stat


class _FakeProcess:
    def __init__(
        self,
        *,
        stdout: bytes = b"",
        stderr: bytes = b"",
        returncode: int = 0,
        stays_running: bool = False,
    ) -> None:
        self.stdout = _TrackingPipe(stdout)
        self.stderr = _TrackingPipe(stderr)
        self.returncode: int | None = None if stays_running else returncode
        self._planned_returncode = returncode
        self._stays_running = stays_running
        self.wait_timeouts: list[float | None] = []
        self.terminate_called = False
        self.kill_called = False

    def wait(self, timeout: float | None = None) -> int:
        self.wait_timeouts.append(timeout)
        if self.returncode is not None:
            return self.returncode
        if self._stays_running:
            raise subprocess.TimeoutExpired(["fixture"], timeout)
        self.returncode = self._planned_returncode
        return self.returncode

    def poll(self) -> int | None:
        return self.returncode

    def terminate(self) -> None:
        self.terminate_called = True
        self.returncode = -15

    def kill(self) -> None:
        self.kill_called = True
        self.returncode = -9


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
            self.assertEqual(
                resolver.to_private_dict(),
                {
                    "resolver_id": capability.resolver_id,
                    "exact_locations": list(expected),
                },
            )
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

            with (
                mock.patch("subprocess.run") as run,
                mock.patch("subprocess.Popen") as popen,
                mock.patch("socket.create_connection") as create_connection,
                mock.patch("socket.socket") as socket_constructor,
            ):
                result = discover_clis(
                    path=str(directory),
                    cwd=Path(temporary),
                    platform_name="Linux",
                    os_name="posix",
                )

            run.assert_not_called()
            popen.assert_not_called()
            create_connection.assert_not_called()
            socket_constructor.assert_not_called()
            self.assertEqual(
                [capability.name for capability in result.capabilities],
                sorted(names, key=lambda value: (value.casefold(), value)),
            )

    def test_unix_command_grouping_is_always_case_sensitive(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            directory = base / "bin"
            directory.mkdir()
            upper_stat = _write_file(base / "fixtures" / "upper").stat()
            lower_stat = _write_file(base / "fixtures" / "lower").stat()

            with mock.patch(
                "capability_map_core.clis.os.scandir",
                return_value=[
                    _FakeDirEntry("Case", upper_stat),
                    _FakeDirEntry("case", lower_stat),
                ],
            ):
                result = discover_clis(
                    path=str(directory),
                    cwd=base,
                    platform_name="Linux",
                    os_name="posix",
                )

            self.assertEqual([item.name for item in result.capabilities], ["Case", "case"])
            self.assertNotIn(
                "case_sensitive", inspect.signature(discover_clis).parameters
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

    def test_windows_grouping_is_always_case_insensitive(self) -> None:
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
            )

            self.assertEqual([item.name for item in result.capabilities], ["Case"])
            self.assertEqual(result.entry_count, 2)
            self.assertNotIn(
                "case_sensitive", inspect.signature(discover_clis).parameters
            )


class CliVersionProbeTests(unittest.TestCase):
    def test_windows_probe_is_securely_unsupported_without_spawning(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            executable = _write_file(Path(temporary) / "tool")

            with mock.patch(
                "capability_map_core.clis.subprocess.Popen"
            ) as popen:
                result = probe_cli_version(
                    executable,
                    probe_platform="windows",
                )

            popen.assert_not_called()
            self.assertEqual(result.status, "error")
            self.assertIn(
                "unsupported_secure_containment",
                [diagnostic.code for diagnostic in result.diagnostics],
            )

    def test_real_windows_host_cannot_be_overridden_to_enable_probe(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            executable = _write_file(Path(temporary) / "tool")

            with (
                mock.patch.object(cli_module.os, "name", "nt"),
                mock.patch("capability_map_core.clis.subprocess.Popen") as popen,
            ):
                result = probe_cli_version(
                    executable,
                    probe_platform="linux",
                )

            popen.assert_not_called()
            self.assertEqual(result.status, "error")
            self.assertIn(
                "unsupported_secure_containment",
                [diagnostic.code for diagnostic in result.diagnostics],
            )

    def test_probe_uses_exact_argv_minimal_environment_limits_and_sanitizes_output(
        self,
    ) -> None:
        if os.name == "nt":
            self.skipTest("Windows probing is securely unsupported")
        with tempfile.TemporaryDirectory() as temporary:
            executable = _write_file(Path(temporary) / "tool")
            secret = "gh" + "p_" + "syntheticvalue123456"
            stdout = f"tool 1.2.3 token={secret} {temporary} " + ("x" * 200)
            process = _FakeProcess(stdout=stdout.encode())
            environment = {
                "PATH": "/minimal/bin",
                "SYSTEMROOT": "C:\\Windows",
                "TEMP": "/safe-temp",
                "TOKEN": secret,
                "UNRELATED": "do-not-copy",
            }

            with mock.patch(
                "capability_map_core.clis.subprocess.Popen", return_value=process
            ) as popen:
                result = probe_cli_version(
                    executable,
                    flags=("version",),
                    environ=environment,
                    timeout=99,
                    output_limit=80,
                )

            popen.assert_called_once()
            args, kwargs = popen.call_args
            self.assertEqual(args[0], [str(executable), "version"])
            self.assertIs(kwargs["stdin"], subprocess.DEVNULL)
            self.assertIs(kwargs["stdout"], subprocess.PIPE)
            self.assertIs(kwargs["stderr"], subprocess.PIPE)
            self.assertFalse(kwargs["shell"])
            self.assertTrue(kwargs["start_new_session"])
            self.assertLessEqual(MAX_PROBE_TIMEOUT_SECONDS, 3)
            self.assertTrue(
                all(
                    timeout is None or timeout <= MAX_PROBE_TIMEOUT_SECONDS
                    for timeout in process.wait_timeouts
                )
            )
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
            self.assertTrue(process.stdout.closed)
            self.assertTrue(process.stderr.closed)

    def test_probe_encodes_no_output_nonzero_timeout_and_error_distinctly(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            executable = _write_file(Path(temporary) / "tool")
            cases = (
                (_FakeProcess(), "no_output", 1.0),
                (
                    _FakeProcess(stdout=b"bad", stderr=b"failure", returncode=9),
                    "nonzero",
                    1.0,
                ),
                (
                    _FakeProcess(
                        stdout=b"partial", stderr=b"late", stays_running=True
                    ),
                    "timeout",
                    0.01,
                ),
                (OSError("cannot execute exact path"), "error", 1.0),
                (RuntimeError("synthetic runner failure"), "error", 1.0),
            )
            for outcome, expected, timeout in cases:
                with self.subTest(expected=expected):
                    if isinstance(outcome, BaseException):
                        patch = mock.patch(
                            "capability_map_core.clis.subprocess.Popen",
                            side_effect=outcome,
                        )
                    else:
                        patch = mock.patch(
                            "capability_map_core.clis.subprocess.Popen",
                            return_value=outcome,
                        )
                    with patch:
                        result = probe_cli_version(
                            executable,
                            environ={"PATH": "/bin"},
                            timeout=timeout,
                        )
                    self.assertEqual(result.status, expected)
                    self.assertNotEqual(result.status, "success")
                    self.assertNotIn(temporary, result.output)

    def test_probe_rejects_non_native_nonregular_and_nonexecutable_paths_without_spawn(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            non_executable = _write_file(base / "not-executable", executable=False)
            directory = base / "directory"
            directory.mkdir()
            foreign_path = (
                "/foreign/posix/tool"
                if os.name == "nt"
                else "C:\\foreign\\windows\\tool.exe"
            )
            rejected = ["untrusted-command-name", foreign_path, directory]
            if os.name != "nt":
                rejected.append(non_executable)

            with (
                mock.patch("capability_map_core.clis.subprocess.Popen") as popen,
                mock.patch("capability_map_core.clis.subprocess.run") as run,
            ):
                for executable in rejected:
                    with self.subTest(executable=str(executable)):
                        with self.assertRaises(ValueError):
                            probe_cli_version(executable)

            popen.assert_not_called()
            run.assert_not_called()

    def test_probe_streams_with_bounded_reads_and_shared_retained_budget(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            executable = _write_file(Path(temporary) / "tool")
            process = _FakeProcess(
                stdout=b"o" * (1024 * 1024),
                stderr=b"e" * (1024 * 1024),
                stays_running=True,
            )

            captures: list[object] = []
            capture_type = cli_module._StreamCapture
            original_init = capture_type.__init__

            def tracking_init(capture, *args, **kwargs) -> None:
                original_init(capture, *args, **kwargs)
                captures.append(capture)

            with (
                mock.patch(
                    "capability_map_core.clis.subprocess.Popen",
                    return_value=process,
                ),
                mock.patch.object(
                    capture_type,
                    "__init__",
                    autospec=True,
                    side_effect=tracking_init,
                ),
            ):
                result = probe_cli_version(
                    executable,
                    timeout=1,
                    output_limit=257,
                    environ={"PATH": "/bin"},
                )

            self.assertLessEqual(len(result.output.encode("utf-8")), 257)
            self.assertTrue(process.terminate_called)
            self.assertTrue(process.stdout.read_sizes)
            self.assertTrue(process.stderr.read_sizes)
            self.assertLessEqual(max(process.stdout.read_sizes), PROBE_READ_CHUNK_BYTES)
            self.assertLessEqual(max(process.stderr.read_sizes), PROBE_READ_CHUNK_BYTES)
            self.assertTrue(process.stdout.closed)
            self.assertTrue(process.stderr.closed)
            self.assertLessEqual(
                sum(capture.max_retained for capture in captures),
                257,
            )
            self.assertIn(
                "version_output_truncated",
                [diagnostic.code for diagnostic in result.diagnostics],
            )

    def test_stream_output_is_combined_stdout_then_stderr_deterministically(self) -> None:
        if os.name == "nt":
            self.skipTest("POSIX executable fixture")
        with tempfile.TemporaryDirectory() as temporary:
            executable = _write_python_executable(
                Path(temporary) / "ordered-tool",
                "import os, time\n"
                "os.write(2, b'stderr-fixed')\n"
                "time.sleep(0.02)\n"
                "os.write(1, b'stdout-fixed')",
            )

            outputs = [
                probe_cli_version(executable, flags=(), timeout=1).output
                for _ in range(5)
            ]

            self.assertEqual(outputs, ["stdout-fixed stderr-fixed"] * 5)

    def test_timeout_kills_descendant_process_group_and_does_not_wait_on_pipes(
        self,
    ) -> None:
        if os.name == "nt":
            self.skipTest("POSIX process-group fixture")
        with tempfile.TemporaryDirectory() as temporary:
            child_pid_file = Path(temporary) / "child.pid"
            executable = _write_python_executable(
                Path(temporary) / "spawning-tool",
                "import pathlib, subprocess, sys, time\n"
                "child = subprocess.Popen(\n"
                "    [sys.executable, '-c', 'import time; time.sleep(30)'],\n"
                "    stdin=subprocess.DEVNULL, stdout=sys.stdout, stderr=sys.stderr,\n"
                ")\n"
                f"pathlib.Path({str(child_pid_file)!r}).write_text(str(child.pid))\n"
                "time.sleep(30)",
            )
            child_pid = 0
            started = time.monotonic()
            try:
                result = probe_cli_version(executable, flags=(), timeout=1.0)
                elapsed = time.monotonic() - started
                deadline = time.monotonic() + 1.0
                while not child_pid_file.exists() and time.monotonic() < deadline:
                    time.sleep(0.02)
                self.assertTrue(child_pid_file.exists())
                child_pid = int(child_pid_file.read_text(encoding="utf-8"))

                self.assertEqual(result.status, "timeout")
                self.assertLess(elapsed, 3.0)
                self.assertTrue(_wait_pid_gone(child_pid))
            finally:
                if child_pid and _pid_exists(child_pid):
                    os.kill(child_pid, signal.SIGKILL)

    def test_second_reader_start_failure_cleans_process_pipes_and_started_thread(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            executable = _write_file(Path(temporary) / "tool")
            process = _FakeProcess(stdout=b"partial", stays_running=True)
            original_start = threading.Thread.start
            start_calls = 0

            def fail_second_start(reader: threading.Thread) -> None:
                nonlocal start_calls
                start_calls += 1
                if start_calls == 2:
                    raise RuntimeError("synthetic second reader failure")
                original_start(reader)

            with (
                mock.patch(
                    "capability_map_core.clis.subprocess.Popen",
                    return_value=process,
                ),
                mock.patch(
                    "capability_map_core.clis.threading.Thread.start",
                    autospec=True,
                    side_effect=fail_second_start,
                ),
            ):
                result = probe_cli_version(executable, timeout=1)

            self.assertEqual(result.status, "error")
            self.assertTrue(process.terminate_called)
            self.assertTrue(process.wait_timeouts)
            self.assertTrue(process.stdout.closed)
            self.assertTrue(process.stderr.closed)
            self.assertFalse(
                any(
                    thread.name.startswith("cli-version-") and thread.is_alive()
                    for thread in threading.enumerate()
                )
            )

    def test_real_noisy_executable_is_stopped_without_capturing_full_output(self) -> None:
        if os.name == "nt":
            self.skipTest("POSIX executable fixture")
        with tempfile.TemporaryDirectory() as temporary:
            executable = _write_python_executable(
                Path(temporary) / "noisy-tool",
                "import os\n"
                "chunk = b'x' * 4096\n"
                "for _ in range(256):\n"
                "    os.write(1, chunk)\n"
                "    os.write(2, chunk)",
            )

            started = time.monotonic()
            result = probe_cli_version(
                executable,
                timeout=2,
                output_limit=1024,
                environ={"PATH": os.environ.get("PATH", "")},
            )

            self.assertLess(time.monotonic() - started, 3)
            self.assertLessEqual(len(result.output.encode("utf-8")), 1024)
            self.assertIn(result.status, {"nonzero", "success"})
            self.assertIn(
                "version_output_truncated",
                [diagnostic.code for diagnostic in result.diagnostics],
            )

    def test_stdout_and_stderr_share_one_output_budget(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            executable = _write_file(Path(temporary) / "tool")
            process = _FakeProcess(stdout=b"a" * 300, stderr=b"b" * 300)

            with mock.patch(
                "capability_map_core.clis.subprocess.Popen", return_value=process
            ):
                result = probe_cli_version(executable, output_limit=400)

            self.assertLessEqual(len(result.output.encode("utf-8")), 400)
            self.assertIn(
                "version_output_truncated",
                [diagnostic.code for diagnostic in result.diagnostics],
            )

    def test_stderr_spool_is_closed_and_uses_full_budget_when_stdout_empty(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            executable = _write_file(Path(temporary) / "tool")
            process = _FakeProcess(stderr=b"z" * 600)
            spools: list[object] = []
            real_temporary_file = tempfile.TemporaryFile

            def tracking_temporary_file(*args, **kwargs):
                spool = real_temporary_file(*args, **kwargs)
                spools.append(spool)
                return spool

            with (
                mock.patch(
                    "capability_map_core.clis.subprocess.Popen",
                    return_value=process,
                ),
                mock.patch(
                    "capability_map_core.clis.tempfile.TemporaryFile",
                    side_effect=tracking_temporary_file,
                ),
            ):
                result = probe_cli_version(executable, output_limit=257)

            self.assertEqual(result.output, "z" * 257)
            self.assertTrue(spools)
            self.assertTrue(all(spool.closed for spool in spools))

    def test_stderr_spool_never_writes_beyond_output_limit(self) -> None:
        if os.name == "nt":
            self.skipTest("Windows probing is securely unsupported")
        with tempfile.TemporaryDirectory() as temporary:
            executable = _write_python_executable(
                Path(temporary) / "noisy-stderr",
                "import os\n"
                "chunk = b'e' * 4096\n"
                "for _ in range(1024):\n"
                "    os.write(2, chunk)",
            )
            tracked_spools: list[_TrackingTemporaryFile] = []
            real_temporary_file = tempfile.TemporaryFile

            def tracking_temporary_file(*args, **kwargs):
                tracked = _TrackingTemporaryFile(
                    real_temporary_file(*args, **kwargs)
                )
                tracked_spools.append(tracked)
                return tracked

            with mock.patch(
                "capability_map_core.clis.tempfile.TemporaryFile",
                side_effect=tracking_temporary_file,
            ):
                result = probe_cli_version(
                    executable,
                    output_limit=257,
                    timeout=2.0,
                )

            self.assertTrue(tracked_spools)
            self.assertLessEqual(
                sum(spool.bytes_written for spool in tracked_spools),
                257,
            )
            self.assertLessEqual(len(result.output.encode("utf-8")), 257)
            self.assertIn(
                "version_output_truncated",
                [diagnostic.code for diagnostic in result.diagnostics],
            )
            self.assertTrue(all(spool.closed for spool in tracked_spools))


if __name__ == "__main__":
    unittest.main()

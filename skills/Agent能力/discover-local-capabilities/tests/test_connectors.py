"""Tests for bounded MCP configuration and verified plugin discovery."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import capability_map_core.connectors as connector_module  # noqa: E402
from capability_map_core.connectors import (  # noqa: E402
    MAX_CONFIG_BYTES,
    ConnectorConfigSpec,
    ConnectorDiscoveryResult,
    discover_connectors,
)
from capability_map_core.roots import RootSpec  # noqa: E402


def _write_json(path: Path, value: object, *, bom: bool = False) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, ensure_ascii=False).encode("utf-8")
    if bom:
        payload = b"\xef\xbb\xbf" + payload
    path.write_bytes(payload)
    return path


def _write_plugin(
    directory: Path,
    marker: str,
    manifest: dict[str, object],
    *,
    bom: bool = False,
) -> Path:
    return _write_json(directory / marker / "plugin.json", manifest, bom=bom)


def _mcp_by(result: ConnectorDiscoveryResult, name: str, provider: str):
    return next(
        capability
        for capability in result.capabilities
        if capability.kind == "mcp"
        and capability.name == name
        and capability.provider == provider
    )


class McpAdapterTests(unittest.TestCase):
    def test_discovers_all_supported_config_shapes_without_collapsing_names(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            home = base / "home"
            project = base / "project"
            (home / ".codex").mkdir(parents=True)
            (home / ".codex" / "config.toml").write_text(
                """
[mcp_servers.shared]
command = "safe-fixture"
enabled = false

[mcpServers.compatible]
url = "https://fixture.invalid/mcp"
enabled = true
""".strip(),
                encoding="utf-8",
            )
            _write_json(
                home / ".claude.json",
                {
                    "mcpServers": {
                        "shared": {"type": "sse", "url": "https://invalid/sse"}
                    }
                },
            )
            _write_json(
                project / ".mcp.json",
                {"mcpServers": {"project-server": {"command": "fixture"}}},
            )
            _write_json(
                project / ".vscode" / "mcp.json",
                {
                    "servers": {
                        "editor-server": {
                            "type": "http",
                            "url": "https://invalid/editor",
                            "disabled": True,
                        }
                    }
                },
            )

            result = discover_connectors(home=home, project=project)

            self.assertIsInstance(result, ConnectorDiscoveryResult)
            mcps = [item for item in result.capabilities if item.kind == "mcp"]
            self.assertEqual(len(mcps), 5)
            self.assertEqual(sum(item.name == "shared" for item in mcps), 2)
            self.assertEqual(
                _mcp_by(result, "shared", "codex").tags,
                ("enabled:disabled", "transport:stdio"),
            )
            self.assertEqual(
                _mcp_by(result, "compatible", "codex").tags,
                ("enabled:enabled", "transport:http"),
            )
            self.assertEqual(
                _mcp_by(result, "shared", "claude").tags,
                ("enabled:unknown", "transport:sse"),
            )
            self.assertEqual(
                _mcp_by(result, "project-server", "project-mcp").scope,
                "project",
            )
            self.assertEqual(
                _mcp_by(result, "editor-server", "vscode").tags,
                ("enabled:disabled", "transport:http"),
            )
            self.assertEqual(len({item.id for item in mcps}), len(mcps))
            self.assertEqual(len(result.resolvers), len(result.capabilities))

    def test_extra_config_specs_are_injected_and_toml_fallback_is_conservative(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            config = base / "portable.toml"
            config.write_text(
                '[mcp_servers."quoted-name"]\ntype = "streamable-http"\n'
                "disabled = false\n",
                encoding="utf-8",
            )
            spec = ConnectorConfigSpec(
                config,
                "extra",
                "portable-codex",
                "toml",
                "extra:portable-codex",
                "<extra-config:portable-codex>",
            )

            with mock.patch.object(connector_module, "_tomllib", None):
                result = discover_connectors(
                    home=base / "empty-home", extra_config_paths=[spec]
                )

            capability = _mcp_by(result, "quoted-name", "portable-codex")
            self.assertEqual(
                capability.tags,
                ("enabled:enabled", "transport:http"),
            )

    def test_toml_fallback_accepts_common_values_and_ignores_nested_env(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            config = base / "codex.toml"
            secret = "gh" + "p_" + "fallback_nested_canary"
            config.write_text(
                """
title = "ignored root value"

[mcp_servers.alpha]
command = "fixture-command"
args = ["--flag", "value"]
enabled = true

[mcp_servers.alpha.env]
TOKEN = "SECRET_CANARY"
COMPLEX = { nested = ["ignored"] }

[mcp_servers."quoted.server"]
type = "sse"
args = []
disabled = false

[mcp_servers.'disabled server']
url = "https://fixture.invalid/private"
disabled = true

[unrelated.table]
values = [1, 2, 3]
""".replace("SECRET_CANARY", secret).strip(),
                encoding="utf-8",
            )
            spec = ConnectorConfigSpec(
                config,
                "extra",
                "fallback-codex",
                "toml",
                "extra:fallback-codex",
                "<extra-config:fallback-codex>",
            )

            with mock.patch.object(connector_module, "_tomllib", None):
                result = discover_connectors(
                    home=base / "empty-home", extra_config_paths=[spec]
                )

            mcps = [item for item in result.capabilities if item.kind == "mcp"]
            self.assertEqual(
                [(item.name, item.tags) for item in mcps],
                [
                    ("alpha", ("enabled:enabled", "transport:stdio")),
                    (
                        "disabled server",
                        ("enabled:disabled", "transport:http"),
                    ),
                    (
                        "quoted.server",
                        ("enabled:enabled", "transport:sse"),
                    ),
                ],
            )
            self.assertNotIn("env", {item.name for item in mcps})
            self.assertNotIn(
                "invalid_toml", {item.code for item in result.diagnostics}
            )
            public = json.dumps(
                [item.to_public_dict() for item in result.capabilities],
                ensure_ascii=True,
            )
            self.assertNotIn(secret, public)

    def test_mcp_public_output_never_contains_arbitrary_configuration_values(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            home = base / "named-home"
            project = base / "project"
            secret = "gh" + "p_" + "synthetic_connector_canary"
            nested_secret = "sk-" + "synthetic_connector_nested"
            command_path = str(base / "named-home" / "private" / "command")
            config = {
                "mcpServers": {
                    "safe-server": {
                        "command": command_path,
                        "args": ["--token", secret],
                        "url": "https://fixture.invalid/private-route",
                        "headers": {"Authorization": "Bearer " + secret},
                        "env": {"TOKEN": nested_secret},
                        "token": secret,
                        "nested": {"payload": [secret, command_path]},
                    }
                }
            }
            config_path = _write_json(project / ".mcp.json", config)

            result = discover_connectors(home=home, project=project)

            capability = _mcp_by(result, "safe-server", "project-mcp")
            public = capability.to_public_dict()
            serialized = json.dumps(public, ensure_ascii=False, sort_keys=True)
            for forbidden in (
                secret,
                nested_secret,
                command_path,
                "private-route",
                "Authorization",
                "command",
                "args",
                "headers",
                "env",
                "token",
                "nested",
                "payload",
            ):
                self.assertNotIn(forbidden, serialized)
            self.assertEqual(public["description"], "")
            self.assertEqual(public["aliases"], [])
            self.assertEqual(public["scenes"], [])
            self.assertEqual(public["version"], None)
            self.assertEqual(
                public["tags"], ["enabled:unknown", "transport:stdio"]
            )
            resolver = next(
                item
                for item in result.resolvers
                if item.resolver_id == capability.resolver_id
            )
            self.assertEqual(resolver.exact_locations, (str(config_path.resolve()),))
            self.assertNotIn(str(base), serialized)

    def test_bom_invalid_oversized_deep_and_permission_are_isolated_diagnostics(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            healthy = _write_json(
                base / "healthy.json",
                {"mcpServers": {"healthy": {"command": "fixture"}}},
                bom=True,
            )
            invalid = base / "invalid.json"
            invalid.write_text("{ damaged", encoding="utf-8")
            oversized = base / "oversized.json"
            oversized.write_bytes(b"{" + b" " * MAX_CONFIG_BYTES + b"}")
            deep = base / "deep.json"
            deep.write_text("[" * 80 + "0" + "]" * 80, encoding="utf-8")
            denied = base / "denied.json"
            denied.write_text("{}", encoding="utf-8")
            specs = [
                ConnectorConfigSpec(
                    path,
                    "extra",
                    f"fixture-{index}",
                    "json",
                    f"extra:fixture:{index}",
                    f"<extra-config:{index}>",
                )
                for index, path in enumerate(
                    (healthy, invalid, oversized, deep, denied), start=1
                )
            ]
            real_open = connector_module.os.open

            def guarded_open(path: object, flags: int, *args: object, **kwargs: object):
                if Path(path) == denied.resolve():  # type: ignore[arg-type]
                    raise PermissionError("synthetic permission denial")
                return real_open(path, flags, *args, **kwargs)

            with mock.patch("capability_map_core.connectors.os.open", guarded_open):
                result = discover_connectors(
                    home=base / "empty-home", extra_config_paths=specs
                )

            self.assertEqual(
                [item.name for item in result.capabilities], ["healthy"]
            )
            codes = {item.code for item in result.diagnostics}
            self.assertIn("bom_detected", codes)
            self.assertIn("invalid_json", codes)
            self.assertIn("config_too_large", codes)
            self.assertIn("structure_too_deep", codes)
            self.assertIn("permission_denied", codes)
            public_diagnostics = json.dumps(
                [item.to_public_dict() for item in result.diagnostics],
                ensure_ascii=False,
            )
            self.assertNotIn(str(base), public_diagnostics)

    def test_default_discovery_never_executes_or_opens_network_connections(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            _write_json(
                base / "project" / ".mcp.json",
                {"mcpServers": {"fixture": {"command": "fixture"}}},
            )
            with mock.patch.object(
                subprocess, "Popen", side_effect=AssertionError("must not execute")
            ), mock.patch.object(
                subprocess, "run", side_effect=AssertionError("must not execute")
            ), mock.patch(
                "socket.socket", side_effect=AssertionError("must not use network")
            ):
                result = discover_connectors(
                    home=base / "home", project=base / "project"
                )

            self.assertEqual(len(result.capabilities), 1)

    def test_generator_of_injected_config_specs_and_paths_is_consumed_once(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            first = _write_json(
                base / "first.json",
                {"mcpServers": {"first": {"command": "fixture"}}},
            )
            second = _write_json(
                base / "second.json",
                {"mcpServers": {"second": {"command": "fixture"}}},
            )
            injected = (
                item
                for item in (
                    first,
                    ConnectorConfigSpec(
                        second,
                        "extra",
                        "second-provider",
                        "json",
                        "extra:second",
                        "<extra:second>",
                    ),
                )
            )

            result = discover_connectors(
                home=base / "empty-home", extra_config_paths=injected
            )

            self.assertEqual(
                {item.name for item in result.capabilities}, {"first", "second"}
            )

    def test_duplicate_logical_keys_keep_distinct_sources_deterministically(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            first_path = _write_json(
                base / "first.json",
                {"mcpServers": {"shared": {"command": "fixture"}}},
            )
            second_path = _write_json(
                base / "second.json",
                {"mcpServers": {"shared": {"type": "sse"}}},
            )
            first = ConnectorConfigSpec(
                first_path,
                "extra",
                "same-provider",
                "json",
                "duplicate-logical-key",
                "<first-source>",
            )
            second = ConnectorConfigSpec(
                second_path,
                "extra",
                "same-provider",
                "json",
                "duplicate-logical-key",
                "<second-source>",
            )

            forward = discover_connectors(
                home=base / "empty-home",
                extra_config_paths=[first, second, first],
            )
            reverse = discover_connectors(
                home=base / "empty-home",
                extra_config_paths=[second, first, second],
            )

            forward_mcps = [item for item in forward.capabilities if item.kind == "mcp"]
            reverse_mcps = [item for item in reverse.capabilities if item.kind == "mcp"]
            self.assertEqual(len(forward_mcps), 2)
            self.assertEqual(len(reverse_mcps), 2)
            self.assertEqual(len({item.id for item in forward_mcps}), 2)
            self.assertEqual(
                [item.to_public_dict() for item in forward_mcps],
                [item.to_public_dict() for item in reverse_mcps],
            )
            self.assertEqual(
                {
                    source.location
                    for item in forward_mcps
                    for source in item.source_locations
                },
                {"<first-source>", "<second-source>"},
            )

    @unittest.skipUnless(
        hasattr(os, "mkfifo") and hasattr(os, "O_NONBLOCK"),
        "nonblocking FIFOs are required",
    )
    def test_config_swap_to_fifo_is_opened_nonblocking_and_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            config = _write_json(
                base / "racy.json",
                {"mcpServers": {"must-not-load": {"command": "fixture"}}},
            )
            spec = ConnectorConfigSpec(
                config,
                "extra",
                "race-fixture",
                "json",
                "extra:race-fixture",
                "<racy-config>",
            )
            real_open = connector_module.os.open
            swapped = False

            def swap_before_open(
                path: object, flags: int, *args: object, **kwargs: object
            ) -> int:
                nonlocal swapped
                if (
                    not swapped
                    and not isinstance(path, int)
                    and Path(path).name == config.name
                ):
                    swapped = True
                    config.unlink()
                    os.mkfifo(config)
                    self.assertTrue(flags & os.O_NONBLOCK)
                return real_open(path, flags, *args, **kwargs)

            started = time.monotonic()
            with mock.patch(
                "capability_map_core.connectors.os.open", swap_before_open
            ):
                result = discover_connectors(
                    home=base / "empty-home", extra_config_paths=[spec]
                )

            self.assertLess(time.monotonic() - started, 1.0)
            self.assertTrue(swapped)
            self.assertFalse(result.capabilities)
            self.assertIn(
                "source_changed", {item.code for item in result.diagnostics}
            )

    @unittest.skipUnless(hasattr(os, "mkfifo"), "FIFOs are required")
    def test_existing_fifo_is_rejected_as_not_regular_without_opening(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            fifo = base / "config.json"
            os.mkfifo(fifo)
            spec = ConnectorConfigSpec(
                fifo,
                "extra",
                "fifo-fixture",
                "json",
                "extra:fifo-fixture",
                "<fifo-config>",
            )
            real_open = connector_module.os.open

            def reject_fifo_open(
                path: object, flags: int, *args: object, **kwargs: object
            ) -> int:
                if not isinstance(path, int) and Path(path) == fifo:
                    raise AssertionError("a known FIFO must not be opened")
                return real_open(path, flags, *args, **kwargs)

            with mock.patch(
                "capability_map_core.connectors.os.open", reject_fifo_open
            ):
                result = discover_connectors(
                    home=base / "empty-home", extra_config_paths=[spec]
                )

            self.assertFalse(result.capabilities)
            self.assertIn(
                "not_regular_file", {item.code for item in result.diagnostics}
            )

    def test_invalid_unicode_mcp_name_is_skipped_and_later_item_continues(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            config = base / "unicode.json"
            config.write_text(
                json.dumps(
                    {
                        "mcpServers": {
                            "\ud800-invalid": {"command": "fixture"},
                            "healthy": {"command": "fixture"},
                        }
                    }
                ),
                encoding="utf-8",
            )
            spec = ConnectorConfigSpec(
                config,
                "extra",
                "unicode-fixture",
                "json",
                "extra:unicode-fixture",
                "<unicode-config>",
            )

            result = discover_connectors(
                home=base / "empty-home", extra_config_paths=[spec]
            )

            self.assertEqual(
                [item.name for item in result.capabilities], ["healthy"]
            )
            self.assertIn(
                "invalid_unicode", {item.code for item in result.diagnostics}
            )

    def test_toml_fallback_rejects_invalid_lines_and_unbalanced_values(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            invalid_line = base / "invalid-line.toml"
            invalid_line.write_text(
                '[mcp_servers.first]\ncommand = "fixture"\nthis is invalid\n',
                encoding="utf-8",
            )
            invalid_array = base / "invalid-array.toml"
            invalid_array.write_text(
                '[mcp_servers.second]\ncommand = "fixture"\nargs = ["broken"\n',
                encoding="utf-8",
            )
            specs = [
                ConnectorConfigSpec(
                    path,
                    "extra",
                    f"invalid-{index}",
                    "toml",
                    f"invalid:{index}",
                    f"<invalid:{index}>",
                )
                for index, path in enumerate((invalid_line, invalid_array), start=1)
            ]

            with mock.patch.object(connector_module, "_tomllib", None):
                result = discover_connectors(
                    home=base / "empty-home", extra_config_paths=specs
                )

            self.assertFalse(result.capabilities)
            self.assertEqual(
                sum(item.code == "invalid_toml" for item in result.diagnostics),
                2,
            )

    def test_same_mcp_name_in_different_container_namespaces_is_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            config = _write_json(
                base / "containers.json",
                {
                    "mcp_servers": {"shared": {"command": "fixture"}},
                    "mcpServers": {"shared": {"type": "sse"}},
                    "servers": {"shared": {"type": "http"}},
                },
            )
            spec = ConnectorConfigSpec(
                config,
                "extra",
                "container-fixture",
                "json",
                "container-fixture",
                "<container-fixture>",
            )

            result = discover_connectors(
                home=base / "empty-home", extra_config_paths=[spec]
            )

            mcps = [item for item in result.capabilities if item.kind == "mcp"]
            self.assertEqual(len(mcps), 3)
            self.assertEqual(len({item.id for item in mcps}), 3)
            self.assertEqual(
                {item.tags for item in mcps},
                {
                    ("enabled:unknown", "transport:stdio"),
                    ("enabled:unknown", "transport:sse"),
                    ("enabled:unknown", "transport:http"),
                },
            )

    def test_equal_size_rewrite_with_restored_mtime_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            config = _write_json(
                base / "rewrite.json",
                {"mcpServers": {"alpha": {"command": "fixture"}}},
            )
            replacement = json.dumps(
                {"mcpServers": {"bravo": {"command": "fixture"}}}
            ).encode("utf-8")
            self.assertEqual(len(replacement), config.stat().st_size)
            original_times = config.stat()
            real_open = connector_module.os.open
            rewritten = False

            def rewrite_before_open(
                path: object, flags: int, *args: object, **kwargs: object
            ) -> int:
                nonlocal rewritten
                if (
                    not rewritten
                    and not isinstance(path, int)
                    and Path(path).name == config.name
                ):
                    rewritten = True
                    config.write_bytes(replacement)
                    os.utime(
                        config,
                        ns=(original_times.st_atime_ns, original_times.st_mtime_ns),
                    )
                return real_open(path, flags, *args, **kwargs)

            spec = ConnectorConfigSpec(
                config,
                "extra",
                "rewrite-fixture",
                "json",
                "rewrite-fixture",
                "<rewrite-fixture>",
            )
            with mock.patch(
                "capability_map_core.connectors.os.open", rewrite_before_open
            ):
                result = discover_connectors(
                    home=base / "empty-home", extra_config_paths=[spec]
                )

            self.assertTrue(rewritten)
            self.assertFalse(result.capabilities)
            self.assertIn(
                "source_changed", {item.code for item in result.diagnostics}
            )

    def test_environment_override_case_folding_depends_on_injected_platform(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            home = base / "home"
            portable = base / "portable"
            (home / ".codex").mkdir(parents=True)
            (portable).mkdir(parents=True)
            (home / ".codex" / "config.toml").write_text(
                '[mcp_servers.unix-default]\ncommand = "fixture"\n',
                encoding="utf-8",
            )
            (portable / "config.toml").write_text(
                '[mcp_servers.windows-override]\ncommand = "fixture"\n',
                encoding="utf-8",
            )
            environment = {"codex_home": str(portable)}

            unix = discover_connectors(
                home=home, environ=environment, platform_name="Linux"
            )
            windows = discover_connectors(
                home=home, environ=environment, platform_name="Windows"
            )

            self.assertEqual(
                [item.name for item in unix.capabilities], ["unix-default"]
            )
            self.assertEqual(
                [item.name for item in windows.capabilities], ["windows-override"]
            )

    @unittest.skipUnless(hasattr(os, "symlink"), "symlinks are required")
    def test_broken_config_symlink_is_distinct_from_missing_config(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            broken = base / "broken.json"
            broken.symlink_to(base / "missing-target.json")
            spec = ConnectorConfigSpec(
                broken,
                "extra",
                "broken-fixture",
                "json",
                "broken-fixture",
                "<broken-fixture>",
            )

            result = discover_connectors(
                home=base / "empty-home", extra_config_paths=[spec]
            )

            self.assertFalse(result.capabilities)
            self.assertIn(
                "broken_symlink", {item.code for item in result.diagnostics}
            )


class PluginDiscoveryTests(unittest.TestCase):
    def test_only_real_nested_manifests_are_plugins_and_versions_remain_distinct(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = base / "cache"
            (root / "publisher-without-manifest" / "package" / "1.0").mkdir(
                parents=True
            )
            first = root / "publisher" / "alpha" / "1.0.0"
            second = root / "publisher" / "alpha" / "2.0.0"
            third = root / "other" / "beta" / "nested"
            _write_plugin(
                first,
                ".codex-plugin",
                {
                    "name": "alpha-plugin",
                    "version": "1.0.0",
                    "description": "first version",
                    "keywords": ["automation", "local"],
                    "provider": "fixture-publisher",
                },
            )
            _write_plugin(
                second,
                ".codex-plugin",
                {
                    "name": "alpha-plugin",
                    "version": "2.0.0",
                    "description": "second version",
                    "keywords": ["automation"],
                    "provider": "fixture-publisher",
                },
            )
            _write_plugin(
                third,
                ".claude-plugin",
                {"name": "beta-plugin", "version": "0.2.0"},
            )

            result = discover_connectors(home=base / "home", plugin_roots=[root])

            plugins = [item for item in result.capabilities if item.kind == "plugin"]
            self.assertEqual(len(plugins), 3)
            self.assertEqual(
                [(item.name, item.version) for item in plugins],
                [
                    ("alpha-plugin", "1.0.0"),
                    ("alpha-plugin", "2.0.0"),
                    ("beta-plugin", "0.2.0"),
                ],
            )
            self.assertEqual(plugins[0].tags, ("automation", "local"))
            self.assertEqual(plugins[0].provider, "fixture-publisher")
            self.assertEqual(plugins[2].provider, "claude-plugin")
            self.assertEqual(len(result.skill_roots), 3)
            self.assertTrue(all(isinstance(item, RootSpec) for item in result.skill_roots))

    def test_plugin_metadata_is_sanitized_and_paths_exist_only_in_resolvers(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = base / "plugin-root"
            plugin_directory = root / "publisher" / "unsafe"
            secret = "gh" + "p_" + "synthetic_plugin_canary"
            manifest_path = _write_plugin(
                plugin_directory,
                ".codex-plugin",
                {
                    "name": "safe-plugin\nname",
                    "version": "1.0\nprivate",
                    "description": f"token={secret}\n{base / 'private'}",
                    "keywords": ["safe", f"password={secret}", str(base / "keyword")],
                    "provider": "provider\nfixture",
                    "arbitrary": {"secret": secret},
                },
            )

            result = discover_connectors(home=base / "home", plugin_roots=[root])

            plugin = next(item for item in result.capabilities if item.kind == "plugin")
            serialized = json.dumps(
                plugin.to_public_dict(), ensure_ascii=False, sort_keys=True
            )
            self.assertEqual(plugin.name, "safe-plugin name")
            self.assertEqual(plugin.version, "1.0 private")
            self.assertEqual(plugin.provider, "provider fixture")
            self.assertNotIn(secret, serialized)
            self.assertNotIn(str(base), serialized)
            self.assertNotIn("arbitrary", serialized)
            resolver = next(
                item
                for item in result.resolvers
                if item.resolver_id == plugin.resolver_id
            )
            self.assertIn(str(manifest_path.resolve()), resolver.exact_locations)
            self.assertIn(str(plugin_directory.resolve()), resolver.exact_locations)

    def test_malformed_manifest_is_diagnostic_and_other_plugins_continue(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = base / "plugins"
            malformed = root / "malformed" / ".codex-plugin" / "plugin.json"
            malformed.parent.mkdir(parents=True)
            malformed.write_text("{broken", encoding="utf-8")
            _write_plugin(
                root / "missing-name",
                ".claude-plugin",
                {"version": "1.0.0"},
            )
            _write_plugin(
                root / "healthy",
                ".claude-plugin",
                {"name": "healthy-plugin", "version": "1.0.0"},
                bom=True,
            )

            result = discover_connectors(home=base / "home", plugin_roots=[root])

            plugins = [item for item in result.capabilities if item.kind == "plugin"]
            self.assertEqual([item.name for item in plugins], ["healthy-plugin"])
            codes = {item.code for item in result.diagnostics}
            self.assertIn("invalid_json", codes)
            self.assertIn("plugin_name_missing", codes)
            self.assertIn("bom_detected", codes)

    def test_plugin_declared_mcp_and_verified_skill_root_are_returned(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = base / "plugins"
            plugin_directory = root / "publisher" / "bundle" / "3.0.0"
            manifest_path = _write_plugin(
                plugin_directory,
                ".claude-plugin",
                {
                    "name": "bundle-plugin",
                    "version": "3.0.0",
                    "provider": "bundle-publisher",
                    "mcpServers": {
                        "embedded": {
                            "type": "sse",
                            "url": "https://fixture.invalid/private",
                            "enabled": True,
                        }
                    },
                },
            )
            skill_file = plugin_directory / "skills" / "nested" / "SKILL.md"
            skill_file.parent.mkdir(parents=True)
            skill_file.write_text("---\nname: nested\n---\n", encoding="utf-8")

            result = discover_connectors(home=base / "home", plugin_roots=[root])

            mcp = _mcp_by(result, "embedded", "bundle-plugin")
            self.assertEqual(mcp.scope, "plugin")
            self.assertEqual(
                mcp.tags, ("enabled:enabled", "transport:sse")
            )
            mcp_resolver = next(
                item
                for item in result.resolvers
                if item.resolver_id == mcp.resolver_id
            )
            self.assertEqual(
                mcp_resolver.exact_locations, (str(manifest_path.resolve()),)
            )
            self.assertEqual(len(result.skill_roots), 1)
            skill_root = result.skill_roots[0]
            self.assertEqual(skill_root.path, plugin_directory.resolve())
            self.assertEqual(skill_root.scope, "plugin")
            self.assertEqual(skill_root.provider, "bundle-plugin")
            self.assertNotIn(str(base), skill_root.logical_key)

    @unittest.skipUnless(hasattr(os, "symlink"), "symlinks are required")
    def test_symlink_plugin_directory_and_manifest_escape_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = base / "plugins"
            outside = base / "outside"
            outside_plugin = outside / "escaped"
            outside_manifest = _write_plugin(
                outside_plugin,
                ".codex-plugin",
                {"name": "must-not-escape", "version": "1"},
            )
            root.mkdir(parents=True)
            (root / "directory-link").symlink_to(
                outside_plugin, target_is_directory=True
            )
            local_marker = root / "file-link" / ".claude-plugin"
            local_marker.mkdir(parents=True)
            (local_marker / "plugin.json").symlink_to(outside_manifest)

            result = discover_connectors(home=base / "home", plugin_roots=[root])

            self.assertFalse(result.capabilities)
            codes = {item.code for item in result.diagnostics}
            self.assertIn("symlink_directory_rejected", codes)
            self.assertIn("symlink_manifest_rejected", codes)

    def test_ordering_is_deterministic_across_input_order(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            first_root = base / "z-root"
            second_root = base / "a-root"
            _write_plugin(
                first_root / "z", ".codex-plugin", {"name": "zeta", "version": "1"}
            )
            _write_plugin(
                second_root / "a", ".claude-plugin", {"name": "alpha", "version": "1"}
            )
            first_config = _write_json(
                base / "z.json", {"mcpServers": {"z-server": {"command": "x"}}}
            )
            second_config = _write_json(
                base / "a.json", {"mcpServers": {"a-server": {"command": "x"}}}
            )
            config_specs = [
                ConnectorConfigSpec(
                    first_config,
                    "extra",
                    "z-provider",
                    "json",
                    "extra:z",
                    "<extra:z>",
                ),
                ConnectorConfigSpec(
                    second_config,
                    "extra",
                    "a-provider",
                    "json",
                    "extra:a",
                    "<extra:a>",
                ),
            ]

            forward = discover_connectors(
                home=base / "home",
                extra_config_paths=config_specs,
                plugin_roots=[first_root, second_root],
            )
            reverse = discover_connectors(
                home=base / "home",
                extra_config_paths=list(reversed(config_specs)),
                plugin_roots=[second_root, first_root],
            )

            self.assertEqual(
                [item.to_public_dict() for item in forward.capabilities],
                [item.to_public_dict() for item in reverse.capabilities],
            )
            self.assertEqual(
                [item.to_private_dict() for item in forward.resolvers],
                [item.to_private_dict() for item in reverse.resolvers],
            )
            self.assertEqual(
                [
                    (item.scope, item.provider, item.logical_key, item.public_prefix)
                    for item in forward.skill_roots
                ],
                [
                    (item.scope, item.provider, item.logical_key, item.public_prefix)
                    for item in reverse.skill_roots
                ],
            )

    def test_plugin_directory_read_failure_does_not_stop_other_roots(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            denied_root = base / "denied"
            healthy_root = base / "healthy"
            denied_root.mkdir()
            _write_plugin(
                healthy_root / "plugin",
                ".codex-plugin",
                {"name": "healthy-plugin", "version": "1"},
            )
            denied_id = (denied_root.stat().st_dev, denied_root.stat().st_ino)
            real_scandir = connector_module.os.scandir

            def guarded_scandir(path: object):
                if isinstance(path, int):
                    value = os.fstat(path)
                    if (value.st_dev, value.st_ino) == denied_id:
                        raise PermissionError("synthetic directory denial")
                return real_scandir(path)  # type: ignore[arg-type]

            with mock.patch(
                "capability_map_core.connectors.os.scandir", guarded_scandir
            ):
                result = discover_connectors(
                    home=base / "empty-home",
                    plugin_roots=[denied_root, healthy_root],
                )

            self.assertEqual(
                [item.name for item in result.capabilities], ["healthy-plugin"]
            )
            self.assertIn(
                "permission_denied", {item.code for item in result.diagnostics}
            )

    @unittest.skipUnless(
        hasattr(os, "mkfifo") and hasattr(os, "O_NONBLOCK"),
        "nonblocking FIFOs are required",
    )
    def test_manifest_swap_to_fifo_is_opened_nonblocking_and_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = base / "plugins"
            manifest = _write_plugin(
                root / "racy",
                ".codex-plugin",
                {"name": "must-not-load", "version": "1"},
            )
            real_open = connector_module.os.open
            swapped = False

            def swap_before_open(
                path: object, flags: int, *args: object, **kwargs: object
            ) -> int:
                nonlocal swapped
                if (
                    not swapped
                    and path == "plugin.json"
                    and kwargs.get("dir_fd") is not None
                ):
                    swapped = True
                    manifest.unlink()
                    os.mkfifo(manifest)
                    self.assertTrue(flags & os.O_NONBLOCK)
                return real_open(path, flags, *args, **kwargs)

            started = time.monotonic()
            with mock.patch(
                "capability_map_core.connectors.os.open", swap_before_open
            ):
                result = discover_connectors(
                    home=base / "empty-home", plugin_roots=[root]
                )

            self.assertLess(time.monotonic() - started, 1.0)
            self.assertTrue(swapped)
            self.assertFalse(result.capabilities)
            self.assertIn(
                "source_changed", {item.code for item in result.diagnostics}
            )

    def test_invalid_unicode_plugin_metadata_is_skipped_per_item(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = base / "plugins"
            manifests = (
                ("invalid-name", {"name": "\ud800-name", "version": "1"}),
                (
                    "invalid-description",
                    {
                        "name": "bad-description",
                        "version": "1",
                        "description": "\ud800-description",
                    },
                ),
                (
                    "invalid-keyword",
                    {
                        "name": "bad-keyword",
                        "version": "1",
                        "keywords": ["safe", "\ud800-keyword"],
                    },
                ),
                ("healthy", {"name": "healthy-plugin", "version": "1"}),
            )
            for directory, manifest in manifests:
                path = root / directory / ".claude-plugin" / "plugin.json"
                path.parent.mkdir(parents=True)
                path.write_text(json.dumps(manifest), encoding="utf-8")

            result = discover_connectors(
                home=base / "empty-home", plugin_roots=[root]
            )

            plugins = [item for item in result.capabilities if item.kind == "plugin"]
            self.assertEqual([item.name for item in plugins], ["healthy-plugin"])
            self.assertEqual(
                sum(item.code == "invalid_unicode" for item in result.diagnostics),
                3,
            )

    def test_insecure_plugin_backend_is_skipped_without_losing_mcp_results(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            config = _write_json(
                base / "mcp.json",
                {"mcpServers": {"healthy-mcp": {"command": "fixture"}}},
            )
            spec = ConnectorConfigSpec(
                config,
                "extra",
                "healthy-provider",
                "json",
                "healthy-config",
                "<healthy-config>",
            )
            root = base / "plugins"
            _write_plugin(
                root / "plugin",
                ".codex-plugin",
                {"name": "must-not-load", "version": "1"},
            )

            with mock.patch.object(connector_module.os, "supports_fd", set()):
                result = discover_connectors(
                    home=base / "empty-home",
                    extra_config_paths=[spec],
                    plugin_roots=[root],
                    platform_name="Windows",
                )

            self.assertEqual(
                [item.name for item in result.capabilities], ["healthy-mcp"]
            )
            self.assertIn(
                "secure_plugin_backend_unavailable",
                {item.code for item in result.diagnostics},
            )

    def test_plugin_backend_typeerror_is_isolated(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = base / "plugins"
            _write_plugin(
                root / "plugin",
                ".codex-plugin",
                {"name": "must-not-load", "version": "1"},
            )
            with mock.patch(
                "capability_map_core.connectors.os.scandir",
                side_effect=TypeError("synthetic unsupported fd scandir"),
            ):
                result = discover_connectors(
                    home=base / "empty-home", plugin_roots=[root]
                )

            self.assertFalse(result.capabilities)
            self.assertIn(
                "secure_plugin_backend_unavailable",
                {item.code for item in result.diagnostics},
            )

    def test_verified_child_directory_closes_fd_on_baseexception(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            child = parent / "child"
            child.mkdir()
            expected = child.stat()
            parent_fd = os.open(parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            real_open = connector_module.os.open
            real_fstat = connector_module.os.fstat
            child_fd: int | None = None

            def recording_open(
                path: object, flags: int, *args: object, **kwargs: object
            ) -> int:
                nonlocal child_fd
                fd = real_open(path, flags, *args, **kwargs)
                if path == "child" and kwargs.get("dir_fd") == parent_fd:
                    child_fd = fd
                return fd

            def failing_fstat(fd: int):
                if child_fd is not None and fd == child_fd:
                    raise KeyboardInterrupt("synthetic fstat failure")
                return real_fstat(fd)

            try:
                with mock.patch(
                    "capability_map_core.connectors.os.open", recording_open
                ), mock.patch(
                    "capability_map_core.connectors.os.fstat", failing_fstat
                ):
                    with self.assertRaises(KeyboardInterrupt):
                        connector_module._open_verified_child_directory(
                            parent_fd, "child", expected
                        )
                self.assertIsNotNone(child_fd)
                with self.assertRaises(OSError):
                    real_fstat(child_fd)  # type: ignore[arg-type]
            finally:
                os.close(parent_fd)

    def test_plugin_entry_limit_is_deterministic_across_scandir_order(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = base / "plugins"
            _write_plugin(
                root / "a-plugin",
                ".codex-plugin",
                {"name": "alpha", "version": "1"},
            )
            for name in ("one", "two", "three", "four"):
                (root / "z-overflow" / name).mkdir(parents=True)
            real_scandir = connector_module.os.scandir
            root_id = (root.stat().st_dev, root.stat().st_ino)

            class ReorderedScandir:
                def __init__(self, target: object, reverse: bool) -> None:
                    self._wrapped = real_scandir(target)  # type: ignore[arg-type]
                    entries = list(self._wrapped)
                    if isinstance(target, int):
                        target_stat = os.fstat(target)
                        if (target_stat.st_dev, target_stat.st_ino) == root_id:
                            entries.sort(key=lambda item: item.name, reverse=reverse)
                    self._entries = entries

                def __enter__(self):
                    return iter(self._entries)

                def __exit__(self, *args: object) -> None:
                    self._wrapped.close()

            def scan(reverse: bool):
                with mock.patch.object(connector_module, "MAX_PLUGIN_ENTRIES", 5), mock.patch(
                    "capability_map_core.connectors.os.scandir",
                    side_effect=lambda target: ReorderedScandir(target, reverse),
                ), mock.patch.object(
                    connector_module,
                    "_secure_plugin_backend_supported",
                    return_value=True,
                ):
                    return discover_connectors(
                        home=base / "empty-home", plugin_roots=[root]
                    )

            forward = scan(False)
            reverse = scan(True)

            self.assertEqual(
                [item.to_public_dict() for item in forward.capabilities],
                [item.to_public_dict() for item in reverse.capabilities],
            )
            self.assertFalse(forward.capabilities)
            self.assertIn(
                "plugin_entry_limit", {item.code for item in forward.diagnostics}
            )


if __name__ == "__main__":
    unittest.main()

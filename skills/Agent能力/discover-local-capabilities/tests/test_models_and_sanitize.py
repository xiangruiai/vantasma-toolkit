"""Tests for the public capability model and recursive sanitizer."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from capability_map_core.models import (  # noqa: E402
    Capability,
    CapabilityStates,
    Diagnostic,
    InventoryMetadata,
    ResolverRecord,
    SourceLocation,
)
from capability_map_core.sanitize import sanitize, sanitize_text  # noqa: E402


class CapabilityModelTests(unittest.TestCase):
    def test_public_schema_is_complete_and_states_are_conservative(self) -> None:
        capability = Capability(
            kind="skill",
            name="Example Skill",
            description="A local example.",
            aliases=["example"],
            tags=["automation"],
            scenes=["workflow"],
            source_locations=[
                SourceLocation("~/.agents/skills/example", "user", "shared")
            ],
            scope="user",
            provider="shared",
            version="1.2.3",
            diagnostics=[Diagnostic("warning", "metadata_partial", "Partial metadata")],
        )

        public = capability.to_public_dict()

        self.assertEqual(
            set(public),
            {
                "id",
                "kind",
                "name",
                "description",
                "aliases",
                "tags",
                "scenes",
                "source_locations",
                "resolver_id",
                "scope",
                "provider",
                "version",
                "states",
                "classification_confidence",
                "diagnostics",
            },
        )
        self.assertEqual(
            public["states"],
            {
                "discovered": "success",
                "probed": "unknown",
                "authenticated": "unknown",
                "verified": "unknown",
            },
        )
        self.assertEqual(public["classification_confidence"], 0.0)
        self.assertEqual(public["source_locations"][0]["location"], "~/.agents/skills/example")

    def test_ids_are_opaque_deterministic_and_path_independent(self) -> None:
        first = Capability(
            kind="skill",
            name="Portable Skill",
            provider="shared",
            scope="user",
            source_locations=[SourceLocation("/Users/alice/.agents/skills/portable")],
        )
        second = Capability(
            kind="skill",
            name="Portable Skill",
            provider="shared",
            scope="user",
            source_locations=[SourceLocation("/home/bob/.agents/skills/portable")],
        )

        self.assertEqual(first.id, second.id)
        self.assertEqual(first.resolver_id, second.resolver_id)
        self.assertRegex(first.id, r"^cap_[0-9a-f]{24}$")
        self.assertRegex(first.resolver_id, r"^res_[0-9a-f]{24}$")
        self.assertNotIn("alice", first.id)
        self.assertNotIn("portable", first.id)

    def test_public_serialization_excludes_private_and_unknown_fields(self) -> None:
        class ExtendedCapability(Capability):
            pass

        exact_path = "/Users/alice/private/skill/SKILL.md"
        capability = ExtendedCapability(
            kind="skill",
            name="Private Skill",
            source_locations=[SourceLocation(exact_path)],
        )
        capability.private_path = exact_path
        capability.unknown_field = "must not be serialized"
        resolver = ResolverRecord(capability.resolver_id, [exact_path])

        public_json = json.dumps(capability.to_public_dict(), sort_keys=True)
        private_json = json.dumps(resolver.to_private_dict(), sort_keys=True)

        self.assertNotIn(exact_path, public_json)
        self.assertNotIn("private_path", public_json)
        self.assertNotIn("unknown_field", public_json)
        self.assertIn(exact_path, private_json)

    def test_public_serialization_has_stable_ordering(self) -> None:
        capability = Capability(
            kind="cli",
            name="runner",
            aliases=["Zulu", "alpha", "alpha"],
            tags=["utility", "build"],
            scenes=["testing", "automation"],
            source_locations=[
                SourceLocation("~/z", "user", "second"),
                SourceLocation("~/a", "user", "first"),
            ],
            diagnostics=[
                Diagnostic("warning", "z_code", "Last"),
                Diagnostic("info", "a_code", "First"),
            ],
        )

        public = capability.to_public_dict()

        self.assertEqual(public["aliases"], ["alpha", "Zulu"])
        self.assertEqual(public["source_locations"][0]["location"], "~/a")
        self.assertEqual(public["diagnostics"][0]["code"], "a_code")

    def test_inventory_metadata_has_a_sanitized_public_form(self) -> None:
        metadata = InventoryMetadata(
            generated_at="2026-08-14T12:00:00Z",
            capability_count=2,
            diagnostics=[Diagnostic("info", "scan", "line one\nline two")],
        )

        public = metadata.to_public_dict()

        self.assertEqual(public["schema_version"], 2)
        self.assertEqual(public["capability_count"], 2)
        self.assertEqual(public["diagnostics"][0]["message"], "line one line two")


class SanitizerTests(unittest.TestCase):
    def test_paths_are_redacted_across_supported_forms(self) -> None:
        home = Path("/Users/alice")
        raw = (
            "/Users/alice/.agents/skills/demo "
            "/opt/acme/private/tool "
            "C:\\Users\\Alice\\private\\tool.exe "
            "file:///var/private/config.json "
            "file:///Users/alice/private/note.md "
            "file://server/share/private/config.json "
            "file://localhost/C:/Users/Alice/private/config.json "
            "path:/srv/private/capability/config.json"
        )

        result = sanitize_text(raw, home=home)

        self.assertIn("~/.agents/skills/demo", result)
        self.assertNotIn("/Users/alice", result)
        self.assertNotIn("/opt/acme", result)
        self.assertNotIn("C:\\Users", result)
        self.assertNotIn("file://", result)
        self.assertNotIn("server/share", result)
        self.assertNotIn("/srv/private", result)
        self.assertGreaterEqual(result.count("<path>"), 7)

    def test_control_table_newline_and_length_safety(self) -> None:
        result = sanitize_text("left|right\nnext\rline\x00end\x1f", max_length=22)

        self.assertEqual(result, "left\\|right next line…")
        self.assertLessEqual(len(result), 22)
        self.assertNotIn("\n", result)
        self.assertNotIn("\r", result)
        self.assertNotIn("\x00", result)
        self.assertNotIn("\x1f", result)

    def test_oversized_strings_are_deterministically_truncated(self) -> None:
        result = sanitize_text("x" * 100, max_length=16)

        self.assertEqual(result, "x" * 15 + "…")
        self.assertEqual(len(result), 16)

    def test_synthetic_credentials_are_redacted(self) -> None:
        github_canary = "gh" + "p_" + "syntheticvalue1234567890"
        openai_canary = "s" + "k-" + "syntheticvalue1234567890"
        jwt_canary = ".".join(
            ["ey" + "JsyntheticHeader", "ey" + "JsyntheticPayload", "syntheticSignature"]
        )
        aws_canary = "AK" + "IA" + "SYNTHETICKEY1234"
        bearer_canary = "bearer-" + "synthetic-value"
        assigned_canaries = {
            "token": "assigned-" + "synthetic-token-value-123",
            "secret": "assigned-" + "synthetic-secret-value-123",
            "password": "assigned-" + "synthetic-password-value-123",
            "api_key": "assigned-" + "synthetic-api-key-value-123",
        }
        raw = (
            f"{github_canary} {openai_canary} {jwt_canary} {aws_canary} "
            f"Bearer {bearer_canary} "
            + " ".join(
                f"{name}={canary}" for name, canary in assigned_canaries.items()
            )
        )

        result = sanitize_text(raw)

        for canary in (
            github_canary,
            openai_canary,
            jwt_canary,
            aws_canary,
            bearer_canary,
            *assigned_canaries.values(),
        ):
            self.assertNotIn(canary, result)
        self.assertGreaterEqual(result.count("<redacted>"), 9)

    def test_nested_dicts_and_lists_are_sanitized_without_leaks(self) -> None:
        token_canary = "gh" + "p_" + "nestedsyntheticvalue123"
        assigned_canary = "nested-assigned-value"
        private_path = "/srv/private/capability/config.json"
        raw = {
            "outer|key": [
                token_canary,
                {"details": f"{private_path}\npassword: {assigned_canary}"},
            ]
        }

        result = sanitize(raw)
        encoded = json.dumps(result, sort_keys=True)

        self.assertIn("outer\\\\|key", encoded)
        self.assertNotIn(token_canary, encoded)
        self.assertNotIn(assigned_canary, encoded)
        self.assertNotIn(private_path, encoded)
        self.assertNotIn("\\n", encoded)
        self.assertEqual(result["outer\\|key"][0], "<redacted>")


if __name__ == "__main__":
    unittest.main()

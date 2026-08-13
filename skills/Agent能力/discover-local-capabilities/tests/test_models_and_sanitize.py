"""Tests for the public capability model and recursive sanitizer."""

from __future__ import annotations

import json
import sys
import unittest
from dataclasses import FrozenInstanceError, asdict, replace
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

    def test_logical_identity_distinguishes_duplicate_public_metadata(self) -> None:
        first = Capability(
            kind="mcp",
            name="duplicate",
            provider="shared",
            scope="user",
            logical_identity="configuration-one",
        )
        second = Capability(
            kind="mcp",
            name="duplicate",
            provider="shared",
            scope="user",
            logical_identity="configuration-two",
        )

        self.assertNotEqual(first.id, second.id)
        self.assertNotEqual(first.resolver_id, second.resolver_id)
        self.assertNotIn("logical_identity", first.to_public_dict())
        self.assertNotIn("logical_identity", asdict(first))

    def test_replace_of_non_identity_field_preserves_logical_identity(self) -> None:
        logical_identity = "configuration-one-synthetic-origin"
        original = Capability(
            kind="mcp",
            name="duplicate",
            provider="shared",
            logical_identity=logical_identity,
        )

        updated = replace(original, description="Updated description")

        self.assertEqual(updated.id, original.id)
        self.assertEqual(updated.resolver_id, original.resolver_id)
        self.assertEqual(updated.description, "Updated description")
        self.assertNotIn(logical_identity, repr(updated))
        self.assertNotIn(logical_identity, json.dumps(asdict(updated), sort_keys=True))
        self.assertNotIn(
            logical_identity, json.dumps(updated.to_public_dict(), sort_keys=True)
        )
        self.assertNotIn("logical_identity", updated.to_public_dict())

    def test_identity_normalizes_unicode_to_nfc(self) -> None:
        composed = Capability(
            kind="skill",
            name="Café",
            provider="Résumé",
            logical_identity="entrée",
        )
        decomposed = Capability(
            kind="skill",
            name="Cafe\u0301",
            provider="Re\u0301sume\u0301",
            logical_identity="entre\u0301e",
        )

        self.assertEqual(composed.id, decomposed.id)
        self.assertEqual(composed.resolver_id, decomposed.resolver_id)
        self.assertEqual(decomposed.name, "Café")

    def test_identity_preserves_name_and_logical_identity_case(self) -> None:
        lower_name = Capability(kind="cli", name="runner")
        upper_name = Capability(kind="cli", name="Runner")
        lower_origin = Capability(
            kind="skill", name="same", logical_identity="origin"
        )
        upper_origin = Capability(
            kind="skill", name="same", logical_identity="Origin"
        )

        self.assertNotEqual(lower_name.id, upper_name.id)
        self.assertNotEqual(lower_name.resolver_id, upper_name.resolver_id)
        self.assertNotEqual(lower_origin.id, upper_origin.id)
        self.assertNotEqual(lower_origin.resolver_id, upper_origin.resolver_id)

    def test_name_empty_after_sanitization_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            Capability(kind="skill", name="\x00\u200b\n")

    def test_identity_objects_and_internal_sequences_are_immutable(self) -> None:
        source = SourceLocation("~/skill", "user", "shared")
        states = CapabilityStates()
        diagnostic = Diagnostic(
            "info", "immutable", "message", {"nested": ["value"]}
        )
        capability = Capability(
            kind="skill",
            name="immutable",
            aliases=["alias"],
            source_locations=[source],
            states=states,
            diagnostics=[diagnostic],
        )
        original_id = capability.id

        with self.assertRaises(FrozenInstanceError):
            capability.name = "mutated"
        with self.assertRaises(FrozenInstanceError):
            source.location = "~/other"
        with self.assertRaises(FrozenInstanceError):
            states.probed = "success"
        with self.assertRaises(AttributeError):
            capability.aliases.append("mutated")
        with self.assertRaises(AttributeError):
            capability.source_locations.append(SourceLocation("~/other"))
        with self.assertRaises(TypeError):
            diagnostic.details["path"] = "/private/path"
        with self.assertRaises(AttributeError):
            diagnostic.details["nested"].append("mutated")
        self.assertEqual(capability.id, original_id)
        self.assertIsInstance(capability.to_public_dict()["aliases"], list)
        self.assertIsInstance(capability.to_public_dict()["source_locations"], list)

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

    def test_public_dataclass_repr_and_asdict_do_not_expose_raw_values(self) -> None:
        exact_path = "/Users/alice/private/skill/SKILL.md"
        token_canary = "gh" + "p_" + "modelsyntheticvalue123"
        raw_description = f"Read {exact_path}\ntoken={token_canary}"
        source = SourceLocation(exact_path, "user", "shared")
        capability = Capability(
            kind="skill",
            name="Private Skill",
            description=raw_description,
            source_locations=[source],
            diagnostics=[
                Diagnostic(
                    "warning",
                    "private_path",
                    raw_description,
                    {"path": exact_path},
                )
            ],
        )
        resolver = ResolverRecord(capability.resolver_id, [exact_path])

        public_views = (
            repr(source),
            repr(capability),
            json.dumps(asdict(capability), sort_keys=True),
        )
        for public_view in public_views:
            self.assertNotIn(exact_path, public_view)
            self.assertNotIn(token_canary, public_view)
        self.assertNotIn(exact_path, repr(resolver))
        with self.assertRaises(TypeError):
            Capability(
                kind="skill",
                name="Bypass",
                source_locations=[exact_path],
            )

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
    def test_each_absolute_path_form_is_independently_redacted(self) -> None:
        cases = {
            "unix_quoted": '"/opt/Acme Tools/秘密/config.json"',
            "unix_escaped_space": "/opt/Acme\\ Tools/秘密/config.json",
            "unix_unquoted_space": "/opt/Acme Tools/秘密/config.json",
            "windows_quoted": "'C:\\Program Files\\工具\\config.json'",
            "unc_quoted": '"\\\\server\\Shared Folder\\秘密\\config.json"',
            "file_url_quoted": '"file:///var/Acme Tools/秘密.json"',
            "file_url_host": "file://server/share/private/config.json",
            "file_url_windows": "file://localhost/C:/Users/Alice/private/config.json",
        }

        for branch, sample in cases.items():
            with self.subTest(branch=branch):
                self.assertEqual(
                    sanitize_text(sample, home=Path("/Users/alice")), "<path>"
                )

    def test_forward_slash_unc_forms_are_independently_redacted(self) -> None:
        cases = {
            "unquoted": "//synthetic-host/synthetic/share",
            "quoted": '"//synthetic-host/synthetic/share"',
            "share_with_space": "//synthetic-host/synthetic share/private.json",
            "quoted_share_with_space": (
                '"//synthetic-host/synthetic share/private.json"'
            ),
        }

        for branch, sample in cases.items():
            with self.subTest(branch=branch):
                self.assertEqual(sanitize_text(sample), "<path>")

    def test_absolute_paths_with_truncating_characters_redact_whole_field(self) -> None:
        samples = (
            "/opt/synthetic`private/config.json",
            '/opt/synthetic"private/config.json',
            "/opt/synthetic'private/config.json",
        )

        for sample in samples:
            with self.subTest(sample=sample):
                self.assertEqual(sanitize_text(sample), "<path>")

    def test_double_quoted_absolute_path_with_escaped_delimiter_is_redacted(self) -> None:
        raw = r'"/opt/Synthetic \"Project\"/file.txt"'

        self.assertEqual(sanitize_text(raw), "<path>")

    def test_single_quoted_absolute_path_with_escaped_delimiter_is_redacted(self) -> None:
        raw = r"'/opt/Synthetic \'Project\'/file.txt'"

        self.assertEqual(sanitize_text(raw), "<path>")

    def test_ordinary_quoted_text_with_escaped_delimiter_is_preserved(self) -> None:
        raw = r'"Synthetic \"Project\" description"'

        self.assertEqual(sanitize_text(raw), raw)

    def test_embedded_double_quoted_path_with_escaped_delimiter_is_redacted(self) -> None:
        raw = r'Read "/opt/Synthetic \"Project\"/file.txt" now'

        self.assertEqual(sanitize_text(raw), "Read <path> now")

    def test_embedded_single_quoted_path_with_escaped_delimiter_is_redacted(self) -> None:
        raw = r"Read '/opt/Synthetic \'Project\'/file.txt' now"

        self.assertEqual(sanitize_text(raw), "Read <path> now")

    def test_embedded_ordinary_quoted_text_is_preserved(self) -> None:
        raw = r'Read "Synthetic \"Project\" description" now'

        self.assertEqual(sanitize_text(raw), raw)

    def test_unquoted_labeled_path_with_spaces_is_conservatively_redacted(self) -> None:
        result = sanitize_text("path:/srv/Private Folder/secret.json")

        self.assertEqual(result, "<path>")

    def test_prose_slashes_and_web_urls_are_not_absolute_paths(self) -> None:
        samples = (
            "supports input / output formats",
            "ratio 1 / 2",
            "documentation https://example.com/input/output",
        )

        for sample in samples:
            with self.subTest(sample=sample):
                self.assertEqual(sanitize_text(sample), sample)

    def test_paths_are_redacted_across_supported_forms(self) -> None:
        home = Path("/Users/alice")
        home_result = sanitize_text("/Users/alice/.agents/skills/demo", home=home)

        self.assertEqual(home_result, "~/.agents/skills/demo")
        cases = {
            "/opt/acme/private/tool": "<path>",
            "C:\\Users\\Alice\\private\\tool.exe": "<path>",
            "file:///var/private/config.json": "<path>",
            "path:/srv/private/capability/config.json": "path:<path>",
        }
        for sample, expected in cases.items():
            with self.subTest(sample=sample):
                self.assertEqual(sanitize_text(sample, home=home), expected)

    def test_control_table_newline_and_length_safety(self) -> None:
        result = sanitize_text("left|right\nnext\rline\x00end\x1f", max_length=22)

        self.assertEqual(result, "left\\|right next line…")
        self.assertLessEqual(len(result), 22)
        self.assertNotIn("\n", result)
        self.assertNotIn("\r", result)
        self.assertNotIn("\x00", result)
        self.assertNotIn("\x1f", result)

    def test_markdown_pipe_escaping_is_odd_and_idempotent(self) -> None:
        for slash_count, expected_count in ((0, 1), (1, 1), (2, 3), (3, 3), (4, 5)):
            with self.subTest(slash_count=slash_count):
                raw = "left" + "\\" * slash_count + "|right"
                once = sanitize_text(raw)
                twice = sanitize_text(once)
                before_pipe = once.split("|", 1)[0]
                actual_count = len(before_pipe) - len(before_pipe.rstrip("\\"))

                self.assertEqual(actual_count, expected_count)
                self.assertEqual(actual_count % 2, 1)
                self.assertEqual(twice, once)

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

    def test_mapping_key_collisions_are_deterministically_disambiguated(self) -> None:
        first = sanitize({"same\nkey": "first", "same key": "second"})
        second = sanitize({"same key": "second", "same\nkey": "first"})

        self.assertEqual(first, second)
        self.assertEqual(len(first), 2)
        self.assertEqual(sorted(first.values()), ["first", "second"])
        self.assertEqual(sorted(first), ["same key", "same key [2]"])

    def test_mapping_collision_suffix_respects_max_length(self) -> None:
        result = sanitize(
            {"abcdefgh": "first", "abcdefgh\n": "second"}, max_length=8
        )

        self.assertEqual(result, {"abcdefgh": "first", "abc… [2]": "second"})
        self.assertTrue(all(len(key) <= 8 for key in result))

    def test_non_json_values_raise_without_calling_untrusted_conversions(self) -> None:
        class Untrusted:
            def __str__(self) -> str:
                raise AssertionError("__str__ must not be called")

            def __repr__(self) -> str:
                raise AssertionError("__repr__ must not be called")

        unsupported = (
            {"set": {"value"}},
            {1: "non-string key"},
            Path("/tmp/private"),
            b"bytes",
            Untrusted(),
        )
        for value in unsupported:
            with self.subTest(value_type=type(value).__name__):
                with self.assertRaises(TypeError):
                    sanitize(value)
        with self.assertRaises(TypeError):
            sanitize_text(Untrusted())


if __name__ == "__main__":
    unittest.main()

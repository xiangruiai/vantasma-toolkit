"""Tests for neutral classification, query routing, and public reports."""

from __future__ import annotations

import json
import sys
import tempfile
import time
import unittest
from pathlib import Path


PACKAGE_DIR = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = PACKAGE_DIR / "scripts"
TAXONOMY_PATH = PACKAGE_DIR / "references" / "scene-taxonomy.json"
sys.path.insert(0, str(SCRIPTS_DIR))

from capability_map_core.classify import (  # noqa: E402
    RouteMatch,
    RouteResult,
    SceneDefinition,
    UnresolvedSummary,
    classify_capabilities,
    load_taxonomy,
    route_query,
    route_result_json,
)
from capability_map_core.models import (  # noqa: E402
    Capability,
    CapabilityStates,
    Diagnostic,
    InventoryMetadata,
    SourceLocation,
)
from capability_map_core.render import (  # noqa: E402
    render_capability_map_markdown,
    render_inventory_json,
)
import scan_capabilities  # noqa: E402


def capability(
    name: str,
    *,
    kind: str = "skill",
    description: str = "",
    aliases: tuple[str, ...] = (),
    tags: tuple[str, ...] = (),
    sources: tuple[SourceLocation, ...] = (),
    diagnostics: tuple[Diagnostic, ...] = (),
    states: CapabilityStates | None = None,
) -> Capability:
    return Capability(
        kind=kind,
        name=name,
        description=description,
        aliases=aliases,
        tags=tags,
        source_locations=sources,
        scope="plugin" if kind == "plugin" else "extra",
        provider="synthetic-provider",
        diagnostics=diagnostics,
        states=states or CapabilityStates(),
    )


class NeutralTaxonomyTests(unittest.TestCase):
    def test_taxonomy_contains_only_generic_scene_evidence(self) -> None:
        raw = json.loads(TAXONOMY_PATH.read_text(encoding="utf-8"))
        taxonomy = load_taxonomy(TAXONOMY_PATH)

        self.assertGreaterEqual(len(taxonomy), 10)
        self.assertEqual(len({scene.id for scene in taxonomy}), len(taxonomy))
        self.assertNotIn("preferred", json.dumps(raw, ensure_ascii=False).casefold())
        for scene in raw["scenes"]:
            self.assertEqual(
                set(scene),
                {
                    "id",
                    "label_zh",
                    "label_en",
                    "keywords",
                    "phrases",
                    "kind_boosts",
                },
            )
        serialized = json.dumps(raw, ensure_ascii=False).casefold()
        for concrete_name in (
            "codex",
            "claude",
            "openclaw",
            "lark",
            "ffmpeg",
            "github",
            "obsidian",
        ):
            self.assertNotIn(concrete_name, serialized)

    def test_classification_uses_local_evidence_and_preserves_identity(self) -> None:
        local = (
            capability(
                "Literature Finder",
                description="Find and synthesize academic sources.",
                tags=("research", "citations"),
            ),
            capability(
                "Motion Studio",
                kind="plugin",
                description="Edit video, audio, and images.",
                tags=("media", "video editing"),
            ),
            capability("opaque-runner", kind="cli"),
        )

        classified = classify_capabilities(local, taxonomy_path=TAXONOMY_PATH)
        by_name = {item.name: item for item in classified}

        self.assertIn("search-research", by_name["Literature Finder"].scenes)
        self.assertIn("media", by_name["Motion Studio"].scenes)
        self.assertEqual(by_name["opaque-runner"].scenes, ())
        self.assertEqual(by_name["Literature Finder"].id, local[0].id)
        self.assertEqual(by_name["Literature Finder"].resolver_id, local[0].resolver_id)
        self.assertGreater(by_name["Literature Finder"].classification_confidence, 0.0)

    def test_unrelated_installed_names_do_not_change_generic_classification(self) -> None:
        target = capability(
            "Evidence Synthesizer",
            description="Research reports with source citations.",
            tags=("research",),
        )
        unrelated = (
            capability("author-tool-alpha", kind="cli"),
            capability("author-tool-beta", kind="plugin"),
        )

        alone = classify_capabilities((target,), taxonomy_path=TAXONOMY_PATH)[0]
        with_unrelated = {
            item.id: item
            for item in classify_capabilities(
                (target, *unrelated), taxonomy_path=TAXONOMY_PATH
            )
        }[target.id]

        self.assertEqual(alone.scenes, with_unrelated.scenes)
        self.assertEqual(
            alone.classification_confidence,
            with_unrelated.classification_confidence,
        )

    def test_low_confidence_and_name_substrings_remain_unclassified(self) -> None:
        unknown = capability(
            "researcherish-runner",
            kind="cli",
            description="Command discovered in PATH.",
            tags=("cli",),
        )

        classified = classify_capabilities((unknown,), taxonomy_path=TAXONOMY_PATH)

        self.assertEqual(classified[0].scenes, ())
        self.assertEqual(classified[0].classification_confidence, 0.0)

    def test_call_time_override_does_not_require_packaged_preferences(self) -> None:
        unknown = capability("private-local-entry", kind="cli")

        classified = classify_capabilities(
            (unknown,),
            taxonomy_path=TAXONOMY_PATH,
            overrides={unknown.id: ("automation",)},
        )

        self.assertEqual(classified[0].scenes, ("automation",))
        self.assertEqual(classified[0].classification_confidence, 1.0)

    def test_duplicate_ids_are_classified_independently_and_deterministically(self) -> None:
        research = capability(
            "Same Identity",
            description="Research reports with source citations.",
            tags=("research", "citations"),
        )
        media = capability(
            "Same Identity",
            description="Edit video and audio media.",
            tags=("video", "audio"),
        )
        self.assertEqual(research.id, media.id)

        forward = classify_capabilities(
            (research, media), taxonomy_path=TAXONOMY_PATH
        )
        reverse = classify_capabilities(
            (media, research), taxonomy_path=TAXONOMY_PATH
        )

        self.assertEqual(
            [item.to_public_dict() for item in forward],
            [item.to_public_dict() for item in reverse],
        )
        self.assertEqual(len(forward), 2)
        by_description = {item.description: item for item in forward}
        self.assertIn(
            "search-research",
            by_description["Research reports with source citations."].scenes,
        )
        self.assertIn(
            "media", by_description["Edit video and audio media."].scenes
        )

    def test_scene_collections_reject_scalar_bytes_and_non_strings(self) -> None:
        valid = {
            "id": "testing-scene",
            "label_zh": "测试",
            "label_en": "Testing",
            "kind_boosts": {"skill": 0.1},
        }
        invalid_fields = (
            {"keywords": "research", "phrases": ()},
            {"keywords": ("research",), "phrases": b"reports"},
            {"keywords": ("research", 7), "phrases": ()},
            {"keywords": ("research",), "phrases": ("reports", object())},
        )
        for fields in invalid_fields:
            with self.subTest(fields=fields):
                with self.assertRaises(TypeError):
                    SceneDefinition(**valid, **fields)

        with self.assertRaises(TypeError):
            SceneDefinition(
                **{**valid, "kind_boosts": "skill"},
                keywords=("research",),
                phrases=(),
            )
        with self.assertRaises(TypeError):
            RouteMatch(
                id="cap_test",
                name="test",
                kind="skill",
                score=1.0,
                evidence="",
                scenes=(),
                resolver_id="res_test",
                state_warning="unknown",
            )
        with self.assertRaises(TypeError):
            UnresolvedSummary(0, names=b"")
        with self.assertRaises(TypeError):
            RouteResult("test", matches="")
        with self.assertRaises(TypeError):
            render_inventory_json("", InventoryMetadata(""), ())
        with self.assertRaises(TypeError):
            render_inventory_json((), InventoryMetadata(""), diagnostics="")


class QueryRoutingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.specialized = capability(
            "Citation Research Workflow",
            description="Search academic literature and synthesize cited evidence.",
            tags=("research", "citations", "literature search"),
        )
        self.generic = capability("search", kind="cli")
        self.unknown = capability("generic-runner", kind="cli")
        self.classified = classify_capabilities(
            (self.generic, self.unknown, self.specialized),
            taxonomy_path=TAXONOMY_PATH,
        )

    def test_specialized_evidenced_capability_outranks_generic_entry(self) -> None:
        result = route_query(
            "research academic sources",
            self.classified,
            taxonomy_path=TAXONOMY_PATH,
        )

        self.assertIsInstance(result, RouteResult)
        self.assertGreaterEqual(len(result.matches), 2)
        self.assertEqual(result.matches[0].id, self.specialized.id)
        self.assertGreater(result.matches[0].score, result.matches[1].score)
        self.assertTrue(result.matches[0].evidence)
        self.assertIn("search-research", result.matches[0].scenes)
        self.assertEqual(result.matches[0].resolver_id, self.specialized.resolver_id)
        self.assertIn("verified", result.matches[0].state_warning)

    def test_bilingual_queries_are_deterministic_and_explain_evidence(self) -> None:
        chinese = route_query(
            "帮我搜索论文并整理引用",
            self.classified,
            taxonomy_path=TAXONOMY_PATH,
        )
        english_one = route_query(
            "search research papers with citations",
            self.classified,
            taxonomy_path=TAXONOMY_PATH,
        )
        english_two = route_query(
            "search research papers with citations",
            tuple(reversed(self.classified)),
            taxonomy_path=TAXONOMY_PATH,
        )

        self.assertEqual(chinese.matches[0].id, self.specialized.id)
        self.assertEqual(english_one.to_public_dict(), english_two.to_public_dict())
        self.assertTrue(
            any("scene:search-research" in item for item in english_one.matches[0].evidence)
        )
        self.assertGreaterEqual(english_one.unresolved.count, 1)
        self.assertIn(self.unknown.id, english_one.unresolved.capability_ids)

    def test_query_is_sanitized_before_it_enters_typed_result(self) -> None:
        secret = "gh" + "p_" + "syntheticcanary123456"
        exact_path = "/srv/private/person/search.txt"

        result = route_query(
            f"research token={secret} {exact_path}",
            self.classified,
            taxonomy_path=TAXONOMY_PATH,
        )
        serialized = json.dumps(result.to_public_dict(), ensure_ascii=False)

        self.assertNotIn(secret, serialized)
        self.assertNotIn(exact_path, serialized)
        self.assertIn("<redacted>", result.query)

    def test_unresolved_summary_preserves_public_name_casing(self) -> None:
        mixed_case = capability("Mixed Case Runner", kind="cli")

        result = route_query(
            "research sources",
            (*self.classified, mixed_case),
            taxonomy_path=TAXONOMY_PATH,
        )

        self.assertIn("Mixed Case Runner", result.unresolved.names)

    def test_chinese_query_phrases_route_to_english_evidenced_capabilities(self) -> None:
        project = capability(
            "Milestone Planning Specialist",
            description="Manage project milestones, roadmaps, and task planning.",
            tags=("project management", "milestone planning"),
        )
        automation = capability(
            "Workflow Automation Specialist",
            description="Automate scheduled workflows and event triggers.",
            tags=("automation", "workflow"),
        )
        infrastructure = capability(
            "Infrastructure Deployment Specialist",
            description="Deploy and operate cloud infrastructure and servers.",
            tags=("cloud infrastructure", "deployment"),
        )
        classified = classify_capabilities(
            (infrastructure, automation, project), taxonomy_path=TAXONOMY_PATH
        )
        cases = (
            ("帮我查看里程碑", project.id, "query:phrase:里程碑"),
            ("请做自动化处理", automation.id, "query:phrase:自动化"),
            ("检查基础设施", infrastructure.id, "query:phrase:基础设施"),
        )

        for query, expected_id, expected_evidence in cases:
            with self.subTest(query=query):
                result = route_query(
                    query, classified, taxonomy_path=TAXONOMY_PATH
                )
                self.assertEqual(result.matches[0].id, expected_id)
                self.assertIn(expected_evidence, result.matches[0].evidence)

        one_character = route_query(
            "项", classified, taxonomy_path=TAXONOMY_PATH
        )
        self.assertEqual(one_character.matches, ())

    def test_duplicate_route_records_are_independent_and_input_order_invariant(self) -> None:
        citations = capability(
            "Same Route Identity",
            description="Research reports with citations.",
            tags=("research", "citations"),
        )
        sources = capability(
            "Same Route Identity",
            description="Research reports from verified sources.",
            tags=("research", "sources"),
        )
        self.assertEqual(citations.id, sources.id)

        forward = route_query(
            "research report citations",
            (citations, sources),
            taxonomy_path=TAXONOMY_PATH,
        )
        reverse = route_query(
            "research report citations",
            (sources, citations),
            taxonomy_path=TAXONOMY_PATH,
        )

        self.assertEqual(route_result_json(forward), route_result_json(reverse))
        self.assertEqual(len(forward.matches), 2)
        self.assertNotEqual(forward.matches[0].evidence, forward.matches[1].evidence)

    def test_stopwords_and_low_information_overlap_do_not_create_routes(self) -> None:
        unrelated = capability(
            "Open Media Utility",
            description="Open and display image media.",
            tags=("media", "utility"),
        )
        report = capability(
            "Report Analyst",
            description="Create data reports from structured tables.",
            tags=("report", "data analysis"),
        )
        research = capability(
            "Citation Researcher",
            description="Research reports with source citations.",
            tags=("research", "citations"),
        )
        classified = classify_capabilities(
            (unrelated, report, research), taxonomy_path=TAXONOMY_PATH
        )

        low_information = route_query(
            "open it and do this",
            classified,
            taxonomy_path=TAXONOMY_PATH,
        )
        report_route = route_query(
            "open the report",
            classified,
            taxonomy_path=TAXONOMY_PATH,
        )
        citation_route = route_query(
            "report with citations",
            classified,
            taxonomy_path=TAXONOMY_PATH,
        )

        self.assertEqual(low_information.matches, ())
        self.assertEqual(report_route.matches[0].id, report.id)
        self.assertNotIn(
            unrelated.id, tuple(item.id for item in report_route.matches)
        )
        self.assertEqual(citation_route.matches[0].id, research.id)


class PublicRenderingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.shadowed = capability(
            "media-helper",
            kind="cli",
            sources=(
                SourceLocation("<PATH:0>/media-helper", "extra", "PATH"),
                SourceLocation("<PATH:2>/media-helper", "extra", "PATH"),
            ),
            diagnostics=(
                Diagnostic(
                    "info",
                    "cli_path_entry",
                    "This PATH entry is effective.",
                    {"effective": True, "path_rank": 0, "shadow_rank": 0},
                ),
                Diagnostic(
                    "info",
                    "cli_path_entry",
                    "This PATH entry is shadowed by an earlier entry.",
                    {"effective": False, "path_rank": 2, "shadow_rank": 1},
                ),
            ),
        )
        self.unknown = capability("opaque-entry", kind="cli")
        self.document = capability(
            "Structured Document Editor",
            description="Create and transform documents and tables.",
            tags=("documents", "tables"),
        )
        self.classified = classify_capabilities(
            (self.unknown, self.document, self.shadowed),
            taxonomy_path=TAXONOMY_PATH,
        )
        self.metadata = InventoryMetadata(
            generated_at="2026-08-14T00:00:00Z",
            capability_count=len(self.classified),
        )
        self.diagnostics = (
            Diagnostic("warning", "synthetic_warning", "One source was skipped."),
        )

    def test_inventory_json_is_complete_and_deterministic(self) -> None:
        first = render_inventory_json(
            self.classified, self.metadata, self.diagnostics
        )
        second = render_inventory_json(
            tuple(reversed(self.classified)), self.metadata, self.diagnostics
        )
        parsed = json.loads(first)

        self.assertEqual(first, second)
        self.assertEqual(parsed["metadata"]["schema_version"], 2)
        self.assertEqual(len(parsed["capabilities"]), 3)
        self.assertEqual(
            {item["id"] for item in parsed["capabilities"]},
            {item.id for item in self.classified},
        )
        shadow = next(item for item in parsed["capabilities"] if item["name"] == "media-helper")
        self.assertEqual(len(shadow["source_locations"]), 2)
        self.assertEqual(len(shadow["diagnostics"]), 2)
        self.assertEqual(parsed["summary"]["unclassified"], 1)
        self.assertEqual(parsed["unclassified"][0]["name"], "opaque-entry")

    def test_markdown_has_usage_boundaries_routes_diagnostics_and_help(self) -> None:
        many_clis = tuple(capability(f"opaque-{index:03d}", kind="cli") for index in range(80))
        classified = classify_capabilities(
            (*self.classified, *many_clis), taxonomy_path=TAXONOMY_PATH
        )

        report = render_capability_map_markdown(
            classified,
            self.metadata,
            self.diagnostics,
            taxonomy_path=TAXONOMY_PATH,
            presentation_cap=5,
        )

        for heading_or_hint in (
            "## 使用方式",
            "## 状态边界",
            "## 场景 → 候选能力",
            "## 待人工归类",
            "## 扫描诊断",
            "刷新",
            "迁移",
            "卸载",
            "帮助",
        ):
            self.assertIn(heading_or_hint, report)
        self.assertIn("discovered", report)
        self.assertIn("authenticated", report)
        self.assertIn("verified", report)
        self.assertLessEqual(sum(f"opaque-{index:03d}" in report for index in range(80)), 5)

    def test_public_outputs_do_not_leak_canaries_paths_or_extra_fields(self) -> None:
        secret = "sk-" + "syntheticsecret123456"
        exact_path = "/srv/private/person/hidden/SKILL.md"

        class ExtendedCapability(Capability):
            pass

        hostile = ExtendedCapability(
            kind="skill",
            name="bad\\*bold*|name\n## injected",
            description=f"secret={secret} read {exact_path}\nnext row | attack",
            tags=("documents",),
            source_locations=(SourceLocation(exact_path),),
        )
        hostile.private_exact_path = exact_path
        hostile.private_value = secret
        classified = classify_capabilities((hostile,), taxonomy_path=TAXONOMY_PATH)
        metadata = {
            "generated_at": "2026-08-14T00:00:00Z",
            "host": f"host-canary {exact_path}",
            "platform": "private-platform-fingerprint",
        }
        diagnostic = Diagnostic(
            "warning",
            "unsafe",
            f"secret={secret} at {exact_path}",
            {"private_path": exact_path},
        )

        inventory = render_inventory_json(classified, metadata, (diagnostic,))
        markdown = render_capability_map_markdown(
            classified,
            metadata,
            (diagnostic,),
            taxonomy_path=TAXONOMY_PATH,
        )
        combined = inventory + markdown

        for forbidden in (
            secret,
            exact_path,
            "private_exact_path",
            "private_value",
            "host-canary",
            "private-platform-fingerprint",
            "\n## injected",
        ):
            self.assertNotIn(forbidden, combined)
        parsed = json.loads(inventory)
        self.assertNotIn("host", parsed["metadata"])
        self.assertNotIn("platform", parsed["metadata"])
        self.assertNotIn("exact_locations", inventory)
        self.assertIn("bad\\\\\\*bold\\*\\|name", markdown)

    def test_thousands_of_capabilities_render_quickly_and_byte_identically(self) -> None:
        capabilities = tuple(
            capability(
                f"local-capability-{index:04d}",
                description="Automate a workflow." if index % 5 == 0 else "",
                tags=("automation",) if index % 5 == 0 else (),
            )
            for index in range(2_000)
        )
        start = time.monotonic()
        classified = classify_capabilities(capabilities, taxonomy_path=TAXONOMY_PATH)
        inventory_one = render_inventory_json(classified, self.metadata, ())
        inventory_two = render_inventory_json(classified, self.metadata, ())
        report_one = render_capability_map_markdown(
            classified,
            self.metadata,
            (),
            taxonomy_path=TAXONOMY_PATH,
            presentation_cap=8,
        )
        report_two = render_capability_map_markdown(
            classified,
            self.metadata,
            (),
            taxonomy_path=TAXONOMY_PATH,
            presentation_cap=8,
        )
        elapsed = time.monotonic() - start

        self.assertEqual(inventory_one, inventory_two)
        self.assertEqual(report_one, report_two)
        self.assertEqual(len(json.loads(inventory_one)["capabilities"]), 2_000)
        self.assertLess(elapsed, 5.0)

    def test_strict_public_render_redacts_sensitive_diagnostic_key_families(self) -> None:
        canaries = tuple(f"sensitive-value-{index}-937461" for index in range(7))
        diagnostic = Diagnostic(
            "warning",
            "sensitive_details",
            "Synthetic diagnostic.",
            {
                "access_token": canaries[0],
                "client-secret": canaries[1],
                "authorization": canaries[2],
                "auth_header": canaries[3],
                "nested": {
                    "cookie": canaries[4],
                    "private_key_pem": canaries[5],
                    "credential_hint": canaries[6],
                },
            },
        )
        item = capability(
            "Diagnostic Carrier",
            diagnostics=(diagnostic,),
        )

        inventory = render_inventory_json((item,), self.metadata, (diagnostic,))
        markdown = render_capability_map_markdown(
            (item,),
            self.metadata,
            (diagnostic,),
            taxonomy_path=TAXONOMY_PATH,
        )

        for canary in canaries:
            self.assertNotIn(canary, inventory)
            self.assertNotIn(canary, markdown)
        self.assertGreaterEqual(inventory.count("<redacted>"), len(canaries))

    def test_diagnostic_summary_merges_all_sources_and_deduplicates(self) -> None:
        shared = Diagnostic("warning", "shared", "Repeated source diagnostic.")
        metadata_only = Diagnostic("info", "metadata_only", "Metadata diagnostic.")
        top_only = Diagnostic("error", "top_only", "Top-level diagnostic.")
        capability_only = Diagnostic(
            "warning", "capability_only", "Capability diagnostic."
        )
        item = capability(
            "Diagnostic Sources",
            diagnostics=(shared, capability_only),
        )
        metadata = InventoryMetadata(
            generated_at="2026-08-14T00:00:00Z",
            capability_count=1,
            diagnostics=(shared, metadata_only),
        )

        inventory = render_inventory_json(
            (item,), metadata, (shared, top_only)
        )
        markdown = render_capability_map_markdown(
            (item,),
            metadata,
            (shared, top_only),
            taxonomy_path=TAXONOMY_PATH,
        )
        parsed = json.loads(inventory)

        self.assertEqual(parsed["summary"]["diagnostics"]["total"], 4)
        self.assertEqual(len(parsed["diagnostics"]), 4)
        self.assertEqual(
            set(parsed["summary"]["diagnostics"]["by_code"]),
            {"shared", "metadata_only", "top_only", "capability_only"},
        )
        self.assertIn("共 4 条诊断", markdown)

    def test_capability_tie_sort_uses_complete_public_record(self) -> None:
        first = capability(
            "Same Identity",
            description="Alpha research workflow.",
            tags=("research",),
        )
        second = capability(
            "Same Identity",
            description="Bravo research workflow.",
            tags=("research",),
        )
        self.assertEqual(first.id, second.id)
        classified = classify_capabilities(
            (first, second), taxonomy_path=TAXONOMY_PATH
        )

        inventory_forward = render_inventory_json(
            classified, self.metadata, ()
        )
        inventory_reverse = render_inventory_json(
            tuple(reversed(classified)), self.metadata, ()
        )
        markdown_forward = render_capability_map_markdown(
            classified,
            self.metadata,
            (),
            taxonomy_path=TAXONOMY_PATH,
        )
        markdown_reverse = render_capability_map_markdown(
            tuple(reversed(classified)),
            self.metadata,
            (),
            taxonomy_path=TAXONOMY_PATH,
        )

        self.assertEqual(inventory_forward, inventory_reverse)
        self.assertEqual(markdown_forward, markdown_reverse)
        self.assertEqual(len(json.loads(inventory_forward)["capabilities"]), 2)


class LegacyCompatibilityTests(unittest.TestCase):
    def test_missing_legacy_routing_rules_are_a_nonfatal_empty_configuration(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(scan_capabilities.load_rules(Path(directory)), [])
        self.assertEqual(scan_capabilities.load_rules(PACKAGE_DIR), [])

    def test_package_docs_reference_neutral_taxonomy_not_deleted_rules(self) -> None:
        docs = "\n".join(
            (
                (PACKAGE_DIR / "SKILL.md").read_text(encoding="utf-8"),
                (PACKAGE_DIR / "README.md").read_text(encoding="utf-8"),
            )
        )

        self.assertNotIn("routing-rules.json", docs)
        self.assertIn("scene-taxonomy.json", docs)
        self.assertIn("中立", docs)


if __name__ == "__main__":
    unittest.main()

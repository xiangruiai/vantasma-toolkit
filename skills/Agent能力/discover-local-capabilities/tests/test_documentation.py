"""Static contracts for the public Skill documentation."""

from __future__ import annotations

import argparse
import contextlib
import io
import re
import shlex
import sys
import unittest
from pathlib import Path


PACKAGE_DIR = Path(__file__).resolve().parents[1]
REPOSITORY_DIR = PACKAGE_DIR.parents[2]
SCRIPTS_DIR = PACKAGE_DIR / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import capability_map  # noqa: E402


PUBLIC_COMMANDS = {
    "scan",
    "setup",
    "status",
    "paths",
    "refresh",
    "route",
    "migrate",
    "uninstall",
    "help-intent",
}


def _subcommands(parser: argparse.ArgumentParser) -> dict[str, argparse.ArgumentParser]:
    action = next(
        item
        for item in parser._actions
        if isinstance(item, argparse._SubParsersAction)
    )
    return dict(action.choices)


def _documented_capability_map_argv(document: str) -> tuple[tuple[str, ...], ...]:
    invocations: list[tuple[str, ...]] = []
    for match in re.finditer(
        r"^[ \t]*```bash[ \t]*\n(.*?)^[ \t]*```[ \t]*$",
        document,
        re.DOTALL | re.MULTILINE,
    ):
        block = match.group(1).replace("\\\n", " ")
        for line in block.splitlines():
            if "capability_map.py" not in line:
                continue
            normalized = re.sub(r"<[^>]+>", "fixture", line.strip())
            tokens = shlex.split(normalized, comments=True)
            script_index = next(
                index
                for index, token in enumerate(tokens)
                if token.endswith("/scripts/capability_map.py")
            )
            invocations.append(tuple(tokens[script_index + 1 :]))
    return tuple(invocations)


class DocumentationContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.skill = (PACKAGE_DIR / "SKILL.md").read_text(encoding="utf-8")
        cls.readme = (PACKAGE_DIR / "README.md").read_text(encoding="utf-8")
        cls.agent = (PACKAGE_DIR / "agents" / "openai.yaml").read_text(
            encoding="utf-8"
        )
        cls.root_readme = (REPOSITORY_DIR / "README.md").read_text(encoding="utf-8")
        cls.package_docs = "\n".join((cls.skill, cls.readme, cls.agent))

    def test_documented_commands_match_the_parser(self) -> None:
        parser_commands = _subcommands(capability_map._parser())
        self.assertEqual(set(parser_commands), PUBLIC_COMMANDS)
        self.assertEqual(
            set(_subcommands(parser_commands["setup"])), {"plan", "apply"}
        )
        documented = {
            "scan": "capability_map.py scan",
            "setup": "capability_map.py setup plan",
            "setup-apply": "capability_map.py setup apply",
            "status": "capability_map.py status",
            "paths": "capability_map.py paths",
            "refresh": "capability_map.py refresh",
            "route": "capability_map.py route",
            "migrate": "capability_map.py migrate",
            "uninstall": "capability_map.py uninstall",
            "help-intent": "capability_map.py help-intent",
        }
        for label, command in documented.items():
            with self.subTest(command=label):
                self.assertIn(command, self.package_docs)

    def test_every_documented_bash_invocation_parses(self) -> None:
        parser = capability_map._parser()
        for document_name, document in (
            ("SKILL.md", self.skill),
            ("README.md", self.readme),
        ):
            invocations = _documented_capability_map_argv(document)
            self.assertTrue(invocations, document_name)
            for argv in invocations:
                with self.subTest(document=document_name, argv=argv):
                    errors = io.StringIO()
                    with contextlib.redirect_stderr(errors):
                        try:
                            parser.parse_args(argv)
                        except SystemExit as error:
                            self.fail(
                                f"documented command failed parser ({error.code}): "
                                f"{argv!r}: {errors.getvalue()}"
                            )

    def test_parser_rejects_unknown_flags_and_missing_required_arguments(self) -> None:
        parser = capability_map._parser()
        invalid = (
            ("status", "--not-a-real-flag"),
            ("setup",),
            ("route",),
            ("migrate",),
            ("help-intent",),
        )
        for argv in invalid:
            with self.subTest(argv=argv), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    parser.parse_args(argv)

    def test_purge_uses_matching_preview_and_confirmed_scope(self) -> None:
        parser = capability_map._parser()
        expected = (
            ("uninstall", "--storage", "fixture", "--dry-run", "--purge-data"),
            ("uninstall", "--storage", "fixture", "--confirmed", "--purge-data"),
        )
        for document_name, document in (
            ("SKILL.md", self.skill),
            ("README.md", self.readme),
        ):
            invocations = _documented_capability_map_argv(document)
            for argv in expected:
                with self.subTest(document=document_name, argv=argv):
                    self.assertIn(argv, invocations)
                    parser.parse_args(argv)

        for statement in (
            "would_purge_data=true",
            "新的当次明确确认",
            "不能先预览普通 uninstall 再添加 `--purge-data`",
        ):
            with self.subTest(statement=statement):
                self.assertIn(statement, self.package_docs)

    def test_purge_filesystem_and_reinstall_limits_are_explicit(self) -> None:
        for statement in (
            "public storage 与 private recovery 必须位于同一 filesystem",
            "cross-filesystem purge is unsupported; migrate public storage to the private recovery filesystem before purge",
            "跨 filesystem 时保守拒绝并恢复安装",
            "active 时可先 migrate 到同一 filesystem",
            "uninstalled 时 migrate 会拒绝",
            "保留 recovery 和数据",
            "审查此前 `paths` 返回的精确路径后自行管理",
            "不能自动删除",
            "Agent 生成新的 opaque `inst_...` installation ID",
            "plan 与 apply 复用同一值",
            "使用者不需要设计 installation ID",
        ):
            with self.subTest(statement=statement):
                self.assertIn(statement, self.package_docs)

    def test_documentation_covers_artifacts_and_private_boundary(self) -> None:
        for artifact in (
            "本机能力地图.md",
            "capability-inventory.json",
            "capability-map.config.json",
            "setup-receipt.md",
            "capability-resolver.json",
            "installation-state.json",
        ):
            with self.subTest(artifact=artifact):
                self.assertIn(artifact, self.package_docs)
        self.assertIn("系统数据目录", self.package_docs)
        self.assertIn("不进入 Obsidian", self.package_docs)
        self.assertIn("精确位置", self.package_docs)

    def test_confirmation_storage_and_agent_choices_are_explicit(self) -> None:
        for token in (
            "--confirmed",
            "--expected-plan-hash",
            "--dry-run",
            "--purge-data",
            "--storage <storage-root>",
            "--vault <vault-root>",
            "--agents codex|claude|both",
            "--scope user|project",
            "零写入",
            "当次明确确认",
            "绝对路径",
            "本地默认目录",
            "Obsidian Vault",
            "自定义目录",
        ):
            with self.subTest(token=token):
                self.assertIn(token, self.package_docs)

    def test_state_boundary_and_natural_language_loop_are_documented(self) -> None:
        for statement in (
            "已发现不等于已认证或已验证",
            "完整读取它的 SKILL.md",
            "默认不联网",
            "默认不执行已发现的 CLI",
            "扫描我的电脑有哪些 Skill、CLI、MCP 和插件",
            "能力地图放在哪里",
            "刚装了一个 Skill，刷新能力地图",
            "帮我找一个能处理视频的本机能力",
        ):
            with self.subTest(statement=statement):
                self.assertIn(statement, self.package_docs)
        self.assertIn("$discover-local-capabilities", self.agent)
        self.assertIn("明确确认", self.agent)
        self.assertIn("自然语言", self.agent)

    def test_package_docs_are_neutral_and_contain_no_machine_snapshot(self) -> None:
        lowered = self.package_docs.casefold()
        for forbidden in (
            "/" + "users" + "/",
            "/" + "home" + "/",
            "routing-rules.json",
            "default_clis",
            "openclaw",
            "opencli",
            "ffmpeg",
            "codem",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, lowered)
        self.assertIn("扫描安装者的电脑", self.readme)
        self.assertIn("不会复制作者的工具、偏好或能力快照", self.readme)

    def test_security_boundaries_match_the_implemented_data_flow(self) -> None:
        for statement in (
            "不读取 `.env`、凭证存储或命令历史",
            "受支持的 MCP 配置会限长解析",
            "secret values、command、args、URL、headers、env 不采集、不持久化、不输出",
            "private namespace 使用 OS 系统数据目录并与公开 artifacts 分层",
            "Obsidian 模式保证 private namespace 位于 Vault 外",
            "默认 local 模式位于同一应用数据根的隐藏 `.private` 子树",
            "custom 是否位于 public root 外取决于路径拓扑",
            "以零写入 setup plan 展示的精确路径为准，确认前审查",
            "不进入 Obsidian",
        ):
            with self.subTest(statement=statement):
                self.assertIn(statement, self.package_docs)
        self.assertNotIn(
            "不读取 `.env`、token、密码、命令历史或 MCP secret values",
            self.package_docs,
        )
        self.assertNotIn("stays outside the selected public directory", self.skill)
        self.assertNotIn(
            "自定义目录或 Obsidian 模式位于所选 public root 外",
            self.package_docs,
        )

    def test_persisted_and_stdout_path_disclosures_are_distinct(self) -> None:
        for statement in (
            "持久化 public artifacts 只保存脱敏内容",
            "持久化 public artifacts 统一脱敏 Home、外部绝对路径、凭证形态和控制字符",
            "private files 持久化精确路径",
            "setup 与 paths 的 stdout 按使用者请求返回精确操作位置",
            "stdout 不属于可分享的 public artifacts",
            "返回当前安装的 public/private artifact paths",
        ):
            with self.subTest(statement=statement):
                self.assertIn(statement, self.package_docs)
        self.assertNotIn(
            "Keep exact local paths only in the private resolver and runtime state",
            self.skill,
        )
        self.assertNotIn("返回当前安装所有精确位置", self.readme)
        self.assertNotIn("公开输出统一脱敏", self.package_docs)

    def test_uninstall_and_purge_lifecycle_matches_the_workflow(self) -> None:
        for statement in (
            "lifecycle=uninstalled、active=false",
            "installed=false、healthy=false 且 health_errors 为空",
            "refresh、migrate 与重复 uninstall 会拒绝",
            "Agent 生成新的 opaque `inst_...` installation ID",
            "`--purge-data` 可从 active 或 uninstalled lifecycle 执行",
            "public artifacts 和完整 owned private namespace",
            "resolver、state、instruction/state backups 与 manifests",
            "不移动非托管公开文件或其他 private namespace",
            "外部变更冲突时拒绝 purge 并保留外部内容",
        ):
            with self.subTest(statement=statement):
                self.assertIn(statement, self.package_docs)

    def test_repository_index_counts_and_v2_description_are_current(self) -> None:
        skill_count = sum(1 for _ in (REPOSITORY_DIR / "skills").rglob("SKILL.md"))
        category_count = sum(
            1 for item in (REPOSITORY_DIR / "skills").iterdir() if item.is_dir()
        )
        self.assertEqual(skill_count, 16)
        self.assertEqual(category_count, 7)
        self.assertIn("16 个 Skill", self.root_readme)
        self.assertIn("按领域分 7 类", self.root_readme)
        self.assertIn("完整扫描", self.root_readme)
        self.assertIn("自然语言路由闭环", self.root_readme)


if __name__ == "__main__":
    unittest.main()

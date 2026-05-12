#!/usr/bin/env python3
"""
飞书多维表格模板自动搭建脚本
=============================
为《飞书多维表格·从零到一》课程自动创建练习模板。

功能：
  1. 创建新的多维表格应用（独立 bitable 或知识库节点）
  2. 支持多张数据表（第一张复用默认表，后续表通过 API 创建）
  3. 每张表独立配置：首字段名 + 自定义字段 + 默认视图重命名 + 示例数据 + 视图
  4. 自动清理默认字段和空行
  5. 设置管理员权限

用法：
  # 内置配置模式（向后兼容）
  python create_bitable_template.py                           # 创建第1课模板
  python create_bitable_template.py --lesson 1                # 同上
  python create_bitable_template.py --lesson 1 --wiki         # 创建到知识库
  python create_bitable_template.py --dry-run                 # 只打印计划

  # JSON 配置模式（推荐）
  python create_bitable_template.py --config template.json              # 从 JSON 创建
  python create_bitable_template.py --config template.json --wiki       # 创建到知识库
  python create_bitable_template.py --config template.json --dry-run    # 预览计划

JSON 配置格式（多表）：
  {
    "app_name": "第N课·标题",
    "tables": [
      {
        "name": "数据表1",
        "first_field_name": "首字段名",
        "default_view_name": "全部数据",
        "fields": [...],
        "views": [...],
        "records": [...]
      },
      {
        "name": "数据表2",
        ...
      }
    ]
  }

  也兼容单表格式（"table" 代替 "tables"）。

依赖：
  - feishu_common.py（同目录）
  - 00.系统/.env（飞书凭据）
"""

import sys
import time
import json
import argparse
from pathlib import Path

# 确保能 import 同目录的 feishu_common
sys.path.insert(0, str(Path(__file__).parent))
from feishu_common import FeishuClient, DELAY

sys.stdout.reconfigure(encoding="utf-8")

# ═══════════════════════════════════════════════════════════
# 常量配置
# ═══════════════════════════════════════════════════════════
import os

ADMIN_PHONE = os.environ.get("FEISHU_ADMIN_PHONE", "18834523581")
ADMIN_OPEN_ID = os.environ.get(
    "FEISHU_ADMIN_OPEN_ID", "ou_36479cbaab14f4cdb9a2ef095de386c1"
)

# 知识库配置（可通过命令行参数覆盖）
SPACE_ID = os.environ.get("FEISHU_WIKI_SPACE_ID", "7610609535908105159")
PARENT_NODE = os.environ.get("FEISHU_WIKI_PARENT_NODE", "DDOLwWnYlijfsUkKuKTcg0bonng")  # 「模板」节点

# 字段类型名称映射（用于 dry-run 显示）
FIELD_TYPE_NAMES = {
    1: "文本", 2: "数字", 3: "单选", 4: "多选", 5: "日期",
    7: "复选框", 11: "人员", 13: "电话", 15: "超链接", 17: "附件",
    99001: "货币", 99002: "评分", 99003: "进度", 99004: "邮箱",
}

# 99xxx extended field types -> (base_type, ui_type) mapping
# Feishu API requires splitting into base type + ui_type for creation
UI_TYPE_MAP = {
    99001: (2, "Currency"),
    99002: (2, "Rating"),
    99003: (2, "Progress"),
    99004: (1, "Email"),
}


# ═══════════════════════════════════════════════════════════
# 第 1 课模板配置（内置，向后兼容）
# ═══════════════════════════════════════════════════════════

LESSON_01_CONFIG = {
    "app_name": "第1课·客户数据对比体验表",
    "tables": [
        {
            "name": "客户信息",
            "first_field_name": "客户姓名",
            "default_view_name": "全部数据",
            "fields": [
                {"field_name": "公司", "type": 1},
                {
                    "field_name": "客户等级",
                    "type": 3,
                    "property": {
                        "options": [
                            {"name": "A级"},
                            {"name": "B级"},
                            {"name": "C级"},
                        ]
                    },
                },
                {
                    "field_name": "签约日期",
                    "type": 5,
                    "property": {"date_formatter": "yyyy/MM/dd"},
                },
                {"field_name": "负责人", "type": 1},
                {
                    "field_name": "合同金额",
                    "type": 2,
                    "property": {"formatter": "0.00"},
                },
                {
                    "field_name": "状态",
                    "type": 3,
                    "property": {
                        "options": [
                            {"name": "待办"},
                            {"name": "进行中"},
                            {"name": "已完成"},
                        ]
                    },
                },
            ],
            "views": [
                {"view_name": "按等级看板", "view_type": "kanban"},
                {"view_name": "签约日历", "view_type": "calendar"},
            ],
            "records": [
                {"客户姓名": "张伟", "公司": "星辰科技", "客户等级": "A级", "签约日期": 1736006400000, "负责人": "李明", "合同金额": 158000, "状态": "已完成"},
                {"客户姓名": "王芳", "公司": "云帆网络", "客户等级": "B级", "签约日期": 1736265600000, "负责人": "张丽", "合同金额": 86000, "状态": "已完成"},
                {"客户姓名": "李强", "公司": "鼎新咨询", "客户等级": "A级", "签约日期": 1736611200000, "负责人": "李明", "合同金额": 220000, "状态": "已完成"},
                {"客户姓名": "赵敏", "公司": "汇通物流", "客户等级": "C级", "签约日期": 1736870400000, "负责人": "王磊", "合同金额": 35000, "状态": "进行中"},
                {"客户姓名": "陈浩", "公司": "蓝桥教育", "客户等级": "B级", "签约日期": 1737129600000, "负责人": "张丽", "合同金额": 92000, "状态": "已完成"},
                {"客户姓名": "刘洋", "公司": "翠微食品", "客户等级": "A级", "签约日期": 1737475200000, "负责人": "李明", "合同金额": 175000, "状态": "已完成"},
                {"客户姓名": "孙静", "公司": "明道传媒", "客户等级": "C级", "签约日期": 1737734400000, "负责人": "王磊", "合同金额": 28000, "状态": "进行中"},
                {"客户姓名": "周杰", "公司": "恒远机械", "客户等级": "B级", "签约日期": 1738339200000, "负责人": "李明", "合同金额": 110000, "状态": "进行中"},
                {"客户姓名": "吴婷", "公司": "锦绣地产", "客户等级": "A级", "签约日期": 1738684800000, "负责人": "张丽", "合同金额": 310000, "状态": "已完成"},
                {"客户姓名": "郑凯", "公司": "万象商贸", "客户等级": "B级", "签约日期": 1738944000000, "负责人": "王磊", "合同金额": 78000, "状态": "已完成"},
                {"客户姓名": "黄蕾", "公司": "创域软件", "客户等级": "C级", "签约日期": 1739289600000, "负责人": "张丽", "合同金额": 42000, "状态": "待办"},
                {"客户姓名": "林峰", "公司": "泰和医药", "客户等级": "A级", "签约日期": 1739548800000, "负责人": "李明", "合同金额": 260000, "状态": "进行中"},
                {"客户姓名": "何欣", "公司": "龙腾电子", "客户等级": "B级", "签约日期": 1739808000000, "负责人": "王磊", "合同金额": 95000, "状态": "进行中"},
                {"客户姓名": "罗琳", "公司": "嘉禾农业", "客户等级": "C级", "签约日期": 1739980800000, "负责人": "张丽", "合同金额": 31000, "状态": "待办"},
                {"客户姓名": "马超", "公司": "信达金融", "客户等级": "A级", "签约日期": 1740153600000, "负责人": "李明", "合同金额": 420000, "状态": "进行中"},
                {"客户姓名": "朱丹", "公司": "华美装饰", "客户等级": "B级", "签约日期": 1740412800000, "负责人": "王磊", "合同金额": 88000, "状态": "待办"},
                {"客户姓名": "谢晨", "公司": "博学文化", "客户等级": "A级", "签约日期": 1740672000000, "负责人": "张丽", "合同金额": 195000, "状态": "待办"},
                {"客户姓名": "韩冰", "公司": "天成建设", "客户等级": "C级", "签约日期": 1740758400000, "负责人": "李明", "合同金额": 55000, "状态": "待办"},
                {"客户姓名": "曹阳", "公司": "盛世集团", "客户等级": "B级", "签约日期": 1741104000000, "负责人": "王磊", "合同金额": 130000, "状态": "待办"},
                {"客户姓名": "冯雪", "公司": "优品零售", "客户等级": "A级", "签约日期": 1741363200000, "负责人": "张丽", "合同金额": 240000, "状态": "待办"},
            ],
        },
    ],
}

# 课程模板注册表（后续课程在此添加配置即可）
LESSON_CONFIGS = {
    1: LESSON_01_CONFIG,
}


# ═══════════════════════════════════════════════════════════
# 配置归一化
# ═══════════════════════════════════════════════════════════

def normalize_config(config: dict) -> dict:
    """将配置归一化为多表格式。

    兼容两种格式：
    - 新格式: {"tables": [{ ... }, { ... }]}
    - 旧格式: {"table": { ... }}  → 自动转为 {"tables": [{ ... }]}
    """
    if "tables" in config:
        return config
    if "table" in config:
        config = dict(config)
        config["tables"] = [config.pop("table")]
        return config
    raise ValueError("配置中缺少 'tables' 或 'table' 字段")


# ═══════════════════════════════════════════════════════════
# 模板搭建器
# ═══════════════════════════════════════════════════════════

class BitableTemplateBuilder:
    """使用飞书 API 创建多维表格练习模板。

    支持两种创建模式：
    - 独立模式：创建独立的多维表格应用
    - 知识库模式（--wiki）：在知识库「模板」节点下创建

    支持多张数据表：第一张复用默认表，后续表通过 API 新建。
    """

    def __init__(self, dry_run=False, wiki_mode=False):
        self.client = FeishuClient()
        self.dry_run = dry_run
        self.wiki_mode = wiki_mode
        self.app_token = None
        self.node_token = None  # 知识库模式下的 node_token
        # 当前正在操作的表（每张表切换时重置）
        self.table_id = None
        self.field_map = {}
        self.warnings = []  # 搭建过程中的警告（降级/失败字段等）

    def build(self, config: dict):
        """执行完整的模板搭建流程"""
        config = normalize_config(config)
        app_name = config["app_name"]
        tables_cfg = config["tables"]

        # 允许 JSON 配置中的 wiki_mode 字段（命令行 --wiki 优先）
        if not self.wiki_mode and config.get("wiki_mode"):
            self.wiki_mode = True

        mode_label = "知识库模式" if self.wiki_mode else "独立模式"

        print(f"\n{'='*60}")
        print(f"  🏗️  开始搭建模板：{app_name}")
        print(f"  📍 模式：{mode_label}")
        print(f"  📊 数据表：{len(tables_cfg)} 张")
        print(f"{'='*60}\n")

        if self.dry_run:
            self._print_plan(config)
            return

        # Step 0: 认证
        self.client.authenticate()

        # Step 1: 创建多维表格应用
        if self.wiki_mode:
            self._create_wiki_app(app_name)
        else:
            self._create_app(app_name)

        # Step 1.5: 获取默认脏表 ID（所有表创建完后删除它）
        default_table_id = self._get_default_table_id()

        # Step 2-N: 逐张搭建数据表
        # 核心策略：ALL tables use "create with fields" API
        # → 首字段直接是 type=1 文本，无默认字段，无空行
        table_results = []
        for idx, table_cfg in enumerate(tables_cfg):
            table_num = idx + 1
            table_name = table_cfg["name"]

            print(f"\n{'─'*60}")
            print(f"  📊 数据表 {table_num}/{len(tables_cfg)}：{table_name}")
            print(f"{'─'*60}")

            # 重置当前表状态
            self.table_id = None
            self.field_map = {}

            # 直接创建干净的表（含字段定义）
            first_field_name = table_cfg.get("first_field_name", "名称")
            default_view_name = table_cfg.get("default_view_name", "全部数据")
            self._create_table_with_fields(
                table_name, first_field_name,
                table_cfg.get("fields", []),
                default_view_name,
            )

            # 写入数据 + 创建视图（无需清理字段/空行）
            if table_cfg.get("records"):
                self._insert_records(table_cfg["records"])
            if table_cfg.get("views"):
                self._create_views(table_cfg["views"])

            table_results.append({
                "name": table_name,
                "table_id": self.table_id,
            })

        # 删除飞书自动创建的默认脏表
        self._delete_table(default_table_id)

        # 设置管理员
        self._set_admin()

        # 完成
        link = self._get_link()
        print(f"\n{'='*60}")
        print(f"  ✅ 模板搭建完成！")
        print(f"  📋 应用 Token: {self.app_token}")
        if self.node_token:
            print(f"  📄 节点 Token: {self.node_token}")
        print(f"  📊 数据表: {len(table_results)} 张")
        for tr in table_results:
            print(f"     - {tr['name']} ({tr['table_id']})")
        print(f"  🔗 打开链接: {link}")
        if self.warnings:
            print(f"\n  ⚠️  需手动处理的事项 ({len(self.warnings)} 项):")
            for i, w in enumerate(self.warnings, 1):
                print(f"     {i}. {w}")
        print(f"{'='*60}\n")

        # 输出结构化结果供调用方使用
        result_info = {
            "app_token": self.app_token,
            "tables": table_results,
            "link": link,
        }
        if self.node_token:
            result_info["node_token"] = self.node_token
        if self.warnings:
            result_info["warnings"] = self.warnings
        print(f"__RESULT_JSON__:{json.dumps(result_info, ensure_ascii=False)}")

        # 生成配置方案文档 markdown 并保存到临时文件
        self._save_config_doc_markdown(config, table_results, link)

    def _save_config_doc_markdown(self, config, table_results, link):
        """生成详尽的配置方案文档 Markdown 并保存到临时文件。

        不直接调用 docx API（表格无法渲染），而是保存到 /tmp/bitable_config_doc.md，
        由 agent 通过 feishu_create_doc 插件创建（能正确渲染 markdown 表格）。
        """
        app_name = config["app_name"]
        tables_cfg = config["tables"]

        print(f"\n📝 生成配置方案文档...")

        markdown_content = self._generate_config_markdown(
            app_name, tables_cfg, table_results, link
        )

        # 保存到临时文件
        doc_path = "/tmp/bitable_config_doc.md"
        with open(doc_path, "w", encoding="utf-8") as f:
            f.write(markdown_content)

        doc_title = f"{app_name} - 配置方案"
        print(f"  ✅ 配置方案已生成: {doc_path}（{len(markdown_content)} 字符）")
        print(f"__CONFIG_DOC_READY__:{doc_path}")
        print(f"__CONFIG_DOC_TITLE__:{doc_title}")

    # ─── Markdown → 飞书 Block 转换 ──────────────────

    def _markdown_to_blocks(self, markdown_content):
        """将 Markdown 文本转换为飞书文档 block 结构。

        注意：tenant_access_token 下，bullet(16)/ordered(17)/callout(14) 会报错，
        全部降级为 text(2) block，通过前缀 "· "/"▸ " 模拟列表样式。
        """
        blocks = []
        for line in markdown_content.split("\n"):
            if not line.strip():
                continue
            if line.startswith("# "):
                blocks.append({
                    "block_type": 3,
                    "heading1": {"elements": [{"text_run": {"content": line[2:].strip()}}]},
                })
            elif line.startswith("## "):
                blocks.append({
                    "block_type": 4,
                    "heading2": {"elements": [{"text_run": {"content": line[3:].strip()}}]},
                })
            elif line.startswith("### "):
                blocks.append({
                    "block_type": 5,
                    "heading3": {"elements": [{"text_run": {"content": line[4:].strip()}}]},
                })
            elif line.startswith("---"):
                blocks.append({
                    "block_type": 22,
                    "divider": {},
                })
            elif line.startswith("> "):
                # callout 不支持，降级为带 ▸ 的文本
                elements = self._parse_inline_bold("▸ " + line[2:].strip())
                blocks.append({
                    "block_type": 2,
                    "text": {"elements": elements},
                })
            elif line.startswith("- "):
                # bullet 不支持，降级为带 · 的文本
                content = line[2:].strip()
                elements = self._parse_inline_bold("· " + content)
                blocks.append({
                    "block_type": 2,
                    "text": {"elements": elements},
                })
            elif line.startswith("  - "):
                # 二级列表
                content = line[4:].strip()
                elements = self._parse_inline_bold("  · " + content)
                blocks.append({
                    "block_type": 2,
                    "text": {"elements": elements},
                })
            else:
                elements = self._parse_inline_bold(line)
                blocks.append({
                    "block_type": 2,
                    "text": {"elements": elements},
                })
        return blocks

    def _parse_inline_bold(self, text):
        """解析 **加粗** 语法，返回 text_run elements 列表"""
        import re
        elements = []
        parts = re.split(r'(\*\*.*?\*\*)', text)
        for part in parts:
            if not part:
                continue
            if part.startswith("**") and part.endswith("**"):
                elements.append({
                    "text_run": {
                        "content": part[2:-2],
                        "text_element_style": {"bold": True},
                    }
                })
            else:
                elements.append({"text_run": {"content": part}})
        return elements if elements else [{"text_run": {"content": text}}]

    # ─── 配置文档内容生成 ─────────────────────────────

    def _generate_config_markdown(self, app_name, tables_cfg, table_results, link):
        """生成九步法配置方案 Markdown（对齐课程：拆→画→建→标→联→视→盘→流→权）"""
        md = []
        field_type_names = {
            1: "文本", 2: "数字", 3: "单选", 4: "多选", 5: "日期",
            7: "复选框", 11: "人员", 13: "电话", 15: "超链接",
            17: "附件", 20: "公式", 99001: "货币",
        }

        # ─── 分析表结构，提取特征 ──────────────────────
        analysis = self._analyze_tables(tables_cfg)
        relations = self._suggest_relations(tables_cfg) if len(tables_cfg) > 1 else []

        # ═══ 标题 + 九步法导语 ═══
        md.append(f"# {app_name} - 配置方案")
        md.append("")
        md.append("> **九步法配置指南**：拆→画→建→标→联→视→盘→流→权。Step 1-4 已由多维表哥祥瑞完成，按 Step 5→9 逐步完成剩余配置。")
        md.append(">")
        md.append("> *以下方案由 AI 生成，仅供参考。请根据实际业务需求调整。*")
        md.append("")

        # ═══ 系统总览思维导图 ═══
        md.append(self._generate_mindmap(app_name, tables_cfg, analysis, relations))
        md.append("")

        # ─── 警告事项 ───
        if self.warnings:
            md.append("> **注意**：")
            for w in self.warnings:
                md.append(f"> - {w}")
            md.append("")

        # ═══ 方案价值 ═══
        md.append("## 方案价值")
        md.append("")
        md.append(self._generate_value_section(app_name, tables_cfg, analysis, relations))
        md.append("")

        # ═══ Step 1 拆业务（已完成） ═══
        md.append("## Step 1 拆业务（已完成）")
        md.append("")
        md.append(f"- **多维表格**：[{app_name}]({link})")
        md.append(f"- **系统类型**：{analysis.get('system_type', '通用')}")
        md.append("- **数据表**：")
        for t_cfg in tables_cfg:
            field_count = len(t_cfg.get("fields", []))
            record_count = len(t_cfg.get("records", []))
            md.append(f"  - {t_cfg['name']}（{field_count} 个字段，{record_count} 条示例数据）")
        md.append("")

        # ═══ Step 2 画逻辑图（已完成） ═══
        md.append("## Step 2 画逻辑图（已完成）")
        md.append("")
        if len(tables_cfg) > 1:
            md.append("数据流转关系如下：")
            md.append("")
            md.append(self._generate_er_diagram(tables_cfg, relations))
            md.append("")
        else:
            md.append("单表系统，无需画逻辑图。")
            md.append("")

        # ═══ Step 3 建底表（已完成） ═══
        md.append("## Step 3 建底表（已完成）")
        md.append("")
        md.append("- **已创建视图**：")
        for t_cfg in tables_cfg:
            default_view = t_cfg.get("default_view_name", "全部数据")
            views = [default_view] + [v["view_name"] for v in t_cfg.get("views", []) if v.get("view_type") != "calendar"]
            md.append(f"  - {t_cfg['name']}：{' / '.join(views)}")
        md.append("")

        # ═══ Step 4 打标签（已完成） ═══
        md.append("## Step 4 打标签（已完成）")
        md.append("")
        for t_cfg in tables_cfg:
            md.append(f"### {t_cfg['name']}")
            md.append("")
            md.append("| 字段名 | 类型 | 选项/配置 | 说明 |")
            md.append("|-------|------|----------|------|")
            first_name = t_cfg.get("first_field_name", "名称")
            for f in t_cfg.get("fields", []):
                f_type = field_type_names.get(f.get("type", 1), f"类型{f.get('type')}")
                prop = f.get("property", {})
                options_str = "—"
                is_first = (f["field_name"] == first_name)
                desc = "首字段" if is_first else self._guess_field_desc(f["field_name"], f.get("type", 1))
                if prop:
                    if "options" in prop:
                        opts = [o["name"] for o in prop["options"]]
                        options_str = " / ".join(opts)
                    elif "date_formatter" in prop:
                        options_str = prop["date_formatter"]
                    elif "formatter" in prop:
                        options_str = f"格式: {prop['formatter']}"
                    elif "currency_code" in prop:
                        options_str = prop["currency_code"]
                md.append(f"| {f['field_name']} | {f_type} | {options_str} | {desc} |")
            md.append("")

        # 公式字段（Step 4 的补充：需手动配置的公式）
        formula_fields = []
        for t_cfg in tables_cfg:
            for f in t_cfg.get("fields", []):
                if f.get("type") == 20:
                    formula_fields.append((t_cfg["name"], f["field_name"]))

        suggested_formulas = self._suggest_formulas(tables_cfg, analysis)

        if formula_fields or suggested_formulas:
            md.append("### 公式字段（需手动配置）")
            md.append("")
            md.append("| 表 | 字段名 | 公式 | 操作 | 用途 |")
            md.append("|----|-------|------|------|------|")
            for table_name, field_name in formula_fields:
                formula = self._guess_formula(table_name, field_name, tables_cfg)
                purpose = self._guess_formula_purpose(field_name)
                md.append(f"| {table_name} | {field_name} | `{formula}` | 点击字段名 → 编辑 → 粘贴公式 | {purpose} |")
            for sf in suggested_formulas:
                action = sf.get("action", "点击\"+\" → 公式 → 粘贴")
                md.append(f"| {sf['table']} | {sf['field']}（新增） | `{sf['formula']}` | {action} | {sf['purpose']} |")
            md.append("")

        # ═══ Step 5 🔗 建关系 ═══
        if len(tables_cfg) > 1:
            md.append("## Step 5 建关系")
            md.append("")
            md.append("> **核心口诀**：先关联，再引用（六字诀）")
            md.append("")
            if relations:
                md.append("| 源表 | 新建字段 | 目标表 | 关联类型 | 操作路径 |")
                md.append("|------|---------|--------|---------|---------|")
                for rel in relations:
                    md.append(f"| {rel['source']} | {rel['field']} | {rel['target']} | {rel['type']} | 点击\"+\" → 关联 → 选择\"{rel['target']}\" |")
                md.append("")
                md.append("**关联建立后的进阶操作**：")
                md.append("- 在关联字段旁添加「查找引用」字段，可跨表引用目标表的任意字段")
                md.append("- 在关联字段旁添加「汇总」字段，可对关联记录的数字字段求和/计数/平均")
            else:
                md.append("- 根据业务需要，可手动添加跨表「关联」字段建立表间关系")
            md.append("")
        else:
            md.append("## Step 5 建关系（单表系统，可跳过）")
            md.append("")
            md.append("当前为单表系统。如后续新增数据表，可通过「关联」字段建立表间关系。")
            md.append("")

        # ═══ Step 6 👁️ 配视图 ═══
        md.append("## Step 6 配视图")
        md.append("")
        md.append("> **核心口诀**：一份数据，多种看法")
        md.append("")
        md.append("| 数据表 | 视图名 | 类型 | 用途 | 配置要点 |")
        md.append("|-------|-------|------|------|---------|")
        for t_cfg in tables_cfg:
            views = self._suggest_views(t_cfg)
            for v in views:
                md.append(f"| {t_cfg['name']} | {v['name']} | {v['type']} | {v['purpose']} | {v['config']} |")
        md.append("")
        md.append("**操作路径**：数据表顶部 → \"+\" 添加视图 → 选择类型 → 设置筛选/分组/排序")
        md.append("")

        # ═══ Step 7 📊 搭仪表盘 ═══
        md.append("## Step 7 搭仪表盘")
        md.append("")
        md.append("> **核心口诀**：先让数据说话，再让画面好看")
        md.append("")
        dashboards = self._suggest_dashboards(tables_cfg, analysis)
        for dash in dashboards:
            md.append(f"**{dash['name']}**（面向：{dash['audience']}）")
            md.append("")
            md.append("| 组件名 | 类型 | 数据源 | 维度/横轴 | 指标/纵轴 | 筛选条件 |")
            md.append("|-------|------|--------|----------|----------|---------|")
            for comp in dash["components"]:
                md.append(f"| {comp['name']} | {comp['type']} | {comp['source']} | {comp['dimension']} | {comp['metric']} | {comp['filter']} |")
            md.append("")
        md.append("**操作路径**：左下角 → 新建仪表盘 → 添加组件 → 设置数据源和样式")
        md.append("")

        # ═══ Step 8 ⚡ 建流程 ═══
        md.append("## Step 8 建流程")
        md.append("")
        md.append("> **核心口诀**：一个触发 + 多个动作，让系统自己转")
        md.append("")
        automations = self._suggest_automations(tables_cfg, analysis)
        md.append("| 名称 | 触发条件 | 执行操作 | 配置说明 |")
        md.append("|------|---------|---------|---------|")
        for auto in automations:
            md.append(f"| {auto['name']} | {auto['trigger']} | {auto['action']} | {auto['detail']} |")
        md.append("")
        md.append("**操作路径**：多维表格右上角 → 自动化 → 新建流程")
        md.append("")

        # ═══ Step 9 🔒 设权限 ═══
        md.append("## Step 9 设权限")
        md.append("")
        md.append("> **核心口诀**：千人千面，权限放最后（因为它依赖前面所有步骤）")
        md.append("")
        roles = self._suggest_roles(tables_cfg, analysis)
        md.append("**角色定义**：")
        md.append("")
        md.append("| 角色 | 成员 | 说明 |")
        md.append("|------|------|------|")
        for role in roles:
            md.append(f"| {role['name']} | {role['members']} | {role['desc']} |")
        md.append("")
        md.append("**数据表权限矩阵**：")
        md.append("")
        table_names = [t["name"] for t in tables_cfg]
        header = "| 角色 | " + " | ".join(table_names) + " | 记录范围 |"
        sep = "|------|" + "|".join(["------"] * len(table_names)) + "|---------|"
        md.append(header)
        md.append(sep)
        for role in roles:
            perms = " | ".join(role.get("table_perms", ["可管理"] * len(table_names)))
            md.append(f"| {role['name']} | {perms} | {role.get('record_scope', '所有记录')} |")
        md.append("")

        # 行列权限
        person_fields = []
        for t_cfg in tables_cfg:
            for f in t_cfg.get("fields", []):
                if f.get("type") == 11:
                    person_fields.append((t_cfg["name"], f["field_name"]))
        if person_fields:
            md.append("**行级权限（数据隔离）**：")
            for table_name, field_name in person_fields:
                md.append(f"- {table_name}：绑定「{field_name}」字段 → \"与成员本人相关的记录\" → 每人只看自己负责的数据")
            md.append("")

        sensitive_fields = [
            (t["name"], f["field_name"])
            for t in tables_cfg
            for f in t.get("fields", [])
            if any(kw in f["field_name"] for kw in ["金额", "薪资", "工资", "成本", "利润", "价格", "报价"])
        ]
        if sensitive_fields:
            md.append("**列级权限（敏感字段保护）**：")
            for table_name, field_name in sensitive_fields:
                md.append(f"- {table_name}.{field_name}：对普通成员设为「不可阅读」")
            md.append("")

        md.append("**操作路径**：多维表格右上角 → 高级权限 → 开启 → 添加自定义角色")
        md.append("")

        # ═══ 应用模式（可选附加步骤） ═══
        if len(tables_cfg) >= 2:
            md.append("## 应用模式（可选进阶）")
            md.append("")
            md.append("当系统复杂度较高、需要面向不同角色提供不同操作界面时，建议开启应用模式。")
            md.append("")
            app_pages = self._suggest_app_pages(tables_cfg, analysis, roles)
            md.append("| 页面组 | 页面 | 组件 | 面向角色 |")
            md.append("|-------|------|------|---------|")
            for page in app_pages:
                md.append(f"| {page['group']} | {page['name']} | {page['components']} | {page['audience']} |")
            md.append("")
            md.append("**操作路径**：多维表格左上角 → 切换到应用模式 → 编辑页面")
            md.append("")

        # ═══ 修改意见区 ═══
        md.append("---")
        md.append("")
        md.append("## 修改意见区")
        md.append("")
        md.append("> **如果需要修改表结构，请直接在下方编辑，然后告诉我。我会按你的修改调整多维表格。**")
        md.append("")
        md.append("### 要新增的字段")
        md.append("| 表 | 字段名 | 类型 | 选项/说明 |")
        md.append("|----|-------|------|----------|")
        md.append("|    |       |      |          |")
        md.append("")
        md.append("### 要删除的字段")
        md.append("| 表 | 字段名 | 原因 |")
        md.append("|----|-------|------|")
        md.append("|    |       |      |")
        md.append("")
        md.append("### 要修改的字段")
        md.append("| 表 | 原字段名 | 修改内容 |")
        md.append("|----|---------|---------|")
        md.append("|    |         |         |")
        md.append("")
        md.append("### 其他修改意见")
        md.append("（自由填写）")

        return "\n".join(md)

    def _analyze_tables(self, tables_cfg):
        """分析所有表的字段特征，用于智能推荐"""
        analysis = {
            "all_fields": [],
            "select_fields": [],
            "date_fields": [],
            "number_fields": [],
            "person_fields": [],
            "status_fields": [],
            "has_money": False,
            "system_type": "通用",
        }

        for t_cfg in tables_cfg:
            table_name = t_cfg["name"]
            for f in t_cfg.get("fields", []):
                fn = f["field_name"]
                ft = f.get("type", 1)
                analysis["all_fields"].append((table_name, fn, ft))

                if ft == 3:
                    opts = [o["name"] for o in f.get("property", {}).get("options", [])]
                    analysis["select_fields"].append((table_name, fn, opts))
                    if any(kw in fn for kw in ["状态", "阶段", "进度", "优先级"]):
                        analysis["status_fields"].append((table_name, fn, opts))
                elif ft == 5:
                    analysis["date_fields"].append((table_name, fn))
                elif ft in (2, 99001):
                    analysis["number_fields"].append((table_name, fn))
                    if any(kw in fn for kw in ["金额", "价格", "成本", "利润", "薪资", "预算", "收入"]):
                        analysis["has_money"] = True
                elif ft == 11:
                    analysis["person_fields"].append((table_name, fn))

        # 推断系统类型
        all_names = " ".join([t["name"] for t in tables_cfg] + [f[1] for f in analysis["all_fields"]])
        if any(kw in all_names for kw in ["项目", "任务", "里程碑", "迭代"]):
            analysis["system_type"] = "项目管理"
        elif any(kw in all_names for kw in ["客户", "线索", "商机", "合同", "销售"]):
            analysis["system_type"] = "CRM"
        elif any(kw in all_names for kw in ["库存", "商品", "出库", "入库", "采购", "供应商"]):
            analysis["system_type"] = "进销存"
        elif any(kw in all_names for kw in ["工单", "服务", "售后", "投诉", "报修"]):
            analysis["system_type"] = "工单系统"

        return analysis

    def _guess_field_desc(self, field_name, field_type):
        """根据字段名猜测用途说明"""
        mapping = {
            "状态": "流程状态管理", "优先级": "紧急程度标记", "阶段": "流程阶段",
            "负责人": "主要负责人", "参与人": "协作成员", "创建人": "记录创建者",
            "截止日期": "任务/事项截止时间", "开始日期": "起始时间", "签约日期": "签约时间",
            "完成日期": "实际完成时间", "创建日期": "记录创建时间",
            "金额": "金额数值", "预算": "预算金额", "成本": "成本费用",
            "备注": "补充说明", "描述": "详细描述", "说明": "说明信息",
            "电话": "联系电话", "邮箱": "电子邮箱", "地址": "地址信息",
            "附件": "相关文件/图片",
        }
        for key, desc in mapping.items():
            if key in field_name:
                return desc
        return ""

    def _generate_value_section(self, app_name, tables_cfg, analysis, relations):
        """生成方案价值说明（基于实际表结构，不水）"""
        sys_type = analysis.get("system_type", "通用")
        table_count = len(tables_cfg)
        total_fields = sum(len(t.get("fields", [])) for t in tables_cfg)
        has_person = bool(analysis.get("person_fields"))
        has_status = bool(analysis.get("status_fields"))
        has_date = bool(analysis.get("date_fields"))
        has_money = analysis.get("has_money", False)

        lines = []

        # 系统定位
        lines.append(f"本方案为你设计了一套 **{table_count} 表联动**的{sys_type}系统，共 {total_fields} 个字段。")

        # 核心价值（根据实际字段特征生成，不空谈）
        values = []
        if table_count > 1 and relations:
            rel_desc = "、".join(f"{r['source']}↔{r['target']}" for r in relations[:3])
            values.append(f"**数据打通**：{rel_desc}跨表关联，消除信息孤岛，一处更新全局同步")
        if has_status:
            status_tables = list(set(t for t, _, _ in analysis["status_fields"]))
            values.append(f"**流程可视**：{'、'.join(status_tables)}的状态字段支持看板拖拽，流程进度一目了然")
        if has_person:
            values.append("**责任到人**：人员字段支持按负责人筛选、行级权限隔离，每人只看自己的数据")
        if has_date:
            values.append("**时间管控**：日期字段支持日历视图、甘特图、到期自动提醒，不漏一个截止日")
        if has_money:
            values.append("**数据决策**：金额字段支持仪表盘汇总分析，用数据驱动业务判断")

        if values:
            lines.append("")
            for v in values:
                lines.append(f"- {v}")

        # 完成 Step 5-9 后能达到的效果
        lines.append("")
        lines.append("完成 Step 5-9 配置后，你将得到：")
        effects = []
        if table_count > 1:
            effects.append("跨表联动的完整数据体系")
        effects.append("多视图切换，不同角色看到不同界面")
        effects.append("仪表盘实时监控关键指标")
        effects.append("自动化规则减少重复操作")
        if has_person:
            effects.append("权限隔离保障数据安全")
        for e in effects:
            lines.append(f"- {e}")

        return "\n".join(lines)

    def _generate_mindmap(self, app_name, tables_cfg, analysis, relations):
        """生成系统总览思维导图 Mermaid（对齐九步法）"""
        import re
        # 提取系统名（去掉"管理系统"等后缀用于根节点）
        sys_name = app_name.replace("管理系统", "").replace("系统", "").strip()
        if not sys_name:
            sys_name = app_name

        # Mermaid mindmap 节点文本需避免特殊字符
        def safe(text):
            return re.sub(r'[()（）\[\]{}]', '', text).strip()

        total_fields = sum(len(t.get('fields', [])) for t in tables_cfg)

        lines = ["```mermaid", "mindmap", f"  root(({safe(sys_name)}))"]

        # 已完成部分
        lines.append("    已完成")
        table_list = " ".join(safe(t['name']) for t in tables_cfg)
        lines.append(f"      拆业务: {table_list}")
        if len(tables_cfg) > 1 and relations:
            rel_desc = " ".join(f"{safe(r['source'])}-{safe(r['target'])}" for r in relations[:3])
            lines.append(f"      画逻辑图: {rel_desc}")
        else:
            lines.append("      画逻辑图")
        lines.append(f"      建底表: {len(tables_cfg)}张表")
        lines.append(f"      打标签: {total_fields}个字段")

        # 待配置部分
        lines.append("    待配置")
        if len(tables_cfg) > 1:
            lines.append("      建关系")
        lines.append("      配视图")
        lines.append("      搭仪表盘")
        lines.append("      建流程")
        lines.append("      设权限")

        lines.append("```")
        return "\n".join(lines)

    def _generate_er_diagram(self, tables_cfg, relations):
        """生成表间关系 ER 图 Mermaid（仅多表时使用）"""
        if len(tables_cfg) < 2:
            return ""

        import re

        field_type_short = {
            1: "text", 2: "number", 3: "select", 4: "multiselect", 5: "date",
            7: "checkbox", 11: "person", 13: "phone", 15: "url",
            17: "attachment", 20: "formula", 99001: "currency",
        }

        # Mermaid erDiagram 实体名/字段名需避免特殊字符和空格
        def safe_name(text):
            # 去掉括号等特殊字符，空格替换为下划线
            return re.sub(r'[()（）\[\]{}<>"\'/\\|]', '', text).replace(' ', '_').strip()

        lines = ["```mermaid", "erDiagram"]

        # 关系线 — 使用简短的半角标签避免解析问题
        if relations:
            for rel in relations:
                rel_type = rel.get("type", "双向关联")
                src = safe_name(rel["source"])
                tgt = safe_name(rel["target"])
                # 提取关系类型简称
                if "1:N" in rel_type or "1对多" in rel_type:
                    lines.append(f'    {src} ||--o{{ {tgt} : "1-N"')
                elif "N:N" in rel_type or "多对多" in rel_type:
                    lines.append(f'    {src} }}o--o{{ {tgt} : "N-N"')
                elif "1:1" in rel_type or "1对1" in rel_type:
                    lines.append(f'    {src} ||--|| {tgt} : "1-1"')
                else:
                    lines.append(f'    {src} ||--o{{ {tgt} : "link"')

        # 实体定义（每张表最多 6 个关键字段）
        for t_cfg in tables_cfg:
            t_name = safe_name(t_cfg["name"])
            lines.append(f"    {t_name} {{")
            fields_shown = 0
            first_name = t_cfg.get("first_field_name", "名称")
            lines.append(f"        text {safe_name(first_name)}")
            fields_shown += 1
            for f in t_cfg.get("fields", []):
                if f["field_name"] == first_name:
                    continue
                if fields_shown >= 6:
                    break
                ft = field_type_short.get(f.get("type", 1), "text")
                fn = safe_name(f["field_name"])
                if fn:
                    lines.append(f"        {ft} {fn}")
                    fields_shown += 1
            lines.append("    }")

        lines.append("```")
        return "\n".join(lines)

    def _suggest_relations(self, tables_cfg):
        """根据表结构推荐跨表关联"""
        relations = []
        seen = set()

        for i, t1 in enumerate(tables_cfg):
            for j, t2 in enumerate(tables_cfg):
                if i >= j:
                    continue
                pair_key = (t1["name"], t2["name"])
                if pair_key in seen:
                    continue

                # 常见的主从关系模式
                pair_patterns = [
                    (["项目", "任务"], "双向关联（1:N）"), (["客户", "合同"], "双向关联（1:N）"),
                    (["客户", "商机"], "双向关联（1:N）"), (["客户", "联系人"], "双向关联（1:N）"),
                    (["客户", "跟进"], "双向关联（1:N）"), (["客户", "订单"], "双向关联（1:N）"),
                    (["商品", "库存"], "双向关联（1:1）"), (["订单", "商品"], "双向关联（N:N）"),
                    (["部门", "成员"], "双向关联（1:N）"), (["分类", "商品"], "双向关联（1:N）"),
                    (["项目", "成员"], "双向关联（N:N）"), (["项目", "文档"], "双向关联（1:N）"),
                    (["项目", "里程碑"], "双向关联（1:N）"), (["项目", "问题"], "双向关联（1:N）"),
                    (["任务", "问题"], "双向关联（1:N）"),
                ]
                # 提取核心名：去掉常见后缀词（用 replace 而非 rstrip 避免逐字符剥离）
                suffixes = ["数据表", "信息表", "管理表", "记录表", "数据", "信息", "管理", "记录", "表"]
                n1_clean = t1["name"]
                n2_clean = t2["name"]
                for suffix in suffixes:
                    if n1_clean.endswith(suffix):
                        n1_clean = n1_clean[:-len(suffix)]
                        break
                for suffix in suffixes:
                    if n2_clean.endswith(suffix):
                        n2_clean = n2_clean[:-len(suffix)]
                        break
                for pattern, rel_type in pair_patterns:
                    if n1_clean in pattern and n2_clean in pattern:
                        relations.append({
                            "source": t1["name"],
                            "field": f"关联{t2['name']}",
                            "target": t2["name"],
                            "target_field": t2.get("first_field_name", "名称"),
                            "type": rel_type,
                        })
                        seen.add(pair_key)
                        break

                # 如果没匹配到模式，检查字段名暗示
                if pair_key not in seen:
                    t1_fields = {f["field_name"] for f in t1.get("fields", [])}
                    for fn in t1_fields:
                        if n2_clean in fn:
                            relations.append({
                                "source": t1["name"],
                                "field": f"关联{t2['name']}",
                                "target": t2["name"],
                                "target_field": t2.get("first_field_name", "名称"),
                                "type": "双向关联",
                            })
                            seen.add(pair_key)
                            break

        return relations

    def _guess_formula(self, table_name, field_name, tables_cfg):
        """根据实际字段名生成具体可粘贴的飞书公式"""
        table_fields = []
        table_cfg = None
        for t in tables_cfg:
            if t["name"] == table_name:
                table_cfg = t
                table_fields = [f["field_name"] for f in t.get("fields", [])]
                break

        # 获取具体字段引用
        date_field = next((f for f in table_fields if "截止" in f or "到期" in f), None)
        start_field = next((f for f in table_fields if "开始" in f), None)
        end_field = next((f for f in table_fields if "截止" in f or "结束" in f or "完成日期" in f), None)
        status_field = next((f for f in table_fields if "状态" in f or "阶段" in f), None)
        person_field = next((f for f in table_fields if any(f.get("type") == 11 for f in (table_cfg or {}).get("fields", []) if f["field_name"] == f)), None)
        num_fields = [f for f in table_fields if any(kw in f for kw in ["金额", "数量", "销售额", "成本", "价格", "预算", "收入"])]

        # 获取状态选项
        status_opts = []
        if table_cfg and status_field:
            for f in table_cfg.get("fields", []):
                if f["field_name"] == status_field:
                    status_opts = [o["name"] for o in f.get("property", {}).get("options", [])]
                    break
        done_opt = next((o for o in status_opts if any(kw in o for kw in ["完成", "关闭", "结束"])), "已完成")

        # 完成率/进度
        if "完成率" in field_name or "进度" in field_name:
            if status_field:
                return f'ROUND([{table_name}].COUNTIF(CurrentValue.[{status_field}]="{done_opt}") / [{table_name}].COUNTIF(CurrentValue.[{status_field}]!="") * 100, 1) & "%"'
            return f'待填写 — 需要状态字段来计算完成率'

        # 逾期预警
        if "逾期" in field_name or "预警" in field_name:
            if date_field:
                return f'IF(ISBLANK([{date_field}]),"",IF([{date_field}]<TODAY(),"⚠️ 已逾期",IF(DAYS([{date_field}],TODAY())<3,"⏰ 即将到期","✅ 正常")))'
            return f'待填写 — 需要截止日期字段'

        # 工期/天数/时长
        if "工期" in field_name or "天数" in field_name or "时长" in field_name:
            if start_field and end_field:
                return f'IF(AND(!ISBLANK([{start_field}]),!ISBLANK([{end_field}])),DATEDIF([{start_field}],[{end_field}],"D"),"")'
            return f'待填写 — 需要开始日期和结束日期字段'

        # 总金额/合计
        if "总" in field_name and any(kw in field_name for kw in ["金额", "额", "合计"]):
            # 尝试找关联表的金额字段
            for t in tables_cfg:
                if t["name"] != table_name:
                    for f in t.get("fields", []):
                        if any(kw in f["field_name"] for kw in ["金额", "价格", "费用"]):
                            return f'[关联{t["name"]}].FILTER(CurrentValue.[{t.get("first_field_name", "名称")}]!="").[{f["field_name"]}].SUM()'
            if num_fields:
                return f'[{num_fields[0]}]'
            return f'待填写 — 建立跨表关联后配置：[关联表].[金额字段].SUM()'

        # 排名
        if "排名" in field_name:
            if num_fields:
                return f'RANK([{num_fields[0]}],[{table_name}].[{num_fields[0]}])'
            return f'待填写 — 需要数值字段来排名'

        # 信息摘要/概览
        if "摘要" in field_name or "概览" in field_name or "简介" in field_name:
            parts = []
            first_field = table_cfg.get("first_field_name", "名称") if table_cfg else "名称"
            if status_field:
                parts.append(f'[{status_field}]')
            if date_field:
                parts.append(f'TEXT([{date_field}],"MM/DD")')
            if parts:
                return f'CONCATENATE([{first_field}]," | ",{",\" | \",".join(parts)})'
            return f'CONCATENATE([{first_field}])'

        # 创建天数
        if "创建" in field_name and "天" in field_name:
            return 'DATEDIF(CREATED_TIME(),TODAY(),"D")'

        return "待填写（请根据业务需求配置）"

    def _guess_formula_purpose(self, field_name):
        """猜测公式用途"""
        mapping = {
            "完成率": "统计完成比例", "进度": "显示进度百分比",
            "逾期": "逾期预警标记", "预警": "预警状态提示",
            "工期": "计算工作天数", "天数": "计算天数差",
            "时长": "计算持续时间", "总金额": "汇总关联金额",
            "排名": "排名计算", "合计": "求和汇总",
            "摘要": "信息汇总展示", "概览": "关键信息一行展示",
            "创建": "记录存在天数",
        }
        for key, purpose in mapping.items():
            if key in field_name:
                return purpose
        return "自定义计算"

    def _suggest_formulas(self, tables_cfg, analysis):
        """根据表结构和系统类型推荐新增的实用公式字段"""
        suggestions = []
        sys_type = analysis.get("system_type", "通用")

        for t_cfg in tables_cfg:
            table_name = t_cfg["name"]
            fields = t_cfg.get("fields", [])
            field_names = [f["field_name"] for f in fields]
            existing_formula_names = [f["field_name"] for f in fields if f.get("type") == 20]

            # ── 通用公式（所有系统类型） ──

            # 逾期预警
            has_deadline = any("截止" in fn or "到期" in fn for fn in field_names)
            has_overdue = any("逾期" in fn or "预警" in fn for fn in field_names + existing_formula_names)
            if has_deadline and not has_overdue:
                date_field = next((fn for fn in field_names if "截止" in fn or "到期" in fn), None)
                if not date_field:
                    continue
                suggestions.append({
                    "table": table_name,
                    "field": "逾期预警",
                    "formula": f'IF(ISBLANK([{date_field}]),"",IF([{date_field}]<TODAY(),"⚠️ 已逾期",IF(DAYS([{date_field}],TODAY())<3,"⏰ 即将到期","✅ 正常")))',
                    "purpose": "自动标记逾期状态",
                    "action": "点击\"+\" → 公式 → 粘贴",
                })

            # 工期天数
            has_start = any("开始" in fn for fn in field_names)
            has_end = any("截止" in fn or "结束" in fn for fn in field_names)
            has_duration = any(kw in fn for fn in field_names + existing_formula_names for kw in ["工期", "天数", "时长"])
            if has_start and has_end and not has_duration:
                start_field = next((fn for fn in field_names if "开始" in fn), None)
                end_field = next((fn for fn in field_names if "截止" in fn or "结束" in fn), None)
                if not start_field or not end_field:
                    continue
                suggestions.append({
                    "table": table_name,
                    "field": "工期（天）",
                    "formula": f'IF(AND(!ISBLANK([{start_field}]),!ISBLANK([{end_field}])),DATEDIF([{start_field}],[{end_field}],"D"),"")',
                    "purpose": "自动计算持续天数",
                    "action": "点击\"+\" → 公式 → 粘贴",
                })

            # 创建天数（所有表通用）
            has_created_days = any("创建" in fn and "天" in fn for fn in field_names + existing_formula_names)
            if not has_created_days:
                suggestions.append({
                    "table": table_name,
                    "field": "创建天数",
                    "formula": 'DATEDIF(CREATED_TIME(),TODAY(),"D")',
                    "purpose": "记录存在天数，便于发现沉寂数据",
                    "action": "点击\"+\" → 公式 → 粘贴",
                })

        # ── 系统类型专属公式 ──

        if sys_type == "CRM":
            for t_cfg in tables_cfg:
                table_name = t_cfg["name"]
                fields = t_cfg.get("fields", [])
                field_names = [f["field_name"] for f in fields]
                n_clean = table_name.rstrip("表").rstrip("信息").rstrip("管理").rstrip("记录")

                # 客户表：跟进相关
                if any(kw in n_clean for kw in ["客户", "线索", "商机"]):
                    # 查找关联的跟进表
                    for t2 in tables_cfg:
                        t2_clean = t2["name"].rstrip("表").rstrip("信息").rstrip("管理").rstrip("记录")
                        if any(kw in t2_clean for kw in ["跟进", "拜访", "沟通"]):
                            date_in_t2 = next((f["field_name"] for f in t2.get("fields", []) if f.get("type") == 5), None)
                            if date_in_t2:
                                suggestions.append({
                                    "table": table_name,
                                    "field": "最近跟进距今",
                                    "formula": f'IF(!ISBLANK([关联{t2["name"]}]),[关联{t2["name"]}].[{date_in_t2}].MAX().DATEDIF(TODAY(),"D") & "天前","未跟进")',
                                    "purpose": "显示距最近一次跟进的天数",
                                    "action": "先建立关联后 → 点击\"+\" → 公式 → 粘贴",
                                })
                            break

                    # 跟进预警
                    if any("最近跟进" in fn or "跟进日期" in fn or "跟进时间" in fn for fn in field_names):
                        follow_field = next((fn for fn in field_names if "跟进" in fn and ("日期" in fn or "时间" in fn)), None)
                        if not follow_field:
                            # "最近跟进" 本身是日期字段
                            follow_field = next((fn for fn in field_names if "最近跟进" in fn), None)
                        if follow_field:
                            suggestions.append({
                                "table": table_name,
                                "field": "跟进预警",
                                "formula": f'IF(ISBLANK([{follow_field}]),"🔴 从未跟进",IF(DAYS(TODAY(),[{follow_field}])>7,"⚠️ 超7天未跟进","✅ 正常"))',
                                "purpose": "自动标记需要跟进的客户",
                                "action": "点击\"+\" → 公式 → 粘贴",
                            })

        elif sys_type == "项目管理":
            for t_cfg in tables_cfg:
                table_name = t_cfg["name"]
                fields = t_cfg.get("fields", [])
                field_names = [f["field_name"] for f in fields]
                n_clean = table_name.rstrip("表").rstrip("信息").rstrip("管理").rstrip("记录")

                # 项目表：完成率
                if any(kw in n_clean for kw in ["项目"]):
                    for t2 in tables_cfg:
                        t2_clean = t2["name"].rstrip("表").rstrip("信息").rstrip("管理").rstrip("记录")
                        if any(kw in t2_clean for kw in ["任务", "事项", "工作"]):
                            status_in_t2 = next((f["field_name"] for f in t2.get("fields", []) if any(kw in f["field_name"] for kw in ["状态", "阶段"])), None)
                            if status_in_t2:
                                # 获取完成选项名
                                done_opt = "已完成"
                                for f in t2.get("fields", []):
                                    if f["field_name"] == status_in_t2:
                                        for o in f.get("property", {}).get("options", []):
                                            if any(kw in o["name"] for kw in ["完成", "关闭", "结束"]):
                                                done_opt = o["name"]
                                                break
                                suggestions.append({
                                    "table": table_name,
                                    "field": "任务完成率",
                                    "formula": f'IF(!ISBLANK([关联{t2["name"]}]),ROUND([关联{t2["name"]}].COUNTIF(CurrentValue.[{status_in_t2}]="{done_opt}") / [关联{t2["name"]}].COUNTA() * 100, 1) & "%","0%")',
                                    "purpose": "自动计算项目下任务完成比例",
                                    "action": "先建立关联后 → 点击\"+\" → 公式 → 粘贴",
                                })
                            break

        elif sys_type == "进销存":
            for t_cfg in tables_cfg:
                table_name = t_cfg["name"]
                n_clean = table_name.rstrip("表").rstrip("信息").rstrip("管理").rstrip("记录")

                if any(kw in n_clean for kw in ["商品", "库存"]):
                    field_names = [f["field_name"] for f in t_cfg.get("fields", [])]
                    stock_field = next((fn for fn in field_names if "库存" in fn or "数量" in fn), None)
                    if stock_field:
                        suggestions.append({
                            "table": table_name,
                            "field": "库存预警",
                            "formula": f'IF([{stock_field}]<=0,"🔴 缺货",IF([{stock_field}]<10,"⚠️ 库存不足","✅ 充足"))',
                            "purpose": "自动标记库存不足的商品",
                            "action": "点击\"+\" → 公式 → 粘贴",
                        })

        return suggestions[:8]

    def _suggest_views(self, t_cfg):
        """为单张表推荐视图"""
        views = []
        table_name = t_cfg["name"]
        fields = t_cfg.get("fields", [])

        select_fields = [(f["field_name"], f.get("property", {}).get("options", []))
                         for f in fields if f.get("type") == 3]
        date_fields = [f["field_name"] for f in fields if f.get("type") == 5]
        person_fields = [f["field_name"] for f in fields if f.get("type") == 11]
        status_fields = [(fn, opts) for fn, opts in select_fields
                         if any(kw in fn for kw in ["状态", "阶段", "进度"])]

        if status_fields:
            sf_name, _ = status_fields[0]
            views.append({
                "name": f"按{sf_name}看板",
                "type": "看板",
                "purpose": f"按{sf_name}拖拽管理流程",
                "config": f"分组依据：{sf_name}",
            })

        if date_fields:
            views.append({
                "name": "日历视图",
                "type": "日历",
                "purpose": "按时间线查看排期",
                "config": f"基于字段：{date_fields[0]}",
            })

        if len(date_fields) >= 2:
            views.append({
                "name": "甘特图",
                "type": "甘特",
                "purpose": "可视化时间跨度和进度",
                "config": f"开始：{date_fields[0]}，结束：{date_fields[1]}",
            })

        if person_fields:
            views.append({
                "name": f"按{person_fields[0]}分组",
                "type": "表格",
                "purpose": f"按{person_fields[0]}查看工作分配",
                "config": f"分组：{person_fields[0]}",
            })

        non_status_selects = [(fn, opts) for fn, opts in select_fields
                              if not any(kw in fn for kw in ["状态", "阶段", "进度"])]
        if non_status_selects:
            sf_name, _ = non_status_selects[0]
            views.append({
                "name": f"按{sf_name}分组",
                "type": "表格",
                "purpose": f"按{sf_name}分类查看",
                "config": f"分组：{sf_name}",
            })

        views.append({
            "name": f"{table_name}录入表单",
            "type": "表单",
            "purpose": "外部人员/协作者录入数据",
            "config": "可分享链接，选择需要展示的字段",
        })

        return views[:5]

    def _suggest_automations(self, tables_cfg, analysis):
        """根据表结构推荐自动化规则"""
        automations = []

        for t_cfg in tables_cfg:
            table_name = t_cfg["name"]
            fields = t_cfg.get("fields", [])
            field_names = [f["field_name"] for f in fields]

            has_status = any("状态" in fn for fn in field_names)
            has_person = any(f.get("type") == 11 for f in fields)
            has_date = any(f.get("type") == 5 for f in fields)
            date_fields = [f["field_name"] for f in fields if f.get("type") == 5]
            status_field = next((fn for fn in field_names if "状态" in fn), None)
            person_field = next((f["field_name"] for f in fields if f.get("type") == 11), None)

            if has_status and has_person:
                automations.append({
                    "name": f"{table_name}完成通知",
                    "trigger": f"记录满足条件：{status_field} 变为\"已完成\"",
                    "action": f"发送飞书消息给 {person_field}",
                    "detail": f"消息模板：\"[{table_name}] {{首字段}} 已完成，请确认\"",
                })

            if has_date:
                deadline = next((fn for fn in date_fields if "截止" in fn or "到期" in fn), date_fields[0])
                automations.append({
                    "name": f"{table_name}到期提醒",
                    "trigger": f"定时触发：每天 9:00",
                    "action": f"筛选 {deadline} = 未来3天内 的记录 → 发送飞书群消息",
                    "detail": f"消息含：记录名称、{deadline}、{'负责人' if has_person else '状态'}",
                })

            if has_person:
                automations.append({
                    "name": f"新增{table_name}通知",
                    "trigger": "添加新记录",
                    "action": f"发送飞书消息给 {person_field}",
                    "detail": f"消息模板：\"你有一条新的{table_name}：{{首字段}}\"",
                })

        if tables_cfg:
            main_table = tables_cfg[0]["name"]
            automations.append({
                "name": "月度数据汇总",
                "trigger": "定时触发：每月1日 10:00",
                "action": f"汇总上月{main_table}数据 → 发送飞书群消息",
                "detail": "统计新增数、完成数、各状态占比",
            })

        if any("截止" in fn or "到期" in fn for _, fn in analysis.get("date_fields", [])):
            automations.append({
                "name": "逾期任务升级",
                "trigger": "记录满足条件：截止日期 < 今天 且 状态 ≠ 已完成",
                "action": "修改记录：优先级设为\"紧急\" + 发送消息给管理员",
                "detail": "自动提升逾期任务优先级并通知管理层",
            })

        return automations[:8]

    def _suggest_roles(self, tables_cfg, analysis):
        """根据系统类型推荐角色和权限"""
        table_count = len(tables_cfg)
        sys_type = analysis["system_type"]
        has_person = bool(analysis["person_fields"])

        roles = []

        roles.append({
            "name": "管理员",
            "members": "系统管理员、部门负责人",
            "desc": "全表可管理，配置字段/视图/自动化",
            "table_perms": ["可管理"] * table_count,
            "record_scope": "所有记录",
        })

        if sys_type == "项目管理":
            roles.append({
                "name": "项目经理",
                "members": "项目负责人",
                "desc": "管理项目和任务分配",
                "table_perms": ["可编辑"] * table_count,
                "record_scope": "所管理项目的记录",
            })
            roles.append({
                "name": "项目成员",
                "members": "开发、设计、测试等",
                "desc": "更新自己负责的任务",
                "table_perms": ["可编辑" if i == 0 else "仅可阅读" for i in range(table_count)],
                "record_scope": "与本人相关的记录",
            })
        elif sys_type == "CRM":
            roles.append({
                "name": "销售主管",
                "members": "销售团队负责人",
                "desc": "查看团队所有客户数据，审批合同",
                "table_perms": ["可编辑"] * table_count,
                "record_scope": "本团队所有记录",
            })
            roles.append({
                "name": "销售",
                "members": "一线销售人员",
                "desc": "管理自己的客户和商机",
                "table_perms": ["可编辑" if i <= 1 else "仅可阅读" for i in range(table_count)],
                "record_scope": "与本人相关的记录",
            })
        else:
            roles.append({
                "name": "编辑者",
                "members": "核心业务人员",
                "desc": "日常数据录入和编辑",
                "table_perms": ["可编辑"] * table_count,
                "record_scope": "与本人相关的记录" if has_person else "所有记录",
            })
            roles.append({
                "name": "阅读者",
                "members": "相关方、领导层",
                "desc": "只读查看数据和报表",
                "table_perms": ["仅可阅读"] * table_count,
                "record_scope": "所有记录",
            })

        return roles

    def _suggest_dashboards(self, tables_cfg, analysis):
        """根据表结构推荐仪表盘设计"""
        dashboards = []
        main_components = []
        main_table = tables_cfg[0]
        mt_name = main_table["name"]
        mt_fields = main_table.get("fields", [])

        # 指标卡：总数
        main_components.append({
            "name": f"{mt_name}总数",
            "type": "指标卡",
            "source": mt_name,
            "dimension": "—",
            "metric": "记录总数（COUNTA）",
            "filter": "—",
        })

        # 指标卡：按状态统计
        status_fields = [(f["field_name"], f.get("property", {}).get("options", []))
                         for f in mt_fields if f.get("type") == 3
                         and any(kw in f["field_name"] for kw in ["状态", "阶段"])]
        if status_fields:
            sf_name, sf_opts = status_fields[0]
            if sf_opts:
                pending_opt = next((o["name"] for o in sf_opts
                                    if any(kw in o["name"] for kw in ["待办", "待处理", "未开始", "新建"])),
                                   sf_opts[0]["name"] if sf_opts else "待办")
                main_components.append({
                    "name": "待处理数",
                    "type": "指标卡",
                    "source": mt_name,
                    "dimension": "—",
                    "metric": f"COUNTA（{sf_name}={pending_opt}）",
                    "filter": f"{sf_name} = {pending_opt}",
                })
                done_opt = next((o["name"] for o in sf_opts
                                 if any(kw in o["name"] for kw in ["已完成", "完成", "关闭", "结束"])),
                                sf_opts[-1]["name"] if sf_opts else "已完成")
                main_components.append({
                    "name": "已完成数",
                    "type": "指标卡",
                    "source": mt_name,
                    "dimension": "—",
                    "metric": f"COUNTA（{sf_name}={done_opt}）",
                    "filter": f"{sf_name} = {done_opt}",
                })

            main_components.append({
                "name": f"{sf_name}分布",
                "type": "饼图",
                "source": mt_name,
                "dimension": sf_name,
                "metric": "记录计数",
                "filter": "—",
            })

        # 数字+日期 → 折线图
        number_fields_in_main = [f for f in mt_fields if f.get("type") in (2, 99001)]
        date_fields_in_main = [f for f in mt_fields if f.get("type") == 5]

        if number_fields_in_main and date_fields_in_main:
            nf = number_fields_in_main[0]["field_name"]
            df = date_fields_in_main[0]["field_name"]
            main_components.append({
                "name": f"{nf}趋势",
                "type": "折线图",
                "source": mt_name,
                "dimension": f"{df}（按月）",
                "metric": f"{nf}（求和）",
                "filter": "—",
            })

        if number_fields_in_main:
            nf = number_fields_in_main[0]["field_name"]
            main_components.append({
                "name": f"{nf}柱状图",
                "type": "柱状图",
                "source": mt_name,
                "dimension": status_fields[0][0] if status_fields else mt_name,
                "metric": f"{nf}（求和）",
                "filter": "—",
            })

        # 人员排行榜
        person_fields_in_main = [f for f in mt_fields if f.get("type") == 11]
        if person_fields_in_main:
            pf = person_fields_in_main[0]["field_name"]
            main_components.append({
                "name": f"按{pf}排行",
                "type": "排行榜",
                "source": mt_name,
                "dimension": pf,
                "metric": "记录计数",
                "filter": "—",
            })

        # 切片器
        main_components.append({
            "name": "时间筛选器",
            "type": "切片器",
            "source": "—",
            "dimension": date_fields_in_main[0]["field_name"] if date_fields_in_main else "创建时间",
            "metric": "—",
            "filter": "联动所有组件",
        })

        dashboards.append({
            "name": f"{analysis['system_type']}总览",
            "audience": "管理员、负责人",
            "components": main_components,
        })

        return dashboards

    def _suggest_app_pages(self, tables_cfg, analysis, roles):
        """推荐应用模式页面结构"""
        pages = []

        pages.append({
            "group": "首页",
            "name": "数据总览",
            "components": "仪表盘嵌入（指标卡+图表）",
            "audience": "所有角色",
        })

        for t_cfg in tables_cfg:
            pages.append({
                "group": "数据管理",
                "name": f"{t_cfg['name']}管理",
                "components": "列表视图 + 筛选 + 新增按钮",
                "audience": roles[1]["name"] if len(roles) > 1 else "编辑者",
            })

        if len(tables_cfg) >= 1:
            main_table = tables_cfg[0]["name"]
            pages.append({
                "group": "快捷操作",
                "name": f"新增{main_table}",
                "components": "表单视图嵌入",
                "audience": "所有角色",
            })

        return pages

    def _get_link(self):
        """根据模式返回对应的打开链接"""
        if self.wiki_mode and self.node_token:
            return f"https://vantasma.feishu.cn/wiki/{self.node_token}"
        return f"https://vantasma.feishu.cn/base/{self.app_token}"

    # ─── 创建应用 ────────────────────────────────────

    def _create_app(self, name: str):
        print(f"📦 创建多维表格应用 [{name}]（独立模式）")
        data = self.client._request(
            "POST",
            "/bitable/v1/apps",
            json={"name": name},
        )
        self.app_token = data["data"]["app"]["app_token"]
        print(f"   ✓ 创建成功，app_token = {self.app_token}")
        time.sleep(DELAY)

    def _create_wiki_app(self, name: str):
        print(f"📦 创建多维表格节点 [{name}]（知识库模式）")
        print(f"   📍 知识库: {SPACE_ID}")
        print(f"   📍 父节点: {PARENT_NODE}")
        data = self.client._request(
            "POST",
            f"/wiki/v2/spaces/{SPACE_ID}/nodes",
            json={
                "obj_type": "bitable",
                "parent_node_token": PARENT_NODE,
                "node_type": "origin",
                "title": name,
            },
        )
        node = data["data"]["node"]
        self.node_token = node["node_token"]
        self.app_token = node["obj_token"]
        print(f"   ✓ 创建成功")
        print(f"     node_token = {self.node_token}")
        print(f"     app_token  = {self.app_token}")
        time.sleep(DELAY)

    # ─── 数据表创建（新方式：带字段创建，无默认字段问题） ──

    def _get_default_table_id(self):
        """获取飞书自动创建的默认数据表 ID（后续删除用）"""
        data = self.client._get(
            f"/bitable/v1/apps/{self.app_token}/tables",
            params={"page_size": 20},
        )
        tables = data.get("data", {}).get("items", [])
        if not tables:
            raise Exception("未找到默认表")
        default_id = tables[0]["table_id"]
        print(f"   📋 默认表: {default_id}（将在所有表创建完后删除）")
        return default_id

    def _create_table_with_fields(self, table_name, first_field_name, field_configs, default_view_name="全部数据"):
        """创建数据表时直接指定字段。

        使用 POST /tables 的 fields 参数：
        - 首字段直接是 type=1（文本），不是多行文本
        - 没有飞书默认的多行文本/单选/日期/附件字段
        - 没有 10 条空白记录
        三个老大难问题一次性解决。
        """
        print(f"\n📊 创建数据表 [{table_name}]（含字段定义）")

        # 构建字段列表：首字段(type=1 文本) + 自定义字段
        fields = [{"field_name": first_field_name, "type": 1}]
        for fc in field_configs:
            field_type = fc["type"]
            if field_type in UI_TYPE_MAP:
                base_type, ui_type = UI_TYPE_MAP[field_type]
                field_def = {"field_name": fc["field_name"], "type": base_type, "ui_type": ui_type}
            else:
                field_def = {"field_name": fc["field_name"], "type": field_type}
            if "property" in fc:
                field_def["property"] = fc["property"]
            fields.append(field_def)

        payload = {
            "table": {
                "name": table_name,
                "default_view_name": default_view_name,
                "fields": fields,
            }
        }

        data = self.client._request(
            "POST",
            f"/bitable/v1/apps/{self.app_token}/tables",
            json=payload,
        )
        self.table_id = data["data"]["table_id"]
        print(f"   ✓ table_id = {self.table_id}")
        print(f"   ✓ {len(fields)} 个字段直接创建完毕（无默认字段）")
        time.sleep(DELAY)

    def _delete_table(self, table_id):
        """删除数据表（用于清理飞书自动创建的默认脏表）"""
        print(f"\n🗑️  删除默认脏表 ({table_id})")
        try:
            self.client._request(
                "DELETE",
                f"/bitable/v1/apps/{self.app_token}/tables/{table_id}",
            )
            print(f"   ✓ 已删除")
        except Exception as e:
            print(f"   ⚠ 删除失败（不影响使用）: {e}")
        time.sleep(DELAY)

    # ─── 写入数据 ────────────────────────────────────

    def _insert_records(self, records: list):
        print(f"\n📝 写入示例数据 ({len(records)} 条)")

        batch_size = 100
        total = 0

        for i in range(0, len(records), batch_size):
            batch = records[i : i + batch_size]
            payload = {
                "records": [{"fields": rec} for rec in batch]
            }
            self.client._request(
                "POST",
                f"/bitable/v1/apps/{self.app_token}/tables/{self.table_id}/records/batch_create",
                json=payload,
            )
            total += len(batch)
            print(f"   ✓ 已写入 {total}/{len(records)} 条")
            time.sleep(DELAY)

    # ─── 创建视图 ────────────────────────────────────

    def _create_views(self, view_configs: list):
        print(f"\n🔭 创建视图")

        for vc in view_configs:
            vtype = vc["view_type"]

            if vtype == "calendar":
                print(f"   ⚠ {vc['view_name']} — 日历视图需手动创建（飞书 API 不支持 view_type=calendar）")
                print(f"     操作：视图栏「+」→ 日历视图 → 选择日期字段")
                continue

            payload = {
                "view_name": vc["view_name"],
                "view_type": vtype,
            }
            try:
                self.client._request(
                    "POST",
                    f"/bitable/v1/apps/{self.app_token}/tables/{self.table_id}/views",
                    json=payload,
                )
                print(f"   ✓ {vc['view_name']} ({vtype})")
            except Exception as e:
                print(f"   ⚠ {vc['view_name']} 创建失败: {e}")
            time.sleep(DELAY)

    # ─── 设置管理员 ──────────────────────────────────

    def _set_admin(self):
        print(f"\n🔑 设置管理员")

        open_id = ADMIN_OPEN_ID
        if not open_id and ADMIN_PHONE:
            try:
                api_path = "/contact/v3" + "/users" + "/batch_get_id"
                data = self.client._request(
                    "POST",
                    api_path,
                    json={"mobiles": [ADMIN_PHONE]},
                    params={"user_id_type": "open_id"},
                )
                user_list = data.get("data", {}).get("user_list", [])
                if user_list:
                    open_id = user_list[0].get("user_id", "")
                    print(f"   ✓ 查到 open_id = {open_id}")
                    print(f"   💡 建议保存到 .env: FEISHU_ADMIN_OPEN_ID={open_id}")
            except Exception as e:
                print(f"   ⚠ 查询用户失败: {e}")
                print(f"   💡 请手动在飞书中添加管理员，或在 .env 中配置 FEISHU_ADMIN_OPEN_ID")
                return

        if not open_id:
            print(f"   ⚠ 无法获取管理员 open_id，跳过")
            return

        try:
            perm_path = f"/drive/v1/permissions/{self.app_token}/members"
            self.client._request(
                "POST",
                perm_path,
                params={"type": "bitable", "need_notification": "false"},
                json={
                    "member_type": "openid",
                    "member_id": open_id,
                    "perm": "full_access",
                },
            )
            print(f"   ✅ 管理员权限设置成功（full_access）")
        except Exception as e:
            print(f"   ⚠ 权限设置失败: {e}")
            print(f"   💡 请手动在飞书中添加管理员")
        time.sleep(DELAY)

    # ─── Dry Run ─────────────────────────────────────

    def _print_plan(self, config: dict):
        mode_label = "知识库模式" if self.wiki_mode else "独立模式"
        tables_cfg = config["tables"]

        print(f"🔍 DRY RUN 模式 — 以下为搭建计划，不实际执行\n")
        print(f"应用名称: {config['app_name']}")
        print(f"创建模式: {mode_label}")
        if self.wiki_mode:
            print(f"知识库 ID: {SPACE_ID}")
            print(f"父节点:    {PARENT_NODE}")
        print(f"数据表数量: {len(tables_cfg)} 张")

        total_records = 0
        total_fields = 0
        total_views = 0

        for idx, t in enumerate(tables_cfg):
            is_first = (idx == 0)
            table_num = idx + 1
            first_field_name = t.get("first_field_name", "名称")
            default_view_name = t.get("default_view_name", "全部数据")

            print(f"\n{'─'*50}")
            print(f"📊 数据表 {table_num}: {t['name']}")
            print(f"{'─'*50}")
            print(f"  创建方式: 带字段直接创建（无默认字段）")
            print(f"  首字段名: {first_field_name} (type=1 文本)")
            print(f"  默认视图名: {default_view_name}")

            fields = t.get("fields", [])
            total_fields += len(fields) + 1
            print(f"\n  字段 ({len(fields) + 1}):")
            print(f"    1. {first_field_name} [文本] (首字段)")
            for i, f in enumerate(fields, 2):
                ftype = FIELD_TYPE_NAMES.get(f["type"], f"type={f['type']}")
                opts = ""
                if f.get("property", {}).get("options"):
                    opts = " → " + "/".join(o["name"] for o in f["property"]["options"])
                print(f"    {i}. {f['field_name']} [{ftype}]{opts}")

            records = t.get("records", [])
            if records:
                total_records += len(records)
                print(f"\n  示例数据: {len(records)} 条")

            views = t.get("views", [])
            if views:
                total_views += len(views)
                print(f"\n  视图 ({len(views)} + 1 默认):")
                print(f"    - {default_view_name} (grid, 默认视图重命名)")
                for v in views:
                    manual = " ⚠ 需手动创建" if v["view_type"] == "calendar" else ""
                    print(f"    - {v['view_name']} ({v['view_type']}){manual}")

        print(f"\n{'═'*50}")
        print(f"📋 搭建总览")
        print(f"{'═'*50}")
        print(f"  数据表: {len(tables_cfg)} 张")
        print(f"  字段总数: {total_fields} 个")
        print(f"  数据总数: {total_records} 条")
        print(f"  视图总数: {total_views} + {len(tables_cfg)} 默认")

        print(f"\n搭建步骤预览:")
        print(f"  1. {'在知识库创建 bitable 节点' if self.wiki_mode else '创建独立 bitable 应用'}")
        for idx, t in enumerate(tables_cfg):
            table_num = idx + 1
            first_field_name = t.get("first_field_name", "名称")
            default_view_name = t.get("default_view_name", "全部数据")
            fields = t.get("fields", [])
            records = t.get("records", [])
            views = t.get("views", [])

            if len(tables_cfg) > 1:
                print(f"  ── 数据表 {table_num}: {t['name']} ──")

            print(f"  {table_num}a. 创建数据表 [{t['name']}]（含 {len(fields)+1} 个字段定义，无默认字段）")
            if records:
                print(f"  {table_num}b. 写入 {len(records)} 条示例数据")
            if views:
                api_views = [v for v in views if v["view_type"] != "calendar"]
                manual_views = [v for v in views if v["view_type"] == "calendar"]
                suffix = f"（{len(manual_views)} 个需手动）" if manual_views else ""
                print(f"  {table_num}c. 创建 {len(api_views)} 个视图{suffix}")

        print(f"  N. 删除飞书自动创建的默认脏表")
        print(f"  N+1. 设置管理员权限")
        print(f"\n✅ 计划生成完毕。去掉 --dry-run 参数即可实际创建。")


# ═══════════════════════════════════════════════════════════
# JSON 配置加载
# ═══════════════════════════════════════════════════════════

def load_json_config(path: str) -> dict:
    """从 JSON 文件加载模板配置"""
    p = Path(path)
    if not p.exists():
        print(f"❌ 配置文件不存在: {path}")
        sys.exit(1)

    try:
        with open(p, "r", encoding="utf-8") as f:
            config = json.load(f)
    except json.JSONDecodeError as e:
        print(f"❌ JSON 解析失败: {e}")
        sys.exit(1)

    # 验证必需字段
    if "app_name" not in config:
        print("❌ JSON 配置缺少 'app_name' 字段")
        sys.exit(1)

    # 支持 tables（多表）或 table（单表）
    if "tables" in config:
        tables = config["tables"]
        if not isinstance(tables, list) or len(tables) == 0:
            print("❌ 'tables' 必须是非空数组")
            sys.exit(1)
    elif "table" in config:
        tables = [config["table"]]
    else:
        print("❌ JSON 配置缺少 'tables' 或 'table' 字段")
        sys.exit(1)

    # 验证每张表的必需字段
    for i, table in enumerate(tables):
        prefix = f"tables[{i}]" if len(tables) > 1 else "table"
        if "name" not in table:
            print(f"❌ {prefix} 缺少 'name' 字段")
            sys.exit(1)
        if "fields" not in table:
            print(f"❌ {prefix} 缺少 'fields' 字段")
            sys.exit(1)

    print(f"📄 已加载配置文件: {path}（{len(tables)} 张数据表）")
    return config


# ═══════════════════════════════════════════════════════════
# 入口
# ═══════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="飞书多维表格课程模板自动搭建",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  %(prog)s --lesson 1                          使用内置第1课配置创建
  %(prog)s --lesson 1 --wiki                   创建到知识库
  %(prog)s --config template.json              从 JSON 文件创建（支持多表）
  %(prog)s --config template.json --wiki       从 JSON 创建到知识库
  %(prog)s --config template.json --dry-run    预览搭建计划
        """,
    )
    parser.add_argument(
        "--lesson", "-l",
        type=int,
        default=None,
        help="课程编号（使用内置配置）",
    )
    parser.add_argument(
        "--config", "-c",
        type=str,
        default=None,
        help="JSON 配置文件路径（推荐，支持多表）",
    )
    parser.add_argument(
        "--wiki", "-w",
        action="store_true",
        help="创建到知识库（而非独立 bitable）",
    )
    parser.add_argument(
        "--space-id",
        type=str,
        default=None,
        help="知识库 space_id（覆盖默认值）",
    )
    parser.add_argument(
        "--parent-node",
        type=str,
        default=None,
        help="知识库父节点 node_token（覆盖默认值）",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只打印搭建计划，不实际创建",
    )
    args = parser.parse_args()

    # 确定配置来源
    if args.config:
        config = load_json_config(args.config)
    elif args.lesson is not None:
        if args.lesson not in LESSON_CONFIGS:
            available = ", ".join(str(k) for k in sorted(LESSON_CONFIGS.keys()))
            print(f"❌ 第 {args.lesson} 课的模板配置尚未添加。")
            print(f"   当前可用: {available}")
            sys.exit(1)
        config = LESSON_CONFIGS[args.lesson]
    else:
        config = LESSON_CONFIGS[1]

    # 覆盖知识库配置
    global SPACE_ID, PARENT_NODE
    if args.space_id:
        SPACE_ID = args.space_id
    if args.parent_node:
        PARENT_NODE = args.parent_node

    builder = BitableTemplateBuilder(dry_run=args.dry_run, wiki_mode=args.wiki)
    builder.build(config)


if __name__ == "__main__":
    main()

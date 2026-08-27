#!/usr/bin/env python3
"""Read-only structural check for a knowledge-system health report."""

from __future__ import annotations

import argparse
from pathlib import Path


REQUIRED_HEADINGS = [
    "## 审计信息",
    "## 健康总览",
    "## 发现清单",
    "## 本次选择修复的问题",
    "## 改造前后对照",
    "## 遗留问题与下次复查",
]

REQUIRED_EVIDENCE_FIELDS = [
    "检查动作：",
    "预期结果：",
    "实际结果：",
    "证据：",
    "下一动作：",
    "完成标志：",
    "回滚方法：",
]

REQUIRED_LANES = [
    "能否找到",
    "能否读懂",
    "能否使用",
    "能否续接",
    "能否恢复",
    "能否安全维护",
]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="只读检查知识系统健康报告的结构和安全约束"
    )
    parser.add_argument("report", type=Path, help="待检查的 Markdown 报告")
    args = parser.parse_args()

    path = args.report.expanduser().resolve()
    if not path.is_file():
        print(f"FAIL: 报告不存在：{path}")
        return 2

    text = path.read_text(encoding="utf-8")
    issues = []

    for heading in REQUIRED_HEADINGS:
        if heading not in text:
            issues.append(f"缺少章节：{heading}")

    for field in REQUIRED_EVIDENCE_FIELDS:
        if field not in text:
            issues.append(f"缺少证据字段：{field}")

    for lane in REQUIRED_LANES:
        if lane not in text:
            issues.append(f"缺少健康维度：{lane}")

    if "100分" in text or "健康分" in text or "综合得分" in text:
        issues.append("疑似使用无依据的精确健康分数")

    if "同步就是备份" in text or "同步等于备份" in text:
        issues.append("疑似把同步误当作备份证明")

    if issues:
        print("FAIL")
        for issue in issues:
            print(f"- {issue}")
        return 1

    print("PASS: 报告结构包含审计范围、证据、优先级、改造对照和回滚信息")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

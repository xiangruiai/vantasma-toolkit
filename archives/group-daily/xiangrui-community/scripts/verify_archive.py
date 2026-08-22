#!/usr/bin/env python3
"""Verify the public group-daily archive without private source data."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any


DATE_NAME = re.compile(r"^\d{4}-\d{2}-\d{2}\.json$")
PHONE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
EMAIL = re.compile(r"(?<![\w.+-])[\w.+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}(?![\w.-])")
WECHAT_ID = re.compile(r"(?:wxid_[A-Za-z0-9_-]+|[A-Za-z0-9_-]+@chatroom)", re.I)
PRIVATE_KEYS = {"wxid", "avatar", "avatar_path", "member_id", "username", "user_id", "open_id", "union_id", "room_id"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return digest


def walk(value: Any):
    if isinstance(value, dict):
        for key, item in value.items():
            yield key, item
            yield from walk(item)
    elif isinstance(value, list):
        for item in value:
            yield from walk(item)


def main() -> int:
    parser = argparse.ArgumentParser(description="校验群日报公开归档")
    parser.add_argument("archive", type=Path)
    args = parser.parse_args()

    index = json.loads((args.archive / "index.json").read_text(encoding="utf-8"))
    entries = index.get("reports", [])
    expected = {Path(entry["file"]).name for entry in entries}
    actual = {path.name for path in (args.archive / "daily").glob("*.json") if DATE_NAME.match(path.name)}
    errors: list[str] = []

    if expected != actual:
        errors.append(f"索引与文件集合不一致：missing={sorted(expected-actual)} extra={sorted(actual-expected)}")
    if index.get("coverage", {}).get("report_count") != len(entries):
        errors.append("coverage.report_count 与 reports 数量不一致")

    for entry in entries:
        path = args.archive / entry["file"]
        if not path.exists():
            continue
        if sha256(path) != entry.get("sha256"):
            errors.append(f"哈希不一致：{entry['file']}")
        report = json.loads(path.read_text(encoding="utf-8"))
        if report.get("date") != path.stem:
            errors.append(f"日期不一致：{entry['file']}")
        text = json.dumps(report, ensure_ascii=False)
        if PHONE.search(text):
            errors.append(f"发现手机号：{entry['file']}")
        if EMAIL.search(text):
            errors.append(f"发现邮箱：{entry['file']}")
        if WECHAT_ID.search(text):
            errors.append(f"发现微信标识：{entry['file']}")
        for key, _ in walk(report):
            if key.lower() in PRIVATE_KEYS:
                errors.append(f"发现私有字段 {key}：{entry['file']}")

    if errors:
        print("archive verification failed")
        for error in errors:
            print(f"- {error}")
        return 1

    print(
        f"archive verification passed: {len(entries)} reports, "
        f"{index['coverage']['first_report']} -> {index['coverage']['latest_report']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

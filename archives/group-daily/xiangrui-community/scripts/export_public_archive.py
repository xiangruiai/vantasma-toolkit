#!/usr/bin/env python3
"""Export private group-daily source JSON into a public, masked archive."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any


DATE_FILE = re.compile(r"^(\d{4}-\d{2}-\d{2})_.*\.json$")
HAS_NAME_CHAR = re.compile(r"[一-鿿A-Za-z]")
MEANINGFUL_CHAR = re.compile(r"[一-鿿A-Za-z0-9]")
PHONE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
EMAIL = re.compile(r"(?<![\w.+-])[\w.+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}(?![\w.-])")
WECHAT_ID = re.compile(r"(?:wxid_[A-Za-z0-9_-]+|[A-Za-z0-9_-]+@chatroom)", re.I)

HOST = {"李祥瑞", "祥瑞", "万涂幻象", "me"}
MASK_SKIP = HOST | {"AI", "群里", "群友", "朋友", "大家", "社区", "今天", "昨天", "当天", "我们", "他们"}
PRIVATE_KEYS = {
    "wxid",
    "avatar",
    "avatar_path",
    "member_id",
    "username",
    "user_id",
    "open_id",
    "union_id",
    "room_id",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="导出脱敏群日报公开归档")
    parser.add_argument("--source", required=True, type=Path, help="简体日报 JSON 目录")
    parser.add_argument("--roster", required=True, type=Path, help="私有成员 roster JSON")
    parser.add_argument("--output", required=True, type=Path, help="公开归档根目录")
    parser.add_argument("--through", type=date.fromisoformat, default=date.today(), help="期望覆盖到的日期")
    parser.add_argument("--group", default="祥瑞和Ta的朋友们", help="归档群名")
    return parser.parse_args()


def load_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def add_name(names: set[str], value: Any) -> None:
    name = str(value or "").strip()
    if name and HAS_NAME_CHAR.search(name):
        names.add(name)


def collect_report_names(report: dict[str, Any], names: set[str]) -> None:
    for timeline in report.get("timeline", []):
        for cast in timeline.get("cast", []):
            add_name(names, cast.get("name"))
    for highlight in report.get("highlights", []):
        add_name(names, highlight.get("name"))
    for sop in report.get("sops", []):
        add_name(names, sop.get("author"))
    for qa in report.get("qas", []):
        add_name(names, qa.get("asker"))
        for answer in qa.get("answers", []):
            add_name(names, answer.get("who"))
    footer = report.get("footer_quote")
    if isinstance(footer, dict) and footer.get("attr"):
        add_name(names, re.split(r"[\s\d]", str(footer["attr"]).strip(), maxsplit=1)[0])


def build_mask_list(roster: dict[str, Any], reports: list[dict[str, Any]]) -> list[str]:
    names: set[str] = set()
    for member in roster.get("members", []):
        add_name(names, member.get("name"))
        for alias in member.get("match_names", []):
            add_name(names, alias)
    for item in roster.get("meta", {}).get("unmatched_senders", []):
        add_name(names, item.get("name"))
    for report in reports:
        collect_report_names(report, names)

    for name in list(names):
        first = re.split(r"[\s\d]", name, maxsplit=1)[0].strip()
        if len(first) >= 2 and first != name:
            names.add(first)

    return sorted(
        (
            name
            for name in names
            if len(name) >= 2
            and name not in MASK_SKIP
            and not any(host in name for host in HOST)
            and HAS_NAME_CHAR.search(name)
        ),
        key=len,
        reverse=True,
    )


def mask_name(name: str) -> str:
    value = (name or "").strip()
    if not value or value in HOST or "*" in value:
        return value
    meaningful = [char for char in value if MEANINGFUL_CHAR.match(char)]
    head = meaningful[0] if meaningful else value[0]
    size = len(meaningful) if meaningful else len(value)
    if size <= 1:
        return head
    return head + "*" * min(size - 1, 3)


def sanitize_text(value: str, mask_list: list[str]) -> str:
    result = value
    for name in mask_list:
        if name in result:
            result = result.replace(name, mask_name(name))
    result = PHONE.sub("[手机号已隐藏]", result)
    result = EMAIL.sub("[邮箱已隐藏]", result)
    result = WECHAT_ID.sub("[微信标识已隐藏]", result)
    return result


def sanitize(value: Any, mask_list: list[str]) -> Any:
    if isinstance(value, str):
        return sanitize_text(value, mask_list)
    if isinstance(value, list):
        return [sanitize(item, mask_list) for item in value]
    if isinstance(value, dict):
        return {
            key: sanitize(item, mask_list)
            for key, item in value.items()
            if key.lower() not in PRIVATE_KEYS
        }
    return value


def iter_string_values(value: Any):
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for item in value:
            yield from iter_string_values(item)
    elif isinstance(value, dict):
        for item in value.values():
            yield from iter_string_values(item)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def date_range(start: date, end: date) -> list[date]:
    if start > end:
        return []
    return [start + timedelta(days=offset) for offset in range((end - start).days + 1)]


def main() -> int:
    args = parse_args()
    source_files = sorted(path for path in args.source.glob("*.json") if DATE_FILE.match(path.name))
    if not source_files:
        raise SystemExit(f"没有找到日报 JSON：{args.source}")

    source_items: list[tuple[date, Path, dict[str, Any]]] = []
    for path in source_files:
        file_date = date.fromisoformat(DATE_FILE.match(path.name).group(1))
        report = load_json(path)
        if report.get("date") != file_date.isoformat():
            raise SystemExit(f"日期不一致：{path}")
        source_items.append((file_date, path, report))

    roster = load_json(args.roster)
    reports = [report for _, _, report in source_items]
    mask_list = build_mask_list(roster, reports)
    output_daily = args.output / "daily"
    output_daily.mkdir(parents=True, exist_ok=True)

    index_entries: list[dict[str, Any]] = []
    for file_date, _, report in source_items:
        public_report = sanitize(copy.deepcopy(report), mask_list)
        public_report["_archive"] = {
            "version": 1,
            "privacy": "公开脱敏版，非原始聊天记录",
            "source_site": "https://www.xiangruiai.com/",
        }
        output_path = output_daily / f"{file_date.isoformat()}.json"
        output_path.write_text(
            json.dumps(public_report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        index_entries.append(
            {
                "date": file_date.isoformat(),
                "file": f"daily/{output_path.name}",
                "lead_title": public_report.get("lead_title", ""),
                "stats": public_report.get("stats", {}),
                "sha256": sha256(output_path),
            }
        )

    available_dates = {item[0] for item in source_items}
    first = min(available_dates)
    latest = max(available_dates)
    historical_missing = [
        item.isoformat() for item in date_range(first, latest) if item not in available_dates
    ]
    pending = [
        item.isoformat()
        for item in date_range(latest + timedelta(days=1), args.through)
    ]
    index = {
        "archive": "祥瑞和Ta的朋友们 · 群日报公开归档",
        "group_name": args.group,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": "已公开网站日报的脱敏归档，不包含原始群聊",
        "coverage": {
            "first_report": first.isoformat(),
            "latest_report": latest.isoformat(),
            "requested_through": args.through.isoformat(),
            "report_count": len(index_entries),
            "historical_missing_dates": historical_missing,
            "not_yet_generated_dates": pending,
        },
        "privacy": {
            "names": "除李祥瑞、祥瑞、万涂幻象外，多字符昵称保留首个有效字符并用星号隐藏",
            "removed_fields": sorted(PRIVATE_KEYS),
            "redacted_patterns": ["中国大陆手机号", "电子邮箱", "wxid", "chatroom id"],
            "excluded_assets": ["头像", "原始聊天记录", "成员名单", "播客凭据", "内部部署配置"],
        },
        "reports": index_entries,
    }
    index_path = args.output / "index.json"
    index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    public_string_values: list[str] = []
    for path in output_daily.glob("*.json"):
        public_string_values.extend(iter_string_values(load_json(path)))
    leaked = [
        name
        for name in mask_list
        if any(name in value for value in public_string_values)
    ]
    if leaked:
        raise SystemExit(f"脱敏后仍发现 {len(leaked)} 个完整昵称，示例：{leaked[:5]}")

    print(
        json.dumps(
            {
                "reports": len(index_entries),
                "first": first.isoformat(),
                "latest": latest.isoformat(),
                "historical_missing": historical_missing,
                "pending": pending,
                "masked_name_variants": len(mask_list),
                "output": str(args.output),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

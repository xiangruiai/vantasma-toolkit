#!/usr/bin/env python3
"""Initialize and operate a conservative three-layer memory system."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parent.parent
ASSETS_DIR = SKILL_DIR / "assets"

PROFILE_PATH = Path("00.系统/agent/user.md")
PROCEDURE_PATH = Path("00.系统/agent/memory.md")
HISTORY_DIR = Path("50.个人/对话日志")
AGENTS_PATH = Path("AGENTS.md")
CLAUDE_PATH = Path("CLAUDE.md")

START_MARKER = "<!-- three-layer-memory:start -->"
END_MARKER = "<!-- three-layer-memory:end -->"

AGENTS_BLOCK = f"""

{START_MARKER}
## 三层记忆协议

对话开始：

1. 读取 `00.系统/agent/user.md`，获取已确认画像。
2. 读取 `00.系统/agent/memory.md`，获取已验证做法。
3. 仅在任务需要历史时搜索 `50.个人/对话日志/`，不要一次加载全部日志。

写入记忆：

1. 先分类为画像、程序、历史或不该记。
2. 先展示目标路径、理由和拟写内容。
3. 未经明确确认不得写入。
4. 不保存密码、密钥、验证码、未经确认的推断和无价值噪声。
5. 使用记忆回答时说明来源文件。
{END_MARKER}
""".lstrip()

CLAUDE_BLOCK = f"""

{START_MARKER}
@AGENTS.md
{END_MARKER}
""".lstrip()

SECRET_PATTERNS = {
    "private_key": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----", re.I),
    "api_key": re.compile(r"\b(?:sk|rk|pk)-[A-Za-z0-9_-]{12,}\b"),
    "password": re.compile(r"(?:密码|password|passwd)\s*[:：=]\s*\S+", re.I),
    "token": re.compile(r"(?:access[_ -]?token|api[_ -]?key)\s*[:：=]\s*\S+", re.I),
    "verification_code": re.compile(r"(?:验证码|verification code)\s*[:：=]?\s*\d{4,8}", re.I),
}


def now_date() -> str:
    return dt.date.today().isoformat()


def output(data: object) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2))


def resolve_vault(raw: str) -> Path:
    vault = Path(raw).expanduser().resolve()
    if not vault.exists() or not vault.is_dir():
        raise ValueError(f"Vault directory does not exist: {vault}")

    dangerous = {Path("/").resolve(), Path.home().resolve(), Path.home().parent.resolve()}
    if vault in dangerous:
        raise ValueError(f"Refusing broad or dangerous Vault target: {vault}")

    has_obsidian_marker = (vault / ".obsidian").is_dir()
    has_structured_vault = (vault / "00.系统").is_dir() and any(
        (vault / name).exists() for name in ["10.项目", "20.领域", "30.资源", "50.个人"]
    )
    if not (has_obsidian_marker or has_structured_vault):
        raise ValueError(
            "Target does not look like an exact Vault root. Open the folder containing .obsidian, "
            "or a structured Vault containing 00.系统 plus a knowledge top-level directory."
        )
    return vault


def render_asset(name: str) -> str:
    return (ASSETS_DIR / name).read_text(encoding="utf-8").replace("{{DATE}}", now_date())


def init_actions(vault: Path) -> list[dict[str, str]]:
    actions: list[dict[str, str]] = []
    templates = [
        (PROFILE_PATH, "user.md"),
        (PROCEDURE_PATH, "memory.md"),
        (HISTORY_DIR / "README.md", "log-readme.md"),
    ]
    for relative, _ in templates:
        absolute = vault / relative
        actions.append(
            {
                "action": "skip_existing" if absolute.exists() else "create",
                "path": str(relative),
            }
        )

    agents = vault / AGENTS_PATH
    agents_text = agents.read_text(encoding="utf-8") if agents.exists() else ""
    actions.append(
        {
            "action": "skip_managed_block" if START_MARKER in agents_text else "append_managed_block",
            "path": str(AGENTS_PATH),
        }
    )

    claude = vault / CLAUDE_PATH
    claude_text = claude.read_text(encoding="utf-8") if claude.exists() else ""
    actions.append(
        {
            "action": "skip_agents_reference"
            if "@AGENTS.md" in claude_text
            else "append_agents_reference",
            "path": str(CLAUDE_PATH),
        }
    )
    return actions


def write_if_missing(path: Path, content: str) -> str:
    if path.exists():
        return "skipped"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.rstrip() + "\n", encoding="utf-8")
    return "created"


def append_managed(path: Path, block: str) -> str:
    if path.exists():
        text = path.read_text(encoding="utf-8")
        if START_MARKER in text:
            return "skipped"
        separator = "" if not text or text.endswith("\n") else "\n"
        path.write_text(text + separator + "\n" + block.rstrip() + "\n", encoding="utf-8")
        return "appended"
    path.write_text(block.rstrip() + "\n", encoding="utf-8")
    return "created"


def cmd_init(args: argparse.Namespace) -> int:
    vault = resolve_vault(args.vault)
    actions = init_actions(vault)
    if args.dry_run:
        output({"ok": True, "dry_run": True, "vault": str(vault), "actions": actions})
        return 0

    results = []
    for relative, asset in [
        (PROFILE_PATH, "user.md"),
        (PROCEDURE_PATH, "memory.md"),
        (HISTORY_DIR / "README.md", "log-readme.md"),
    ]:
        status = write_if_missing(vault / relative, render_asset(asset))
        results.append({"status": status, "path": str(relative)})

    results.append({"status": append_managed(vault / AGENTS_PATH, AGENTS_BLOCK), "path": str(AGENTS_PATH)})

    claude = vault / CLAUDE_PATH
    claude_text = claude.read_text(encoding="utf-8") if claude.exists() else ""
    if "@AGENTS.md" in claude_text:
        results.append({"status": "skipped", "path": str(CLAUDE_PATH)})
    else:
        results.append({"status": append_managed(claude, CLAUDE_BLOCK), "path": str(CLAUDE_PATH)})

    output({"ok": True, "vault": str(vault), "results": results})
    return 0


def secret_categories(text: str) -> list[str]:
    return [name for name, pattern in SECRET_PATTERNS.items() if pattern.search(text)]


def target_for_layer(vault: Path, layer: str) -> Path:
    if layer == "profile":
        return vault / PROFILE_PATH
    if layer == "procedure":
        return vault / PROCEDURE_PATH
    if layer == "history":
        return vault / HISTORY_DIR / f"{now_date()} 记忆记录.md"
    raise ValueError(f"Unsupported layer: {layer}")


def normalized_entry(content: str, source: str) -> str:
    clean = " ".join(content.split())
    return f"- {clean}｜来源：{source or '人工确认'}｜确认时间：{now_date()}"


def history_template(entry: str) -> str:
    return f"""---
标题: {now_date()} 记忆记录
标签:
  - 三层记忆
  - 历史层
类型: conversation-log
日期: {now_date()}
状态: 使用中
---

# {now_date()} 记忆记录

## 事件

{entry}
"""


def cmd_append(args: argparse.Namespace) -> int:
    vault = resolve_vault(args.vault)
    if not args.confirmed:
        output(
            {
                "ok": False,
                "requires_confirmation": True,
                "layer": args.layer,
                "target": str(target_for_layer(vault, args.layer).relative_to(vault)),
                "content": " ".join(args.content.split()),
            }
        )
        return 2

    found_secrets = secret_categories(f"{args.content}\n{args.source}")
    if found_secrets:
        output({"ok": False, "rejected": "suspected_secret", "categories": found_secrets})
        return 3

    target = target_for_layer(vault, args.layer)
    if args.layer != "history" and not target.exists():
        output({"ok": False, "error": "memory_not_initialized", "missing": str(target.relative_to(vault))})
        return 4

    entry = normalized_entry(args.content, args.source)
    if target.exists():
        text = target.read_text(encoding="utf-8")
        if entry in text or " ".join(args.content.split()) in text:
            output({"ok": True, "status": "duplicate_skipped", "path": str(target.relative_to(vault))})
            return 0
        target.write_text(text.rstrip() + "\n\n" + entry + "\n", encoding="utf-8")
        status = "appended"
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(history_template(entry), encoding="utf-8")
        status = "created"

    output({"ok": True, "status": status, "path": str(target.relative_to(vault)), "entry": entry})
    return 0


def redact(text: str) -> str:
    result = text
    for pattern in SECRET_PATTERNS.values():
        result = pattern.sub("[REDACTED]", result)
    return result


def iter_memory_files(vault: Path):
    fixed = [vault / PROFILE_PATH, vault / PROCEDURE_PATH]
    for path in fixed:
        if path.exists():
            yield path
    history = vault / HISTORY_DIR
    if history.exists():
        for path in sorted(history.glob("*.md")):
            yield path


def cmd_recall(args: argparse.Namespace) -> int:
    vault = resolve_vault(args.vault)
    query = args.query.strip().lower()
    tokens = [token for token in re.split(r"\s+", query) if token]
    matches = []
    for path in iter_memory_files(vault):
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            lowered = line.lower()
            score = (3 if query and query in lowered else 0) + sum(token in lowered for token in tokens)
            if score:
                matches.append(
                    {
                        "score": score,
                        "path": str(path.relative_to(vault)),
                        "line": line_number,
                        "snippet": redact(line.strip())[:240],
                    }
                )
    matches.sort(key=lambda item: (-item["score"], item["path"], item["line"]))
    output({"ok": True, "query": args.query, "matches": matches[: args.limit]})
    return 0


def cmd_audit(args: argparse.Namespace) -> int:
    vault = resolve_vault(args.vault)
    required = [PROFILE_PATH, PROCEDURE_PATH, HISTORY_DIR / "README.md", AGENTS_PATH, CLAUDE_PATH]
    missing = [str(path) for path in required if not (vault / path).exists()]

    agents_text = (vault / AGENTS_PATH).read_text(encoding="utf-8") if (vault / AGENTS_PATH).exists() else ""
    protocol_loaded = START_MARKER in agents_text and END_MARKER in agents_text
    claude_text = (vault / CLAUDE_PATH).read_text(encoding="utf-8") if (vault / CLAUDE_PATH).exists() else ""
    claude_linked = "@AGENTS.md" in claude_text

    seen: dict[str, tuple[str, int]] = {}
    duplicates = []
    secrets = []
    for path in iter_memory_files(vault):
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            stripped = line.strip()
            categories = secret_categories(stripped)
            if categories:
                secrets.append(
                    {
                        "path": str(path.relative_to(vault)),
                        "line": line_number,
                        "categories": categories,
                    }
                )
            if len(stripped) < 20 or stripped.startswith(("#", "<!--", "---")):
                continue
            key = re.sub(r"｜来源：.*$", "", stripped)
            if key in seen:
                first_path, first_line = seen[key]
                duplicates.append(
                    {
                        "text": redact(key)[:160],
                        "first": f"{first_path}:{first_line}",
                        "duplicate": f"{path.relative_to(vault)}:{line_number}",
                    }
                )
            else:
                seen[key] = (str(path.relative_to(vault)), line_number)

    output(
        {
            "ok": not missing and protocol_loaded and claude_linked and not secrets,
            "vault": str(vault),
            "missing": missing,
            "protocol_loaded": protocol_loaded,
            "claude_linked": claude_linked,
            "duplicates": duplicates,
            "suspected_secrets": secrets,
        }
    )
    return 0 if not missing and protocol_loaded and claude_linked and not secrets else 5


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="Initialize the three-layer memory skeleton")
    init_parser.add_argument("--vault", required=True)
    init_parser.add_argument("--dry-run", action="store_true")
    init_parser.set_defaults(func=cmd_init)

    append_parser = subparsers.add_parser("append", help="Append a confirmed memory")
    append_parser.add_argument("--vault", required=True)
    append_parser.add_argument("--layer", required=True, choices=["profile", "procedure", "history"])
    append_parser.add_argument("--content", required=True)
    append_parser.add_argument("--source", default="")
    append_parser.add_argument("--confirmed", action="store_true")
    append_parser.set_defaults(func=cmd_append)

    recall_parser = subparsers.add_parser("recall", help="Recall memories by keyword")
    recall_parser.add_argument("--vault", required=True)
    recall_parser.add_argument("--query", required=True)
    recall_parser.add_argument("--limit", type=int, default=10)
    recall_parser.set_defaults(func=cmd_recall)

    audit_parser = subparsers.add_parser("audit", help="Audit memory structure and safety")
    audit_parser.add_argument("--vault", required=True)
    audit_parser.set_defaults(func=cmd_audit)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        return args.func(args)
    except (OSError, ValueError) as exc:
        output({"ok": False, "error": str(exc)})
        return 1


if __name__ == "__main__":
    sys.exit(main())

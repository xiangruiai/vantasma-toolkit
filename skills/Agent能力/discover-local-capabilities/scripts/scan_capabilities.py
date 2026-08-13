#!/usr/bin/env python3
"""Read-only inventory of local Agent Skills, CLI tools, MCP names, and plugins."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


DEFAULT_CLIS = [
    "codex", "claude", "openclaw", "lark-cli", "opencli", "obsidian", "ov",
    "qmd", "rg", "gh", "git", "python3", "node", "ffmpeg", "yt-dlp",
    "docker", "vercel", "curl",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate a local capability map without changing the machine.")
    parser.add_argument("--project", type=Path, default=Path.cwd(), help="Project root to scan for project-local Skills.")
    parser.add_argument("--output-dir", type=Path, default=Path(".capability-map"), help="Report directory.")
    parser.add_argument("--skill-root", action="append", type=Path, default=[], help="Additional Skill root; repeatable.")
    parser.add_argument("--cli", action="append", default=[], help="Additional CLI name; repeatable.")
    parser.add_argument("--probe-versions", action="store_true", help="Run safe version probes with a short timeout.")
    return parser.parse_args()


def redact_path(path: Path, home: Path) -> str:
    try:
        resolved = path.expanduser().resolve()
    except OSError:
        resolved = path.expanduser().absolute()
    try:
        return "~/" + str(resolved.relative_to(home.resolve()))
    except ValueError:
        return str(resolved)


def parse_frontmatter(skill_md: Path) -> tuple[str, str]:
    try:
        text = skill_md.read_text(encoding="utf-8", errors="replace")[:16000]
    except OSError:
        return skill_md.parent.name, ""
    if not text.startswith("---"):
        return skill_md.parent.name, ""
    parts = text.split("---", 2)
    if len(parts) < 3:
        return skill_md.parent.name, ""
    frontmatter = parts[1]
    name_match = re.search(r"(?m)^name:\s*[\"']?([^\n\"']+)", frontmatter)
    desc_match = re.search(r"(?ms)^description:\s*(.+?)(?=\n[A-Za-z0-9_-]+:|\Z)", frontmatter)
    name = name_match.group(1).strip() if name_match else skill_md.parent.name
    description = desc_match.group(1).strip().strip("\"'") if desc_match else ""
    description = re.sub(r"\s+", " ", description)
    return name, description


def skill_roots(home: Path, project: Path, extras: list[Path]) -> list[tuple[Path, str, str]]:
    roots = [
        (home / ".codex" / "skills", "user", "Codex"),
        (home / ".agents" / "skills", "user", "Shared"),
        (home / ".claude" / "skills", "user", "Claude"),
        (project / ".codex" / "skills", "project", "Codex"),
        (project / ".agents" / "skills", "project", "Shared"),
        (project / ".claude" / "skills", "project", "Claude"),
    ]
    roots.extend((path.expanduser(), "extra", "Custom") for path in extras)
    return roots


def discover_skills(home: Path, project: Path, extras: list[Path]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for root, scope, agent in skill_roots(home, project, extras):
        if not root.is_dir():
            continue
        try:
            skill_files = sorted(root.glob("*/SKILL.md"))
        except OSError:
            continue
        for skill_md in skill_files:
            try:
                real = skill_md.resolve()
            except OSError:
                real = skill_md.absolute()
            key = str(real)
            name, description = parse_frontmatter(skill_md)
            record = grouped.setdefault(key, {
                "name": name,
                "description": description,
                "real_path": redact_path(real.parent, home),
                "locations": [],
                "scopes": [],
                "agents": [],
                "kind": "skill",
            })
            visible = redact_path(skill_md.parent, home)
            if visible not in record["locations"]:
                record["locations"].append(visible)
            if scope not in record["scopes"]:
                record["scopes"].append(scope)
            if agent not in record["agents"]:
                record["agents"].append(agent)
    return sorted(grouped.values(), key=lambda item: item["name"].lower())


def probe_version(name: str, path: str) -> str:
    flags = ["--version"]
    if name == "java":
        flags = ["-version"]
    try:
        result = subprocess.run(
            [path, *flags], capture_output=True, text=True, timeout=2.5,
            env={**os.environ, "NO_COLOR": "1"}, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "无法读取"
    line = (result.stdout or result.stderr).strip().splitlines()
    return line[0][:160] if line else "无版本输出"


def discover_clis(names: list[str], home: Path, probe: bool) -> tuple[list[dict[str, Any]], list[str]]:
    found: list[dict[str, Any]] = []
    missing: list[str] = []
    for name in dict.fromkeys(names):
        path = shutil.which(name)
        if not path:
            missing.append(name)
            continue
        record: dict[str, Any] = {
            "name": name,
            "path": redact_path(Path(path), home),
            "kind": "cli",
            "status": "discovered",
        }
        if probe:
            record["version"] = probe_version(name, path)
            record["status"] = "version-probed"
        found.append(record)
    return found, missing


def safe_json_names(path: Path, key: str) -> list[str]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    value = data.get(key, {}) if isinstance(data, dict) else {}
    return sorted(str(name) for name in value) if isinstance(value, dict) else []


def discover_connectors(home: Path, project: Path) -> list[dict[str, str]]:
    found: dict[tuple[str, str], dict[str, str]] = {}

    codex_config = home / ".codex" / "config.toml"
    if codex_config.is_file() and sys.version_info >= (3, 11):
        try:
            import tomllib
            data = tomllib.loads(codex_config.read_text(encoding="utf-8"))
            for key in ("mcp_servers", "mcpServers"):
                value = data.get(key, {}) if isinstance(data, dict) else {}
                if isinstance(value, dict):
                    for name in value:
                        found[("mcp", str(name))] = {"kind": "mcp", "name": str(name), "source": "~/.codex/config.toml"}
        except (OSError, ValueError):
            pass

    for config in (project / ".mcp.json", home / ".claude.json"):
        for name in safe_json_names(config, "mcpServers"):
            found[("mcp", name)] = {"kind": "mcp", "name": name, "source": redact_path(config, home)}

    plugin_root = home / ".codex" / "plugins" / "cache"
    if plugin_root.is_dir():
        for child in sorted(plugin_root.iterdir()):
            if child.is_dir() and not child.name.startswith("."):
                found[("plugin", child.name)] = {"kind": "plugin", "name": child.name, "source": "~/.codex/plugins/cache"}

    return sorted(found.values(), key=lambda item: (item["kind"], item["name"].lower()))


def load_rules(skill_dir: Path) -> list[dict[str, Any]]:
    path = skill_dir / "references" / "routing-rules.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        # v2 retired author-specific preferred routes. The compatibility
        # scanner keeps running with no legacy routes until the new entrypoint
        # takes over dynamic classification.
        return []


def capability_index(skills: list[dict[str, Any]], clis: list[dict[str, Any]], connectors: list[dict[str, str]]) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    for item in skills:
        items.append({"name": item["name"], "kind": "Skill", "evidence": item["real_path"]})
    for item in clis:
        items.append({"name": item["name"], "kind": "CLI", "evidence": item["path"]})
    for item in connectors:
        items.append({"name": item["name"], "kind": item["kind"].upper(), "evidence": item["source"]})
    return items


def choose_routes(rules: list[dict[str, Any]], index: list[dict[str, str]]) -> list[dict[str, Any]]:
    routes: list[dict[str, Any]] = []
    for rule in rules:
        candidates: list[dict[str, str]] = []
        for preferred in rule["preferred"]:
            needle = preferred.lower()
            matches = [item for item in index if item["name"].lower() == needle]
            if not matches:
                matches = [item for item in index if needle in item["name"].lower()]
            candidates.extend(matches)
        unique: list[dict[str, str]] = []
        seen: set[tuple[str, str]] = set()
        for item in candidates:
            key = (item["kind"], item["name"])
            if key not in seen:
                seen.add(key)
                unique.append(item)
        selected = unique[0] if unique else None
        routes.append({
            "scene": rule["scene"],
            "selected": selected,
            "alternatives": unique[1:4],
            "reason": rule["reason"],
            "status": "discovered" if selected else "missing",
        })
    return routes


def markdown_report(data: dict[str, Any]) -> str:
    lines = [
        "# 本机能力地图",
        "",
        f"> 生成时间：{data['metadata']['generated_at']}  ",
        f"> 扫描项目：`{data['metadata']['project']}`  ",
        "> 状态说明：`已发现` 仅代表本机存在，执行任务前仍需检查认证、权限与真实可用性。",
        "",
        "## 场景 → 首选能力",
        "",
        "| 状态 | 场景 | 首选能力 | 类型 | 证据 | 备选 |",
        "|---|---|---|---|---|---|",
    ]
    for route in data["routes"]:
        selected = route["selected"] or {"name": "未命中", "kind": "-", "evidence": "-"}
        alternatives = "、".join(item["name"] for item in route["alternatives"]) or "-"
        status = "已发现" if route["status"] == "discovered" else "缺失"
        lines.append(f"| {status} | {route['scene']} | `{selected['name']}` | {selected['kind']} | `{selected['evidence']}` | {alternatives} |")

    lines.extend(["", "## 已发现 Skills", "", "| 名称 | 说明 | 作用域 | 可见位置 |", "|---|---|---|---|"])
    for item in data["skills"]:
        desc = item["description"].replace("|", "\\|")[:160] or "-"
        lines.append(f"| `{item['name']}` | {desc} | {', '.join(item['scopes'])} | `{item['real_path']}` |")

    lines.extend(["", "## 已发现 CLI", "", "| 名称 | 状态 | 版本 | 路径 |", "|---|---|---|---|"])
    for item in data["clis"]:
        lines.append(f"| `{item['name']}` | {item['status']} | {item.get('version', '未探测')} | `{item['path']}` |")

    lines.extend(["", "## MCP / Plugins", "", "| 类型 | 名称 | 来源 |", "|---|---|---|"])
    for item in data["connectors"]:
        lines.append(f"| {item['kind'].upper()} | `{item['name']}` | `{item['source']}` |")

    lines.extend(["", "## 扫描边界", "", "- 未读取 `.env`、token、密钥或命令历史。", "- 未安装、更新、授权或调用任何发现到的能力。", "- 默认未执行版本命令；只有显式使用 `--probe-versions` 才会探测版本。", "- `discovered` 不等于 `authenticated` 或 `task-verified`。", ""])
    return "\n".join(lines)


def main() -> int:
    args = parse_args()
    home = Path.home()
    project = args.project.expanduser().resolve()
    output_dir = args.output_dir.expanduser()
    if not output_dir.is_absolute():
        output_dir = project / output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    skills = discover_skills(home, project, args.skill_root)
    clis, missing_clis = discover_clis(DEFAULT_CLIS + args.cli, home, args.probe_versions)
    connectors = discover_connectors(home, project)
    rules = load_rules(Path(__file__).resolve().parent.parent)
    routes = choose_routes(rules, capability_index(skills, clis, connectors))

    data = {
        "metadata": {
            "generated_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
            "host": platform.node(),
            "platform": platform.platform(),
            "project": redact_path(project, home),
            "states": ["discovered", "version-probed", "authenticated", "task-verified"],
        },
        "summary": {
            "skills": len(skills),
            "clis": len(clis),
            "connectors": len(connectors),
            "routes_matched": sum(1 for route in routes if route["status"] == "discovered"),
        },
        "routes": routes,
        "skills": skills,
        "clis": clis,
        "missing_clis": missing_clis,
        "connectors": connectors,
    }

    markdown_path = output_dir / "capability-map.md"
    json_path = output_dir / "capability-map.json"
    markdown_path.write_text(markdown_report(data), encoding="utf-8")
    json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"Markdown: {markdown_path}")
    print(f"JSON: {json_path}")
    print(json.dumps(data["summary"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

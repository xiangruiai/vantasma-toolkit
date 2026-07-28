#!/usr/bin/env python3
"""Install this skill into Codex, Claude Code, or both without overwriting."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parent.parent
def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", choices=["codex", "claude", "both"], default="both")
    parser.add_argument(
        "--destination-root",
        default=str(Path.home()),
        help="Home-like root used for installation; defaults to the current user's home directory.",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    destination_root = Path(args.destination_root).expanduser().resolve()
    targets = {
        "codex": destination_root / ".codex" / "skills" / SKILL_DIR.name,
        "claude": destination_root / ".claude" / "skills" / SKILL_DIR.name,
    }
    names = ["codex", "claude"] if args.target == "both" else [args.target]
    results = []
    for name in names:
        target = targets[name]
        if target.exists():
            results.append({"target": name, "status": "skipped_existing", "path": str(target)})
            continue
        if args.dry_run:
            results.append({"target": name, "status": "would_install", "path": str(target)})
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(SKILL_DIR, target)
        results.append({"target": name, "status": "installed", "path": str(target)})

    print(json.dumps({"ok": True, "results": results}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
import argparse
import json
import os
import platform
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile

NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}


FONT_ALIASES = {
    "宋体": ["宋体", "SimSun", "Songti", "STSong", "Songti SC"],
    "黑体": ["黑体", "SimHei", "Heiti", "STHeiti", "Heiti SC"],
    "仿宋": ["仿宋", "FangSong", "STFangsong"],
    "幼圆": ["幼圆", "YouYuan", "Yuanti", "Yuanti SC"],
    "ＭＳ ゴシック": ["ＭＳ ゴシック", "MS Gothic", "Hiragino Sans"],
    "ＭＳ 明朝": ["ＭＳ 明朝", "MS Mincho", "Hiragino Mincho"],
}

OPEN_SOURCE_FALLBACKS = {
    "Arial": ["Liberation Sans", "Arimo"],
    "Calibri": ["Carlito"],
    "Cambria": ["Caladea"],
    "Courier New": ["Liberation Mono", "Cousine"],
    "Times New Roman": ["Liberation Serif", "Tinos"],
    "宋体": ["Source Han Serif SC", "Noto Serif CJK SC"],
    "黑体": ["Source Han Sans SC", "Noto Sans CJK SC"],
    "仿宋": ["Source Han Serif SC", "Noto Serif CJK SC"],
    "幼圆": ["Noto Sans CJK SC"],
    "ＭＳ ゴシック": ["Noto Sans CJK JP", "Source Han Sans"],
    "ＭＳ 明朝": ["Noto Serif CJK JP", "Source Han Serif"],
}

FONT_SUFFIXES = {".ttf", ".otf", ".ttc"}
FONT_CACHE_PATH = Path(tempfile.gettempdir()) / "template_fidelity_font_probe_cache.json"
FONT_CACHE_TTL_SECONDS = 24 * 60 * 60


def qn(name):
    prefix, local = name.split(":", 1)
    return "{%s}%s" % (NS[prefix], local)


def parse_template_fonts(path):
    with ZipFile(path) as zf:
        if "word/fontTable.xml" not in zf.namelist():
            return []
        root = ET.fromstring(zf.read("word/fontTable.xml"))
        return sorted({font.get(qn("w:name")) for font in root.findall("w:font", NS) if font.get(qn("w:name"))})


def collect_installed_font_text():
    if os.environ.get("TEMPLATE_FIDELITY_DISABLE_FONT_CACHE") != "1":
        try:
            ttl = int(os.environ.get("TEMPLATE_FIDELITY_FONT_CACHE_TTL", str(FONT_CACHE_TTL_SECONDS)))
            if FONT_CACHE_PATH.exists() and time.time() - FONT_CACHE_PATH.stat().st_mtime <= ttl:
                cached = json.loads(FONT_CACHE_PATH.read_text(encoding="utf-8"))
                text = cached.get("text")
                sources = cached.get("sources")
                if isinstance(text, str) and isinstance(sources, list):
                    return text, [str(source) for source in sources] + [f"cache:{FONT_CACHE_PATH}"]
        except Exception:
            pass

    chunks = []
    sources = []
    if platform.system() == "Darwin":
        try:
            cp = subprocess.run(["system_profiler", "SPFontsDataType"], capture_output=True, text=True, timeout=45)
            chunks.append(cp.stdout + "\n" + cp.stderr)
            sources.append("system_profiler SPFontsDataType")
        except Exception as exc:
            sources.append(f"system_profiler failed: {exc}")
    for root in [
        "/System/Library/Fonts",
        "/Library/Fonts",
        str(Path.home() / "Library/Fonts"),
        str(Path.home() / ".local/share/fonts"),
    ]:
        p = Path(root)
        if p.exists():
            chunks.append("\n".join(str(x) for x in p.rglob("*") if x.suffix.lower() in FONT_SUFFIXES))
            sources.append(root)
    text = "\n".join(chunks)
    if os.environ.get("TEMPLATE_FIDELITY_DISABLE_FONT_CACHE") != "1":
        try:
            tmp = FONT_CACHE_PATH.with_suffix(".tmp")
            tmp.write_text(json.dumps({"text": text, "sources": sources}, ensure_ascii=False), encoding="utf-8")
            tmp.replace(FONT_CACHE_PATH)
        except Exception:
            pass
    return text, sources


def normalize_name(value):
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", value.lower())


def probes_for(font):
    return [font] + [alias for alias in FONT_ALIASES.get(font, []) if alias != font]


def installed_match(installed_text, font):
    evidence = []
    for probe in probes_for(font):
        if re.search(re.escape(probe), installed_text, re.I):
            evidence.append(probe)
    return evidence[:8]


def font_files_in(paths):
    files = []
    for raw in paths:
        if not raw:
            continue
        path = Path(raw).expanduser()
        if path.exists():
            if path.is_file() and path.suffix.lower() in FONT_SUFFIXES:
                files.append(path)
            elif path.is_dir():
                files.extend([p for p in path.rglob("*") if p.suffix.lower() in FONT_SUFFIXES])
    return sorted(set(files))


def find_candidates(font, font_files):
    normalized_probes = {normalize_name(probe) for probe in probes_for(font)}
    candidates = []
    for file_path in font_files:
        stem = normalize_name(file_path.stem)
        if any(probe and probe in stem for probe in normalized_probes):
            candidates.append(str(file_path))
    return candidates[:20]


def install_font_files(candidates):
    target_dir = Path.home() / "Library" / "Fonts"
    target_dir.mkdir(parents=True, exist_ok=True)
    installed = []
    skipped = []
    for source in candidates:
        src = Path(source)
        dst = target_dir / src.name
        if dst.exists():
            skipped.append({"source": str(src), "target": str(dst), "reason": "target_exists"})
            continue
        shutil.copy2(src, dst)
        installed.append({"source": str(src), "target": str(dst)})
    return {"target_dir": str(target_dir), "installed": installed, "skipped": skipped}


def build_report(template, font_dirs, install=False):
    required = parse_template_fonts(template)
    installed_text, sources = collect_installed_font_text()
    skill_dir = Path(__file__).resolve().parents[1]
    default_font_dir = skill_dir / "assets" / "fonts"
    search_dirs = [str(default_font_dir)] + [str(Path(p).expanduser()) for p in font_dirs]
    candidate_files = font_files_in(search_dirs)
    rows = []
    all_install_candidates = []

    for font in required:
        evidence = installed_match(installed_text, font)
        candidates = find_candidates(font, candidate_files)
        if not evidence:
            all_install_candidates.extend(candidates)
        rows.append(
            {
                "font": font,
                "available_likely": bool(evidence),
                "installed_evidence": evidence,
                "local_candidates": candidates,
                "open_source_fallbacks": OPEN_SOURCE_FALLBACKS.get(font, []),
                "action": "ok" if evidence else ("install_candidate" if candidates else "provide_font_or_approve_fallback"),
            }
        )

    report = {
        "template": str(Path(template).resolve()),
        "policy": "Do not silently replace fonts. Install licensed fonts or explicitly approve fallback mapping before final PDF delivery.",
        "required_fonts": required,
        "installed_sources_checked": sources,
        "font_dirs_checked": search_dirs,
        "fonts": rows,
        "missing_fonts": [row["font"] for row in rows if not row["available_likely"]],
        "install": None,
    }
    if install:
        unique_candidates = sorted(set(all_install_candidates))
        report["install"] = install_font_files(unique_candidates)
    return report


def main():
    parser = argparse.ArgumentParser(description="Prepare a font plan for a DOCX template.")
    parser.add_argument("template")
    parser.add_argument("--font-dir", action="append", default=[], help="Directory or font file containing licensed fonts.")
    parser.add_argument("--install", action="store_true", help="Copy matching local candidate fonts to ~/Library/Fonts.")
    parser.add_argument("--report", required=True)
    args = parser.parse_args()

    report = build_report(Path(args.template).expanduser(), args.font_dir, args.install)
    Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not report["missing_fonts"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

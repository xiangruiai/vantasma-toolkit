#!/usr/bin/env python3
"""群日报 skill 环境自检。

检查项:
    1. macOS 平台（必须）
    2. Python 依赖: Pillow（必须）, openai-whisper（可选，转写用）, silk-python（同上）
    3. vchat CLI（强烈建议）
    4. wechat-decrypt 项目路径（必须，至少 contact.db 和 head_image.db 存在）
    5. Chrome / Chromium 浏览器（必须，PNG 截图用）
    6. 环境变量 GROUP_DAILY_VAULT（可选）、VCHAT_DATA_DIR（可选）

每项给出 ✅ / ⚠️ / ❌ 和修复建议。
"""
import os
import platform
import shutil
import sys
from pathlib import Path


ANSI_GREEN = "\033[32m"
ANSI_YELLOW = "\033[33m"
ANSI_RED = "\033[31m"
ANSI_DIM = "\033[2m"
ANSI_RESET = "\033[0m"


def ok(msg, detail=""):
    print(f"  {ANSI_GREEN}✅{ANSI_RESET} {msg}", end="")
    if detail:
        print(f"  {ANSI_DIM}{detail}{ANSI_RESET}")
    else:
        print()


def warn(msg, fix=""):
    print(f"  {ANSI_YELLOW}⚠️{ANSI_RESET}  {msg}")
    if fix:
        print(f"     {ANSI_DIM}修复: {fix}{ANSI_RESET}")


def fail(msg, fix=""):
    print(f"  {ANSI_RED}❌{ANSI_RESET} {msg}")
    if fix:
        print(f"     {ANSI_DIM}修复: {fix}{ANSI_RESET}")


def header(title):
    print(f"\n{ANSI_DIM}── {title} ─────────────{ANSI_RESET}")


def check_platform():
    header("平台")
    if platform.system() == "Darwin":
        ok(f"macOS {platform.mac_ver()[0]}")
        return True
    fail(f"系统是 {platform.system()}，本 skill 仅支持 macOS",
         "请在 macOS 上运行")
    return False


def check_python_deps():
    header("Python 依赖")
    has_pillow = False
    try:
        import PIL  # noqa: F401
        ok("Pillow")
        has_pillow = True
    except ImportError:
        fail("Pillow 未装（PNG 截图必需）",
             "pip3 install Pillow --break-system-packages")

    has_whisper = False
    try:
        import whisper  # noqa: F401
        ok("openai-whisper（语音转写）")
        has_whisper = True
    except ImportError:
        warn("openai-whisper 未装（无法转写语音；不需要语音功能可忽略）",
             "pip3 install openai-whisper --break-system-packages")

    try:
        import pysilk  # noqa: F401
        ok("silk-python（语音解码）")
    except ImportError:
        if has_whisper:
            warn("silk-python 未装（语音解码必需）",
                 "pip3 install silk-python --break-system-packages")
        else:
            warn("silk-python 未装",
                 "pip3 install silk-python --break-system-packages")

    return has_pillow


def check_vchat():
    header("vchat CLI（首选数据访问路径）")
    vchat = shutil.which("vchat")
    if vchat:
        ok("vchat 已安装", detail=vchat)
        return True
    warn("vchat 不在 PATH 中（强烈建议安装）",
         "见 https://github.com/<wechat-decrypt-repo>"
         "（祥瑞 wechat-decrypt 项目目前未开源，"
         "可暂用 MCP 工具 + 本 skill 自带脚本作为兜底）")
    return False


def check_wechat_decrypt():
    header("vchat 数据目录")
    root = os.environ.get("VCHAT_DATA_DIR", "~/Projects/wechat-decrypt")
    root_path = Path(os.path.expanduser(root))

    if not root_path.exists():
        fail(f"目录不存在: {root_path}",
             "git clone <wechat-decrypt repo> 到此路径，或设置环境变量 "
             "VCHAT_DATA_DIR 指向你的解密项目根目录")
        return False

    ok(f"项目根目录存在: {root_path}")

    contact_db = root_path / "decrypted/contact/contact.db"
    head_db = root_path / "decrypted/head_image/head_image.db"

    if not contact_db.exists():
        fail(f"联系人 db 缺失: {contact_db}",
             "在 wechat-decrypt 项目里跑解密脚本生成")
        return False
    ok(f"contact.db 存在", detail=f"{contact_db.stat().st_size / 1024:.0f} KB")

    if not head_db.exists():
        warn(f"头像 db 缺失: {head_db}",
             "解码所有头像会失败，但 skill 仍可跑（fallback 到首字 placeholder）")
    else:
        ok("head_image.db 存在",
           detail=f"{head_db.stat().st_size / 1024 / 1024:.1f} MB")

    return True


def check_browser():
    header("浏览器（HTML → PNG 用）")
    candidates = [
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
        "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    ]
    for p in candidates:
        if os.access(p, os.X_OK):
            ok(f"找到", detail=p)
            return True

    if shutil.which("google-chrome") or shutil.which("chromium"):
        ok("在 PATH 中找到 chrome/chromium")
        return True

    fail("没找到 Chrome / Chromium",
         "从 https://www.google.com/chrome/ 下载安装")
    return False


def check_env_vars():
    header("环境变量（可选）")
    gd_vault = os.environ.get("GROUP_DAILY_VAULT")
    if gd_vault:
        path = Path(os.path.expanduser(gd_vault))
        if path.exists():
            ok(f"GROUP_DAILY_VAULT", detail=str(path))
        else:
            warn(f"GROUP_DAILY_VAULT 指向不存在的目录: {path}",
                 f"mkdir -p '{path}' 或修改环境变量")
    else:
        default = Path.home() / "Documents/GroupDaily"
        warn(f"GROUP_DAILY_VAULT 未设，将用默认值 {default}",
             "如需指向已有目录（如 Obsidian Vault 子目录）"
             "，export GROUP_DAILY_VAULT=/your/path")

    wd_path = os.environ.get("VCHAT_DATA_DIR")
    if wd_path:
        ok(f"VCHAT_DATA_DIR", detail=wd_path)
    else:
        warn("VCHAT_DATA_DIR 未设，将用默认值 ~/Projects/wechat-decrypt",
             "如果你的解密项目在别处，export VCHAT_DATA_DIR=/your/path")


def main():
    print(f"{ANSI_DIM}group-daily skill 环境自检{ANSI_RESET}")

    plat_ok = check_platform()
    py_ok = check_python_deps()
    vchat_ok = check_vchat()
    wd_ok = check_wechat_decrypt()
    br_ok = check_browser()
    check_env_vars()

    print()
    if all([plat_ok, py_ok, wd_ok, br_ok]):
        if vchat_ok:
            print(f"{ANSI_GREEN}✅ 所有必装项就绪，可以跑 skill 全流程。{ANSI_RESET}")
        else:
            print(f"{ANSI_YELLOW}⚠️  能跑，但 vchat 缺失会导致部分功能降级（拉历史用 MCP 容易爆 token、语音转写依赖系统 whisper）。{ANSI_RESET}")
    else:
        print(f"{ANSI_RED}❌ 必装项缺失，跑 skill 会失败。请按上面提示修复后重试。{ANSI_RESET}")
        sys.exit(1)


if __name__ == "__main__":
    main()

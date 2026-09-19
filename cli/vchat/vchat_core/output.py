"""vchat_core.output · 统一输出 helper。

- emit(obj, *, json_mode, human=...)：根据全局 --json 走结构化还是人读
- color helpers：尊重 NO_COLOR / --no-color 环境
"""

import json
import os
import sys
from typing import Any, Callable, Optional


# 颜色控制 ─────────────────────────────────────────
_FORCE_NO_COLOR = bool(os.environ.get("NO_COLOR"))


def disable_color() -> None:
    """显式关掉颜色（--no-color flag）。"""
    global _FORCE_NO_COLOR
    _FORCE_NO_COLOR = True


def _use_color() -> bool:
    if _FORCE_NO_COLOR:
        return False
    return sys.stdout.isatty()


def color(text: str, code: str) -> str:
    if not _use_color():
        return text
    return f"\033[{code}m{text}\033[0m"


def dim(s: str) -> str:    return color(s, "2")
def bold(s: str) -> str:   return color(s, "1")
def red(s: str) -> str:    return color(s, "31")
def green(s: str) -> str:  return color(s, "32")
def yellow(s: str) -> str: return color(s, "33")
def blue(s: str) -> str:   return color(s, "34")
def cyan(s: str) -> str:   return color(s, "36")


# JSON / human 双模式输出 ────────────────────────────
def emit(
    payload: Any,
    *,
    json_mode: bool = False,
    human: Optional[Callable[[Any], str]] = None,
) -> None:
    """根据 json_mode 输出。

    Args:
        payload: 结构化数据（dict/list/...）。json_mode=True 时直接 JSON 输出。
        json_mode: 来自 args.json
        human: 一个把 payload 转人读字符串的函数。json_mode=False 时调用。
    """
    if json_mode:
        json.dump(payload, sys.stdout, ensure_ascii=False, indent=2, default=str)
        sys.stdout.write("\n")
        return
    if human is None:
        # fallback：直接 print
        print(payload)
        return
    print(human(payload))


def err(msg: str) -> None:
    """统一错误输出（stderr + 红色）。"""
    print(red(msg), file=sys.stderr)


def warn(msg: str) -> None:
    print(yellow(msg), file=sys.stderr)


def info(msg: str) -> None:
    """进度/提示信息走 stderr。"""
    print(msg, file=sys.stderr)

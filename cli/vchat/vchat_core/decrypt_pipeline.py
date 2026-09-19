"""vchat_core.decrypt_pipeline · 跨平台一键解密编排

macOS:   调 vchat_native/find_keys_macos（C 程序）扫内存
Windows: 调 vchat_core.find_keys_windows（纯 Python ctypes）扫内存
Linux:   暂不支持（无微信桌面版）

流程：
  1. 扫内存得到 {db_rel: key_hex}
  2. 用 crypto.quick_verify_key 二次校验
  3. 用 crypto.decrypt_db 解所有 db，落到 $VCHAT_DATA_DIR/decrypted/
  4. keys.json 缓存到 $VCHAT_DATA_DIR/keys.json
"""

import json
import os
import platform
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from . import crypto


WX_CONTAINER_MACOS = Path.home() / "Library/Containers/com.tencent.xinWeChat/Data/Documents/xwechat_files"


def find_wechat_main_pid() -> Optional[int]:
    """找微信主进程 pid（跨平台）。"""
    sys_name = platform.system()
    if sys_name == "Darwin":
        try:
            out = subprocess.run(
                ["pgrep", "-f", "WeChat.app/Contents/MacOS/WeChat$"],
                capture_output=True, text=True, timeout=5
            )
            if out.returncode == 0:
                pids = [int(p) for p in out.stdout.split() if p.strip()]
                return pids[0] if pids else None
        except Exception:
            pass
        return None
    if sys_name == "Windows":
        from . import find_keys_windows
        return find_keys_windows.find_wechat_pid()
    return None


def find_wechat_pids() -> List[int]:
    """找需要扫描的微信进程。

    常规消息库的 key 在 WeChat 主进程中；较新的附属库（如 weclaw.db）
    由 WeChatAppEx 打开，key 只会出现在对应子进程内存中。
    """
    if platform.system() != "Darwin":
        pid = find_wechat_main_pid()
        return [pid] if pid else []
    patterns = [
        r"/Applications/WeChat.app/Contents/MacOS/WeChat$",
        r"/Applications/WeChat.app/Contents/MacOS/WeChatAppEx\.app/Contents/MacOS/WeChatAppEx( |$)",
    ]
    pids: List[int] = []
    for pattern in patterns:
        try:
            out = subprocess.run(["pgrep", "-f", pattern], capture_output=True,
                                 text=True, timeout=5)
            if out.returncode == 0:
                for raw in out.stdout.split():
                    pid = int(raw)
                    if pid not in pids:
                        pids.append(pid)
        except (ValueError, OSError, subprocess.TimeoutExpired):
            continue
    return pids


def find_db_storage() -> Optional[Path]:
    """定位当前账号的 db_storage 目录（xwechat_files/<wxid>_<r>/db_storage/）。"""
    sys_name = platform.system()
    if sys_name == "Darwin":
        if not WX_CONTAINER_MACOS.exists():
            return None
        candidates = []
        for child in WX_CONTAINER_MACOS.iterdir():
            if child.is_dir() and not child.name.startswith("all_users"):
                ds = child / "db_storage"
                if ds.is_dir():
                    mt = max((f.stat().st_mtime for f in ds.rglob("*.db")), default=0)
                    candidates.append((mt, ds, child.name))
        if not candidates:
            return None
        candidates.sort(reverse=True)
        return candidates[0][1]
    if sys_name == "Windows":
        from . import find_keys_windows
        return find_keys_windows.find_db_storage_windows()
    return None


def enumerate_dbs(db_storage: Path) -> List[Path]:
    """列所有 .db 文件，跳过 -shm / -wal。"""
    return sorted([p for p in db_storage.rglob("*.db")])


def run_key_scanner(scanner_binary: Path, pid: int) -> Dict[str, str]:
    """跑 find_keys_macos（macOS 专用），返回 {db_rel_path: key_hex}。"""
    if not scanner_binary.exists():
        raise RuntimeError(f"扫描器未编译: {scanner_binary}\n→ 跑 `make -C vchat_native`")
    if hasattr(os, "geteuid") and os.geteuid() != 0:
        raise PermissionError("内存扫描需要 root（sudo）")
    out = subprocess.run(
        [str(scanner_binary), "--pid", str(pid)],
        capture_output=True, text=True, timeout=180
    )
    sys.stderr.write(out.stderr)
    if out.returncode > 4:
        raise RuntimeError(f"扫描器退出 {out.returncode}")
    # 部分匹配（returncode=1）也接受，0 全匹配
    try:
        return json.loads(out.stdout) if out.stdout.strip() else {}
    except json.JSONDecodeError as e:
        raise RuntimeError(f"扫描器输出不是 JSON: {e}\n输出 head: {out.stdout[:200]}")


def match_keys_to_dbs(candidates: List[str], dbs: List[Path],
                      verbose: bool = True) -> Dict[str, str]:
    """对每个 db 试候选 key，返回 {db_path: key_hex}。

    优化：先用第一个 db 把所有 working keys 找出来（candidates 集合 → working_keys 子集），
    再用 working_keys 去覆盖其他 db。这样从 O(N_cand × N_db) 降到 O(N_cand + N_working × N_db)。
    """
    if not dbs or not candidates:
        return {}

    if verbose:
        print(f"▶ 阶段 A: 用首个 db ({dbs[0].name}) 锁定 working key 集合…", file=sys.stderr)

    # 阶段 A：找首个 db 能用的所有 key
    working: List[str] = []
    for i, k in enumerate(candidates):
        if crypto.quick_verify_key(dbs[0], k):
            working.append(k)
        if verbose and (i + 1) % 500 == 0:
            print(f"  ... {i+1}/{len(candidates)}", file=sys.stderr)
    if verbose:
        print(f"  ✓ 首个 db 锁定 {len(working)} 个 working key", file=sys.stderr)

    if not working:
        # 首个 db 没匹配，挨个试（fallback —— 不太可能发生）
        if verbose:
            print(f"  首个 db 没匹配，全量回退…", file=sys.stderr)
        found: Dict[str, str] = {}
        for db in dbs:
            for k in candidates:
                if crypto.quick_verify_key(db, k):
                    found[str(db)] = k
                    break
        return found

    # 阶段 B：用 working key 集合覆盖其他 db
    if verbose:
        print(f"▶ 阶段 B: 用 {len(working)} 个 working key 覆盖剩余 {len(dbs)-1} 个 db…",
              file=sys.stderr)
    found: Dict[str, str] = {str(dbs[0]): working[0]}
    for db in dbs[1:]:
        for k in working:
            if crypto.quick_verify_key(db, k):
                found[str(db)] = k
                break
    return found


def decrypt_all(db_storage: Path, key_map: Dict[str, str], out_root: Path) -> Dict[str, dict]:
    """按 key 解所有 db，输出到 out_root/<rel>。"""
    results = {}
    out_root.mkdir(parents=True, exist_ok=True)
    for enc_path_str, key_hex in key_map.items():
        enc_path = Path(enc_path_str)
        rel = enc_path.relative_to(db_storage)
        out_path = out_root / rel
        try:
            info = crypto.decrypt_db(enc_path, out_path, key_hex)
            results[str(rel)] = {"ok": True, **info}
        except Exception as e:
            results[str(rel)] = {"ok": False, "err": str(e)}
    return results


def full_pipeline(scanner: Path, data_dir: Path,
                  cached_keys: Optional[Path] = None,
                  output_root: Optional[Path] = None) -> dict:
    """一键完整流程，跨平台调度。返回结果摘要。

    Args:
        scanner: find_keys_macos 编译产物路径（macOS 走 C；Windows 不用）
        data_dir: VCHAT_DATA_DIR 根（产物落到 data_dir/decrypted/）
        cached_keys: keys.json 缓存（若存在则复用，跳过内存扫描）
    """
    storage = find_db_storage()
    if not storage:
        raise RuntimeError(
            "找不到微信数据目录。请先登录微信桌面版至少一次。\n"
            f"  macOS:   {WX_CONTAINER_MACOS}\n"
            f"  Windows: %USERPROFILE%\\Documents\\WeChat Files\\<wxid>\\db_storage"
        )
    dbs = enumerate_dbs(storage)
    if output_root is not None:
        from .snapshot import fingerprint, MAX_FILES
        if len(dbs) > MAX_FILES:
            raise RuntimeError('snapshot source database bound exceeded')
        source_fingerprints = {str(db.relative_to(storage)): fingerprint(db) for db in dbs}
    else:
        source_fingerprints = None
    print(f"▶ 找到 {len(dbs)} 个加密 db @ {storage.parent.name}", file=sys.stderr)

    # 复用旧 key
    key_map: Dict[str, str] = {}
    if cached_keys and cached_keys.exists():
        try:
            cached = json.loads(cached_keys.read_text())
            print(f"▶ 复用上次 keys（{len(cached)} 个）", file=sys.stderr)
            for db in dbs:
                rel = str(db.relative_to(storage))
                k = cached.get(rel)
                if k and crypto.quick_verify_key(db, k):
                    key_map[str(db)] = k
        except Exception as e:
            print(f"⚠ 旧 keys 读不出，重新扫: {e}", file=sys.stderr)

    if len(key_map) < len(dbs):
        pids = find_wechat_pids()
        if not pids:
            raise RuntimeError("微信主进程没在运行（启动并登录微信后再试）")
        print(f"▶ 内存扫描 `x'<key><salt>'` 模式（{len(pids)} 个微信进程）…", file=sys.stderr)

        sys_name = platform.system()
        if sys_name == "Darwin":
            rel_to_key: Dict[str, str] = {}
            scan_errors = []
            for pid in pids:
                try:
                    found = run_key_scanner(scanner, pid)
                    rel_to_key.update(found)
                except (RuntimeError, PermissionError) as e:
                    scan_errors.append(f"pid={pid}: {e}")
            if not rel_to_key and scan_errors:
                if key_map:
                    print(f"⚠ 内存扫描不可用（{'；'.join(scan_errors)}）；"
                          f"缓存密钥已覆盖 {len(key_map)}/{len(dbs)} 个库，跳过扫描继续解密\n"
                          f"  新增库的密钥可跑 `vchat key` 捕获后重跑解密", file=sys.stderr)
                else:
                    raise RuntimeError("；".join(scan_errors)
                                       + "；新增库可跑 `vchat key` 捕获密钥")
        elif sys_name == "Windows":
            from . import find_keys_windows
            rel_to_key = find_keys_windows.find_keys(pid=pids[0], storage_root=storage)
        else:
            raise RuntimeError(f"暂不支持 {sys_name}（仅 macOS / Windows）")

        print(f"  按 salt 匹配 {len(rel_to_key)} 个 db", file=sys.stderr)

        for db in dbs:
            if str(db) in key_map:
                continue
            rel = str(db.relative_to(storage)).replace("\\", "/")
            k = rel_to_key.get(rel) or rel_to_key.get(str(db.relative_to(storage)))
            if k and crypto.quick_verify_key(db, k):
                key_map[str(db)] = k

    matched = len(key_map)
    print(f"▶ 匹配 {matched}/{len(dbs)} 个 db", file=sys.stderr)

    # 保存 keys（按 rel path）
    rel_keys = {}
    for db_str, k in key_map.items():
        rel = str(Path(db_str).relative_to(storage))
        rel_keys[rel] = k

    if cached_keys:
        cached_keys.parent.mkdir(parents=True, exist_ok=True)
        cached_keys.write_text(json.dumps(rel_keys, indent=2))

    # 解密所有
    actual_output = output_root if output_root is not None else data_dir / 'decrypted'
    print(f"▶ 解密 → {actual_output}", file=sys.stderr)
    results = decrypt_all(storage, key_map, actual_output)
    ok = sum(1 for v in results.values() if v.get("ok"))
    fail = matched - ok

    return {
        "data_dir": str(data_dir),
        "db_storage": str(storage),
        "dbs_total": len(dbs),
        "dbs_matched": matched,
        "dbs_decrypted_ok": ok,
        "dbs_failed": fail,
        "missing_keys": [str(Path(d).relative_to(storage)) for d in dbs if str(d) not in key_map],
        "results": results,
        "source_fingerprints": source_fingerprints,
    }

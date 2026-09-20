"""vchat_core.find_keys_windows · Windows 微信进程内存扫描（纯 Python + ctypes）

跟 vchat_native/find_keys_macos.c 完全对称：
  - 找 WeChat.exe 主进程 pid
  - OpenProcess(PROCESS_VM_READ | PROCESS_QUERY_INFORMATION)
  - VirtualQueryEx 遍历 readable region
  - ReadProcessMemory 读 region 内容
  - 扫 ASCII 模式 `x'<64hex_key><32hex_salt>'`
  - 按 salt fingerprint 匹配本地 db
  - 输出 {db_rel: key_hex} 字典

参考：Microsoft Win32 文档（OpenProcess / VirtualQueryEx / ReadProcessMemory）。
完全用 stdlib ctypes，不引入任何外部包（避免 Windows 用户装 pywin32 / pyMeow 等额外依赖）。
"""

import ctypes
import ctypes.wintypes as wt
import hashlib
import os
import struct
from pathlib import Path
from typing import Dict, List, Optional, Tuple


# Win32 常量
PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_VM_READ           = 0x0010
TH32CS_SNAPPROCESS        = 0x00000002

MEM_COMMIT  = 0x1000
PAGE_READWRITE          = 0x04
PAGE_EXECUTE_READWRITE  = 0x40
PAGE_READONLY           = 0x02
PAGE_GUARD              = 0x100
PAGE_NOACCESS           = 0x01

KEY_HEX = 64
SALT_HEX = 32
PATTERN_LEN = 2 + KEY_HEX + SALT_HEX + 1  # x' + 96 hex + '

# 微信 4.x 主进程名从 WeChat.exe 变成 Weixin.exe（4.0 起），两个都认。
WECHAT_EXE_NAMES = ("weixin.exe", "wechat.exe")


# ── ctypes 结构 ──────────────────────────────────────
class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wt.DWORD),
        ("cntUsage", wt.DWORD),
        ("th32ProcessID", wt.DWORD),
        ("th32DefaultHeapID", ctypes.c_void_p),
        ("th32ModuleID", wt.DWORD),
        ("cntThreads", wt.DWORD),
        ("th32ParentProcessID", wt.DWORD),
        ("pcPriClassBase", wt.LONG),
        ("dwFlags", wt.DWORD),
        ("szExeFile", wt.WCHAR * 260),
    ]


class MEMORY_BASIC_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BaseAddress",       ctypes.c_void_p),
        ("AllocationBase",    ctypes.c_void_p),
        ("AllocationProtect", wt.DWORD),
        ("PartitionId",       wt.WORD),
        ("RegionSize",        ctypes.c_size_t),
        ("State",             wt.DWORD),
        ("Protect",           wt.DWORD),
        ("Type",              wt.DWORD),
    ]


def _is_windows() -> bool:
    return os.name == "nt"


def _kernel32():
    return ctypes.WinDLL("kernel32", use_last_error=True)


class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
    _fields_ = [
        ("cb", wt.DWORD), ("PageFaultCount", wt.DWORD),
        ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t),
    ]


def _working_set(pid: int) -> int:
    """进程工作集字节数，用来在多开的同名微信进程里挑主进程。失败返回 0。"""
    k = _kernel32()
    h = k.OpenProcess(PROCESS_QUERY_INFORMATION, False, pid)
    if not h:
        return 0
    try:
        counters = PROCESS_MEMORY_COUNTERS()
        counters.cb = ctypes.sizeof(counters)
        # GetProcessMemoryInfo 在 psapi.dll（kernel32 里只有 K32GetProcessMemoryInfo）
        for dll, fn in (("psapi", "GetProcessMemoryInfo"), ("kernel32", "K32GetProcessMemoryInfo")):
            try:
                query = getattr(ctypes.WinDLL(dll), fn)
            except (OSError, AttributeError):
                continue
            query.argtypes = [wt.HANDLE, ctypes.POINTER(PROCESS_MEMORY_COUNTERS), wt.DWORD]
            query.restype = wt.BOOL
            if query(h, ctypes.byref(counters), counters.cb):
                return int(counters.WorkingSetSize)
            return 0
        return 0
    finally:
        k.CloseHandle(h)



def find_wechat_pids() -> List[int]:
    """所有候选主进程 pid（Weixin.exe / WeChat.exe），按工作集从大到小排序。

    微信 4.x 会同时起多个同名进程（渲染 / 工具进程），主进程工作集最大，
    密钥也只在主进程里；排序后第一个即主进程。
    """
    if not _is_windows():
        return []
    k = _kernel32()
    snap = k.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snap == -1:
        return []
    found: List[Tuple[int, int]] = []
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        if not k.Process32FirstW(snap, ctypes.byref(entry)):
            return []
        while True:
            if entry.szExeFile.lower() in WECHAT_EXE_NAMES:
                found.append((_working_set(entry.th32ProcessID), entry.th32ProcessID))
            if not k.Process32NextW(snap, ctypes.byref(entry)):
                break
    finally:
        k.CloseHandle(snap)
    found.sort(reverse=True)
    return [pid for _, pid in found]


def find_wechat_pid() -> Optional[int]:
    """主进程 pid（工作集最大的 Weixin.exe / WeChat.exe）。"""
    pids = find_wechat_pids()
    return pids[0] if pids else None



def _open_process(pid: int):
    k = _kernel32()
    h = k.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid)
    if not h:
        raise OSError(f"OpenProcess({pid}) 失败：{ctypes.get_last_error()}")
    return h


def _readable_region(prot: int) -> bool:
    if prot & PAGE_GUARD or prot & PAGE_NOACCESS:
        return False
    return bool(prot & (PAGE_READWRITE | PAGE_EXECUTE_READWRITE))


def _enumerate_regions(handle):
    k = _kernel32()
    addr = ctypes.c_void_p(0)
    mbi = MEMORY_BASIC_INFORMATION()
    sz = ctypes.sizeof(mbi)
    while True:
        ret = k.VirtualQueryEx(handle, addr, ctypes.byref(mbi), sz)
        if ret == 0:
            break
        if (mbi.State == MEM_COMMIT and _readable_region(mbi.Protect)
                and mbi.RegionSize > 0 and mbi.RegionSize < 256 * 1024 * 1024):
            yield (mbi.BaseAddress, mbi.RegionSize)
        next_addr = (mbi.BaseAddress or 0) + mbi.RegionSize
        if next_addr <= (addr.value or 0):
            break
        addr = ctypes.c_void_p(next_addr)


def _read_region(handle, base, size) -> Optional[bytes]:
    k = _kernel32()
    buf = (ctypes.c_ubyte * size)()
    read = ctypes.c_size_t(0)
    ok = k.ReadProcessMemory(handle, ctypes.c_void_p(base), buf,
                             size, ctypes.byref(read))
    if not ok or read.value == 0:
        return None
    return bytes(buf[:read.value])


_HEX = b"0123456789abcdefABCDEF"


def _scan_buffer(buf: bytes) -> List[Tuple[str, str]]:
    """扫 x'<64hex><32hex>' 模式。返回 [(key_hex, salt_hex), ...]"""
    out = []
    n = len(buf)
    i = 0
    while i + PATTERN_LEN <= n:
        if buf[i] != ord("x") or buf[i + 1] != ord("'"):
            i += 1
            continue
        if buf[i + 2 + KEY_HEX + SALT_HEX] != ord("'"):
            i += 1
            continue
        # 验证 96 hex
        ok = True
        for j in range(KEY_HEX + SALT_HEX):
            if buf[i + 2 + j] not in _HEX:
                ok = False
                break
        if ok:
            key_hex = buf[i + 2 : i + 2 + KEY_HEX].decode("ascii").lower()
            salt_hex = buf[i + 2 + KEY_HEX : i + 2 + KEY_HEX + SALT_HEX].decode("ascii").lower()
            out.append((key_hex, salt_hex))
            i += PATTERN_LEN
        else:
            i += 1
    return out


def collect_db_salts(storage_root: Path) -> Dict[str, str]:
    """扫数据目录里所有 .db，提前 16 字节做 salt 指纹。返回 {rel_path: salt_hex}。"""
    salts: Dict[str, str] = {}
    for db in storage_root.rglob("*.db"):
        try:
            with open(db, "rb") as f:
                head = f.read(16)
        except OSError:
            continue
        if len(head) < 16 or head.startswith(b"SQLite format 3"):
            continue  # 明文 db 或无效
        rel = str(db.relative_to(storage_root)).replace("\\", "/")
        salts[rel] = head.hex().lower()
    return salts


def find_db_storage_windows() -> Optional[Path]:
    """Windows 上微信数据通常在 %USERPROFILE%/Documents/xwechat_files/<wxid>/db_storage/
    （微信 4.x；3.x 是 Documents/WeChat Files/<wxid>/db_storage/）。

    多账号并存时（本机就有 hulaquan8_bd40 和 wxid_..._04c0 两个），选 db 最新写入的那个，
    跟 macOS 分支一致，避免解到半年前不用的老账号。
    """
    if not _is_windows():
        return None
    candidates = [
        Path.home() / "Documents" / "WeChat Files",
        Path.home() / "Documents" / "xwechat_files",
    ]
    found = []
    for base in candidates:
        if not base.exists():
            continue
        for child in base.iterdir():
            if not child.is_dir() or child.name.lower() in ("all users", "all_users", "applet"):
                continue
            ds = child / "db_storage"
            if ds.is_dir():
                newest = max((p.stat().st_mtime for p in ds.rglob("*.db")), default=0)
                found.append((newest, ds))
    if not found:
        return None
    found.sort(key=lambda item: item[0], reverse=True)
    return found[0][1]


def find_keys(pid: Optional[int] = None,
              storage_root: Optional[Path] = None) -> Dict[str, str]:
    """主入口：扫内存 + 匹配 salt → 返回 {db_rel_path: key_hex}"""
    if not _is_windows():
        raise OSError("find_keys_windows 仅支持 Windows")

    if pid is None:
        pid = find_wechat_pid()
    if not pid:
        raise RuntimeError("没找到 WeChat.exe 主进程")

    if storage_root is None:
        storage_root = find_db_storage_windows()
    if storage_root is None or not storage_root.exists():
        raise RuntimeError("没找到微信数据目录（%USERPROFILE%/Documents/WeChat Files）")

    salts = collect_db_salts(storage_root)
    if not salts:
        raise RuntimeError(f"{storage_root} 下没找到加密 db")

    # salt → db_rel 反查
    salt_to_db = {v: k for k, v in salts.items()}

    handle = _open_process(pid)
    try:
        found: Dict[str, str] = {}
        seen = set()
        scanned_mb = 0
        regions = 0
        for base, size in _enumerate_regions(handle):
            buf = _read_region(handle, base, size)
            if not buf:
                continue
            regions += 1
            scanned_mb += size / (1024 * 1024)
            for k_hex, s_hex in _scan_buffer(buf):
                if (k_hex, s_hex) in seen:
                    continue
                seen.add((k_hex, s_hex))
                db = salt_to_db.get(s_hex)
                if db and db not in found:
                    found[db] = k_hex
            if len(found) == len(salts):
                break  # 全找齐了
        return found
    finally:
        _kernel32().CloseHandle(handle)

"""vchat_core.cache · sqlite 连接缓存

按 mtime 检测是否需要重连，支持只读 URI 模式 + per-key 锁。
"""

import sqlite3
import threading
from pathlib import Path
from typing import Optional

from . import get_decrypted_dir


class DBCache:
    """基于 mtime 的 sqlite 连接缓存。

    用法:
        cache = DBCache()
        conn = cache.get("contact/contact.db")
        conn.execute("SELECT ...").fetchall()

    线程安全：每个 db 路径有独立的 lock，防止并发解密同一 db。
    """

    def __init__(self, root: Optional[Path] = None):
        self._root: Path = root or get_decrypted_dir()
        self._conns: dict[str, sqlite3.Connection] = {}
        self._mtimes: dict[str, float] = {}
        self._global_lock = threading.Lock()
        self._per_key_locks: dict[str, threading.Lock] = {}

    def _lock_for(self, rel_path: str) -> threading.Lock:
        with self._global_lock:
            if rel_path not in self._per_key_locks:
                self._per_key_locks[rel_path] = threading.Lock()
            return self._per_key_locks[rel_path]

    def get(self, rel_path: str) -> sqlite3.Connection:
        """取一个 sqlite 连接。rel_path 形如 'message/message_0.db'。"""
        full = self._root / rel_path
        if not full.exists():
            raise FileNotFoundError(f"解密 db 不存在: {full}")

        with self._lock_for(rel_path):
            cur_mtime = full.stat().st_mtime
            if (rel_path in self._conns
                    and self._mtimes.get(rel_path) == cur_mtime):
                return self._conns[rel_path]

            # 关旧连接（如果有）
            if rel_path in self._conns:
                try:
                    self._conns[rel_path].close()
                except Exception:
                    pass

            # 只读模式打开
            # 解密产物是独立快照，不包含源数据库的 WAL/SHM。
            uri = full.resolve().as_uri() + "?mode=ro&immutable=1"
            conn = sqlite3.connect(uri, uri=True, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            self._conns[rel_path] = conn
            self._mtimes[rel_path] = cur_mtime
            return conn

    def close_all(self):
        with self._global_lock:
            for c in self._conns.values():
                try:
                    c.close()
                except Exception:
                    pass
            self._conns.clear()
            self._mtimes.clear()


# 模块级单例（兼容旧代码风格）
_default_cache: Optional[DBCache] = None


def default_cache() -> DBCache:
    global _default_cache
    if _default_cache is None:
        _default_cache = DBCache()
    return _default_cache


def get(rel_path: str) -> sqlite3.Connection:
    """快捷接口：用默认 cache 取连接。"""
    return default_cache().get(rel_path)

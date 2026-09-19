"""vchat_core · 已解密微信 db 的查询库

零外部依赖（仅 Python stdlib），独立实现 vchat CLI 所有数据访问能力。
"""

import os
from pathlib import Path


__version__ = "2.0.0"
__version_info__ = (2, 0, 0)


def get_data_dir() -> Path:
    """解析数据根目录（含 `decrypted/` 子目录的那一层）。

    优先级：
        1. `VCHAT_DATA_DIR` 环境变量
        2. `WECHAT_DECRYPT_PATH` 环境变量（旧变量名，向后兼容）
        3. `~/.vchat/data`
        4. `~/Projects/wechat-decrypt`（更早期的默认值，向后兼容）
    """
    for env in ("VCHAT_DATA_DIR", "WECHAT_DECRYPT_PATH"):
        v = os.environ.get(env)
        if v:
            return Path(os.path.expanduser(v))

    for default in (Path.home() / ".vchat/data",
                    Path.home() / "Projects/wechat-decrypt"):
        if (default / "decrypted").exists():
            return default

    # 都不存在，返回新默认值（让上层报"目录不存在"）
    return Path.home() / ".vchat/data"


def get_decrypted_dir() -> Path:
    """`<data_dir>/decrypted/` ——所有 sqlite db 实际存放路径。"""
    data = get_data_dir()
    from .snapshot import active
    value = active(data)
    if value is not None:
        # Invalid/missing mounted snapshots raise. Never silently mix accounts
        # by falling back to the old unbound decrypted directory.
        return Path(value['snapshot_root']) / value['output_relative']
    return data / "decrypted"


__all__ = ["get_data_dir", "get_decrypted_dir"]

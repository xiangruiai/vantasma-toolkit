"""vchat_core.exitcodes · BSD sysexits.h 语义化退出码。

工业级 CLI 应该用 sysexits 标准让脚本能精确判断错误类型。
"""

EX_OK           = 0   # 成功
EX_USAGE        = 64  # 命令行用法错误
EX_DATAERR      = 65  # 用户输入的数据格式错（如非法日期）
EX_NOINPUT      = 66  # 输入文件/数据不存在（如数据目录未解密）
EX_NOUSER       = 67  # 找不到指定的用户/联系人
EX_UNAVAILABLE  = 69  # 依赖的服务/资源不可用（如 WeChat 没在运行）
EX_SOFTWARE     = 70  # 内部软件错误
EX_OSERR        = 71  # 操作系统错误
EX_OSFILE       = 72  # 关键系统文件不存在（如 contact.db 缺失）
EX_CANTCREAT    = 73  # 无法创建输出文件
EX_IOERR        = 74  # I/O 错
EX_TEMPFAIL     = 75  # 临时失败，可重试
EX_NOPERM       = 77  # 权限不够（如未 sudo）
EX_CONFIG       = 78  # 配置错误

__all__ = [n for n in globals() if n.startswith("EX_")]

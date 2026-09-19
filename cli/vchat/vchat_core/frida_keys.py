"""frida spawn + CCKeyDerivationPBKDF hook：恢复微信 4.1.8x 新增库的解密密钥。

背景：微信 4.1.8 起（chatlog FAQ #197），SQLCipher 密钥不再常驻进程内存，
按旧模式扫描 `x'<key><salt>'` 全部落空。但微信每次打开加密库时仍会调用
系统 CommonCrypto 的 CCKeyDerivationPBKDF（kCCPBKDF2 + kCCPRFHmacAlgSHA512、
256000 轮）做密钥派生，调用参数携带主密钥与目标库 salt。

方法（参考 igaojin.me/2026/04/18 公开逆向笔记）：
  1. frida.spawn 重启微信（attach 会错过启动期派生）；
  2. hook CCKeyDerivationPBKDF，过滤 algo=kCCPBKDF2 且 rounds>1000 的调用，
     捕获 (password, salt, rounds, prf)；
  3. 离线按相同参数 PBKDF2 派生各库密钥，按 db 文件头 salt 配对，
     用首页 HMAC 验证后回写 keys.json。

仅读取本机微信进程的派生参数，用于恢复本机数据库的本地解密能力。
"""
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, Optional

# CommonCrypto pseudo-random algorithm 常量 → hashlib 名称
PRF_NAMES = {3: 'sha256', 5: 'sha512'}
WECHAT_BIN = '/Applications/WeChat.app/Contents/MacOS/WeChat'
FRIDAENV_PYTHON = os.path.expanduser('~/.vchat/fridaenv/bin/python')

HOOK_JS = r"""
function toHex(ptr, len) {
    try {
        var arr = new Uint8Array(ptr.readByteArray(len));
        return Array.from(arr).map(b => b.toString(16).padStart(2, '0')).join('');
    } catch(e) { return null; }
}
var pbkdf2 = typeof Module.getGlobalExportByName === "function"
    ? Module.getGlobalExportByName("CCKeyDerivationPBKDF")
    : Module.getExportByName(null, "CCKeyDerivationPBKDF");
if (pbkdf2) {
    Interceptor.attach(pbkdf2, {
        onEnter: function(args) {
            var algo = args[0].toInt32();
            var rounds = args[6].toInt32();
            if (algo !== 2 || rounds <= 1000) return;
            var pwd = toHex(args[1], args[2].toInt32());
            var salt = toHex(args[3], args[4].toInt32());
            if (pwd && salt) send({type:"key", pwd:pwd, salt:salt,
                                   rounds:rounds, prf:args[5].toInt32(),
                                   len:args[2].toInt32()});
        }
    });
    send("[+] CCKeyDerivationPBKDF hooked @ " + pbkdf2);
} else { send("[-] CCKeyDerivationPBKDF not found"); }
"""


def _pbkdf2(prf: int, password: bytes, salt: bytes, rounds: int, dklen: int = 32) -> bytes:
    name = PRF_NAMES.get(prf, 'sha512')
    return hashlib.pbkdf2_hmac(name, password, salt, rounds, dklen=dklen)


def _frida_or_reexec() -> Optional[object]:
    """返回 frida 模块；本环境没有时若存在 fridaenv 则原地重_exec。"""
    local_python = Path(__file__).resolve().parents[2] / 'vchat-fridaenv/bin/python'
    if local_python.exists() and Path(sys.prefix) != local_python.parent.parent:
        os.execv(str(local_python), [str(local_python), os.path.abspath(sys.argv[0]), *sys.argv[1:]])
    try:
        import frida  # noqa: F401
        return frida
    except ImportError:
        pass
    if os.path.exists(FRIDAENV_PYTHON):
        print(f"▶ 本环境无 frida，改用 {FRIDAENV_PYTHON} 重跑 `vchat key`…", file=sys.stderr)
        os.execv(FRIDAENV_PYTHON, [FRIDAENV_PYTHON, os.path.abspath(sys.argv[0]),
                                   sys.argv[1], *sys.argv[2:]])
    print("❌ 未安装 frida。安装：python3 -m pip install --user frida frida-tools", file=sys.stderr)
    return None


def run_key_capture(data_dir: Path, cached_keys: Path,
                    duration: int = 600, assume_yes: bool = False,
                    verbose: bool = True) -> Dict[str, str]:
    """spawn 微信捕获 PBKDF2 派生，恢复无密钥库；返回新恢复的 {rel_path: key_hex}。

    Args:
        data_dir: vchat 数据根（解密产物与 keys.json 所在）
        cached_keys: keys.json 路径
        duration: 等待用户登录/开库的最长秒数
        assume_yes: 跳过"将重启微信"的交互确认
        verbose: 打印进度
    """
    # 延迟导入：避免无 frida 环境下 import 本模块即失败
    from . import decrypt_pipeline as dp
    from . import crypto

    def log(msg):
        if verbose:
            print(msg, file=sys.stderr)

    if sys.platform != 'darwin':
        raise RuntimeError('vchat key 目前仅支持 macOS')
    if not assume_yes:
        ans = input('将关闭并重启微信（需重新登录）以捕获新库密钥，继续? [y/N] ')
        if ans.strip().lower() not in ('y', 'yes'):
            print('已取消'); return {}

    frida = _frida_or_reexec()
    if frida is None:
        raise RuntimeError('frida 不可用')

    storage = dp.find_db_storage()
    if not storage:
        raise RuntimeError('找不到微信数据目录，请先登录微信桌面版')
    dbs = dp.enumerate_dbs(storage)

    # 目标库：缓存密钥缺失或验证失败的
    key_map: Dict[str, str] = {}
    if cached_keys.exists():
        cached = json.loads(cached_keys.read_text())
        for db in dbs:
            rel = str(db.relative_to(storage))
            k = cached.get(rel)
            if k and crypto.quick_verify_key(db, k):
                key_map[str(db)] = k
    targets = {}  # salt_bytes -> rel
    for db in dbs:
        if str(db) in key_map:
            continue
        with open(db, 'rb') as f:
            salt = f.read(16)
        if len(salt) == 16:
            targets[salt] = str(db.relative_to(storage))
    if not targets:
        log(f'▶ 全部 {len(dbs)} 个库已有有效密钥，无需捕获')
        return {}

    log(f'▶ {len(targets)} 个库缺有效密钥：' + '、'.join(sorted(targets.values())))

    # 关闭旧实例，spawn 捕获
    subprocess.run(['pkill', '-x', 'WeChat'], capture_output=True)
    time.sleep(3)
    captured = []
    wechat_pid = frida.spawn(WECHAT_BIN)
    session = frida.attach(wechat_pid)
    script = session.create_script(HOOK_JS)
    script.on('message', lambda m, d: captured.append(m['payload'])
              if m.get('type') == 'send' and isinstance(m.get('payload'), dict)
              and m['payload'].get('type') == 'key' else None)
    script.load()
    frida.resume(wechat_pid)
    log(f'▶ 已启动微信 pid={wechat_pid}，请登录；捕获窗口 {duration}s …')

    recovered: Dict[str, str] = {}
    deadline = time.time() + duration
    while time.time() < deadline and len(recovered) < len(targets):
        time.sleep(2)
        while captured:
            call = captured.pop(0)
            try:
                pwd = bytes.fromhex(call['pwd'])
                salt = bytes.fromhex(call['salt'])
            except Exception:
                continue
            rel = targets.get(salt)
            if not rel:
                continue  # 与缺密钥库无关的派生
            dk = _pbkdf2(call.get('prf', 5), pwd, salt, call['rounds']).hex()
            db = storage / rel
            if crypto.quick_verify_key(db, dk):
                key_map[str(db)] = dk
                recovered[rel] = dk
                log(f'  ✓ {rel} 密钥已恢复')
    try:
        session.detach()
    except Exception:
        pass

    # 合并回 keys.json
    cached = json.loads(cached_keys.read_text()) if cached_keys.exists() else {}
    cached.update(recovered)
    cached_keys.write_text(json.dumps(cached, indent=1))
    log(f'▶ 恢复 {len(recovered)}/{len(targets)} 个库，keys.json 已更新')
    return recovered

#!/usr/bin/env python3
"""Windows 微信 4.x 就地取密钥：frida 挂钩 AES 密钥编排，写 keys.json 给 `vchat decrypt` 用。

为什么需要它
------------
微信 ≤ 4.1.7（Windows）会在进程内存里缓存 SQLCipher 原始密钥，格式
`x'<64hex_enc_key><32hex_salt>'`，`vchat_core.find_keys_windows` 扫内存就能拿到。
**4.1.8 起这个缓存没了**：微信用 AES-NI，密钥编排（key schedule）时密钥只存在于
CPU 寄存器/xmm，明文不落内存。实测（4.1.15.11，Windows 11）：
  · 34 个进程 / 13.4 GB 可读内存，ASCII+UTF-16 的 x'…' 与裸 hex 串：0 命中
  · 主进程 1.33 GB 逐字节 32 字节滑窗（读取覆盖率 100%，判据先自测通过）：0 命中
  · bcrypt.dll 的 PBKDF2 / 对称密钥导入挂钩：0 次调用（说明加密实现是静态链接进 Weixin.dll 的）

所以改成「在密钥诞生的那一刻取」：Weixin.dll 里 aeskeygenassist / aesimc 指令点就是
AES-256 的密钥编排，挂钩它们，命中时把寄存器/栈/指针内存 dump 下来，逐 32 字节窗口
当候选密钥，用 SQLCipher page-1 的 HMAC 判据验真。每个库一把独立密钥，需逐库抓。

用法
----
    pip install frida pycryptodome
    # 不重启微信（推荐；靠用户正常使用把各库打开）：
    python tools/win_key_capture.py --mode attach_all --seconds 1800
    # 重启式全量（登录瞬间所有库都会开一遍，一次拿齐）：
    python tools/win_key_capture.py --mode spawn --seconds 900
    vchat decrypt

只读进程内存、只挂钩自己的进程，不修改微信数据、不上传任何内容。
"""
from __future__ import annotations

import argparse
import json
import struct
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))   # 让 tools/ 能 import vchat_core

from vchat_core import crypto, get_data_dir                     # noqa: E402
from vchat_core import find_keys_windows as fkw                 # noqa: E402

PAGE = 4096
# SQLite 头偏移 16..19 = 页大小(2B) + 写版本 + 读版本；微信用 WAL 模式 → 02，02
PLAIN_PREFIXES = (b"\x10\x00\x02\x02", b"\x10\x00\x01\x01")
WEIXIN_EXE_CANDIDATES = (r"C:\Program Files\Tencent\Weixin\Weixin.exe",)


def find_weixin_dll() -> Path:
    base = Path(r"C:\Program Files\Tencent\Weixin")
    cands = sorted(base.glob(r"*\Weixin.dll"))
    if not cands:
        raise SystemExit("找不到 Weixin.dll；微信装在别处时用 --dll 指定")
    return sorted(cands, key=lambda p: p.stat().st_mtime)[-1]


def scan_key_schedule_sites(dll: Path) -> list[int]:
    """扫 .text 找 aeskeygenassist(66 0F 3A DF) / aesimc(66 0F 38 DB) 指令点。"""
    data = dll.read_bytes()
    e = struct.unpack_from("<I", data, 0x3C)[0]
    coff = e + 4
    nsec = struct.unpack_from("<H", data, coff + 2)[0]
    sizeopt = struct.unpack_from("<H", data, coff + 16)[0]
    sec_off = coff + 20 + sizeopt
    text = None
    for i in range(nsec):
        s = sec_off + i * 40
        nm = data[s:s + 8].rstrip(b"\0").decode(errors="ignore")
        vsize, vaddr, rawsize, rawptr = struct.unpack_from("<IIII", data, s + 8)
        if nm == ".text":
            text = (vaddr, rawsize, rawptr)
    if not text:
        raise SystemExit("该 PE 没有 .text 段")
    tvaddr, trawsize, trawptr = text
    body = data[trawptr:trawptr + trawsize]
    sites: list[int] = []
    for pat in (b"\x66\x0f\x3a\xdf", b"\x66\x0f\x38\xdb"):
        i = body.find(pat)
        while i >= 0:
            sites.append(tvaddr + i)
            i = body.find(pat, i + 1)
    return sorted(set(sites))


HOOK_JS = r"""
var SITES = [%s], MAX_HITS = %d, SALTS = [%s];
var sent = 0, seen = {}, allHits = 0;

function matchedSalts(hex) {
    var out = [];
    for (var i = 0; i < SALTS.length; i++) { if (hex.indexOf(SALTS[i]) >= 0) out.push(i); }
    return out;
}
function looksLikePtr(p) {
    try { return !p.isNull() && p.compare(ptr('0x10000')) > 0 && p.compare(ptr('0x7fffffffffff')) < 0; }
    catch (e) { return false; }
}
function hexOf(p, n) {
    try {
        if (p.isNull()) return null;
        var a = new Uint8Array(p.readByteArray(n)), s = '';
        for (var i = 0; i < a.length; i++) s += ('0' + a[i].toString(16)).slice(-2);
        return s;
    } catch (e) { return null; }
}

function snap(ctx, rva) {
    if (sent > MAX_HITS) return;
    var names = ['rax','rbx','rcx','rdx','rsi','rdi','r8','r9','r10','r11','r12','r13','r14','r15','rsp','rbp'];
    var regs = {}, i;
    for (i = 0; i < names.length; i++) {
        try { regs[names[i]] = ctx[names[i]].toString(); } catch (e) { regs[names[i]] = '0x0'; }
    }
    var xmms = [];
    for (i = 0; i < 16; i++) {
        var v = null;
        try { v = ctx['xmm' + i]; } catch (e) { v = null; }
        if (v) {
            var s = '';
            for (var j = 0; j < v.length; j++) s += ('0' + v[j].toString(16)).slice(-2);
            xmms.push(s);
        } else { xmms.push(null); }
    }
    var sig = xmms.join('') + regs.rcx + regs.rdx + regs.r8 + regs.rsp;
    if (seen[sig]) return;
    seen[sig] = 1;
    allHits++;
    if (allHits %% 500 === 0) send({type: 'probe_stat', all: allHits, db: sent});

    var ptrs = [];
    try {
        var sp = ctx.rsp;
        if (looksLikePtr(sp)) {
            var hs = hexOf(sp, 2048);
            if (hs) ptrs.push({p: sp, src: 'stack', hex: hs});
            for (var off = 0; off < 1024; off += 8) {
                try {
                    var q = sp.add(off).readPointer();
                    if (looksLikePtr(q)) ptrs.push({p: q, src: 'stack->' + off});
                } catch (e) {}
            }
        }
    } catch (e) {}
    for (i = 0; i < names.length; i++) {
        try {
            var p = ctx[names[i]];
            if (looksLikePtr(p)) ptrs.push({p: p, src: 'reg:' + names[i]});
        } catch (e) {}
    }
    // 廉价探测：现场里出现某个库的 salt 才说明这是数据库的 cipher 上下文
    var probe = [], matched = [];
    for (i = 0; i < ptrs.length && i < 64; i++) {
        var h = ptrs[i].hex ? ptrs[i].hex : hexOf(ptrs[i].p, 512);
        if (!h) continue;
        probe.push({p: ptrs[i].p, src: ptrs[i].src, hex: h});
        var m = matchedSalts(h);
        for (var k = 0; k < m.length; k++) if (matched.indexOf(m[k]) < 0) matched.push(m[k]);
    }
    if (!matched.length) return;      // 与库无关的密钥编排（消息/网络加密）——不烧预算
    sent++;

    var bufs = [];
    for (i = 0; i < probe.length; i++) {
        var h2 = probe[i].hex.length >= 4096 ? probe[i].hex : hexOf(probe[i].p, 2048);
        if (h2) bufs.push({src: probe[i].src, at: probe[i].p.toString(), hex: h2});
    }
    var cnt = 0;
    for (i = 0; i < probe.length && i < 12 && cnt < 16; i++) {
        for (var off = 0; off < 256 && cnt < 16; off += 8) {
            try {
                var q2 = probe[i].p.add(off).readPointer();
                if (looksLikePtr(q2)) {
                    var h3 = hexOf(q2, 2048);
                    if (h3) { bufs.push({src: probe[i].src + '->' + off, at: q2.toString(), hex: h3}); cnt++; }
                }
            } catch (e) {}
        }
    }
    send({type: 'hit', rva: rva, bufs: bufs, matched: matched});
}

function install(a, rva) { Interceptor.attach(a, { onEnter: function () { snap(this.context, rva); } }); }
var installed = 0, done = false;
function tryInstall() {
    if (done) return;
    var mod = null;
    try { mod = Process.findModuleByName('Weixin.dll'); } catch (e) { mod = null; }
    if (!mod) return;
    done = true;
    for (var i = 0; i < SITES.length; i++) {
        try { install(mod.base.add(SITES[i]), SITES[i]); installed++; }
        catch (e) { if (installed < 3) send({type: 'info', msg: 'site ' + SITES[i].toString(16) + ': ' + e}); }
    }
    send({type: 'ready', hooks: installed, base: mod.base.toString()});
}
tryInstall();
if (!done) {
    var waited = 0, t = setInterval(function () {
        waited += 100; tryInstall();
        if (done || waited >= 180000) clearInterval(t);
        if (!done && waited >= 180000) send({type: 'info', msg: 'Weixin.dll never appeared'});
    }, 100);
}
"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["attach_all", "attach", "spawn"], default="attach_all")
    ap.add_argument("--seconds", type=int, default=1800)
    ap.add_argument("--dll")
    ap.add_argument("--wechat-exe")
    ap.add_argument("--max-hits", type=int, default=300)
    ap.add_argument("--dump", default="win_key_hits.jsonl")
    args = ap.parse_args()

    try:
        import frida
        from Crypto.Cipher import AES
    except ImportError as e:
        raise SystemExit(f"缺少依赖：{e}；先跑 pip install frida pycryptodome")

    dll = Path(args.dll) if args.dll else find_weixin_dll()
    sites = scan_key_schedule_sites(dll)
    print(f"DLL: {dll}\nAES 密钥编排指令点: {len(sites)}", flush=True)

    try:
        storage = fkw.find_db_storage_windows()
    except Exception:
        storage = None
    if not storage:
        raise SystemExit("找不到 微信 db_storage（先登录一次微信桌面版）")
    print(f"db_storage: {storage}", flush=True)

    dbs, salts = [], []
    for db in sorted(storage.rglob("*.db")):
        with open(db, "rb") as f:
            p1 = f.read(PAGE)
        if len(p1) != PAGE or not any(p1):
            continue
        iv = p1[PAGE - 80:PAGE - 64]
        expects = tuple(bytes(a ^ b for a, b in zip(pref, iv[:4])) for pref in PLAIN_PREFIXES)
        dbs.append((str(db), p1[16:32], expects))
        salts.append(p1[:16].hex())
    if not dbs:
        raise SystemExit(f"{storage} 下没找到可解密的 db")
    print(f"库: {len(dbs)} 个", flush=True)

    keys_path = get_data_dir() / "keys.json"
    found: dict[str, str] = {}
    if keys_path.exists():
        try:
            found = json.loads(keys_path.read_text(encoding="utf-8"))
        except Exception:
            found = {}

    def save() -> None:
        keys_path.parent.mkdir(parents=True, exist_ok=True)
        keys_path.write_text(json.dumps(found, indent=1, ensure_ascii=False))

    # 预算只给「还没拿到 key」的库：已入库的库会不停重做密钥编排，会把命中上限吃光
    missing = [i for i, d in enumerate(dbs) if str(Path(d[0]).relative_to(storage)) not in found]
    filter_salts = [salts[i] for i in missing] or salts
    print(f"待补库 {len(missing)}/{len(dbs)}", flush=True)

    ct_all = b"".join(d[1] for d in dbs)
    dump_fh = Path(args.dump).open("a", encoding="utf-8")
    counter = [0]
    lock = threading.Lock()

    def on_message(msg, data):
        if msg.get("type") != "send":
            return
        p = msg["payload"]
        kind = p.get("type")
        if kind == "ready":
            print(f"✓ hooks installed: {p}", flush=True)
            return
        if kind == "info":
            print(f"  ! {p['msg']}", flush=True)
            return
        if kind == "probe_stat":
            print(f"  … 已捕获 {p['all']} 次密钥编排现场，其中库相关 {p['db']} 次", flush=True)
            return
        if kind != "hit":
            return
        with lock:
            counter[0] += 1
            n = counter[0]
        dump_fh.write(json.dumps({"n": n, **p}) + "\n")
        dump_fh.flush()

        cands = set()
        xs = [x for x in p["xmms"] if x]
        for a in xs:
            for b in xs:
                cands.add(a + b)
        for buf in p["bufs"]:
            h = buf["hex"]
            for i in range(0, max(0, len(h) - 64) + 1, 2):
                cands.add(h[i:i + 64])
        survivors = []
        for cand in cands:
            try:
                key = bytes.fromhex(cand)
            except ValueError:
                continue
            out = AES.new(key, AES.MODE_ECB).decrypt(ct_all)
            for i, d in enumerate(dbs):
                if out[i * 16:i * 16 + 4] in d[2]:
                    survivors.append((cand, d[0]))
                    break
        added = 0
        for cand, db in survivors:
            if crypto.quick_verify_key(Path(db), cand):
                rel = str(Path(db).relative_to(storage))
                found[rel] = cand
                save()
                added += 1
                print(f"  ✓✓ VERIFIED {rel}  key={cand}   (累计 {len(found)}/{len(dbs)})", flush=True)
        print(f"  · 现场#{n} rva={hex(p['rva'])} "
              f"matched={[Path(dbs[i][0]).name for i in p.get('matched', [])]} "
              f"候选={len(cands)} 初筛={len(survivors)} 验真={added}", flush=True)

    device = frida.get_local_device()
    if args.mode == "spawn":
        exe = args.wechat_exe or WEIXIN_EXE_CANDIDATES[0]
        pid = device.spawn([exe])
        session = device.attach(pid)
        script = session.create_script(HOOK_JS % (", ".join(hex(s) for s in sites), args.max_hits,
                                                  ", ".join("'%s'" % s for s in filter_salts)))
        script.on("message", on_message)
        script.load()
        device.resume(pid)
        print(f"spawned pid={pid} — 请在微信里完成登录（登录会触发所有库的密钥编排）", flush=True)
    else:
        pids = fkw.find_wechat_pids() if args.mode == "attach_all" else [fkw.find_wechat_pid()]
        pids = [p for p in pids if p]
        if not pids:
            raise SystemExit("微信没在跑")
        print(f"attach 到 Weixin.exe: {pids}", flush=True)
        for pid in pids:
            try:
                session = device.attach(pid)
                script = session.create_script(HOOK_JS % (", ".join(hex(s) for s in sites),
                                                          args.max_hits,
                                                          ", ".join("'%s'" % s for s in filter_salts)))
                script.on("message", on_message)
                script.load()
                print(f"✓ attach pid={pid}", flush=True)
            except Exception as e:
                print(f"attach pid={pid} 失败: {e}", flush=True)

    print(f"采集 {args.seconds}s …（每验出一把 key 立刻写 {keys_path}）", flush=True)
    try:
        time.sleep(args.seconds)
    except KeyboardInterrupt:
        pass
    print(f"\n共 {counter[0]} 个库相关现场，累计 {len(found)}/{len(dbs)} 个库有 key → {keys_path}\n"
          f"接着跑：vchat decrypt", flush=True)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""微信群活跃度全量提取：vchat 导出 + 解密库 zstd 解压，产出多维表格写入所需的全部批次文件。

用法:
    python3 extract_group_activity.py <群名或chatroom_id> [--out DIR] [--since "YYYY-MM-DD HH:MM:SS"]

输出（默认 /tmp/group-activity-<chatroom前缀>/）:
    activity.csv            成员活跃度明细（含进群时间、活跃标签）
    daily.csv               每日消息数
    batch_activity_*.json   成员表 record-batch-create 批次（200/批）
    msg_batch_*.json        发言记录表 record-batch-create 批次（200/批）
    join_groups.json        进群时间分组 {时间: [wxid...]}，用于增量补写
    summary.json            各项计数，用于写入后核对

--since 只影响 msg_batch（增量追加新消息用），activity/daily 永远全量重算。
"""
import argparse, csv, hashlib, json, os, re, sqlite3, subprocess, sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta

try:
    import zstandard
except ImportError:
    sys.exit("需要 zstandard: pip3 install zstandard")

SELF_WXID_NAME = os.environ.get("GAB_SELF_NAME", "我")  # vchat 导出里本人 sender_name 是 "me"，用此名替换（export GAB_SELF_NAME=你的名字）
VCHAT_MSG_DIR = os.path.expanduser("~/.vchat/data/decrypted/message")
TEXT_TYPES = {1, 244813135921}
TYPE_LABEL = {1: "文本", 3: "图片", 34: "语音", 42: "名片", 43: "视频", 47: "表情", 48: "位置"}
SUB_LABEL = {1: "文本", 4: "视频分享", 5: "链接分享", 6: "文件", 8: "动图", 19: "合并转发",
             24: "笔记", 33: "小程序", 36: "小程序", 50: "视频号名片", 51: "视频号",
             57: "引用回复", 62: "视频号", 63: "视频号直播", 87: "群公告", 92: "音乐",
             2000: "转账", 2001: "红包", 124: "接龙", 129: "接龙"}

def sh(cmd):
    return subprocess.run(cmd, capture_output=True, text=True).stdout

def label_of(total):
    if total == 0: return "潜水（零发言）"
    if total >= 100: return "核心活跃"
    if total >= 30: return "高活跃"
    if total >= 10: return "中活跃"
    if total >= 3: return "低活跃"
    return "仅冒泡"

def flat(s): return re.sub(r"[^\w一-鿿]+", "", s.lower())
def tokens(s): return [t for t in re.split(r"[^\w一-鿿]+", s.lower()) if len(t) >= 2]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("group")
    ap.add_argument("--out", default=None)
    ap.add_argument("--since", default=None, help="只导出此时间之后的消息批次（增量追加用）")
    args = ap.parse_args()

    # ── 1. 定位群 ──
    if args.group.endswith("@chatroom"):
        chatroom = args.group
    else:
        info = sh(["vchat", "group-info", args.group])
        mm = re.search(r"username:\s+(\S+@chatroom)", info)
        if not mm: sys.exit(f"找不到群: {args.group}\n{info[:300]}")
        chatroom = mm.group(1)
    out = args.out or f"/tmp/group-activity-{chatroom.split('@')[0]}"
    os.makedirs(out, exist_ok=True)
    since_ts = int(datetime.strptime(args.since, "%Y-%m-%d %H:%M:%S").timestamp()) if args.since else 0

    # ── 2. vchat 导出 + 成员名单 ──
    exp = os.path.join(out, "messages.json")
    sh(["vchat", "export", chatroom, "-o", exp])
    data = json.load(open(exp))
    members = {}
    for line in sh(["vchat", "group-members", chatroom]).splitlines():
        mm = re.match(r"\s{2}(\S+)\s{2,}(.+)$", line)
        if mm: members[mm.group(1)] = mm.group(2).strip()

    # ── 3. 解密库原始行（内容 + 系统消息） ──
    tbl = "Msg_" + hashlib.md5(chatroom.encode()).hexdigest()
    dbpath = None
    for f in sorted(os.listdir(VCHAT_MSG_DIR)):
        if not f.endswith(".db"): continue
        p = os.path.join(VCHAT_MSG_DIR, f)
        try:
            if sqlite3.connect(p).execute(f"SELECT COUNT(*) FROM {tbl}").fetchone():
                dbpath = p; break
        except sqlite3.Error: continue
    if not dbpath: sys.exit(f"解密库里找不到表 {tbl}")
    db = sqlite3.connect(dbpath)
    dctx = zstandard.ZstdDecompressor()

    def dec(raw):
        if isinstance(raw, bytes):
            if raw[:4] == b"\x28\xb5\x2f\xfd":
                try: return dctx.decompress(raw, max_output_size=10**7).decode("utf-8", "replace")
                except Exception: return ""
            return raw.decode("utf-8", "replace")
        return raw or ""

    def xml_tag(c, tag):
        mm = re.search(rf"<{tag}>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</{tag}>", c, re.S)
        return mm.group(1).strip() if mm else ""

    raw_by_lid = {r[0]: (r[1], r[2], r[3]) for r in db.execute(
        f"SELECT local_id, local_type, create_time, message_content FROM {tbl}")}

    # ── 4. 入群/移出事件（建群初始名单 + 邀请 + 扫码 + 清退） ──
    initial_time, initial_names, invites, removes = None, [], [], []
    for lid, (lt, t, raw) in raw_by_lid.items():
        if lt != 10000: continue
        c = dec(raw)
        if "群聊参与人还有" in c:
            initial_time = t
            plain = re.search(r'<link name="others" type="link_plain">\s*<plain><!\[CDATA\[(.*?)\]\]></plain>', c, re.S)
            if plain: initial_names = [n.strip() for n in plain.group(1).split("、")]
            continue
        mm = re.search(r'"(.+?)"邀请"(.+?)"加入了?群聊', c) or re.search(r'你邀请"(.+?)"加入了?群聊', c)
        if mm:
            for name in mm.group(mm.lastindex).split("、"): invites.append((t, name.strip()))
            continue
        mm = re.search(r'"(.+?)"通过扫描.{0,20}?二维码加入群聊', c)  # 扫码入群（社区群大量存在）
        if mm: invites.append((t, mm.group(1).strip())); continue
        mm = re.search(r'^你将"(.+?)"移出了?群聊', c) or re.search(r'^"(.+?)"将"(.+?)"移出了?群聊', c)
        if mm:
            for n in mm.group(mm.lastindex).split("、"): removes.append((t, n.strip()))
    events = [(initial_time, n, "建群初始") for n in initial_names] if initial_time else []
    events += [(t, n, "邀请入群") for t, n in invites]

    # ── 5. 成员统计 ──
    msgs = [m for m in data["messages"] if m["local_type"] != 10000 and m["sender_wxid"] != chatroom]
    now = datetime.now(); week_ago = (now - timedelta(days=7)).timestamp()
    stats = defaultdict(lambda: {"total": 0, "text": 0, "first": None, "last": None, "days": set(), "week": 0, "name": ""})
    for m in msgs:
        s = stats[m["sender_wxid"]]; t = m["create_time"]
        s["total"] += 1
        if m["local_type"] in TEXT_TYPES: s["text"] += 1
        if s["first"] is None or t < s["first"]: s["first"] = t
        if s["last"] is None or t > s["last"]: s["last"] = t; s["name"] = m["sender_name"]
        s["days"].add(datetime.fromtimestamp(t).date())
        if t >= week_ago: s["week"] += 1

    def display_name(w):
        s = stats.get(w)
        n = (s["name"] if s and s["name"] else "") or members.get(w, w)
        return SELF_WXID_NAME if n == "me" else n

    # ── 6. 进群时间匹配（精确名 → token → 包含；兜底建群初始） ──
    by_full = {}; by_tok = defaultdict(list)
    for t, n, src in events:
        by_full.setdefault(flat(n), (t, src))
        for tk in tokens(n): by_tok[tk].append((t, src))
    def join_time_of(w):
        names = {display_name(w), members.get(w, "")} - {""}
        for nm in names:
            if flat(nm) in by_full: return by_full[flat(nm)][0]
        cands = []
        for nm in names:
            nf = flat(nm)
            for tk, evs in by_tok.items():
                if len(tk) >= 3 and (tk in nf or nf in tk): cands += evs
            for tk in tokens(nm):
                cands += by_tok.get(tk, [])
        uniq = set(cands)
        if len(uniq) == 1: return cands[0][0]
        if initial_time: return initial_time  # 有建群初始名单的群：改名认不出的按建群初始
        s = stats.get(w)
        return s["first"] if s else None  # 无初始名单的群：用首次发言近似（进群不晚于此）

    # ── 7. activity.csv + 批次 ──
    rows = []
    for w in set(members) | set(stats):
        s = stats.get(w); total = s["total"] if s else 0
        jt = join_time_of(w)
        rows.append({
            "昵称": display_name(w), "wxid": w, "总发言数": total,
            "文本消息数": s["text"] if s else 0, "活跃天数": len(s["days"]) if s else 0,
            "近7天发言数": s["week"] if s else 0,
            "首次发言": datetime.fromtimestamp(s["first"]).strftime("%Y-%m-%d %H:%M:%S") if s else "",
            "最近发言": datetime.fromtimestamp(s["last"]).strftime("%Y-%m-%d %H:%M:%S") if s else "",
            "进群时间": datetime.fromtimestamp(jt).strftime("%Y-%m-%d %H:%M:%S") if jt else "",
            "移出时间": "",
            "活跃标签": label_of(total), "在群状态": "在群" if w in members else "已退群"})
    # 移出时间回填（只允许已退群行）+ 隐形退群成员（进过群但没在任何已知行里的人）
    known = {}
    for r in rows: known.setdefault(flat(r["昵称"]), []).append(r)
    orphan_removes = []
    for t, n in removes:
        hits = known.get(flat(n), [])
        if len(hits) == 1 and hits[0]["在群状态"] == "已退群" and not hits[0].get("移出时间"):
            hits[0]["移出时间"] = datetime.fromtimestamp(t).strftime("%Y-%m-%d %H:%M:%S")
        elif not hits: orphan_removes.append((t, n))
    ghosts = {}
    for t, n in orphan_removes:
        ghosts.setdefault(flat(n), {"name": n, "join": None, "remove": t})
    for t, n, _src in events:
        fn = flat(n)
        if fn and fn not in known and fn not in ghosts: ghosts[fn] = {"name": n, "join": t, "remove": None}
        elif fn in ghosts and ghosts[fn]["join"] is None: ghosts[fn]["join"] = t
    # 隐形成员 wxid 找回：昵称唯一命中联系人库才用（重名不猜）
    contact_idx = {}
    try:
        cdb = sqlite3.connect(os.path.expanduser("~/.vchat/data/decrypted/contact/contact.db"))
        cdb.text_factory = lambda b: b.decode("utf-8", "replace")
        for u, nick, remark in cdb.execute("SELECT username, nick_name, remark FROM contact"):
            for n in (nick, remark):
                fn = flat(n or "")
                if fn: contact_idx.setdefault(fn, set()).add(u)
    except sqlite3.Error:
        pass
    def ghost_wxid(name):
        us = {u for u in contact_idx.get(flat(name), set()) if "@chatroom" not in u and not u.startswith("gh_")}
        return next(iter(us)) if len(us) == 1 else ""
    for g in ghosts.values():
        rows.append({"昵称": g["name"], "wxid": ghost_wxid(g["name"]), "总发言数": 0, "文本消息数": 0, "活跃天数": 0,
                     "近7天发言数": 0, "首次发言": "", "最近发言": "",
                     "进群时间": datetime.fromtimestamp(g["join"]).strftime("%Y-%m-%d %H:%M:%S") if g["join"] else "",
                     "移出时间": datetime.fromtimestamp(g["remove"]).strftime("%Y-%m-%d %H:%M:%S") if g["remove"] else "",
                     "活跃标签": "潜水（零发言）", "在群状态": "已退群"})
    rows.sort(key=lambda r: -r["总发言数"])
    fields = list(rows[0].keys())
    with open(os.path.join(out, "activity.csv"), "w", newline="") as f:
        wtr = csv.DictWriter(f, fieldnames=fields); wtr.writeheader(); wtr.writerows(rows)
    for i in range(0, len(rows), 200):
        b = rows[i:i+200]
        json.dump({"fields": fields, "rows": [[r[k] if r[k] != "" else None for k in fields] for r in b]},
                  open(os.path.join(out, f"batch_activity_{i//200}.json"), "w"), ensure_ascii=False)
    jg = defaultdict(list)
    for r in rows:
        if r["进群时间"]: jg[r["进群时间"]].append(r["wxid"])
    json.dump(jg, open(os.path.join(out, "join_groups.json"), "w"), ensure_ascii=False)

    # ── 8. daily.csv ──
    daily = Counter(datetime.fromtimestamp(m["create_time"]).strftime("%Y-%m-%d") for m in msgs)
    with open(os.path.join(out, "daily.csv"), "w", newline="") as f:
        w = csv.writer(f); w.writerow(["日期", "消息数"])
        for d in sorted(daily): w.writerow([d, daily[d]])

    # ── 9. 发言记录批次（--since 增量） ──
    def strip_prefix(c):
        mm = re.match(r"^[\w@.]+:\n", c)
        return c[mm.end():] if mm else c
    out_msgs = []
    for m in sorted(msgs, key=lambda x: (x["create_time"], x["local_id"])):
        t = m["create_time"]
        if t <= since_ts: continue
        lt = m["local_type"]; w = m["sender_wxid"]
        raw = raw_by_lid.get(m["local_id"], (None, None, None))[2]
        c = strip_prefix(dec(raw))
        if lt == 1: lab, content = "文本", c
        elif lt in TYPE_LABEL: lab, content = TYPE_LABEL[lt], f"[{TYPE_LABEL[lt]}]"
        elif lt > 2**32:
            sub = lt >> 32; lab = SUB_LABEL.get(sub, f"其他({sub})")
            title = xml_tag(c, "title")
            if sub == 57:
                ref_n, ref_c = xml_tag(c, "displayname"), xml_tag(c, "content")
                content = title + (f"\n↩️ 回复 {ref_n}: {ref_c[:100]}" if ref_n and "<" not in ref_c and "&lt;" not in ref_c else "")
            elif sub == 5:
                url = xml_tag(c, "url"); content = f"[链接] {title}" + (f"\n{url[:200]}" if url else "")
            elif sub == 6: content = f"[文件] {title}"
            elif sub == 87: content = "[群公告] " + (xml_tag(c, "textannouncement") or title)[:500]
            else: content = f"[{lab}]" + (f" {title}" if title else "")
        else: lab, content = f"其他({lt})", ""
        out_msgs.append([datetime.fromtimestamp(t).strftime("%Y-%m-%d %H:%M:%S"),
                         display_name(w), w, lab, (content or "").strip()[:1800] or None])
    for i in range(0, len(out_msgs), 200):
        json.dump({"fields": ["时间", "发言人", "wxid", "类型", "内容"], "rows": out_msgs[i:i+200]},
                  open(os.path.join(out, f"msg_batch_{i//200:03d}.json"), "w"), ensure_ascii=False)  # 3位编号保证字典序=时间序

    # ── 10. summary ──
    summary = {"chatroom": chatroom, "out_dir": out,
               "成员数": len(members), "总消息数": len(msgs), "发言记录批次条数": len(out_msgs),
               "发过言人数": len(stats), "零发言人数": len([w for w in members if w not in stats]),
               "标签分布": dict(Counter(r["活跃标签"] for r in rows if r["在群状态"] == "在群")),
               "活动表行数": len(rows), "每日趋势天数": len(daily),
               "进群事件": {"建群初始": len(initial_names), "邀请+扫码": len(invites)},
               "清退事件": len(removes), "隐形退群成员": len(ghosts)}
    json.dump(summary, open(os.path.join(out, "summary.json"), "w"), ensure_ascii=False, indent=1)
    print(json.dumps(summary, ensure_ascii=False, indent=1))

if __name__ == "__main__":
    main()

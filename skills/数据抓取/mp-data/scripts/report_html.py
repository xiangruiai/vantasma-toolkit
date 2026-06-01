#!/usr/bin/env python3
"""万涂幻象公众号数据 → HTML 可视化报告"""

import json, math, re, sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from html import escape

DATA_PATH = Path("/tmp/mp_all_publish_data.json")


def parse_date(d, reference_year=None):
    if reference_year is None:
        reference_year = datetime.now().year
    d = d.strip()
    m = re.match(r"(\d{4})年(\d{1,2})月(\d{1,2})日", d)
    if m:
        return f"{m.group(1)}/{int(m.group(2)):02d}/{int(m.group(3)):02d}"
    m = re.match(r"(\d{1,2})月(\d{1,2})日", d)
    if m:
        month, day = int(m.group(1)), int(m.group(2))
        now = datetime.now()
        year = reference_year if month <= now.month else reference_year - 1
        return f"{year}/{month:02d}/{day:02d}"
    if any(kw in d for kw in ["星期", "昨天", "今天", "小时前", "分钟前"]):
        now = datetime.now()
        return f"{now.year}/{now.month:02d}/{now.day:02d}"
    return d


def classify_article(title):
    t = title.lower()
    if any(kw in t for kw in ["多维表格", "bitable", "多维"]):
        return "飞书多维表格"
    if any(kw in t for kw in ["coze", "扣子", "skill"]):
        return "Coze/Skills"
    if any(kw in t for kw in ["飞书", "feishu", "lark", "aily"]):
        return "飞书其他"
    if any(kw in t for kw in ["gpt", "claude", "gemini", "deepseek", "kimi", "豆包", "通义", "文心"]):
        return "AI产品/工具"
    if any(kw in t for kw in ["ai", "人工智能", "大模型", "agent", "智能体"]):
        return "AI通用话题"
    return "其他"


def title_cell(a):
    t = escape(a["t"])
    url = a.get("u", "")
    if url:
        return f'<a href="{escape(url)}" target="_blank">{t}</a>'
    return t


def median(values):
    if not values:
        return 0
    s = sorted(values)
    n = len(s)
    if n % 2 == 1:
        return s[n // 2]
    return (s[n // 2 - 1] + s[n // 2]) / 2


def stdev(values):
    if len(values) < 2:
        return 0
    avg = sum(values) / len(values)
    return math.sqrt(sum((x - avg) ** 2 for x in values) / (len(values) - 1))


def percentile(values, p):
    if not values:
        return 0
    s = sorted(values)
    k = (len(s) - 1) * p / 100
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return s[int(k)]
    return s[f] * (c - k) + s[c] * (k - f)


def engagement_rate(a):
    if a["r"] == 0:
        return 0
    return (a["l"] + a["w"] + a["s"]) / a["r"] * 100


def generate_html(articles):
    for a in articles:
        a["date"] = parse_date(a["d"])
        a["type"] = classify_article(a["t"])
        a["eng"] = engagement_rate(a)

    # === Global stats ===
    total = len(articles)
    total_reads = sum(a["r"] for a in articles)
    total_shares = sum(a["s"] for a in articles)
    total_wow = sum(a["w"] for a in articles)
    total_likes = sum(a["l"] for a in articles)
    avg_reads = total_reads / total if total else 0
    reads_list = [a["r"] for a in articles]
    med_reads = median(reads_list)
    sd_reads = stdev(reads_list)
    cv_reads = sd_reads / avg_reads * 100 if avg_reads else 0

    share_rate = total_shares / total_reads * 100 if total_reads else 0
    like_rate = total_likes / total_reads * 100 if total_reads else 0
    wow_rate = total_wow / total_reads * 100 if total_reads else 0
    eng_rate_all = (total_likes + total_wow + total_shares) / total_reads * 100 if total_reads else 0

    # 80/20 concentration
    sorted_by_reads = sorted(reads_list, reverse=True)
    top20pct_count = max(1, total // 5)
    top20pct_reads = sum(sorted_by_reads[:top20pct_count])
    concentration = top20pct_reads / total_reads * 100 if total_reads else 0

    p25 = percentile(reads_list, 25)
    p75 = percentile(reads_list, 75)
    p90 = percentile(reads_list, 90)

    # === Monthly ===
    monthly = defaultdict(lambda: {
        "count": 0, "total_reads": 0, "total_shares": 0,
        "total_wow": 0, "total_likes": 0, "articles": []
    })
    for a in articles:
        m = a["date"][:7].replace("/", "-")
        monthly[m]["count"] += 1
        monthly[m]["total_reads"] += a["r"]
        monthly[m]["total_shares"] += a["s"]
        monthly[m]["total_wow"] += a["w"]
        monthly[m]["total_likes"] += a["l"]
        monthly[m]["articles"].append(a)

    months_sorted = sorted(monthly.keys())

    chart_months = json.dumps(months_sorted)
    chart_reads = json.dumps([monthly[m]["total_reads"] for m in months_sorted])
    chart_avg = json.dumps([round(monthly[m]["total_reads"] / monthly[m]["count"]) if monthly[m]["count"] else 0 for m in months_sorted])
    chart_count = json.dumps([monthly[m]["count"] for m in months_sorted])
    chart_share_rate = json.dumps([round(monthly[m]["total_shares"] / monthly[m]["total_reads"] * 100, 2) if monthly[m]["total_reads"] else 0 for m in months_sorted])
    chart_like_rate = json.dumps([round(monthly[m]["total_likes"] / monthly[m]["total_reads"] * 100, 2) if monthly[m]["total_reads"] else 0 for m in months_sorted])
    chart_wow_rate = json.dumps([round(monthly[m]["total_wow"] / monthly[m]["total_reads"] * 100, 2) if monthly[m]["total_reads"] else 0 for m in months_sorted])
    chart_eng_rate = json.dumps([round((monthly[m]["total_likes"] + monthly[m]["total_wow"] + monthly[m]["total_shares"]) / monthly[m]["total_reads"] * 100, 2) if monthly[m]["total_reads"] else 0 for m in months_sorted])
    chart_median = json.dumps([round(median([a["r"] for a in monthly[m]["articles"]])) for m in months_sorted])

    # reads distribution histogram
    if reads_list:
        max_read = max(reads_list)
        bucket_size = max(50, math.ceil(max_read / 15 / 50) * 50)
        buckets = defaultdict(int)
        for r in reads_list:
            b = (r // bucket_size) * bucket_size
            buckets[b] += 1
        bucket_labels = []
        bucket_values = []
        for b in sorted(buckets.keys()):
            bucket_labels.append(f"{b}-{b + bucket_size}")
            bucket_values.append(buckets[b])
    else:
        bucket_labels, bucket_values = [], []
    chart_dist_labels = json.dumps(bucket_labels)
    chart_dist_values = json.dumps(bucket_values)

    # === Type stats ===
    type_stats = defaultdict(lambda: {"count": 0, "reads": 0, "shares": 0, "likes": 0, "wow": 0})
    for a in articles:
        ts = type_stats[a["type"]]
        ts["count"] += 1
        ts["reads"] += a["r"]
        ts["shares"] += a["s"]
        ts["likes"] += a["l"]
        ts["wow"] += a["w"]
    type_names = sorted(type_stats.keys(), key=lambda x: type_stats[x]["reads"] / max(type_stats[x]["count"], 1), reverse=True)
    chart_type_names = json.dumps(type_names, ensure_ascii=False)
    chart_type_avg = json.dumps([round(type_stats[t]["reads"] / type_stats[t]["count"]) if type_stats[t]["count"] else 0 for t in type_names])

    # === Tables ===
    top20 = sorted(articles, key=lambda x: x["r"], reverse=True)[:20]
    top20_eng = sorted([a for a in articles if a["r"] >= 50], key=lambda x: x["eng"], reverse=True)[:20]
    high_share = sorted([a for a in articles if a["r"] > 100 and a["s"] / max(a["r"], 1) > 0.15], key=lambda x: x["s"] / max(x["r"], 1), reverse=True)[:15]
    high_potential = sorted([a for a in articles if a["r"] < avg_reads and a["eng"] > eng_rate_all * 1.5 and a["r"] >= 50], key=lambda x: x["eng"], reverse=True)[:10]

    # Monthly rows
    monthly_rows = ""
    for m in months_sorted:
        d = monthly[m]
        avg = d["total_reads"] / d["count"] if d["count"] else 0
        med = median([a["r"] for a in d["articles"]])
        sr = d["total_shares"] / d["total_reads"] * 100 if d["total_reads"] else 0
        lr = d["total_likes"] / d["total_reads"] * 100 if d["total_reads"] else 0
        wr = d["total_wow"] / d["total_reads"] * 100 if d["total_reads"] else 0
        er = (d["total_likes"] + d["total_wow"] + d["total_shares"]) / d["total_reads"] * 100 if d["total_reads"] else 0
        mx = max(a["r"] for a in d["articles"])
        monthly_rows += f'<tr><td>{m}</td><td class="r">{d["count"]}</td><td class="r">{d["total_reads"]:,}</td><td class="r">{avg:,.0f}</td><td class="r">{med:,.0f}</td><td class="r">{lr:.2f}%</td><td class="r">{wr:.2f}%</td><td class="r">{sr:.1f}%</td><td class="r">{er:.1f}%</td><td class="r">{mx:,}</td></tr>\n'

    # TOP20 reads rows
    top20_rows = ""
    for i, a in enumerate(top20, 1):
        sr = a["s"] / a["r"] * 100 if a["r"] else 0
        lr = a["l"] / a["r"] * 100 if a["r"] else 0
        wr = a["w"] / a["r"] * 100 if a["r"] else 0
        top20_rows += f'<tr><td class="r">{i}</td><td class="ttl">{title_cell(a)}</td><td class="r">{a["r"]:,}</td><td class="r">{a["l"]}</td><td class="r">{lr:.2f}%</td><td class="r">{a["w"]}</td><td class="r">{wr:.2f}%</td><td class="r">{a["s"]}</td><td class="r">{sr:.1f}%</td><td class="r">{a["eng"]:.1f}%</td><td>{a["date"]}</td></tr>\n'

    # TOP20 engagement rows
    top20_eng_rows = ""
    for i, a in enumerate(top20_eng, 1):
        sr = a["s"] / a["r"] * 100 if a["r"] else 0
        lr = a["l"] / a["r"] * 100 if a["r"] else 0
        wr = a["w"] / a["r"] * 100 if a["r"] else 0
        top20_eng_rows += f'<tr><td class="r">{i}</td><td class="ttl">{title_cell(a)}</td><td class="r">{a["r"]:,}</td><td class="r">{lr:.2f}%</td><td class="r">{wr:.2f}%</td><td class="r">{sr:.1f}%</td><td class="r">{a["eng"]:.1f}%</td><td>{a["date"]}</td></tr>\n'

    # High share rows
    high_share_rows = ""
    for i, a in enumerate(high_share, 1):
        sr = a["s"] / a["r"] * 100
        high_share_rows += f'<tr><td class="r">{i}</td><td class="ttl">{title_cell(a)}</td><td class="r">{a["r"]:,}</td><td class="r">{a["s"]}</td><td class="r">{sr:.1f}%</td><td>{a["date"]}</td></tr>\n'

    # High potential rows
    high_potential_rows = ""
    for i, a in enumerate(high_potential, 1):
        lr = a["l"] / a["r"] * 100 if a["r"] else 0
        wr = a["w"] / a["r"] * 100 if a["r"] else 0
        sr = a["s"] / a["r"] * 100 if a["r"] else 0
        high_potential_rows += f'<tr><td class="r">{i}</td><td class="ttl">{title_cell(a)}</td><td class="r">{a["r"]:,}</td><td class="r">{lr:.2f}%</td><td class="r">{wr:.2f}%</td><td class="r">{sr:.1f}%</td><td class="r">{a["eng"]:.1f}%</td><td>{a["date"]}</td></tr>\n'

    # Type rows (enhanced)
    type_rows = ""
    for t in type_names:
        s = type_stats[t]
        avg_t = s["reads"] / s["count"] if s["count"] else 0
        sr = s["shares"] / s["reads"] * 100 if s["reads"] else 0
        lr = s["likes"] / s["reads"] * 100 if s["reads"] else 0
        wr = s["wow"] / s["reads"] * 100 if s["reads"] else 0
        er = (s["likes"] + s["wow"] + s["shares"]) / s["reads"] * 100 if s["reads"] else 0
        pct = s["reads"] / total_reads * 100 if total_reads else 0
        type_rows += f'<tr><td>{t}</td><td class="r">{s["count"]}</td><td class="r">{avg_t:,.0f}</td><td class="r">{lr:.2f}%</td><td class="r">{wr:.2f}%</td><td class="r">{sr:.1f}%</td><td class="r">{er:.1f}%</td><td class="r">{pct:.1f}%</td></tr>\n'

    today = datetime.now().strftime("%Y-%m-%d")

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>万涂幻象 · 数据报告 · {today}</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.7/dist/chart.umd.min.js"></script>
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ font-family: -apple-system, "PingFang SC", sans-serif; background:#fafafa; color:#222; line-height:1.5; font-size:14px; }}
.wrap {{ max-width:1200px; margin:0 auto; padding:24px 20px 48px; }}

h1 {{ font-size:22px; font-weight:700; color:#111; }}
.sub {{ color:#999; font-size:13px; margin-top:4px; }}

.kpi {{ display:flex; gap:1px; background:#e8e8e8; border-radius:10px; overflow:hidden; margin:24px 0; }}
.kpi-item {{ flex:1; background:#fff; padding:16px 8px; text-align:center; }}
.kpi-item .v {{ font-size:22px; font-weight:700; color:#333; font-variant-numeric:tabular-nums; }}
.kpi-item .k {{ font-size:11px; color:#999; margin-top:2px; }}

.card {{ background:#fff; border:1px solid #eee; border-radius:10px; padding:20px; margin-bottom:16px; }}
.card h2 {{ font-size:15px; font-weight:600; color:#333; margin-bottom:14px; }}
.card .desc {{ font-size:12px; color:#999; margin:-10px 0 14px; }}
.row {{ display:flex; gap:16px; }}
.row > .card {{ flex:1; min-width:0; }}

canvas {{ width:100%!important; max-height:260px; }}

.stat-grid {{ display:grid; grid-template-columns:1fr 1fr 1fr; gap:12px; margin-bottom:16px; }}
.stat-box {{ background:#f8f9fa; border-radius:8px; padding:12px; text-align:center; }}
.stat-box .v {{ font-size:18px; font-weight:700; color:#333; }}
.stat-box .k {{ font-size:11px; color:#999; margin-top:2px; }}

.tbl {{ width:100%; overflow-x:auto; }}
table {{ width:100%; border-collapse:collapse; font-size:13px; white-space:nowrap; }}
th {{ padding:8px 10px; text-align:left; font-weight:600; color:#666; font-size:11px; text-transform:uppercase; letter-spacing:0.3px; border-bottom:2px solid #eee; }}
th.r {{ text-align:right; }}
td {{ padding:7px 10px; border-bottom:1px solid #f0f0f0; }}
td.r {{ text-align:right; font-variant-numeric:tabular-nums; }}
td.ttl {{ max-width:380px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }}
td.ttl a {{ color:#333; text-decoration:none; }}
td.ttl a:hover {{ color:#1a73e8; text-decoration:underline; }}
tr:hover {{ background:#f8f9fa; }}

.tag {{ display:inline-block; padding:1px 6px; border-radius:3px; font-size:11px; font-weight:500; }}
.tag-good {{ background:#e6f4ea; color:#1e8e3e; }}
.tag-warn {{ background:#fef7e0; color:#ea8600; }}
.tag-bad {{ background:#fce8e6; color:#c5221f; }}

@media (max-width:768px) {{
    .kpi {{ flex-wrap:wrap; }}
    .kpi-item {{ min-width:calc(33% - 1px); }}
    .row {{ flex-direction:column; }}
    .stat-grid {{ grid-template-columns:1fr 1fr; }}
}}
</style>
</head>
<body>
<div class="wrap">

<h1>万涂幻象 · 公众号数据报告</h1>
<div class="sub">{today} / {total} 篇文章 / 数据来源 mp.weixin.qq.com</div>

<!-- KPI -->
<div class="kpi">
    <div class="kpi-item"><div class="v">{total}</div><div class="k">总篇数</div></div>
    <div class="kpi-item"><div class="v">{total_reads:,}</div><div class="k">总阅读</div></div>
    <div class="kpi-item"><div class="v">{avg_reads:,.0f}</div><div class="k">篇均阅读</div></div>
    <div class="kpi-item"><div class="v">{med_reads:,.0f}</div><div class="k">中位数阅读</div></div>
    <div class="kpi-item"><div class="v">{like_rate:.2f}%</div><div class="k">赞阅比</div></div>
    <div class="kpi-item"><div class="v">{wow_rate:.2f}%</div><div class="k">在看阅比</div></div>
    <div class="kpi-item"><div class="v">{share_rate:.1f}%</div><div class="k">分享率</div></div>
    <div class="kpi-item"><div class="v">{eng_rate_all:.1f}%</div><div class="k">综合互动率</div></div>
</div>

<!-- Distribution stats -->
<div class="card">
    <h2>阅读量分布特征</h2>
    <div class="desc">衡量内容表现的稳定性和集中度</div>
    <div class="stat-grid">
        <div class="stat-box"><div class="v">{avg_reads:,.0f}</div><div class="k">均值</div></div>
        <div class="stat-box"><div class="v">{med_reads:,.0f}</div><div class="k">中位数</div></div>
        <div class="stat-box"><div class="v">{sd_reads:,.0f}</div><div class="k">标准差</div></div>
        <div class="stat-box"><div class="v">{cv_reads:.0f}%</div><div class="k">变异系数 CV</div></div>
        <div class="stat-box"><div class="v">{p25:,.0f}</div><div class="k">P25 下四分位</div></div>
        <div class="stat-box"><div class="v">{p75:,.0f}</div><div class="k">P75 上四分位</div></div>
        <div class="stat-box"><div class="v">{p90:,.0f}</div><div class="k">P90 头部线</div></div>
        <div class="stat-box"><div class="v">{concentration:.0f}%</div><div class="k">前20%文章贡献</div></div>
        <div class="stat-box"><div class="v">{max(reads_list) if reads_list else 0:,}</div><div class="k">最高阅读</div></div>
    </div>
    <canvas id="cDist" style="max-height:200px;"></canvas>
</div>

<!-- Charts Row 1 -->
<div class="row">
    <div class="card"><h2>月度总阅读</h2><canvas id="c1"></canvas></div>
    <div class="card"><h2>篇均 vs 中位数 / 发文量</h2><canvas id="c2"></canvas></div>
</div>

<!-- Charts Row 2 -->
<div class="row">
    <div class="card">
        <h2>月度互动率趋势</h2>
        <div class="desc">赞阅比 / 在看阅比 / 分享率 / 综合互动率</div>
        <canvas id="c3"></canvas>
    </div>
    <div class="card"><h2>内容类型篇均阅读</h2><canvas id="c4"></canvas></div>
</div>

<!-- TOP 20 Reads -->
<div class="card">
    <h2>TOP 20 文章（按阅读量）</h2>
    <div class="tbl"><table>
        <thead><tr><th class="r">序号</th><th>标题</th><th class="r">阅读</th><th class="r">赞</th><th class="r">赞阅比</th><th class="r">在看</th><th class="r">在看率</th><th class="r">分享</th><th class="r">分享率</th><th class="r">互动率</th><th>日期</th></tr></thead>
        <tbody>{top20_rows}</tbody>
    </table></div>
</div>

<!-- TOP 20 Engagement -->
<div class="card">
    <h2>TOP 20 文章（按互动率）</h2>
    <div class="desc">阅读量 &ge; 50 的文章按综合互动率（赞+在看+分享/阅读）排序，发现读者真正认可的内容</div>
    <div class="tbl"><table>
        <thead><tr><th class="r">序号</th><th>标题</th><th class="r">阅读</th><th class="r">赞阅比</th><th class="r">在看率</th><th class="r">分享率</th><th class="r">互动率</th><th>日期</th></tr></thead>
        <tbody>{top20_eng_rows}</tbody>
    </table></div>
</div>

<!-- Monthly Summary -->
<div class="card">
    <h2>月度汇总</h2>
    <div class="tbl"><table>
        <thead><tr><th>月份</th><th class="r">篇数</th><th class="r">总阅读</th><th class="r">篇均</th><th class="r">中位数</th><th class="r">赞阅比</th><th class="r">在看率</th><th class="r">分享率</th><th class="r">互动率</th><th class="r">最高</th></tr></thead>
        <tbody>{monthly_rows}</tbody>
    </table></div>
</div>

<!-- Content Type ROI -->
<div class="card">
    <h2>内容类型深度分析</h2>
    <div class="desc">不同内容类型的读者互动行为差异</div>
    <div class="tbl"><table>
        <thead><tr><th>类型</th><th class="r">篇数</th><th class="r">篇均阅读</th><th class="r">赞阅比</th><th class="r">在看率</th><th class="r">分享率</th><th class="r">互动率</th><th class="r">阅读占比</th></tr></thead>
        <tbody>{type_rows}</tbody>
    </table></div>
</div>

<!-- High share -->
<div class="row">
    <div class="card">
        <h2>高分享率文章（&gt;15%，阅读&gt;100）</h2>
        <div class="desc">分享率远超平均，说明内容触发了"值得推荐给别人"的社交传播意愿</div>
        <div class="tbl"><table>
            <thead><tr><th class="r">序号</th><th>标题</th><th class="r">阅读</th><th class="r">分享</th><th class="r">分享率</th><th>日期</th></tr></thead>
            <tbody>{high_share_rows if high_share_rows else '<tr><td colspan="6" style="text-align:center;color:#999;">暂无符合条件的文章</td></tr>'}</tbody>
        </table></div>
    </div>
</div>

<!-- High potential -->
<div class="card">
    <h2>高潜力文章（高互动 + 低阅读）</h2>
    <div class="desc">阅读低于均值但互动率超过整体 1.5 倍的文章。读到的人很认可，说明内容好但分发不够，值得二次推广</div>
    <div class="tbl"><table>
        <thead><tr><th class="r">序号</th><th>标题</th><th class="r">阅读</th><th class="r">赞阅比</th><th class="r">在看率</th><th class="r">分享率</th><th class="r">互动率</th><th>日期</th></tr></thead>
        <tbody>{high_potential_rows if high_potential_rows else '<tr><td colspan="8" style="text-align:center;color:#999;">暂无符合条件的文章</td></tr>'}</tbody>
    </table></div>
</div>

<!-- Methodology -->
<div class="card" style="background:#f8f9fa;">
    <h2>指标说明</h2>
    <div style="font-size:12px;color:#666;line-height:1.8;columns:2;column-gap:32px;">
        <p><b>赞阅比</b> = 点赞 / 阅读 &times; 100%。衡量内容的认同感和情感共鸣。公众号典型值 0.5-2%。</p>
        <p><b>在看阅比</b> = 在看 / 阅读 &times; 100%。读者愿意让朋友圈好友看到，社交背书意愿。</p>
        <p><b>分享率</b> = 分享 / 阅读 &times; 100%。主动转发给特定好友，最强传播信号。公众号典型值 3-8%。</p>
        <p><b>综合互动率</b> = (赞 + 在看 + 分享) / 阅读 &times; 100%。综合衡量内容质量。</p>
        <p><b>变异系数 CV</b> = 标准差 / 均值 &times; 100%。越大说明阅读波动越大，爆款和低阅读的差距大。</p>
        <p><b>前 20% 贡献度</b>：头部集中度。若接近 80%，符合二八定律，说明少数爆款撑起大部分流量。</p>
        <p><b>中位数 vs 均值</b>：中位数 &lt;&lt; 均值 说明被少数高阅读文章拉高了均值，大部分文章表现低于"平均"。</p>
        <p><b>高潜力文章</b>：阅读低于均值但互动率超过整体 1.5 倍，说明内容本身好但曝光不足。</p>
    </div>
</div>

</div>
<script>
Chart.defaults.font.family = "-apple-system, 'PingFang SC', sans-serif";
Chart.defaults.font.size = 11;
const months = {chart_months};
const B = '#4285f4', G = '#34a853', O = '#fbbc04', R = '#ea4335', P = '#ab47bc', T = '#009688';

// Monthly total reads
new Chart(document.getElementById('c1'), {{
    type:'bar',
    data:{{ labels:months, datasets:[{{ data:{chart_reads}, backgroundColor:B+'50', hoverBackgroundColor:B+'90', borderRadius:4, borderSkipped:false }}] }},
    options:{{ responsive:true, plugins:{{ legend:{{ display:false }} }}, scales:{{ y:{{ beginAtZero:true, ticks:{{ callback:v=>v>=1000?(v/1000)+'k':v }}, grid:{{ color:'#f0f0f0' }} }}, x:{{ grid:{{ display:false }} }} }} }}
}});

// Avg vs Median vs Count
new Chart(document.getElementById('c2'), {{
    type:'line',
    data:{{ labels:months, datasets:[
        {{ label:'篇均', data:{chart_avg}, borderColor:B, borderWidth:2, pointRadius:3, pointBackgroundColor:B, fill:false, tension:0.3, yAxisID:'y' }},
        {{ label:'中位数', data:{chart_median}, borderColor:P, borderWidth:2, pointRadius:3, pointBackgroundColor:P, fill:false, tension:0.3, borderDash:[5,3], yAxisID:'y' }},
        {{ label:'发文', data:{chart_count}, borderColor:O+'80', backgroundColor:O+'30', type:'bar', yAxisID:'y1', borderRadius:3, borderSkipped:false }}
    ] }},
    options:{{ responsive:true, interaction:{{ mode:'index', intersect:false }}, plugins:{{ legend:{{ position:'bottom', labels:{{ usePointStyle:true, pointStyle:'circle', padding:12, font:{{ size:11 }} }} }} }}, scales:{{ y:{{ position:'left', beginAtZero:true, grid:{{ color:'#f0f0f0' }} }}, y1:{{ position:'right', beginAtZero:true, grid:{{ drawOnChartArea:false }} }}, x:{{ grid:{{ display:false }} }} }} }}
}});

// Engagement rates trend (multi-line)
new Chart(document.getElementById('c3'), {{
    type:'line',
    data:{{ labels:months, datasets:[
        {{ label:'综合互动率', data:{chart_eng_rate}, borderColor:R, borderWidth:2.5, pointRadius:3, pointBackgroundColor:R, fill:false, tension:0.3 }},
        {{ label:'分享率', data:{chart_share_rate}, borderColor:G, borderWidth:2, pointRadius:2.5, pointBackgroundColor:G, fill:false, tension:0.3 }},
        {{ label:'在看率', data:{chart_wow_rate}, borderColor:B, borderWidth:1.5, pointRadius:2, pointBackgroundColor:B, fill:false, tension:0.3, borderDash:[4,2] }},
        {{ label:'赞阅比', data:{chart_like_rate}, borderColor:O, borderWidth:1.5, pointRadius:2, pointBackgroundColor:O, fill:false, tension:0.3, borderDash:[4,2] }}
    ] }},
    options:{{ responsive:true, interaction:{{ mode:'index', intersect:false }}, plugins:{{ legend:{{ position:'bottom', labels:{{ usePointStyle:true, pointStyle:'circle', padding:10, font:{{ size:11 }} }} }} }}, scales:{{ y:{{ beginAtZero:true, ticks:{{ callback:v=>v+'%' }}, grid:{{ color:'#f0f0f0' }} }}, x:{{ grid:{{ display:false }} }} }} }}
}});

// Content type avg reads
new Chart(document.getElementById('c4'), {{
    type:'bar',
    data:{{ labels:{chart_type_names}, datasets:[{{ data:{chart_type_avg}, backgroundColor:[B+'70',G+'70',O+'70',R+'70',P+'70','#78909c70'], borderRadius:4, borderSkipped:false }}] }},
    options:{{ responsive:true, indexAxis:'y', plugins:{{ legend:{{ display:false }} }}, scales:{{ x:{{ grid:{{ color:'#f0f0f0' }} }}, y:{{ grid:{{ display:false }} }} }} }}
}});

// Reads distribution histogram
new Chart(document.getElementById('cDist'), {{
    type:'bar',
    data:{{ labels:{chart_dist_labels}, datasets:[{{ data:{chart_dist_values}, backgroundColor:T+'50', hoverBackgroundColor:T+'90', borderRadius:2, borderSkipped:false }}] }},
    options:{{ responsive:true, plugins:{{ legend:{{ display:false }}, tooltip:{{ callbacks:{{ title:items=>items[0].label+' 阅读', label:item=>item.raw+' 篇文章' }} }} }}, scales:{{ y:{{ beginAtZero:true, title:{{ display:true, text:'文章数', font:{{ size:11 }} }}, grid:{{ color:'#f0f0f0' }} }}, x:{{ title:{{ display:true, text:'阅读量区间', font:{{ size:11 }} }}, grid:{{ display:false }}, ticks:{{ maxRotation:45, font:{{ size:10 }} }} }} }} }}
}});
</script>
</body>
</html>"""
    return html


def main():
    if not DATA_PATH.exists():
        print(f"ERROR: 数据文件不存在 {DATA_PATH}")
        print("请先运行 scrape.py 抓取数据")
        sys.exit(1)

    articles = json.loads(DATA_PATH.read_text())
    output = "/tmp/mp_report.html"
    if len(sys.argv) > 1:
        output = sys.argv[1]

    html = generate_html(articles)
    Path(output).write_text(html, encoding="utf-8")
    print(f"HTML 报告已生成: {output}")
    print(f"用浏览器打开: open {output}")


if __name__ == "__main__":
    main()

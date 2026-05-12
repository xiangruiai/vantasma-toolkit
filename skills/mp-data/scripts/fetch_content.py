#!/usr/bin/env python3
"""抓取微信公众号文章正文内容

用 CDP 浏览器打开文章 URL，提取标题、正文、发布时间等。
支持单篇和批量模式。
"""

import subprocess, json, sys, time
from pathlib import Path

CDP_BASE = "http://localhost:3456"


def cdp_request(endpoint, method="GET", data=None):
    cmd = ["curl", "-s"]
    if method == "POST":
        cmd.extend(["-X", "POST", f"{CDP_BASE}/{endpoint}", "-d", data or ""])
    else:
        cmd.append(f"{CDP_BASE}/{endpoint}")
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    try:
        return json.loads(r.stdout)
    except (json.JSONDecodeError, Exception):
        return {"raw": r.stdout}


def fetch_article(url):
    """抓取单篇文章内容，返回 dict"""
    tab = cdp_request(f"new?url={url}")
    target_id = tab.get("targetId")
    if not target_id:
        return {"error": "无法创建浏览器标签页", "url": url}

    time.sleep(3)

    extract_js = r"""
(function() {
    var title = document.querySelector('#activity-name');
    var author = document.querySelector('#js_name') || document.querySelector('.rich_media_meta_nickname');
    var pubTime = document.querySelector('#publish_time');
    var content = document.querySelector('#js_content');

    if (!content) return JSON.stringify({error: 'no_content'});

    // 提取纯文本，保留段落换行
    var paragraphs = content.querySelectorAll('p, section > span, h1, h2, h3, h4, li');
    var textParts = [];
    var seen = new Set();
    paragraphs.forEach(function(p) {
        var text = p.innerText.trim();
        if (text && !seen.has(text)) {
            seen.add(text);
            textParts.push(text);
        }
    });

    // 如果段落提取太少，回退到整体 innerText
    var fullText = textParts.length > 3 ? textParts.join('\n\n') : content.innerText.trim();

    // 提取图片
    var images = [];
    content.querySelectorAll('img[data-src]').forEach(function(img) {
        images.push(img.getAttribute('data-src'));
    });

    return JSON.stringify({
        title: title ? title.innerText.trim() : '',
        author: author ? author.innerText.trim() : '',
        publish_time: pubTime ? pubTime.innerText.trim() : '',
        content: fullText,
        images: images.slice(0, 20),
        word_count: fullText.length
    });
})()
"""
    result = cdp_request(f"eval?target={target_id}", "POST", extract_js)
    cdp_request(f"close?target={target_id}")

    value = result.get("value", "")
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return {"error": "解析失败", "raw": value, "url": url}
    return {"error": "未知响应", "url": url}


def fetch_batch(articles, output_path=None, delay=2):
    """批量抓取文章内容

    articles: list of dict，每个至少包含 'u'(url) 和 't'(title) 字段
    """
    results = []
    total = len(articles)
    for i, a in enumerate(articles):
        url = a.get("u", "")
        title = a.get("t", "未知标题")
        if not url:
            print(f"  [{i+1}/{total}] 跳过（无 URL）: {title}")
            continue

        print(f"  [{i+1}/{total}] {title[:40]}...")
        article_data = fetch_article(url)
        article_data["original_title"] = title
        article_data["original_url"] = url
        article_data["reads"] = a.get("r", 0)
        results.append(article_data)

        if i < total - 1:
            time.sleep(delay)

    if output_path:
        Path(output_path).write_text(
            json.dumps(results, ensure_ascii=False, indent=2)
        )
        print(f"\n已保存 {len(results)} 篇文章内容到 {output_path}")

    return results


def main():
    import argparse
    parser = argparse.ArgumentParser(description="抓取微信公众号文章内容")
    parser.add_argument("url", nargs="?", help="单篇文章 URL")
    parser.add_argument("--batch", help="批量模式：JSON 数据文件路径（如 /tmp/mp_all_publish_data.json）")
    parser.add_argument("--top", type=int, default=0, help="批量模式下只取阅读量前 N 篇")
    parser.add_argument("--output", "-o", default="/tmp/mp_articles_content.json", help="输出路径")
    parser.add_argument("--delay", type=float, default=2, help="批量请求间隔秒数")
    args = parser.parse_args()

    if args.url:
        result = fetch_article(args.url)
        if args.output:
            Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2))
        print(json.dumps(result, ensure_ascii=False, indent=2)[:500])
    elif args.batch:
        data = json.loads(Path(args.batch).read_text())
        if args.top > 0:
            data.sort(key=lambda x: x.get("r", 0), reverse=True)
            data = data[:args.top]
        print(f"=== 批量抓取 {len(data)} 篇文章内容 ===\n")
        fetch_batch(data, args.output, args.delay)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""公众号全量文章数据抓取脚本

使用 Playwright 驱动浏览器，自动检测登录状态并提取 token，
逐页抓取发表记录页数据。支持任意公众号（需扫码登录对应后台）。

依赖：pip install playwright && playwright install chromium
"""

import json, sys, re
from pathlib import Path

SKILL_DIR = Path(__file__).parent
EXTRACT_JS = (SKILL_DIR / "extract.js").read_text()
OUTPUT_PATH = Path("/tmp/mp_all_publish_data.json")
USER_DATA_DIR = Path.home() / ".mp-data-browser"

LOGIN_URL = "https://mp.weixin.qq.com/"
PUBLISH_URL = "https://mp.weixin.qq.com/cgi-bin/appmsgpublish?sub=list&begin={begin}&count=10&token={token}&lang=zh_CN"


def extract_token(url):
    m = re.search(r'token=(\d+)', url)
    return m.group(1) if m else None


def ensure_login(page):
    """确保已登录，未登录则等待扫码。返回 token。"""
    page.goto(LOGIN_URL, wait_until="networkidle", timeout=15000)

    token = extract_token(page.url)
    if token:
        return token

    has_qr = page.locator(".login__type__container__scan, .login__type__container_scan, .qrcode").first
    if has_qr.count():
        print("请用微信扫描浏览器中的二维码登录公众号后台...")
    else:
        print("等待页面加载，如需登录请在弹出的浏览器中操作...")

    for _ in range(60):
        page.wait_for_timeout(3000)
        token = extract_token(page.url)
        if token:
            print("登录成功！")
            return token
        try:
            page.evaluate("() => 1")
        except Exception:
            page.wait_for_timeout(2000)
            token = extract_token(page.url)
            if token:
                print("登录成功！")
                return token

    return None


def get_account_name(page):
    """获取当前登录的公众号名称"""
    return page.evaluate("""
        () => {
            var el = document.querySelector('.weui-desktop-account__nickname') ||
                     document.querySelector('.nickname') ||
                     document.querySelector('[class*=account] [class*=name]');
            return el ? el.innerText.trim() : '';
        }
    """) or "未知公众号"


def scrape_page(page, token, page_num):
    begin = page_num * 10
    url = PUBLISH_URL.format(begin=begin, token=token)
    page.goto(url, wait_until="networkidle", timeout=15000)
    page.wait_for_timeout(2000)
    result = page.evaluate(EXTRACT_JS)
    if isinstance(result, str):
        try:
            return json.loads(result)
        except json.JSONDecodeError:
            return []
    return result if isinstance(result, list) else []


def scrape_all(page, token, max_pages=100):
    all_articles = []
    for p in range(max_pages):
        articles = scrape_page(page, token, p)
        if not articles:
            print(f"Page {p + 1}: empty, stopping")
            break
        for a in articles:
            a["page"] = p + 1
        all_articles.extend(articles)
        print(f"Page {p + 1}: {len(articles)} articles (total: {len(all_articles)})")
        if len(articles) < 10:
            break
    return all_articles


def main():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("ERROR: 需要安装 Playwright")
        print("运行: pip install playwright && playwright install chromium")
        sys.exit(1)

    print("=== 公众号数据抓取 ===\n")

    with sync_playwright() as pw:
        print("启动浏览器...")
        context = pw.chromium.launch_persistent_context(
            str(USER_DATA_DIR),
            headless=False,
            args=["--disable-blink-features=AutomationControlled"],
            viewport={"width": 1280, "height": 800},
        )
        page = context.pages[0] if context.pages else context.new_page()

        print("检查登录态...")
        token = ensure_login(page)
        if not token:
            print("ERROR: 登录超时（3 分钟），请重试")
            context.close()
            sys.exit(1)

        account = get_account_name(page)
        print(f"当前公众号: {account}")
        print(f"Token: {token}\n")

        print("开始抓取...\n")
        articles = scrape_all(page, token)

        context.close()

    OUTPUT_PATH.write_text(json.dumps(articles, ensure_ascii=False, indent=2))
    print(f"\n共 {len(articles)} 篇文章，已保存到 {OUTPUT_PATH}")
    return articles


if __name__ == "__main__":
    main()

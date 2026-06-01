#!/usr/bin/env python3
"""
飞书 API 公共模块
提供 .env 加载、认证、带重试的 API 请求等基础能力，
供 feishu_wiki_fetcher.py 和 feishu_wiki_uploader.py 共用。
"""

import os
import sys
import time
from pathlib import Path

try:
    import requests
except ImportError:
    print("需要安装 requests: pip install requests")
    sys.exit(1)

# ═══════════════════════════════════════════════════════════
# 路径常量
# ═══════════════════════════════════════════════════════════
SCRIPT_DIR = Path(__file__).parent.resolve()
VAULT_DIR = SCRIPT_DIR.parent.parent  # 00.系统/scripts/ → vault root

# ═══════════════════════════════════════════════════════════
# API 常量
# ═══════════════════════════════════════════════════════════
BASE_URL = "https://open.feishu.cn/open-apis"
DELAY = 0.35       # API 调用间隔（秒），避免触发限流
MAX_RETRY = 3      # 最大重试次数


# ═══════════════════════════════════════════════════════════
# 凭据加载（优先级：环境变量 > OpenClaw 配置 > .env 文件）
# ═══════════════════════════════════════════════════════════
def _load_from_openclaw():
    """从 OpenClaw 配置文件读取飞书凭据（与飞书插件共用同一个应用）"""
    import json as _json
    for config_path in [
        Path.home() / ".openclaw" / "openclaw.json",
        Path.home() / ".openclaw-dev" / "openclaw.json",
    ]:
        if config_path.exists():
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    cfg = _json.load(f)
                feishu = cfg.get("channels", {}).get("feishu", {})
                app_id = feishu.get("appId", "")
                app_secret = feishu.get("appSecret", "")
                if app_id and app_secret:
                    return app_id, app_secret
            except (ValueError, KeyError):
                pass
    return None, None


def _load_from_env_file():
    """从 .env 文件加载飞书凭据"""
    vault_root = VAULT_DIR
    for env_candidate in [vault_root / "00.系统" / ".env", SCRIPT_DIR / ".env"]:
        if env_candidate.exists():
            for line in env_candidate.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())
            break
    return os.environ.get("FEISHU_APP_ID", ""), os.environ.get("FEISHU_APP_SECRET", "")


def load_env():
    """
    加载飞书凭据，优先级：
    1. 环境变量 FEISHU_APP_ID / FEISHU_APP_SECRET
    2. OpenClaw 配置 (~/.openclaw/config.json → channels.feishu)
    3. .env 文件 (00.系统/.env 或 scripts/.env)
    """
    # 1. 环境变量
    app_id = os.environ.get("FEISHU_APP_ID", "")
    app_secret = os.environ.get("FEISHU_APP_SECRET", "")
    if app_id and app_secret:
        return app_id, app_secret

    # 2. OpenClaw 配置（与飞书插件共用凭据）
    app_id, app_secret = _load_from_openclaw()
    if app_id and app_secret:
        return app_id, app_secret

    # 3. .env 文件
    app_id, app_secret = _load_from_env_file()
    if app_id and app_secret:
        return app_id, app_secret

    print("❌ 缺少飞书凭据。支持以下方式配置：")
    print("   1. 环境变量 FEISHU_APP_ID + FEISHU_APP_SECRET")
    print("   2. OpenClaw 配置 (~/.openclaw/config.json → channels.feishu)")
    print("   3. .env 文件 (00.系统/.env)")
    sys.exit(1)


# 惰性加载：仅在实际使用时才读取 .env（避免 import 时因缺少 .env 而退出）
APP_ID = None
APP_SECRET = None


def get_credentials():
    """获取飞书凭据（首次调用时从 .env 加载）"""
    global APP_ID, APP_SECRET
    if APP_ID is None or APP_SECRET is None:
        APP_ID, APP_SECRET = load_env()
    return APP_ID, APP_SECRET


# ═══════════════════════════════════════════════════════════
# 飞书 API 基础客户端
# ═══════════════════════════════════════════════════════════
class FeishuClient:
    """
    飞书 API 基础客户端，提供：
    - authenticate()  认证并获取 tenant_access_token
    - _get()          带重试的 GET 请求
    - _post()         带重试的 POST 请求（支持 raw 模式）
    - _request()      底层请求方法，含限流自动重试
    """

    def __init__(self):
        self.session = requests.Session()
        self.token = None

    def authenticate(self):
        """获取 tenant_access_token 并设置到 session headers"""
        app_id, app_secret = get_credentials()
        resp = self._post(
            "/auth/v3/tenant_access_token/internal",
            json={"app_id": app_id, "app_secret": app_secret},
            raw=True,
        )
        data = resp.json()
        if data.get("code") != 0:
            raise Exception(f"认证失败: {data.get('msg', data)}")
        self.token = data["tenant_access_token"]
        self.session.headers.update({"Authorization": f"Bearer {self.token}"})
        print("✓ 飞书认证成功")

    # ─── 内部请求方法 ─────────────────────────────
    def _get(self, path, params=None):
        """带重试的 GET 请求"""
        return self._request("GET", path, params=params)

    def _post(self, path, json=None, raw=False):
        """带重试的 POST 请求。raw=True 时返回原始 Response 对象（用于认证等特殊场景）。"""
        if raw:
            resp = self.session.post(f"{BASE_URL}{path}", json=json)
            return resp
        return self._request("POST", path, json=json)

    def _request(self, method, path, **kwargs):
        """底层请求方法，包含限流自动重试逻辑"""
        url = f"{BASE_URL}{path}"
        for attempt in range(MAX_RETRY):
            try:
                resp = self.session.request(method, url, **kwargs)
                data = resp.json()
                code = data.get("code", -1)
                if code == 0:
                    return data
                # 频率限制，等待后重试
                if code == 99991400:
                    wait = 2 ** (attempt + 1)
                    print(f"    ⚠ 触发限流，等待 {wait}s...")
                    time.sleep(wait)
                    continue
                raise Exception(f"API错误 code={code}: {data.get('msg', '')}")
            except requests.RequestException as e:
                if attempt < MAX_RETRY - 1:
                    time.sleep(2 ** (attempt + 1))
                    continue
                raise Exception(f"请求失败: {e}")
        raise Exception(f"达到最大重试次数 ({MAX_RETRY})")

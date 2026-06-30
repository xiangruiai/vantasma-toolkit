# 部署与域名绑定

祥瑞白板录制工具建议部署到 Cloudflare Pages，然后在火山引擎 TrafficRoute DNS 里绑定 `xiangruiai.com` 的子域名。

## 当前域名现状

从 DNS 查询看，现有个人主页已经走 Cloudflare Pages：

| 域名 | 当前指向 |
|---|---|
| `www.xiangruiai.com` | `xiangruiai.pages.dev` |
| `dengxiabai.xiangruiai.com` | `dengxiabai.pages.dev` |
| `waytoagi-edu.xiangruiai.com` | `waytoagi-edu.pages.dev` |

所以不要直接改 `www.xiangruiai.com`，它是个人主页。白板录制工具建议使用：

```text
whiteboard.xiangruiai.com
```

也可以换成 `record.xiangruiai.com`、`board.xiangruiai.com` 或 `tools.xiangruiai.com`。

## GitHub 仓库

源码放在工具箱仓库里，不再单独维护白板工具仓库：

```text
https://github.com/xiangruiai/vantasma-toolkit/tree/main/apps/whiteboard-recorder
```

当前本地项目来自 `excalicord` fork，发布时需要保留第三方来源说明。完整来源说明见：

```text
THIRD_PARTY_NOTICES.md
```

## Cloudflare Pages 设置

1. 打开 Cloudflare Pages，创建项目。
2. 连接 GitHub 仓库 `xiangruiai/vantasma-toolkit`。
3. 设置构建参数：

```text
Framework preset: Vite
Build command: npm ci && npm run build
Build output directory: dist
Root directory: apps/whiteboard-recorder
Node.js version: 20 或 22
```

项目根目录带有 `wrangler.toml`，Cloudflare CLI 部署时会读取：

```text
name = "vantasma-whiteboard-recorder"
pages_build_output_dir = "dist"
```

也可以在子目录里直接部署：

```bash
cd apps/whiteboard-recorder
npm run deploy:cloudflare
```

部署后需要在 Cloudflare Pages 的环境变量中配置：

```text
RESEND_API_KEY
```

否则移动端“发送桌面打开链接”这个功能会返回邮件服务未配置。

4. 部署成功后会得到一个 `*.pages.dev` 地址，例如：

```text
vantasma-whiteboard-recorder.pages.dev
```

5. 在 Cloudflare Pages 项目里添加 Custom domain：

```text
whiteboard.xiangruiai.com
```

## 火山引擎 DNS 记录

在火山引擎 TrafficRoute DNS 套件中添加一条记录：

| 字段 | 值 |
|---|---|
| 记录类型 | `CNAME` |
| 主机记录 | `whiteboard` |
| 线路 | 默认 |
| 记录值 | Cloudflare Pages 给出的 `*.pages.dev` 地址 |
| TTL | 10 分钟 |

示例：

```text
whiteboard.xiangruiai.com CNAME <Cloudflare Pages 分配的 pages.dev 地址>
```

如果 Cloudflare Pages 要求 TXT 验证，按页面提示再添加一条 TXT 记录即可。

## 验证

DNS 生效后执行：

```bash
dig +short whiteboard.xiangruiai.com CNAME
curl -I https://whiteboard.xiangruiai.com
```

预期结果：

- CNAME 指向对应 `*.pages.dev`
- HTTPS 返回 `200`
- 摄像头、麦克风、录屏能力只能在 HTTPS 或 localhost 下正常工作

## 备用方案：Vercel

项目里保留了 `vercel.json`，也可以部署到 Vercel。若用 Vercel，域名记录通常改为：

```text
whiteboard.xiangruiai.com CNAME cname.vercel-dns.com
```

但当前 `xiangruiai.com` 体系已经在用 Cloudflare Pages，所以优先建议继续用 Cloudflare Pages。

# feishu-multi

> 对 AI 说一句“帮我双开飞书”，在 macOS 上同时运行两个原生飞书客户端，分别登录两个账号。

这不是 Lark，也不是网页版，更不需要安装第三方双开器。这个 Skill 会基于你电脑里已经安装的中国版飞书官网客户端，生成一个独立的“飞书双开.app”。

## ✦ 能做什么

- 同时运行官网版飞书和第二个原生飞书
- 两个客户端使用独立登录态，分别登录不同账号
- 飞书升级后自动检测版本并安全重建副本
- 只退出第二个飞书，不影响官网版飞书
- 检查副本版本、进程、签名和数据目录
- 重建前归档旧副本，不删除第二账号的数据

## ✦ 它是怎么实现的

飞书 macOS 客户端的 App 包内部仍使用 `Lark.app`、`com.electron.lark` 等技术标识，这不代表安装的是国际版 Lark。

这个 Skill 会：

1. 复制已安装的飞书官网版客户端
2. 把副本的 Bundle ID 从 `com.electron.lark` 隔离为 `com.electron.lar2`
3. 把数据目录标识从 `LarkShell` 隔离为 `LarkDual2`
4. 对修改过的 Mach-O、dylib、Helper、Framework 和主 App 逐层重新签名
5. 使用 Hardened Runtime 与 Electron 所需的最小 entitlements 启动副本

默认结果：

| 项目 | 位置 |
|---|---|
| 官网版飞书 | `/Applications/Lark.app` |
| 双开副本 | `/Applications/飞书双开.app` |
| 第二账号数据 | `~/Library/Application Support/LarkDual2` |
| 旧副本归档 | `~/Applications/Feishu Multi Backups/` |

如果 `/Applications` 不可写，副本会自动安装到 `~/Applications/飞书双开.app`。

## ✦ 环境要求

- macOS
- 已从飞书官网安装中国版飞书客户端
- 源 App 的 Bundle ID 为 `com.electron.lark`
- Claude Code、Codex 或其他支持 Agent Skills 的 AI 编程工具

脚本只调用 macOS 自带的 `codesign`、`ditto`、`PlistBuddy`、`perl` 等工具，没有第三方运行时依赖。

当前已在 Apple Silicon Mac、飞书 `131.0.6778.268` 上完成真实双实例验证。Intel Mac 和未来改变内部结构的飞书版本尚未实测，脚本遇到不兼容结构时会在替换旧副本前停止。

## ✦ 安装

### 让 Agent 自动安装（推荐）

把下面这句话贴给 Codex、Claude Code 或其他支持 Skill 的 Agent：

> **帮我安装 https://github.com/xiangruiai/vantasma-toolkit 里的 feishu-multi skill，路径是 skills/飞书办公/feishu-multi。安装到当前 Agent 的 skills 目录，检查脚本权限并运行 status；确认无误后告诉我重启或开启新对话，再用“帮我双开飞书”触发。**

Codex 也可以使用自带的 `skill-installer` 从 GitHub 路径安装。

### Codex 手动安装

```bash
python3 ~/.codex/skills/.system/skill-installer/scripts/install-skill-from-github.py \
  --repo xiangruiai/vantasma-toolkit \
  --path 'skills/飞书办公/feishu-multi'
```

安装后开启一个新对话，让 Codex 重新发现 Skill。

### Claude Code 手动安装

```bash
git clone https://github.com/xiangruiai/vantasma-toolkit.git
cp -R 'vantasma-toolkit/skills/飞书办公/feishu-multi' ~/.claude/skills/
```

安装后重启 Claude Code。

## ✦ 用法

安装后直接对 Agent 说：

- “帮我双开飞书”
- “再开一个飞书”
- “检查飞书双开是否正常”
- “飞书升级了，重建双开”
- “退出第二个飞书”

也可以直接运行脚本：

```bash
bash scripts/feishu-multi.sh auto
```

| 命令 | 行为 |
|---|---|
| `auto` | 自动检查，必要时重建，然后启动两个飞书 |
| `setup` | 创建副本，但暂不启动 |
| `start` | 启动官网版和已有副本 |
| `rebuild` | 归档旧副本，按当前官网版重建并启动 |
| `status` | 查看版本、PID、签名和数据目录 |
| `stop` | 只退出第二个飞书 |

查看全部参数：

```bash
bash scripts/feishu-multi.sh --help
```

如果官网版飞书不在默认位置：

```bash
bash scripts/feishu-multi.sh auto --source-app '/自定义路径/Lark.app'
```

## ✦ 安全设计

- 不修改官网版飞书
- 不删除聊天记录和登录数据
- 新副本完整构建并验签后，才替换现有副本
- 旧副本移动到可恢复的归档目录
- 拒绝把副本目标设置为官网版飞书本体
- 新版飞书结构不兼容时提前停止，不盲目替换二进制
- 不上传账号、聊天记录或任何飞书数据

## ✦ 常见问题

### 为什么源 App 叫 Lark.app？

这是中国版飞书官网客户端在 macOS App 包内使用的文件名和技术标识。脚本会严格校验本地已安装客户端，不会下载或改用国际版 Lark。

### 飞书更新后第二个客户端打不开怎么办？

对 Agent 说“飞书升级了，重建双开”，或者运行：

```bash
bash scripts/feishu-multi.sh rebuild
```

第二账号的数据目录不会因为重建 App 而删除。

### 首次打开需要重新登录吗？

第一次创建副本时需要在第二个飞书里登录账号。以后重建会继续复用 `LarkDual2` 数据目录。

### 会不会影响飞书自动更新？

官网版飞书保持原样。官网版更新后，副本不会自动继承新二进制；下次运行 `auto` 时会检测版本差异并重建。

## ✦ 免责声明

本项目与飞书、字节跳动及其关联公司无关，也未获得其授权或背书。飞书、Lark 等名称及商标归各自权利人所有。

客户端升级可能改变内部结构。使用前请确认自己有权在当前设备和账号上运行客户端，一切使用后果由使用者自行承担。

## License

MIT。见 [LICENSE](LICENSE)。

---

## ✦ 关于作者

本 Skill 来自 **万涂幻象多维表格社区**：民间最大的飞书多维表格生态社区，围绕让 AI 真正落地沉淀内容、社区、产品与系统。更多工具与介绍见[仓库主页](../../../README.md)。

| | |
|---|---|
| 🌐 个人主页 | https://www.xiangruiai.com |
| 🏠 社区主页 | https://vantasma.feishu.cn/wiki/MC1nwBft0izODokXe4acHKjZnsh |
| 📚 开源知识库（飞书 Wiki · 311+ 篇） | https://vantasma.feishu.cn/wiki/space/7574356946532925441 |
| ✉️ 联系 | li@xiangruiai.com |

---

**万涂幻象出品** · 作者 **祥瑞** · 个人网站 [www.xiangruiai.com](https://www.xiangruiai.com)

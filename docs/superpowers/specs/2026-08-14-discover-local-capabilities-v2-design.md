# discover-local-capabilities v2 设计规格

日期：2026-08-14  
状态：已确认方向，待实现  
目标目录：`skills/Agent能力/discover-local-capabilities`

## 1. 背景

现有 Skill 能扫描少量本机能力并生成 Markdown 与 JSON，但它把作者常用工具写进 `DEFAULT_CLIS` 和 `routing-rules.json`。其他人安装后虽然不会获得作者的能力本体，却会继承作者的候选工具和路由偏好。

现有实现还存在以下缺口：

- Skill 只扫描根目录下一层，漏掉 `.system`、插件内嵌 Skill 和深层项目 Skill。
- CLI 只扫描固定白名单，不是安装者 `PATH` 中的完整库存。
- 插件只取缓存顶层目录名，可能把发布者或仓库名误当成插件。
- MCP 同名来源会互相覆盖，且报告没有完整表达状态边界。
- 软链接按真实路径去重后，没有保留所有可见位置。
- 报告会写入主机名、平台详情和未经统一脱敏的 Skill 描述。
- 能力地图生成后没有形成持久的 Agent 路由闭环。

v2 要把它重构成一个中立、可解释、可回滚的本机能力发现与自然语言路由系统。

## 2. 第一性原理

本系统遵循以下原则：

1. 能力来自安装者的电脑，不来自作者的模板。
2. 发现能力不等于安装、认证或验证能力。
3. 完整库存与日常路由分离，避免丢能力，也避免浪费 Agent 上下文。
4. 路由依据本机证据和通用语义，不写死具体工具名称或作者偏好。
5. Agent 收到自然语言任务后先查地图，再读取具体 Skill 或工具说明，最后验证并执行。
6. 所有配置写入必须先展示计划并得到当次明确确认。
7. 所有修改都可识别、可更新、可备份、可回滚、可卸载。
8. 本机能力清单本身属于隐私数据，默认不联网、不上传、不提交进仓库。

## 3. 使用者体验

### 3.1 首次初始化

使用者可以直接说：

```text
扫描我的电脑有哪些 Skill、CLI、MCP 和插件，生成能力地图。
```

Agent 执行只读计划：

1. 扫描本机能力。
2. 检测普通本地目录和已知 Obsidian Vault 候选。
3. 检测 Codex、Claude Code 的当前有效指令文件。
4. 展示将创建、修改和备份的绝对路径。
5. 让使用者选择存储位置、Agent 类型和用户级或项目级作用域。

计划阶段不得写入任何文件。使用者明确确认后，Agent 才执行安装。

### 3.2 安装回执

完成后必须明确显示：

- 人类可读能力地图路径。
- 完整脱敏库存路径。
- 私有路径解析索引路径。
- 配置和安装回执路径。
- Agent 指令文件及备份路径。
- Skill、CLI、MCP、插件、未分类项和扫描诊断数量。
- 需要重启或新开哪些 Agent 会话。
- 可以直接使用的自然语言示例。

### 3.3 日常自然语言调用

Agent 的托管规则要求：

```text
收到需要本机工具或本机能力的任务
→ 读取精简能力地图
→ 根据任务语义匹配场景和候选能力
→ 必要时读取完整库存与私有解析索引
→ 如果候选是 Skill，完整读取对应 SKILL.md
→ 检查认证、权限、依赖和任务级可用性
→ 执行并返回证据
```

使用者还可以直接问：

- “我的电脑能做什么？”
- “能力地图怎么用？”
- “能力地图放在哪里？”
- “帮我找一个能处理视频的本机能力。”
- “刚装了一个 Skill，刷新能力地图。”
- “把能力地图迁移到另一个 Obsidian Vault。”
- “卸载能力地图路由，但保留地图数据。”

## 4. 系统架构

### 4.1 模块边界

生产代码使用 Python 标准库，拆成可独立测试的模块：

```text
scripts/
├── capability_map.py              命令入口
├── scan_capabilities.py           旧命令兼容入口
└── capability_map_core/
    ├── models.py                  数据模型与 schema
    ├── roots.py                   跨平台根目录发现
    ├── skills.py                  Skill 采集器
    ├── clis.py                    PATH CLI 采集器
    ├── connectors.py              MCP 与插件采集器
    ├── sanitize.py                统一脱敏
    ├── classify.py                动态分类与查询路由
    ├── render.py                  Markdown 与 JSON 输出
    ├── storage.py                 本地与 Obsidian 存储
    ├── instructions.py            Agent 托管块安装
    └── transactions.py            原子写入、备份与回滚
```

### 4.2 统一能力模型

每项能力至少包含：

```text
id
kind                       skill | cli | mcp | plugin
name
description
aliases
tags
scenes
source_locations           脱敏后的所有可见位置
resolver_id                指向私有解析索引
scope                      user | project | system | plugin | extra
provider
version
states.discovered
states.probed
states.authenticated
states.verified
classification_confidence
diagnostics
```

扫描器只能证明 `discovered`。默认情况下，其他状态为 `unknown`。版本探测成功后才能设置 `probed=success`；超时、错误和无输出必须分别记录，不能统一标为已探测。

### 4.3 发现流水线

流水线固定为：

```text
RootProvider
→ Skill / CLI / MCP / Plugin Collectors
→ Normalizer
→ Sanitizer
→ Classifier
→ Reporter
→ Storage
```

每个采集器失败时写入诊断，不应导致其他采集器丢失结果。只有 schema、事务或目标路径错误才终止整体写入。

## 5. 完整能力发现

### 5.1 Skill

扫描以下来源：

- Codex、Claude Code、共享 Agent 的用户级 Skill 根目录。
- 当前项目中的 `.codex/skills`、`.claude/skills`、`.agents/skills`。
- Codex 和 Claude 插件目录中的嵌套 Skill。
- `.system` 等隐藏 Skill 目录。
- 使用者显式传入的额外根目录。

递归遍历必须：

- 跟随 Skill 根内的软链接。
- 使用 inode、file-id 或规范化真实路径防止循环。
- 按物理 `SKILL.md` 去重。
- 保留每个可见路径、scope 和 provider。
- 对断链、权限拒绝、解析失败和越界链接生成诊断。
- 使用可靠 YAML frontmatter 读取逻辑，并对无效 YAML 降级到目录名。

### 5.2 CLI

默认枚举安装者 `PATH` 中全部可执行入口：

- Unix 检查普通文件和执行位。
- Windows 使用 `PATHEXT` 并处理大小写。
- 同名 CLI 按 PATH 顺序保存 shadow chain，第一项标记为 effective。
- 完整库存保存所有入口，Markdown 只展示有明确语义的候选和汇总。
- 不能可靠分类的 CLI 放入“待人工归类”，不能丢弃。

默认不得执行 CLI。只有显式版本探测时才允许运行安全版本命令，并必须使用 `shell=False`、`stdin=DEVNULL`、最小环境、短超时、输出上限和统一脱敏。

### 5.3 MCP

使用配置适配器识别：

- Codex TOML。
- Claude JSON。
- 项目 `.mcp.json`。
- VS Code `.vscode/mcp.json`。
- 插件 manifest 中声明的 MCP。

公开库存只允许保存名称、启用状态、scope、provider 和 transport 类型。禁止持久化 command、args、URL、headers、env、token 或任意配置值。同名 MCP 的不同来源必须保留，不能覆盖。

### 5.4 插件

递归识别真实插件 manifest，例如：

- `.codex-plugin/plugin.json`
- `.claude-plugin/plugin.json`
- 受支持的 marketplace 或安装记录

插件以 manifest 中的 name、version 和 provider 标识。缓存顶层目录不能直接当作插件。插件内 Skill 同时进入 Skill 采集器，但两种实体分别保留。

## 6. 中立分类与路由

发布包不得包含作者私有能力快照或具体工具优先列表。

分类器只包含通用场景定义和通用评分原则：

- Skill frontmatter 的 tags、name、description 权重最高。
- 插件 manifest 的 description、keywords 次之。
- CLI 名称、别名和来源目录作为低权重信号。
- 当前任务查询与能力文本的词元重合决定动态匹配分数。
- 专用能力优先于无法说明用途的通用入口。
- 分类置信度不足时进入“待人工归类”。
- 不通过名称子串臆造用途，不因作者常用某工具就设为首选。

使用者可以在生成后的配置中添加个人别名、分类和路由覆盖。这些覆盖只属于使用者本机，不进入开源仓库。

## 7. 双层地图与私有解析索引

### 7.1 使用者选择的目录

普通目录模式默认建议：

- macOS：`~/Library/Application Support/Vantasma/Agent能力地图/`
- Linux：`${XDG_DATA_HOME:-~/.local/share}/vantasma/agent-capabilities/`
- Windows：`%LOCALAPPDATA%\Vantasma\Agent能力地图\`

Obsidian 模式默认建议 `<vault>/Agent/本机能力地图/`，允许使用者修改名称和位置。

### 7.2 文件结构

使用者选择的位置保存可阅读、可同步、可分享前审查的文件：

```text
<storage-root>/Agent能力地图/
├── 本机能力地图.md
├── capability-inventory.json
├── capability-map.config.json
└── setup-receipt.md
```

精简 Markdown 包含：

- 使用方式。
- 场景反向索引。
- 状态边界。
- 待人工归类摘要。
- 刷新、迁移、卸载和求助方式。

完整 JSON 包含全部脱敏能力和诊断，不包含真实机密值。

### 7.3 私有解析索引

为了让 Agent 能找到真实文件，同时避免 Obsidian 同步或分享时暴露绝对路径，真实路径单独写入系统数据目录：

```text
<private-data-root>/capability-resolver.json
```

要求：

- Unix 权限为 `0600`。
- 不写入 Obsidian Vault。
- 不进入 Markdown 或公开库存。
- 每项通过 `resolver_id` 与公开库存关联。
- Agent 只有在执行候选能力时才读取。
- 安装回执明确说明它的位置和隐私属性。

## 8. Agent 托管规则

### 8.1 支持目标

首版支持：

- Codex 用户级：当前有效的 `$CODEX_HOME/AGENTS.override.md` 或 `$CODEX_HOME/AGENTS.md`。
- Codex 项目级：项目根 `AGENTS.md`。
- Claude Code 用户级：`~/.claude/CLAUDE.md`。
- Claude Code 项目级：项目根 `CLAUDE.md`。

Codex 官方说明指出，全局非空 `AGENTS.override.md` 会遮蔽 `AGENTS.md`。安装器必须检测当前有效文件并向使用者解释，不得默默写入不会生效的文件。

参考：

- https://learn.chatgpt.com/docs/agent-configuration/agents-md
- https://docs.anthropic.com/zh-CN/docs/claude-code/memory

### 8.2 托管块

托管块使用稳定标记：

```md
<!-- vantasma:discover-local-capabilities:start id=<installation-id> schema=1 -->
## 本机能力路由

处理需要本机工具或本机能力的任务前，先读取 `<map-path>`。
需要解析真实位置时读取 `<resolver-path>`。
如果候选是 Skill，完整读取其 SKILL.md。
已发现不等于已认证或已验证，执行前检查权限、依赖和任务级可用性。
刷新、迁移、求助或卸载请求交给 discover-local-capabilities。
<!-- vantasma:discover-local-capabilities:end -->
```

更新只替换同一 installation id 的完整块。重复块、标记损坏、结束标记缺失或块外冲突必须停止并展示诊断。

### 8.3 事务与回滚

每次修改前：

1. 保存原文件、权限、换行风格和 SHA-256。
2. 在同目录临时文件中生成新内容。
3. 校验托管块和文件 hash。
4. 原子替换目标。
5. 任一步失败时按 manifest 回滚本次已修改文件。

卸载默认只移除托管块，保留地图和使用者其他内容。清理地图数据需要单独确认。迁移先写新位置并验证，再更新托管块；旧数据默认保留。

## 9. 命令接口

新入口：

```text
capability_map.py scan
capability_map.py setup plan
capability_map.py setup apply --confirmed --expected-plan-hash HASH
capability_map.py status
capability_map.py paths
capability_map.py refresh --dry-run | --confirmed
capability_map.py route --query TEXT --json
capability_map.py migrate --to PATH --dry-run | --confirmed
capability_map.py uninstall --dry-run | --confirmed [--purge-data]
```

`setup plan` 必须零写入，并在 stdout 返回确定性的 plan 与 hash。`setup apply` 使用同样参数重新计算计划，hash 不一致时拒绝执行，防止确认后目标发生变化。

保留 `scan_capabilities.py` 作为兼容入口，映射到 `capability_map.py scan`。

## 10. 隐私和安全

所有输入均视为不可信，包括 Skill frontmatter、CLI 名称、MCP 名称、插件 manifest、PATH、软链接和版本输出。

所有进入 Markdown、JSON、stdout 的文本必须先经过统一 `sanitize()`：

- 不输出 hostname、用户名和完整平台指纹。
- Home 路径转换为 `~/...`。
- Skill 描述中的 Unix、Windows 和 `file://` 绝对路径统一脱敏。
- Bearer、JWT、GitHub/OpenAI/AWS key，以及 `token|secret|password|api_key=...` 统一替换为 `<redacted>`。
- 删除控制字符，转义 Markdown 表格符和换行，并限制字段长度。
- 版本 stdout 和 stderr 使用相同脱敏。
- 生成物不得被仓库默认收集，仓库示例只能使用合成 fixture。

脚本本身不得联网、上传、安装、更新、授权或调用发现到的能力。版本探测是唯一允许执行发现项的路径，且默认关闭。

## 11. 错误处理

- 单个 Skill、CLI、MCP 或插件读取失败时记录诊断并继续。
- 权限拒绝、断链、循环、无效 YAML/JSON/TOML 和无法解码内容分别编码。
- 输出写入采用 staging 目录和原子替换，失败不得留下看似完整的半成品。
- 私有解析索引写入失败时，不安装 Agent 路由。
- Agent 指令文件冲突或托管块损坏时，不自动修复用户内容。
- Obsidian 配置不可读时，允许手动指定 Vault，不扫描 Vault 内容。
- 路由无可靠候选时返回“未命中”及待人工分类项，不编造工具。

## 12. 测试策略

使用标准库 `unittest`、`TemporaryDirectory` 和 `unittest.mock`，严格遵循 RED、GREEN、REFACTOR。

### 12.1 发现测试

- 隐藏、嵌套、项目级和插件内 Skill。
- 软链接环、断链、多入口、同名不同物理 Skill。
- 非 UTF-8、BOM、多行 YAML、无效 frontmatter、权限拒绝。
- PATH 重复目录、空段、相对路径、Unicode、空格、同名 shadow。
- Unix 执行位和 Windows PATHEXT、大小写。
- 真实插件 manifest、多版本插件和缓存发布者目录。
- MCP 同名多来源、损坏配置和恶意超大配置。
- 数千 Skill 与 CLI 下的时间和内存上限。

### 12.2 隐私测试

- 默认扫描不得调用 `subprocess.run` 或网络 API。
- hostname、用户名、Home 路径、外部路径和 Skill 描述中的 canary 全部脱敏。
- token、JWT、GitHub/OpenAI/AWS key 在 Markdown、JSON、stdout 中零命中。
- MCP 公开 schema 不包含 command、args、URL、headers、env 或值。
- 版本探测使用最小环境、短超时、输出上限和统一脱敏。

### 12.3 存储和路由测试

- `setup plan` 零写入。
- 首次安装、重复安装和版本更新幂等。
- macOS、Linux、Windows 默认目录。
- 多 Vault、中文、空格、长路径、iCloud 和网络盘路径。
- Codex override 遮蔽检测。
- CRLF、权限和现有用户内容保持。
- 托管块损坏、重复标记和块外冲突。
- 中途失败自动回滚。
- 迁移先新后旧，卸载后用户内容不变。
- 新会话能从指令文件找到地图和解析索引。

### 12.4 自然语言与路由测试

- “怎么用”“地图在哪”“刷新”“迁移”“卸载”能够映射到正确操作。
- 任务查询只按本机能力文本与通用语义评分。
- 缺少作者工具时仍能生成完整地图。
- 未分类能力保留在库存中。
- 路由命中后能解析 Skill 路径，并提示先读 `SKILL.md`。

## 13. 发布门禁

只有同时满足以下条件才能替换 GitHub 原版本：

1. 全部单元测试与集成测试通过。
2. Skill `quick_validate.py` 通过。
3. 合成 DLP canary 在 Markdown、JSON 和 stdout 中零泄露。
4. 默认执行能力和网络调用均为零。
5. 仓库中不存在真实 `capability-map.*`、真实本机快照、作者私有路由偏好、`/Users/`、`/home/` 或 secret pattern。
6. 文档、命令接口、schema 和实际行为一致。
7. 在隔离临时 Home 中完成一次首次安装、刷新、路由、迁移和卸载闭环。
8. README 和仓库 Skill 清单同步更新。

## 14. 非目标

v2 不负责：

- 自动安装缺失能力。
- 自动登录、授权或获取凭证。
- 自动证明某项能力已认证或已验证。
- 上传能力地图到云端。
- 为未识别工具编造用途。
- 把万涂幻象本机能力快照发布给安装者。
- 在未确认时修改 Obsidian、AGENTS.md、CLAUDE.md 或其他用户文件。


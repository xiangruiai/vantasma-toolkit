# 本机能力地图

`discover-local-capabilities` 安装的是一套中立的 discovery 与 routing logic。它扫描安装者的电脑，盘点本机已有的 Skill、PATH CLI、MCP server 和 plugin，再生成可审查的能力地图与自然语言路由闭环。

安装这个 Skill 不会复制作者的工具、偏好或能力快照，也不会预置某个具体工具为首选。分类只依据安装者机器上的名称、说明、标签、manifest 和通用场景语义；证据不足的能力会保留在“待人工归类”。

通用场景定义位于 [`references/scene-taxonomy.json`](references/scene-taxonomy.json)。它只包含中立的中英文语义，不包含具体工具优先列表。

## 安装 Skill 包

把仓库中的 Skill 目录复制到目标 Agent 的 Skill root，然后重启或新开该 Agent 会话：

```bash
cp -R "<repo-root>/skills/Agent能力/discover-local-capabilities" "<agent-skill-root>/"
```

这一步只安装发现逻辑，不会生成能力地图或改 Agent 指令。后续 setup 仍须先展示零写入计划，并单独取得当次明确确认。

## 一句话使用

安装后可以直接对 Agent 说：

```text
扫描我的电脑有哪些 Skill、CLI、MCP 和插件，生成能力地图。
```

Agent 会先让你选择存储位置、Agent 和作用域，执行零写入计划，展示将涉及的绝对路径。只有得到当次明确确认后，它才能写入地图和托管指令。完成后 Agent 必须告知本次操作返回的精确位置，并提醒这些 stdout 信息应作为私有运维输出处理。

日常也可以直接说：

```text
我的电脑能做什么？
能力地图放在哪里？
帮我找一个能处理视频的本机能力。
刚装了一个 Skill，刷新能力地图。
把能力地图迁移到另一个目录。
卸载能力地图路由，但保留地图数据。
```

## 发现范围

- 递归发现 Codex、Claude Code、共享 Agent、当前项目和插件内嵌的 `SKILL.md`
- 合并同一物理 Skill 的软链接入口，同时保留所有可见来源
- 枚举安装者 `PATH` 中的完整可执行库存与 shadow chain
- 从受支持的配置和 manifest 发现 MCP 与 plugin，只公开允许的元数据
- 生成完整脱敏库存与按场景压缩的日常地图
- 区分 `discovered`、`probed`、`authenticated`、`verified` 四种状态

扫描只证明能力被发现。已发现不等于已认证或已验证，Agent 在执行真实任务前仍要检查权限、登录态、依赖与任务级可用性。

## 存储选择

首次 setup 提供三种选择：

| 选择 | CLI 表达 | 公开文件位置 |
|---|---|---|
| 本地默认目录 | 省略 `--storage` 与 `--vault` | 当前操作系统的应用数据目录 |
| Obsidian Vault | `--vault <vault-root>` | `<vault-root>/Agent/本机能力地图/` |
| 自定义目录 | `--storage <storage-root>` | 指定目录本身 |

公开目录保存：

```text
<public-storage-root>/
├── 本机能力地图.md
├── capability-inventory.json
├── capability-map.config.json
└── setup-receipt.md
```

私有系统数据目录保存：

```text
<private-system-data-root>/
├── capability-resolver.json
└── installation-state.json
```

`capability-resolver.json` 保存执行候选所需的真实位置，`installation-state.json` 保存可恢复的安装状态。private namespace 使用 OS 系统数据目录并与公开 artifacts 分层，且不进入 Obsidian。Obsidian 模式保证 private namespace 位于 Vault 外；默认 local 模式位于同一应用数据根的隐藏 `.private` 子树；custom 是否位于 public root 外取决于路径拓扑，以零写入 setup plan 展示的精确路径为准，确认前审查。Unix 上要求私有文件使用 `0600`。公开库存使用脱敏位置和 opaque ID，但分享前仍应人工检查，因为能力清单本身也是隐私数据。

持久化 public artifacts 只保存脱敏内容，private files 持久化精确路径。setup 与 paths 的 stdout 按使用者请求返回精确操作位置，用于当前会话的安装、排错和交付；该 stdout 不属于可分享的 public artifacts，不要将它当作脱敏报告转发。

## Agent 与作用域

用 `--agents codex|claude|both` 选择 Codex、Claude Code 或两者，用 `--scope user|project` 选择用户级或项目级托管规则。项目级模式还应传入 `--project "<project-root>"`。

安装器只管理带稳定标记的区块。它保留文件原内容、权限和换行，写前生成计划，写中执行冲突检测，失败时尝试补偿；不会默默修复损坏标记或覆盖外部修改。

## 首次 setup

以下示例使用自定义目录。选 Obsidian 时，把 `--storage "<storage-root>"` 换成 `--vault "<vault-root>"`；选本地默认目录时省略两者。

先运行零写入计划：

```bash
python3 "<skill-dir>/scripts/capability_map.py" setup plan \
  --storage "<storage-root>" --agents both --scope project \
  --project "<project-root>"
```

检查 stdout JSON 中的绝对路径、变化、备份、警告、计数和 `plan_hash`。计划阶段不创建目录、不写地图、不改 Agent 指令。

只有在使用者当次明确确认后，使用完全相同的选择执行：

```bash
python3 "<skill-dir>/scripts/capability_map.py" setup apply \
  --storage "<storage-root>" --agents both --scope project \
  --project "<project-root>" --confirmed \
  --expected-plan-hash "<plan-hash>"
```

目标内容在确认后发生变化、参数不同或 hash 过期时，apply 会拒绝。重新运行 plan，并重新取得确认，不要复用之前的许可。

首次 setup 通常可让命令自动生成 opaque installation ID。需要新身份时，由 Agent 生成新的 opaque `inst_...` installation ID，使用者不需要设计 installation ID；Agent 必须在 plan 与 apply 复用同一值，通过 `--installation-id "<inst-id>"` 传入，且不得复用 inactive 安装的旧 ID。

`setup apply` 的 stdout 会返回地图、库存、配置、持久化回执、私有 resolver、私有 state、指令文件、manifest 和备份的精确操作位置，并给出 Skill、CLI、MCP、plugin、未分类项与诊断计数。持久化的 `setup-receipt.md` 是脱敏 artifact，不等同于这份 stdout。指令文件变化后，新开 Agent 会话再使用路由。

## 日常自然语言路由

托管完成后，Agent 对需要本机能力的任务遵循：

1. 先读精简的 `本机能力地图.md`。
2. 按任务语义匹配场景与本机候选。
3. 必要时读取 `capability-inventory.json`；选定候选后才从私有 resolver 解析真实位置。
4. 如果候选是 Skill，完整读取它的 SKILL.md。
5. 检查认证、权限、依赖与任务级可用性，再执行并返回证据。

结构化查询：

```bash
python3 "<skill-dir>/scripts/capability_map.py" route \
  --storage "<storage-root>" --query "<task-query>" --json
```

无可靠命中时返回未命中，不根据作者偏好或名称子串编造用途。

## 命令参考

| 命令 | 用途 | 写入规则 |
|---|---|---|
| `capability_map.py scan` | 只读扫描并输出脱敏 JSON | 只有使用 `--output-dir` 时写入，且要求 `--confirmed` |
| `capability_map.py setup plan` | 生成确定性安装计划和 hash | 零写入 |
| `capability_map.py setup apply` | 生成地图并安装托管指令 | 要求 `--confirmed --expected-plan-hash <plan-hash>` |
| `capability_map.py status` | 返回 `installed`、`healthy`、`lifecycle` 与 `health_errors` | 不写入 |
| `capability_map.py paths` | 返回当前安装的 public/private artifact paths | 不写入 |
| `capability_map.py refresh` | 重新发现本机能力并更新地图 | 先 `--dry-run`，写入时用 `--confirmed` |
| `capability_map.py route` | 按 `--query <task-query>` 匹配本机候选；`--json` 输出结构化结果 | 不写入 |
| `capability_map.py migrate` | 用 `--to <new-storage-root>` 迁移并更新托管指令 | 先 `--dry-run`，写入时用 `--confirmed` |
| `capability_map.py uninstall` | 移除托管指令，默认保留数据 | 先 `--dry-run`，写入时用 `--confirmed` |
| `capability_map.py help-intent` | 将“在哪、刷新、迁移、卸载”等问法归一为操作意图 | 不写入 |

常用命令：

```bash
python3 "<skill-dir>/scripts/capability_map.py" status --storage "<storage-root>"
python3 "<skill-dir>/scripts/capability_map.py" paths --storage "<storage-root>"
python3 "<skill-dir>/scripts/capability_map.py" refresh --storage "<storage-root>" --dry-run
python3 "<skill-dir>/scripts/capability_map.py" refresh --storage "<storage-root>" --confirmed
python3 "<skill-dir>/scripts/capability_map.py" migrate --storage "<storage-root>" --to "<new-storage-root>" --dry-run
python3 "<skill-dir>/scripts/capability_map.py" migrate --storage "<storage-root>" --to "<new-storage-root>" --confirmed
python3 "<skill-dir>/scripts/capability_map.py" uninstall --storage "<storage-root>" --dry-run
python3 "<skill-dir>/scripts/capability_map.py" uninstall --storage "<storage-root>" --confirmed
python3 "<skill-dir>/scripts/capability_map.py" help-intent --query "能力地图放在哪里"
```

`--to` 接收目标公开目录。迁移到另一个 Obsidian Vault 时，传入该 Vault 内最终的 `<vault-root>/Agent/本机能力地图` 目录；私有 resolver 和 state 仍留在系统数据目录。

`uninstall` 默认只移除 Agent 中的托管路由，公开地图与私有 state 保留，同时写入 `lifecycle=uninstalled、active=false`。此后 `status` 返回 `installed=false、healthy=false 且 health_errors 为空`，`refresh、migrate 与重复 uninstall 会拒绝`。在同一公开目录重新 setup 时，由 Agent 生成新的 opaque `inst_...` installation ID，并在 plan 与 apply 复用同一值，使新安装使用新的 private namespace，而旧 state 继续保留为 uninstalled 证据。

数据清理是单独的破坏性 scope。必须先用完整 purge 参数预览：

```bash
python3 "<skill-dir>/scripts/capability_map.py" uninstall --storage "<storage-root>" --dry-run --purge-data
```

确认 stdout 中 `would_purge_data=true`，再向使用者取得针对本次 purge scope 的新的当次明确确认，然后使用相同 selector 和 `--purge-data` 执行：

```bash
python3 "<skill-dir>/scripts/capability_map.py" uninstall --storage "<storage-root>" --confirmed --purge-data
```

不能先预览普通 uninstall 再添加 `--purge-data`。`--purge-data` 可从 active 或 uninstalled lifecycle 执行，它会将托管的 public artifacts 和完整 owned private namespace 可恢复地移入命令回传的 recovery directory，包括 resolver、state、instruction/state backups 与 manifests。它不移动非托管公开文件或其他 private namespace。外部变更冲突时拒绝 purge 并保留外部内容，并在可安全恢复时回滚本次托管变更。

当前可恢复 purge 要求 public storage 与 private recovery 必须位于同一 filesystem。跨 filesystem 时保守拒绝并恢复安装，明确返回 `cross-filesystem purge is unsupported; migrate public storage to the private recovery filesystem before purge`。active 时可先 migrate 到同一 filesystem，再重新走完整的 purge 预览与确认；uninstalled 时 migrate 会拒绝。后者的安全路径是保留 recovery 和数据，选择由 Agent 生成的新 installation ID 重装，或由使用者审查此前 `paths` 返回的精确路径后自行管理，不能自动删除。

## Standalone scan

只读扫描：

```bash
python3 "<skill-dir>/scripts/capability_map.py" scan --project "<project-root>"
```

写入独立 scan bundle：

```bash
python3 "<skill-dir>/scripts/capability_map.py" scan \
  --project "<project-root>" --output-dir "<storage-root>" --confirmed
```

可重复添加 `--skill-root "<extra-skill-root>"`。只有明确需要版本时才加 `--probe-versions explicit`，它会执行有时限和输出上限的版本探测。兼容入口 `"<skill-dir>/scripts/scan_capabilities.py"` 会把旧式 scan 参数映射到 v2；新集成应直接使用 `capability_map.py`。

## 隐私与安全边界

- 默认不联网，默认不执行已发现的 CLI
- 不读取 `.env`、凭证存储或命令历史
- 受支持的 MCP 配置会限长解析，但 secret values、command、args、URL、headers、env 不采集、不持久化、不输出
- 不安装、更新、授权、调用或删除发现到的能力
- 仅 `--probe-versions explicit` 可以执行受限版本探测
- 持久化 public artifacts 统一脱敏 Home、外部绝对路径、凭证形态和控制字符；精确路径 stdout 按上述私有运维输出处理
- 任何使用者的本机能力库存都不会随这个 Skill 发布或上传

## 状态、故障与平台限制

先运行 `status`。`installed=true` 只说明活动安装和必需文件存在；只有 `healthy=true` 才说明配置、state、库存、resolver 权限与 Agent 托管块通过校验。逐项报告 `health_errors`，不要把存在性当作健康性。

计划过期时重新 plan。托管标记冲突时停止，不自动编辑使用者内容。迁移成功后旧安装显示 `lifecycle=migrated`，旧位置的 refresh、migrate、uninstall 与 purge 会拒绝，后续操作使用新位置。普通 uninstall 后保留数据并进入 uninstalled lifecycle，只允许之后执行 purge，或让 Agent 生成新 installation ID 重新 setup。

发现层面针对 macOS、Linux 和 Windows 的 Skill roots、PATH 与 PATHEXT 设计。完整 setup 的强事务保证目前以 POSIX 的 secure directory-fd、no-follow、atomic replace 与 `0600` 为基础；可恢复 purge 还要求 public storage 与 private recovery 在同一 filesystem。Windows 上缺少相应 POSIX 语义时，setup 或 purge 可能 fail closed。此时可以使用只读 scan，但不要在 setup 与 status 未实际通过前宣称持久 Agent 路由已经安全安装。

## License

遵循本仓库根目录的 [LICENSE](../../../LICENSE)。

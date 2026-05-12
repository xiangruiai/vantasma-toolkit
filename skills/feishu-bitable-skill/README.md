# 飞书多维表格技能 (feishu-bitable-skill)

OpenClaw 技能：飞书多维表格的完整生命周期管理 — 从零搭建 + 日常 CRUD。

## 功能

- **从零搭建**：描述业务需求 → AI 自动分析、设计表结构、调用 API 创建多维表格 + 配置方案文档
- **日常操作**：查询记录、批量导入、字段管理、视图管理、筛选排序
- **无默认字段问题**：通过自研脚本在创建时直接指定字段，源头避免飞书 API 的默认字段和空行

## 一键安装

```bash
zsh <(curl -fsSL https://raw.githubusercontent.com/Larkin0302/feishu-bitable-skill/main/install.sh)
```

或者手动安装：

```bash
git clone https://github.com/Larkin0302/feishu-bitable-skill ~/.openclaw/skills/feishu-bitable
zsh ~/.openclaw/skills/feishu-bitable/install.sh
```

安装器会自动：
1. 部署技能文件到 `~/.openclaw/skills/feishu-bitable/`
2. 安装飞书官方插件 (`@larksuiteoapi/feishu-openclaw-plugin`)
3. 禁用 OpenClaw 自带的 stock feishu 插件（避免冲突）
4. 检查 Python 依赖和飞书凭据

## 前置要求

- [OpenClaw](https://openclaw.com) 已安装
- Python 3 + `requests` 库
- 飞书自建应用的 App ID / App Secret（[创建指南](https://open.feishu.cn/document/home/introduction-to-custom-app-development/self-built-application-development-process)）
- **推荐模型**：`claude-opus-4-6` 或 `claude-sonnet-4-6`（需要强指令遵循能力，弱模型可能不按技能流程执行）

> **飞书应用权限要求**：多维表格读写、云文档创建、通讯录读取。具体权限列表见飞书开放平台文档。

## 配置凭据

在 `~/.openclaw/openclaw.json` 中添加：

```json
{
  "channels": {
    "feishu": {
      "appId": "你的 App ID",
      "appSecret": "你的 App Secret"
    }
  }
}
```

## 使用方式

| 在飞书中说 | 功能 |
|-----------|------|
| 「搭建一个项目管理系统」 | 从零搭建多维表格 |
| 「做一个 CRM」 | 需求分析 → 表结构设计 → 自动创建 |
| 「查一下客户表的记录」 | 查询记录 |
| 「批量导入这些数据」 | 批量写入 |
| 「给订单表加一个状态字段」 | 字段管理 |

## 文件结构

```
feishu-bitable-skill/
├── install.sh                    # 一键安装器
├── SKILL.md                      # 技能定义（OpenClaw 读取）
├── _meta.json                    # 技能元数据
├── references/                   # AI 参考文档
│   ├── system-patterns.md        # 4 套典型系统模式
│   ├── formula-reference.md      # 公式函数参考
│   ├── automation-workflow.md    # 自动化与工作流
│   ├── permissions-guide.md      # 权限设计指南
│   └── field-type-mapping.md     # 字段类型映射
└── scripts/                      # Python 脚本
    ├── create_bitable_template.py  # 多维表格搭建脚本
    └── feishu_common.py            # 飞书 API 公共模块
```

## 更新

```bash
cd ~/.openclaw/skills/feishu-bitable && git pull
```

或重新运行安装命令。

## License

MIT

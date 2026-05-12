# 字段类型映射与创建指南

## 扩展类型映射（数字子类型）

数字字段（type=2）通过不同的 `ui_type` 和 `property` 配置实现多种扩展类型。

| 目标字段 | type | ui_type | property 关键参数 |
|---------|------|---------|------------------|
| 普通数字 | 2 | Number | `formatter:"0"` |
| 小数 | 2 | Number | `formatter:"0.0"` 或 `"0.00"` |
| 千分位 | 2 | Number | `formatter:"0,000"` |
| 百分比 | 2 | Number | `formatter:"0.00%"` |
| 货币(CNY) | 2 | Currency | `currency_code:"CNY", formatter:"0.00"` |
| 货币(USD) | 2 | Currency | `currency_code:"USD", formatter:"0.00"` |
| 货币(EUR) | 2 | Currency | `currency_code:"EUR", formatter:"0.00"` |
| 进度 | 2 | Progress | `min:0, max:1, range_customize:true` |
| 评分(5星) | 2 | Rating | `min:0, max:5, rating:{symbol:"star"}` |
| 评分(心形) | 2 | Rating | `min:0, max:5, rating:{symbol:"heart"}` |
| 评分(火焰) | 2 | Rating | `min:0, max:3, rating:{symbol:"fire"}` |

### 创建货币字段示例

```json
{
  "field_name": "合同金额",
  "type": 2,
  "property": {
    "currency_code": "CNY",
    "formatter": "0.00"
  }
}
```

### 创建评分字段示例

```json
{
  "field_name": "客户评级",
  "type": 2,
  "property": {
    "min": 0,
    "max": 5,
    "rating": {
      "symbol": "star"
    }
  }
}
```

---

## API 不可创建字段 + 占位策略

| 字段/功能 | 限制 | 占位方案 |
|----------|------|---------|
| 公式字段表达式 | 可创建 type=20 字段，但无法设置 `formula_expression` | 创建占位字段，在交付报告中给出公式建议 |
| 查找引用 | 不可通过 API 创建 | 在交付报告中说明需手动创建，给出字段名+引用表+引用字段 |
| 流程字段 | 不可通过 API 创建 | 在交付报告中说明配置方式 |
| 按钮字段 | 不可通过 API 创建 | 在交付报告中说明 |
| AI 字段 | 不可通过 API 创建 | 在交付报告中说明 |

---

## 字段创建顺序规则

创建字段时需要遵守以下顺序，避免依赖缺失：

### 优先级顺序

```
1. 基础字段（文本、数字、日期、电话、邮箱等）
   → 无依赖，最先创建

2. 分类字段（单选、多选、复选框、评分、进度）
   → 无依赖，可与基础字段同批

3. 协同字段（人员、群组）
   → 无依赖

4. 自动编号（type=1005）
   → 无依赖

5. 创建时间/更新时间（type=1001/1002）
   → 无依赖

6. 关联字段（type=18 单向 / type=21 双向）
   → ⚠️ 依赖被关联表已存在！多表场景先建所有表，再建关联

7. 查找引用
   → ⚠️ 不可通过 API 创建，手动占位

8. 公式字段（type=20）
   → 最后创建，表达式需手动填写
```

### 多表场景的创建顺序

```
Step 1: 创建所有数据表（不含关联字段）
Step 2: 为每张表创建基础字段（1-5 类）
Step 3: 创建跨表关联字段（type=21 双向关联）
Step 4: 创建公式占位字段
Step 5: 提示用户手动创建查找引用字段
```

---

## 超链接字段特殊处理

超链接字段（type=15）有特殊约束：

- **创建时**：必须完全省略 `property` 参数（传空对象 `{}` 也会报错）
- **写入值**：必须用对象 `{text:"显示文本", link:"https://..."}` 而非纯字符串

```json
// ✅ 正确
{ "field_name": "官网", "type": 15 }

// ❌ 错误（传了空 property）
{ "field_name": "官网", "type": 15, "property": {} }
```

---

## 自动编号配置

```json
// 自增数字
{
  "field_name": "编号",
  "type": 1005,
  "property": {
    "auto_serial": {
      "type": "auto_increment_number"
    }
  }
}

// 自定义格式（如 WO-20240226-0001）
{
  "field_name": "工单号",
  "type": 1005,
  "property": {
    "auto_serial": {
      "type": "custom",
      "options": [
        { "type": "system_number", "value": "autoIncrement" }
      ]
    }
  }
}
```

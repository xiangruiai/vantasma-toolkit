# 飞书多维表格公式函数参考

## 飞书公式 vs Excel 的核心差异

在写公式前必须理解以下差异，**不能用 Excel 思维**：

| 差异点 | Excel | 飞书多维表格 |
|--------|-------|-------------|
| 引用方式 | 单元格引用（A1、B2:B10） | 字段引用（`[字段名]`、`[表名].[字段名]`） |
| 跨表统计 | VLOOKUP/SUMIFS | 链式调用：`[表].FILTER(条件).[字段].SUM()` |
| 多条件统计 | SUMIFS/COUNTIFS | 不支持 SUMIFS/COUNTIFS，用 `FILTER().SUM()` 替代 |
| 迭代变量 | 无 | `CurrentValue` — 在 FILTER/SUMIF/COUNTIF 中代表当前遍历的元素 |
| 统计函数语法 | `SUMIF(range, criteria, sum_range)` | `[表].[字段].SUMIF(CurrentValue>条件)` 链式调用 |

---

## CurrentValue 详解

`CurrentValue` 是飞书公式的核心概念，在 FILTER/SUMIF/COUNTIF/MAP 中使用。

### 引用数据表时

`CurrentValue` = 该表中的每一行记录，可通过 `.字段名` 访问列值。

```
[销售总表].FILTER(CurrentValue.[销售人员]=[销售人员]).[销售额].SUM()
```

### 引用字段时

`CurrentValue` = 该字段中的每一个单元格值。

```
[多选字段].FILTER(CurrentValue="选项A")
```

**注**：`CurrentValue` 与 `@CurrentValue` 等价。

---

## 函数速查表

### 日期函数（17 个）

| 函数 | 语法 | 说明 | 示例 |
|------|------|------|------|
| DATE | `DATE(年,月,日)` | 数字转日期 | `DATE(2024,1,1)` → 2024/01/01 |
| DATEDIF | `DATEDIF(起始,结束,单位)` | 日期差（Y/M/D） | `DATEDIF("2024-01-01","2024-03-01","D")` → 60 |
| DAY | `DAY(日期)` | 取日 | `DAY("2024-01-15")` → 15 |
| DAYS | `DAYS(结束,起始)` | 天数差 | `DAYS("2024-01-08","2024-01-01")` → 7 |
| EDATE | `EDATE(日期,月数)` | 偏移 N 月 | `EDATE("2024-01-31",1)` → 2024/02/29 |
| EOMONTH | `EOMONTH(日期,月数)` | 偏移 N 月的月末 | `EOMONTH("2024-01-01",1)` → 2024/02/29 |
| HOUR | `HOUR(时间)` | 取小时 | `HOUR("11:40:59")` → 11 |
| MINUTE | `MINUTE(时间)` | 取分钟 | `MINUTE("11:40:59")` → 40 |
| MONTH | `MONTH(日期)` | 取月 | `MONTH("2024-12-01")` → 12 |
| NETWORKDAYS | `NETWORKDAYS(起始,结束,[假日])` | 净工作日 | `NETWORKDAYS("2024-01-01","2024-01-12")` → 8 |
| SECOND | `SECOND(时间)` | 取秒 | `SECOND("11:40:59")` → 59 |
| TODAY | `TODAY()` | 当天日期 | — |
| WEEKDAY | `WEEKDAY(日期,[类型])` | 星期几（1=周日起，2=周一起） | `WEEKDAY("2024-01-01",2)` → 1 |
| WEEKNUM | `WEEKNUM(日期,[类型])` | 第几周 | — |
| WORKDAY | `WORKDAY(起始,天数,[假日])` | N 工作日后的日期 | `WORKDAY("2024-01-01",7)` → 2024/01/11 |
| YEAR | `YEAR(日期)` | 取年 | `YEAR("2024-01-01")` → 2024 |
| DURATION | `DURATION(天,[时],[分],[秒])` | 生成时长，可加减日期 | `NOW()+DURATION(0,12)` → 12 小时后 |

### 逻辑函数（21 个）

| 函数 | 语法 | 说明 |
|------|------|------|
| IF | `IF(条件,真值,假值)` | 条件判断 |
| IFS | `IFS(条件1,值1,条件2,值2,...)` | 多条件判断，返回首个为真的值 |
| AND | `AND(条件1,条件2,...)` | 全部为真返回 TRUE |
| OR | `OR(条件1,条件2,...)` | 任一为真返回 TRUE |
| NOT | `NOT(条件)` | 取反 |
| SWITCH | `SWITCH(表达式,匹配1,值1,...,默认值)` | 精确匹配（类似 switch-case） |
| ISBLANK | `ISBLANK(值)` | 是否为空 |
| ISNULL | `ISNULL(值)` | 是否为空（同 ISBLANK） |
| IFBLANK | `IFBLANK(值,空值替代)` | 空值替代 |
| IFERROR | `IFERROR(值,错误替代)` | 错误替代 |
| ISERROR | `ISERROR(值)` | 是否为错误值 |
| ISNUMBER | `ISNUMBER(值)` | 是否为数字 |
| TRUE/FALSE | `TRUE()`/`FALSE()` | 返回布尔值 |
| CONTAIN | `CONTAIN(范围,值1,值2,...)` | 范围是否包含指定值（非文本匹配） |
| CONTAINSALL | `CONTAINSALL(范围,值1,值2,...)` | 是否包含所有指定值 |
| CONTAINSONLY | `CONTAINSONLY(范围,值1,值2,...)` | 是否仅包含指定值 |
| MAP | `数据范围.MAP(CurrentValue表达式)` | 映射处理（不可嵌套） |
| RANK | `RANK(值,范围,[升序])` | 排名（默认降序） |
| RECORD_ID | `RECORD_ID()` | 获取记录唯一 ID |
| RANDOMBETWEEN | `RANDOMBETWEEN(最小,最大,[持续更新])` | 随机整数 |
| RANDOMITEM | `LIST(...).RANDOMITEM([持续更新])` | 随机选一个 |

### 文本函数（22 个）

| 函数 | 语法 | 说明 |
|------|------|------|
| CONCATENATE | `CONCATENATE(str1,str2,...)` | 拼接字符串 |
| FORMAT | `FORMAT("{1}的{2}",值1,值2)` | 模板拼接 |
| LEFT/RIGHT/MID | `LEFT(str,n)` / `RIGHT(str,n)` / `MID(str,start,len)` | 截取子串 |
| LEN | `LEN(文本)` | 字符串长度 |
| FIND | `FIND(查找值,范围,[起始])` | 查找位置（-1=未找到） |
| REPLACE | `REPLACE(文本,位置,长度,新文本)` | 按位置替换 |
| SUBSTITUTE | `SUBSTITUTE(文本,旧文本,新文本,[序号])` | 按内容替换 |
| UPPER/LOWER | `UPPER(str)` / `LOWER(str)` | 大小写转换 |
| TRIM | `TRIM(文本)` | 去前后空格 |
| SPLIT | `SPLIT(文本,分隔符)` | 分割文本 |
| TEXT | `TEXT(值,格式)` | 格式化（"YYYY/MM/DD"、"ddd"、"0.0%"） |
| TODATE | `TODATE(文本)` | 文本转日期 |
| HYPERLINK | `HYPERLINK(链接,[显示文本])` | 创建超链接 |
| CHAR | `CHAR(数字)` | Unicode 字符（`CHAR(10)` = 换行） |
| CONTAINTEXT | `CONTAINTEXT(文本,查找文本)` | 文本包含判断 |
| ENCODEURL | `ENCODEURL(文本)` | URL 编码 |
| REGEXMATCH | `REGEXMATCH(文本,正则)` | 正则匹配判断 |
| REGEXEXTRACT | `REGEXEXTRACT(文本,正则)` | 正则提取首个匹配 |
| REGEXEXTRACTALL | `REGEXEXTRACTALL(文本,正则)` | 正则提取全部匹配 |
| REGEXREPLACE | `REGEXREPLACE(文本,正则,替换)` | 正则替换 |

### 数字函数（常用）

| 函数 | 语法 | 说明 |
|------|------|------|
| SUM | `SUM(值1,值2,...)` | 求和 |
| AVERAGE | `AVERAGE(值1,值2,...)` | 平均值 |
| MAX/MIN | `MAX(...)` / `MIN(...)` | 最大/最小值 |
| MEDIAN | `MEDIAN(值1,值2,...)` | 中位数 |
| ROUND | `ROUND(数值,位数)` | 四舍五入 |
| ROUNDUP/ROUNDDOWN | `ROUNDUP(数值,位数)` | 向上/向下舍入 |
| INT | `INT(数值)` | 向下取整 |
| ABS | `ABS(数值)` | 绝对值 |
| MOD | `MOD(被除数,除数)` | 取余 |
| POWER | `POWER(底数,指数)` | 乘幂 |
| CEILING | `CEILING(值,[因数])` | 向上取整到因数倍数 |
| FLOOR | `FLOOR(值,[因数])` | 向下取整到因数倍数 |
| COUNTA | `COUNTA(值1,值2,...)` | 统计非空值个数 |
| VALUE | `VALUE(文本)` | 文本转数字 |
| SEQUENCE | `SEQUENCE(起始,结束,[步长])` | 生成数字序列 |

### 统计函数（关键 4 个）

| 函数 | 语法 | 说明 | 示例 |
|------|------|------|------|
| FILTER | `数据范围.FILTER(条件)` | 筛选符合条件的记录 | `[销售表].FILTER(CurrentValue.[金额]>1000)` |
| SUMIF | `[表].[字段].SUMIF(条件)` | 条件求和 | `[销售表].[金额].SUMIF(CurrentValue>1000)` |
| COUNTIF | `数据范围.COUNTIF(条件)` | 条件计数 | `[库存表].COUNTIF(CurrentValue.[库存]>100)` |
| LOOKUP | `LOOKUP(搜索值,匹配字段,结果字段,[模式])` | 快速查找引用 | `LOOKUP([姓名],[销售表].[姓名],[销售表].[金额])` |

**多条件统计**（替代 SUMIFS/COUNTIFS）：

```
// 多条件求和
[销售表].FILTER(
  CurrentValue.[销售人员]=[销售人员]
  && CurrentValue.[销售时间]>TODATE(2024-01-01)
).[销售额].SUM()

// 多条件计数
[订单表].FILTER(
  CurrentValue.[状态]="已完成"
  && CurrentValue.[金额]>1000
).COUNTA()
```

### 列表函数（12 个）

| 函数 | 语法 | 说明 |
|------|------|------|
| LIST | `LIST(值1,值2,...)` | 创建列表 |
| ARRAYJOIN | `ARRAYJOIN(数组,[分隔符])` | 数组转字符串（默认逗号） |
| FIRST/LAST | `集合.FIRST()` / `集合.LAST()` | 首个/末个元素 |
| NTH | `集合.NTH(位置)` | 第 N 个元素（从 1 开始） |
| SORT | `SORT(列表,[升序])` | 排序 |
| SORTBY | `SORTBY(数据范围,排序列,[升序]).结果列` | 按指定列排序 |
| UNIQUE | `UNIQUE(值1,值2,...)` | 去重 |
| LISTCOMBINE | `LISTCOMBINE(字段1,字段2,...)` | 合并多个列表 |

### 位置函数

| 函数 | 语法 | 说明 |
|------|------|------|
| DISTANCE | `DISTANCE([位置1],[位置2])` | 两点直线距离（千米） |

---

## 高频公式模式

### 1. 跨表条件求和

```
[销售表].FILTER(CurrentValue.[销售人员]=[销售人员]).[销售额].SUM()
```

### 2. 多条件筛选求和

```
[销售表].FILTER(
  CurrentValue.[销售人员]=[销售人员]
  && CurrentValue.[年份]=年份
  && CurrentValue.[销售额]>0
).[销售额].SUM()
```

### 3. 条件计数

```
[订单表].COUNTIF(CurrentValue.[状态]="已完成")
```

### 4. 多条件判断分级

```
IFS(
  [分数]>=90, "优秀",
  [分数]>=80, "良好",
  [分数]>=60, "及格",
  TRUE, "不及格"
)
```

### 5. 日期差计算（工期/逾期）

```
DATEDIF([开始日期],[截止日期],"D")
```

### 6. 逾期预警

```
IF([截止日期]<TODAY(), "已逾期", IF([截止日期]=TODAY(), "今天截止", "正常"))
```

### 7. 文本模板拼接

```
FORMAT("{1}-{2}-{3}", YEAR([日期]), MONTH([日期]), [类型])
```

### 8. 空值安全处理

```
IFBLANK([字段], "未填写")
```

### 9. 跨表查找引用

```
LOOKUP([客户名称],[客户表].[客户名称],[客户表].[联系电话])
```

### 10. 百分比计算

```
ROUND([已完成]/[总数]*100, 1) & "%"
```

---

## 性能优化范式

### 推荐的 FILTER 写法

条件中使用简单的 `CurrentValue.列名 操作符 值/列名` 格式：

```
// ✅ 推荐：简单字段比较
[销售表].FILTER(
  CurrentValue.[销售人员]=[销售人员]
  && CurrentValue.[销售额]>0
).[销售额].SUM()

// ❌ 避免：条件中对 CurrentValue 做复杂运算
[销售表].FILTER(
  CurrentValue.[反馈详情].CONTAINTEXT([关键词])
).[反馈数量].COUNTA()
```

### 优化技巧

1. **减少变量列**：多个统计列共用变量时，用一个变量字段替代多个硬编码
2. **避免模糊匹配**：CONTAINTEXT 在 FILTER 中性能差，改用标签字段精确匹配
3. **复杂运算用插件**：大数据量 + 多变量场景考虑多维表格插件

---

## 计算限制

| 限制项 | 上限 |
|--------|------|
| FILTER 结果记录数 | 20,000 条 |
| 计算结果元素数（数组） | 200 个 |
| 单层嵌套数组元素 | 200 个 |
| ARRAYJOIN/CONCATENATE/UNIQUE/SORT 入参 | 5,000 个 |
| 中间计算结果字符串 | 1 MB |
| 单个单元格结果 | 4 MB |
| 单列计算结果 | 100 MB |
| 单表计算结果 | 256 MB |
| 单表存储容量 | 10 GB |

---

## 工作流/自动化中的公式限制

在工作流和自动化的节点中可以使用公式，但以下函数**不支持**：

| 不支持的函数 | 替代方案 |
|-------------|---------|
| LOOKUP | 使用"查找记录"节点替代 |
| CONTAINS | 使用条件判断节点替代 |
| HYPERLINK | 直接拼接 URL 字符串 |
| DISTANCE | 无替代 |
| ISNULL | 使用 ISBLANK |
| MAP | 使用循环节点替代 |
| SORTBY | 使用排序节点替代 |

**日期字段注意**：工作流中日期以数字形式参与计算（距过去某时间的天数），如需显示为日期格式，需切换数据类型。

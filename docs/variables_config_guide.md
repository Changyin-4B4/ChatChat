# 变量配置指南（variables_config.json）

本文件说明如何在 `variables_config.json` 中定义变量。JSON 必须为标准 JSON（不支持 `//` 或 `/* */` 注释）

* 文件名：`variables_config.json`
* 顶层结构：对象或数组。推荐使用对象并包含 `"variables": [ ... ]`

## 字段总览（每个变量对象）

### 必填字段

* `name`：字符串。变量名或唯一名，例如 `"好感度"`，`"exp"`。
* `var_type`：字符串。变量类型：
  * `"record"`：记录型变量
  * `"stage_independent"`：阶段自变量（支持阶段描述/计算）
* `update_type`：字符串。更新方式：
  * `"keyword_count"`：关键词计数更新，会依据关键词出现的次数，应用多次更新
  * `"keyword_appear"`：关键词出现更新，不看出现次数，出现则应用一次更新
  * `"llm_fuzzy"`：交由 LLM 对剧情文本进行判断，更新变量值

### 可选字段（缺失将使用默认值或按逻辑忽略）

* `update_config`：字符串。更新配置，若使用 LLM 更新，则为 `.txt` 路径。若使用关键词，则固定为 `variables_keyword.json`
* `pre_update`：布尔。是否在前置阶段更新，默认 `false`
* `initial_value`：数值。初始值，默认 `0.0`
* `min_value`：数值或字符串。下界，默认 `"-inf"`（负无穷）
* `max_value`：数值或字符串。上界，默认 `"inf"`（正无穷）
* `update_constraint`：数组。更新约束（详见"约束配置"）（不设置该属性则不对该变量进行约束）
* `reset_type`：字符串。重置方式：（不设置该属性则不对该变量进行重置，同时，`reset_config`，`reset_value` 将不会生效）
  * `"keyword"`：关键词重置，出现设定的关键词，就重置该变量
  * `"llm"`：交由 LLM 对剧情文本进行判断，决定是否重置变量值
* `reset_config`：字符串。重置配置，若使用 LLM 更新，则为 `.txt` 路径。若使用关键词，则固定为 `variables_keyword.json`
* `reset_value`：数值。重置后设置的值，默认 `0.0`

### 阶段相关（仅 `var_type = "stage_independent"` 才有意义）

* `relative_name`：字符串。阶段的标签名，例如 `"情感阶段"`、`"时间"`。
* `relative_method`：字符串。阶段计算方式：
  * `"ladder"` 阶梯
  * `"cycle"` 周期
* `relative_stage_config`：数组。阶段计算参数：
  * **ladder** ：阈值列表，如 `[20, 50]`，此时，从 `min_value` 到 20，为阶段 0；20 到 50，为阶段 1；50 到 `max_value`，为阶段 2
  * **cycle** ：形如 `[60, 60, 24, 30, 12]`，用于多级周期分解，此时，假设变量本身代表秒数，则会按照周期大小，分解为：分，时，日，月；对于这类型，返回的索引是倒序的，即返回时的顺序为：月、日、时、分（不包含秒）
  * 若以天为计时 `[30, 12]` 则分解为月，此时返回索引只有一个月份数值，会随着天数增加在 12 个月份之间循环
  * 对于周期嵌套数量没有限制
* `relative_value`：整数或整数数组，即 ladder 类型的阶段数值，cycle 类型的索引（可能是列表）（交由程序计算，不必填）。
* `relative_description`：数组或嵌套数组。阶段文案：
  * **阶梯** ：`["陌生", "熟悉", "在意"]`
  * **周期** ：单维或多维，如 `["一月","二月",...]` 或是 `[["凌晨","上午","下午","晚上"], ["1天","2天",...], ["上旬","中旬","下旬"], ["一月","二月",...]]`
* `relative_current_description`：字符串或数组。索引对应的当前阶段描述（由程序计算，不必填）。

## 阶段索引规则

**重要：所有阶段索引从 0 开始计数！**

### LADDER 模式示例

```json
"relative_stage_config": [20, 50],
"relative_description": ["陌生", "熟悉", "在意"]
```

| 变量值范围     | relative_value | 描述   |
| -------------- | -------------- | ------ |
| min_value ~ 20 | 0              | "陌生" |
| 20 ~ 50        | 1              | "熟悉" |
| 50 ~ max_value | 2              | "在意" |

### CYCLE 模式示例

**示例 1：时间分解**

以分为单位（变量本身代表分钟数），配置为 `[360, 4, 10, 3, 12]`：

* 一个时段（6小时）包含 360 分钟
* 一天包含 4 个时段
* 一旬包含 10 天
* 一月包含 3 旬
* 月份以 12 为周期循环

假设当前值为 7320 分钟：

* `relative_value = (2, 1, 5, 2)` → 3月中旬（第2旬）第6天下午（第3时段）
* `relative_current_description = ("三月", "中旬", "6天", "下午")`

**注意：** 返回的索引是倒序的（从大单位到小单位：月-旬-天-时段）

**示例 2：不可省略中间级**

❌  **错误** ：想省略"天数"这一级

```json
"relative_stage_config": [360, 40, 3, 12],  // 想让一旬包含40个时段
"relative_description": [
  ["一月", "二月", ...],
  ["上旬", "中旬", "下旬"],
  ["凌晨", "上午", "下午", "晚上"]
]
```

此时，余数会在 0-39，无法匹配到只有 4 个数值的时段内。

✓  **正确** ：必须保留所有中间级

```json
"relative_stage_config": [360, 4, 10, 3, 12],
"relative_description": [
  ["一月", "二月", ...],
  ["上旬", "中旬", "下旬"],
  ["1天", "2天", ..., "10天"],
  ["凌晨", "上午", "下午", "晚上"]
]
```

如果不想在世界书中显示某一级（如"天数"），可以在世界书配置中选择性忽略。

关于cycle的更多详细说明，参见

## 约束配置（update_constraint）

用于限制"当且仅当其他变量处于某范围时，此变量才可更新"。

### 语法规则

* **与关系（AND）** ：数组中直接列出约束条件
* **或关系（OR）** ：使用对象 `{"or": [[...], [...]]}` 包裹多条约束作为一组"或"

### 单个约束格式

1. **完整约束** ：`[下界, "变量名", 上界]`

* 含义：`下界 < 变量.stage_value < 上界`

1. **仅下界** ：`[下界, "变量名"]`

* 含义：`变量.stage_value > 下界`

1. **仅上界** ：`["变量名", 上界]`

* 含义：`变量.stage_value < 上界`

### 示例

```json
"update_constraint": [
  [1, "好感度"],
  {"or": [["好感度", 3], [2, "饥饿度", 5]]}
]
```

**解释：** 此变量仅在以下情况更新：

1. 好感度阶段数值 > 1（注意，从 0 计数，1 代表的是第二个阶段）
2. 且满足以下任一条件：
   * 好感度阶段数值 < 3
   * 2 < 饥饿度阶段数值 < 5

**注意：**

* 约束里的"变量名"必须引用同一 JSON 中已定义的变量的 `name`
* 阶段值指 `get_stage()['relative_value']`（内部按你的阶段计算方法决定）
* 约束的并列数量没有限制

## 路径与读写

* `update_config`、`reset_config` 支持相对路径（相对卡片目录，如存放在 `卡片文件夹/update&reset/xxx.txt`，只需要填写为 `update&reset/xxx.txt`，不能放在卡片文件夹之外）
* 程序通过 `IO_Manager` 读取，无需写绝对盘符路径

## 数值书写规范

* 支持数值类型与字符串 `"inf"`/`"-inf"`：
  * `"max_value": "inf"`，`"min_value": "-inf"`
* 其他数值请直接填数字：`0.0`、`100`、`-50` 等

## 最小模板

```json
{
  "variables": [
    {
      "name": "变量名",
      "var_type": "record",
      "update_type": "keyword_count",
      "update_config": "variables_keyword.json",
      "pre_update": false,
      "initial_value": 0.0,
      "min_value": "-inf",
      "max_value": "inf"
    }
  ]
}
```

## 完整示例模板

```json
{
  "variables": [
    {
      "name": "好感度",
      "var_type": "stage_independent",
      "update_type": "keyword_count",
      "update_config": "variables_keyword.json",
      "pre_update": true,
      "initial_value": 0.0,
      "min_value": 0.0,
      "max_value": 100.0,
      "update_constraint": [],
      "reset_type": "keyword",
      "reset_config": "variables_keyword.json",
      "reset_value": 0.0,

      "relative_name": "情感阶段",
      "relative_method": "ladder",
      "relative_stage_config": [20, 50, 80],
      "relative_description": ["陌生", "熟悉", "在意", "亲密"]
    },
    {
      "name": "游戏天数",
      "var_type": "stage_independent",
      "update_type": "keyword_appear",
      "update_config": "variables_keyword.json",
      "pre_update": false,
      "initial_value": 1440.0,
      "min_value": 0.0,
      "max_value": "inf",

      "relative_name": "日期",
      "relative_method": "cycle",
      "relative_stage_config": [1440, 30, 12],
      "relative_description": [
        ["一月", "二月", "三月", "四月", "五月", "六月", "七月", "八月", "九月", "十月", "十一月", "十二月"],
        ["1日", "2日", "3日", ..., "30日"]
      ]
    }
  ]
}
```

参考当前仓库中的 `config/variables_config.json`，内含 4 个变量的完整示例（好感度/游戏内的天数/日期/饥饿度）。

## 常见错误与排查

### 1. 文件路径错误

* ❌ `"update_config": "C:/Users/.../example.txt"`（绝对路径）
* ✓ `"update_config": "update&reset/example.txt"`（相对于卡片目录）

### 2. 关键词配置文件命名错误

* ❌ `"update_config": "keyword.json"`（必须是固定名称）
* ✓ `"update_config": "variables_keyword.json"`

### 3. 约束中引用不存在的变量

```json
"update_constraint": [
  [1, "不存在的变量名"]  // ❌ 会导致运行时错误
]
```

### 4. 阶段描述数量与阶段数不匹配

```json
"relative_stage_config": [20, 50],        // 产生 3 个阶段（0, 1, 2）
"relative_description": ["陌生", "熟悉"]  // ❌ 只有 2 个描述
```

**正确示例：**

```json
"relative_stage_config": [20, 50],
"relative_description": ["陌生", "熟悉", "在意"]  // ✓ 3 个描述对应 3 个阶段
```

### 5. JSON 格式错误

* 不支持注释（`//` 或 `/* */`）
* 末尾不能有多余逗号
* 字符串必须用双引号 `"`
* 对象的最后一个属性后不能有逗号

**错误示例：**

```json
{
  "name": "好感度",
  "var_type": "record",  // ❌ 最后一个属性后有逗号
}
```

**正确示例：**

```json
{
  "name": "好感度",
  "var_type": "record"
}
```

### 6. CYCLE 模式配置错误

* ❌ 省略中间级会导致余数无法匹配
* ✓ 必须保留所有中间级，可以在世界书配置中选择性隐藏

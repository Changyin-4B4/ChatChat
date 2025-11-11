# 变量关键词配置指南（Variables Keyword）

本文件说明如何通过 JSON 配置文件为基于关键词的变量更新和重置功能设置规则。

---

## 文件概述

* **文件格式** ：`.json`（JSON）
* **编码** ：UTF-8
* **用途** ：定义关键词触发的变量更新/重置规则，支持数值浮动效果
* **路径** ：相对于工作目录（如 `config/variables_keywords.json`）

---

## 基本结构

```json
{
  "_description": "变量关键词映射配置文件，支持数值浮动效果",
  "_format_explanation": {
    "stage_mapping": "阶段自变量到因变量的映射规则",
    "min_value": "最小值",
    "max_value": "最大值"
  },
  "[变量名]_keywords": {
    "[分组名]": {
      "keywords": ["关键词1", "关键词2", ...],
      "min_value": 最小值,
      "max_value": 最大值
    }
  },
  "[变量名]_reset": {
    "keywords": ["重置关键词1", "重置关键词2", ...]
  }
}
```

### 核心概念

| 概念               | 说明                                                       |
| ------------------ | ---------------------------------------------------------- |
| **变量名**   | 与 `variables_update.py`中定义的变量名称一致             |
| **关键词组** | 包含关键词列表和数值范围的配置项                           |
| **数值浮动** | 通过 `min_value`和 `max_value`实现随机范围内的数值变化 |
| **重置规则** | 通过 `_reset`后缀定义触发重置的关键词列表                |

---

## 配置类型

### 1. UPDATE 配置（关键词更新）

用于在剧情文本中检测关键词并更新变量值。

#### 1.1 配置格式

```json
"[变量名]_keywords": {
  "[分组名]": {
    "keywords": ["关键词1", "关键词2", ...],
    "min_value": 数值,
    "max_value": 数值
  }
}
```

#### 1.2 字段说明

| 字段                  | 类型   | 必填 | 说明                                                        |
| --------------------- | ------ | ---- | ----------------------------------------------------------- |
| `[变量名]_keywords` | Object | 是   | 变量的关键词配置，变量名必须与代码中定义的一致              |
| `[分组名]`          | String | 是   | 关键词组的名称（可任意命名，如 `positive`、`negative`） |
| `keywords`          | Array  | 是   | 关键词列表（字符串数组）                                    |
| `min_value`         | Number | 是   | 触发后的最小变化值                                          |
| `max_value`         | Number | 是   | 触发后的最大变化值                                          |

#### 1.3 更新类型

根据 `variables_update.py` 中的 `UpdateType`，关键词更新支持两种模式：

##### A. KEYWORD_COUNT（计数模式）

* **行为** ：统计关键词出现次数，每次出现都计分
* **计算公式** ：

```python
  total_score = count * random_value(min_value, max_value)
```

* **适用场景** ：需要累积效果的变量（如重复动作）

 **示例** ：

```json
"体力_keywords": {
  "running": {
    "keywords": ["奔跑", "跑步"],
    "min_value": -2.0,
    "max_value": -1.0
  }
}
```

 **效果** ：

* 文本：`"他奔跑了10分钟，然后继续奔跑"`
* 结果：检测到 2 次 "奔跑" → 累积扣除体力 2 × (-1.5) = -3.0

---

##### B. KEYWORD_APPEAR（出现模式）

* **行为** ：同一组关键词只计分一次（无论出现几次）
* **计算公式** ：

```python
  total_score = random_value(min_value, max_value)  # 只计算一次
```

* **适用场景** ：状态判断类变量（如情绪变化）

 **示例** ：

```json
"好感度_keywords": {
  "positive": {
    "keywords": ["喜欢", "爱慕", "欣赏"],
    "min_value": 4.0,
    "max_value": 6.0
  }
}
```

 **效果** ：

* 文本：`"她很喜欢你，真的很喜欢"`
* 结果：检测到 "喜欢" 出现 2 次，但**只计分一次** → 好感度 +5.0（在 4.0-6.0 范围内随机）

---

#### 1.4 数值浮动机制

 **固定值** （`min_value == max_value`）：

```json
"日期_keywords": {
  "next_day": {
    "keywords": ["次日", "第二天"],
    "min_value": 1.0,
    "max_value": 1.0
  }
}
```

* 每次触发固定增加 **1.0**

 **范围浮动** （`min_value < max_value`）：

```json
"好感度_keywords": {
  "positive": {
    "keywords": ["喜欢"],
    "min_value": 4.0,
    "max_value": 6.0
  }
}
```

* 每次触发随机增加 **4.0 到 6.0** 之间的值

---

#### 1.5 完整示例

```json
{
  "好感度_keywords": {
    "positive": {
      "keywords": ["喜欢", "爱慕", "欣赏", "感激", "尊敬"],
      "min_value": 4.0,
      "max_value": 6.0
    },
    "negative": {
      "keywords": ["厌恶", "憎恨", "鄙视", "失望"],
      "min_value": -6.0,
      "max_value": -4.0
    },
    "slightly_positive": {
      "keywords": ["微笑", "点头", "温柔"],
      "min_value": 0.5,
      "max_value": 1.5
    },
    "slightly_negative": {
      "keywords": ["皱眉", "冷漠", "无视"],
      "min_value": -1.5,
      "max_value": -0.5
    }
  }
}
```

 **效果演示** ：

| 文本内容             | 匹配关键词         | 变化值（范围） | 说明           |
| -------------------- | ------------------ | -------------- | -------------- |
| "她对你微笑"         | `微笑`           | +0.5 到 +1.5   | 轻微正面       |
| "他憎恨你的所作所为" | `憎恨`           | -6.0 到 -4.0   | 强烈负面       |
| "她微笑着表示感激"   | `微笑`、`感激` | +4.5 到 +7.5   | 两个分组都触发 |

---

### 2. RESET 配置（关键词重置）

用于检测特定关键词并触发变量重置。

#### 2.1 配置格式

```json
"[变量名]_reset": {
  "keywords": ["关键词1", "关键词2", ...]
}
```

#### 2.2 字段说明

| 字段               | 类型   | 必填 | 说明                                         |
| ------------------ | ------ | ---- | -------------------------------------------- |
| `[变量名]_reset` | Object | 是   | 变量的重置配置，变量名必须与代码中定义的一致 |
| `keywords`       | Array  | 是   | 触发重置的关键词列表                         |

#### 2.3 重置行为

* **触发条件** ：文本中包含任一关键词（不区分大小写）
* **重置目标** ：将变量值恢复到 `reset_value`（在 `variables_update.py` 中定义）
* **优先级** ：重置判断优先于更新判断

#### 2.4 示例

```json
{
  "好感度_reset": {
    "keywords": ["死亡", "决裂", "背叛", "永别"]
  },
  "游戏内的天数_reset": {
    "keywords": ["重置", "回到开始", "时光倒流"]
  }
}
```

 **效果演示** ：

| 文本内容                 | 匹配关键词   | 结果                           |
| ------------------------ | ------------ | ------------------------------ |
| "角色在战斗中死亡"       | `死亡`     | 好感度重置为 `reset_value`   |
| "时光倒流，一切回到开始" | `回到开始` | 游戏天数重置为 `reset_value` |

---

## 配置规则

### 1. 命名规范

#### 1.1 变量名一致性

 **配置文件中的键名必须与variables_config.json中定义的变量名完全一致** ：

✓  **正确** ：

```python
    {
      "name": "好感度",
      "var_type": "stage_independent",
      "update_type": "llm_fuzzy",
      "update_config": "update&reset/exp_update.txt",
      "pre_update": false,
      "initial_value": 0.0,
      "min_value": 0.0,
      "max_value": 100.0,
      "reset_type": "llm",
      "reset_config": "update&reset/exp_reset.txt",
      "relative_name": "情感阶段",
      "relative_method": "ladder",
      "relative_stage_config": [20.0, 50.0],
      "relative_description": ["陌生", "熟悉", "在意"]
    },# variables_update.py
variable = Variable(
    name="好感度",  # ← 变量名
    ...
)
```

```json
// variables_keywords.json
{
  "好感度_keywords": { ... }  // ← 配置键名
}
```

❌  **错误** ：

```json
{
  "affection_keywords": { ... }  // ← 与代码中的 "好感度" 不一致
}
```

#### 1.2 后缀规则

| 后缀          | 用途     | 示例                |
| ------------- | -------- | ------------------- |
| `_keywords` | 更新配置 | `好感度_keywords` |
| `_reset`    | 重置配置 | `好感度_reset`    |

---

### 2. 数值范围

#### 2.1 合法范围

* **必须符合变量的 `min_value` 和 `max_value` 限制**
* 超出范围的值会被自动限制

 **示例** ：

```python
# variables_update.py
variable = Variable(
    name="好感度",
    min_value=0.0,
    max_value=100.0,
    ...
)
```

```json
// variables_keywords.json
{
  "好感度_keywords": {
    "extreme_positive": {
      "keywords": ["拯救生命"],
      "min_value": 50.0,  // ✓ 在 0.0-100.0 范围内
      "max_value": 50.0
    }
  }
}
```

#### 2.2 数值类型

* **必须是数字类型** （整数或浮点数）
* 推荐使用 **浮点数** （保留 1 位小数）

✓  **正确** ：

```json
"min_value": 4.0,
"max_value": 6.0
```

❌  **错误** ：

```json
"min_value": "4.0",  // 字符串类型
"max_value": "6.0"
```

---

### 3. 关键词匹配

#### 3.1 匹配规则

* **不区分大小写**
* **子串匹配** ：`"跑"` 可以匹配 `"奔跑"`、`"跑步"`
* **优先使用精确关键词** ，避免过度匹配

#### 3.2 关键词设计建议

✓  **好的关键词设计** ：

```json
{
  "positive": {
    "keywords": ["喜欢", "爱慕", "欣赏"],  // 明确的正向词汇
    "min_value": 4.0,
    "max_value": 6.0
  }
}
```

❌  **不好的关键词设计** ：

```json
{
  "positive": {
    "keywords": ["好", "不错"],  // 过于宽泛，容易误匹配
    "min_value": 4.0,
    "max_value": 6.0
  }
}
```

 **问题** ：`"好"` 可能匹配到 `"不好"`、`"好像"`，导致误判。

---

### 4. 分组策略

#### 4.1 按强度分组

```json
{
  "好感度_keywords": {
    "extreme_positive": {
      "keywords": ["拯救生命", "牺牲自我"],
      "min_value": 8.0,
      "max_value": 10.0
    },
    "strong_positive": {
      "keywords": ["感激涕零", "爱慕"],
      "min_value": 4.0,
      "max_value": 6.0
    },
    "mild_positive": {
      "keywords": ["微笑", "点头"],
      "min_value": 0.5,
      "max_value": 1.5
    },
    "mild_negative": {
      "keywords": ["皱眉", "冷漠"],
      "min_value": -1.5,
      "max_value": -0.5
    },
    "strong_negative": {
      "keywords": ["憎恨", "鄙视"],
      "min_value": -6.0,
      "max_value": -4.0
    }
  }
}
```

#### 4.2 按场景分组

```json
{
  "体力_keywords": {
    "combat": {
      "keywords": ["战斗", "激战", "厮杀"],
      "min_value": -5.0,
      "max_value": -3.0
    },
    "running": {
      "keywords": ["奔跑", "疾跑", "冲刺"],
      "min_value": -2.0,
      "max_value": -1.0
    },
    "rest": {
      "keywords": ["休息", "睡眠", "恢复"],
      "min_value": 3.0,
      "max_value": 5.0
    }
  }
}
```

---

## 完整配置示例

```json
{
  "_description": "变量关键词映射配置文件，支持数值浮动效果",
  "_format_explanation": {
    "stage_mapping": "阶段自变量到因变量的映射规则",
    "min_value": "最小值",
    "max_value": "最大值"
  },
  "好感度_keywords": {
    "positive": {
      "keywords": ["喜欢", "爱慕", "欣赏"],
      "min_value": 4.0,
      "max_value": 6.0
    },
    "negative": {
      "keywords": ["厌恶", "憎恨", "鄙视"],
      "min_value": -6.0,
      "max_value": -4.0
    }
  },
  "好感度_reset": {
    "keywords": ["死亡", "决裂", "背叛"]
  }
}
```

---

## 常见错误与排查

### 1. 变量名不匹配

❌  **错误** ：

```python
# 代码中
variable = Variable(name="好感度", ...)
```

```json
// 配置文件中
{
  "affection_keywords": { ... }  // ← 键名不匹配
}
```

✓  **正确** ：

```json
{
  "好感度_keywords": { ... }
}
```

---

### 2. 数值类型错误

❌  **错误** ：

```json
{
  "好感度_keywords": {
    "positive": {
      "keywords": ["喜欢"],
      "min_value": "4.0",  // ← 字符串类型
      "max_value": "6.0"
    }
  }
}
```

✓  **正确** ：

```json
{
  "min_value": 4.0,
  "max_value": 6.0
}
```

---

### 3. 缺少必需字段

❌  **错误** ：

```json
{
  "好感度_keywords": {
    "positive": {
      "keywords": ["喜欢"]
      // ← 缺少 min_value 和 max_value
    }
  }
}
```

✓  **正确** ：

```json
{
  "好感度_keywords": {
    "positive": {
      "keywords": ["喜欢"],
      "min_value": 4.0,
      "max_value": 6.0
    }
  }
}
```

---

### 4. 配置文件路径错误

❌  **错误** ：

```python
update_config="/absolute/path/to/config.json"  // ← 绝对路径
```

✓  **正确** （使用相对路径）：

```python
update_config="config/variables_keywords.json"
```

### 关键词维护

* ✅ 定期审查关键词的触发效果
* ✅ 避免过于宽泛的关键词（如 "好"、"不"）
* ✅ 使用同义词扩充关键词列表
* ✅ 记录边界案例并调整权重

---

## 附录：完整模板

```json
{
  "_description": "变量关键词映射配置文件",
  "_version": "1.0.0",
  "_last_updated": "YYYY-MM-DD",
  
  "[变量名]_keywords": {
    "[分组名1]": {
      "keywords": ["关键词1", "关键词2", "关键词3"],
      "min_value": 最小值,
      "max_value": 最大值
    },
    "[分组名2]": {
      "keywords": ["关键词4", "关键词5"],
      "min_value": 最小值,
      "max_value": 最大值
    }
  },
  
  "[变量名]_reset": {
    "keywords": ["重置关键词1", "重置关键词2"]
  }
}
```

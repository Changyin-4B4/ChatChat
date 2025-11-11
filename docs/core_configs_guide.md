# 核心配置覆盖指南（core_configs.json）

本文件说明如何通过 `core_configs.json` 定义游玩中的全局配置。JSON 必须包含所有键；值为空则不覆写，非空即覆写。

* **文件名** ：`core_configs.json`
* **位置** ：工作目录根目录（与 `config/`、`data/` 同级）

## 解析规则

* **空值不覆写** ：`null`、空字符串 `""`、空对象 `{}`、空数组 `[]` → 使用程序内置默认值
* **非空即覆写** ：将 JSON 中对应键的值直接替换 `core.configs` 的同名变量
* **整体替换** ：对象类型（如 `API_PROVIDERS`、`DEFAULT_WORKFLOW_CONFIG`）为整体替换，不支持"部分字段合并"行为
* **路径读取** ：`DEFAULT_OPENING` 仅存储路径字符串（相对于工作目录），实际内容读取在使用处完成

---

## 键列表与含义

### 1. LENGTH_LIMIT（数组）

* **类型** ：`[int, int]`
* **默认** ：`[500, 700]`
* **用途** ：控制创作内容的字数范围（最小值，最大值）
* **格式要求** ：
* 必须是包含两个整数的数组
* 第一个值（最小值）必须小于第二个值（最大值）
* 负数表示不限制：`-1` 表示该边界不生效
* **示例** ：

```json
  "LENGTH_LIMIT": [100, 200]   // 100-200 字"LENGTH_LIMIT": [-1, 500]    // 最多 500 字（无下限）"LENGTH_LIMIT": [300, -1]    // 至少 300 字（无上限）"LENGTH_LIMIT": [-1, -1]     // 无字数限制
```

### 2. USER_NAME（字符串）

* **默认** ：`"布雷德"`
* **用途** ：替换 prompt 中的 `<user>` 标签
* **示例** ：

```json
  "USER_NAME": "小明"
```

### 3. CHAT_METHOD（整数）

* **默认** ：`0`
* **取值** ：`0` 或 `1`
* **说明** ：
* `0`：指导式对话
  * 玩家输入用于指导 LLM 创作
  * 创作内容会体现（一定程度上复述）输入
  * 输入**不**进入聊天记录
* `1`：交互式对话
  * 玩家输入进入聊天记录
  * 创作内容会以输入为已发送的剧情续写
* **注意** ：如需使用交互式对话，还需修改 `create` 对应的 YAML 文件的相关开关
* **示例** ：

```json
  "CHAT_METHOD": 1  // 启用交互式对话
```

### 4. MEMORY_DEPTH（整数）

* **默认** ：`5`
* **用途** ：历史摘要的回忆深度（控制保留最近几层完整对话）
* **示例** ：

```json
  "MEMORY_DEPTH": 10  // 保留最近 10 层完整对话
```

### 5. JUDGER_MEMORY_DEPTH（整数）

* **默认** ：`3`
* **用途** ：Judger 阶段（pre_process 和 post_process）的回忆深度
* **示例** ：

```json
  "JUDGER_MEMORY_DEPTH": 5
```

### 6. DEFAULT_OPENING（字符串，路径）

* **默认** ：`"information/first_message.txt"`
* **用途** ：开场白文件路径（相对于工作目录）
* **行为** ：
* 填写路径字符串会覆写默认路径
* 留空 `""` 则不覆写，使用默认值
* 内容读取在调用处通过 `global_io_manager.read_txt(DEFAULT_OPENING)` 完成
* **示例** ：

```json
  "DEFAULT_OPENING": "custom/my_opening.txt"
```

### 7. API_PROVIDERS（对象）

* **默认** ：

```json
  {  "deepseek": {    "api_key": "",    "base_url": "https://api.deepseek.com"  },  "siliconflow": {    "api_key": "",    "base_url": "https://api.siliconflow.cn/v1"  },  "gemini": {    "api_key": "",    "base_url": ""  }}
```

* **用途** ：配置各 API 供应商的密钥和地址
* **支持的供应商** ：
* `deepseek`：DeepSeek API
* `siliconflow`：硅基流动 API
* `gemini`：Google Gemini API
* **注意事项** ：
* **整体替换** ：如需修改某一项，请完整给出整个对象（包含所有供应商）
* 不支持单项增量合并
* `api_key` 为空时该供应商不可用
* **示例** ：

```json
  "API_PROVIDERS": {  "deepseek": {    "api_key": "sk-xxxxx",    "base_url": "https://api.deepseek.com"  },  "siliconflow": {    "api_key": "sk-yyyyy",    "base_url": "https://api.siliconflow.cn/v1"  },  "gemini": {    "api_key": "your-gemini-key",    "base_url": ""  }}
```

### 8. DEFAULT_WORKFLOW_CONFIG（对象）

* **默认** ：

```json
  {  "stages": ["pre_process", "create", "post_process"],  "api_configs": {    "pre_process": {      "provider": "deepseek",      "model": "deepseek-reasoner"    },    "create": {      "provider": "deepseek",      "model": "deepseek-reasoner"    },    "post_process": {      "provider": "deepseek",      "model": "deepseek-reasoner"    }  },  "prompt_configs": {    "pre_process": "judger_prompt_pre.yaml",    "create": "prompt.yaml",    "post_process": "judger_prompt_post.yaml"  }}
```

* **用途** ：控制各阶段的 API 供应商、模型和提示词文件
* **字段说明** ：
* `stages`：工作流阶段列表（通常固定为三个阶段）
* `api_configs`：各阶段使用的 API 配置
  * `provider`：API 供应商名称（必须在 `API_PROVIDERS` 中存在）
  * `model`：模型名称（供应商支持的模型标识符）
* `prompt_configs`：各阶段使用的 YAML 提示词文件（相对于 `prompts/` 目录）
* **注意事项** ：
* **整体替换** ：修改任何部分都需提供完整对象
* `provider` 必须在 `API_PROVIDERS` 中已配置且有效
* YAML 文件路径相对于 `prompts/` 目录
* **示例** ：

```json
  "DEFAULT_WORKFLOW_CONFIG": {  "stages": ["pre_process", "create", "post_process"],  "api_configs": {    "pre_process": {      "provider": "deepseek",      "model": "deepseek-reasoner"    },    "create": {      "provider": "siliconflow",      "model": "deepseek-ai/DeepSeek-V3"    },    "post_process": {      "provider": "gemini",      "model": "gemini-2.0-flash-exp"    }  },  "prompt_configs": {    "pre_process": "judger_prompt_pre.yaml",    "create": "custom_prompt.yaml",    "post_process": "judger_prompt_post.yaml"  }}
```

---

## 完整示例

### 示例 1：保留所有默认值

```json
{
  "LENGTH_LIMIT": [],
  "USER_NAME": "",
  "CHAT_METHOD": null,
  "MEMORY_DEPTH": null,
  "JUDGER_MEMORY_DEPTH": null,
  "DEFAULT_OPENING": "",
  "API_PROVIDERS": {},
  "DEFAULT_WORKFLOW_CONFIG": {}
}
```

### 示例 2：基础配置（仅修改必要项）

```json
{
  "LENGTH_LIMIT": [100, 200],
  "USER_NAME": "小明",
  "CHAT_METHOD": 0,
  "MEMORY_DEPTH": 5,
  "JUDGER_MEMORY_DEPTH": 3,
  "DEFAULT_OPENING": "information/first_message.txt",
  "API_PROVIDERS": {
    "deepseek": {
      "api_key": "sk-your-deepseek-key",
      "base_url": "https://api.deepseek.com"
    },
    "siliconflow": {
      "api_key": "",
      "base_url": "https://api.siliconflow.cn/v1"
    },
    "gemini": {
      "api_key": "",
      "base_url": ""
    }
  },
  "DEFAULT_WORKFLOW_CONFIG": {
    "stages": ["pre_process", "create", "post_process"],
    "api_configs": {
      "pre_process": {
        "provider": "deepseek",
        "model": "deepseek-reasoner"
      },
      "create": {
        "provider": "deepseek",
        "model": "deepseek-chat"
      },
      "post_process": {
        "provider": "deepseek",
        "model": "deepseek-reasoner"
      }
    },
    "prompt_configs": {
      "pre_process": "judger_prompt_pre.yaml",
      "create": "prompt.yaml",
      "post_process": "judger_prompt_post.yaml"
    }
  }
}
```

### 示例 3：多模型混用配置

```json
{
  "LENGTH_LIMIT": [500, 700],
  "USER_NAME": "布雷德",
  "CHAT_METHOD": 0,
  "MEMORY_DEPTH": 10,
  "JUDGER_MEMORY_DEPTH": 5,
  "DEFAULT_OPENING": "information/first_message.txt",
  "API_PROVIDERS": {
    "deepseek": {
      "api_key": "sk-deepseek-key",
      "base_url": "https://api.deepseek.com"
    },
    "siliconflow": {
      "api_key": "sk-siliconflow-key",
      "base_url": "https://api.siliconflow.cn/v1"
    },
    "gemini": {
      "api_key": "gemini-key",
      "base_url": ""
    }
  },
  "DEFAULT_WORKFLOW_CONFIG": {
    "stages": ["pre_process", "create", "post_process"],
    "api_configs": {
      "pre_process": {
        "provider": "deepseek",
        "model": "deepseek-reasoner"
      },
      "create": {
        "provider": "siliconflow",
        "model": "deepseek-ai/DeepSeek-V3"
      },
      "post_process": {
        "provider": "gemini",
        "model": "gemini-2.0-flash-exp"
      }
    },
    "prompt_configs": {
      "pre_process": "judger_prompt_pre.yaml",
      "create": "prompt.yaml",
      "post_process": "judger_prompt_post.yaml"
    }
  }
}
```

---

## 常见错误与排查

### 1. LENGTH_LIMIT 格式错误

❌  **错误** ：

```json
"LENGTH_LIMIT": "100,200"  // 字符串
```

✓  **正确** ：

```json
"LENGTH_LIMIT": [100, 200]  // 数组
```

### 2. LENGTH_LIMIT 最小值大于最大值

❌  **错误** ：

```json
"LENGTH_LIMIT": [700, 500]
```

✓  **正确** ：

```json
"LENGTH_LIMIT": [500, 700]
```

### 3. API_PROVIDERS 部分覆写

❌  **错误** （想只修改 deepseek 的 key）：

```json
"API_PROVIDERS": {
  "deepseek": {
    "api_key": "new-key"
  }
}
```

 **问题** ：会丢失 `siliconflow` 和 `gemini` 的配置！

✓  **正确** ：

```json
"API_PROVIDERS": {
  "deepseek": {
    "api_key": "new-key",
    "base_url": "https://api.deepseek.com"
  },
  "siliconflow": {
    "api_key": "",
    "base_url": "https://api.siliconflow.cn/v1"
  },
  "gemini": {
    "api_key": "",
    "base_url": ""
  }
}
```

### 4. provider 不存在

❌  **错误** ：

```json
"api_configs": {
  "create": {
    "provider": "openai",  // API_PROVIDERS 中没有定义
    "model": "gpt-4"
  }
}
```

✓  **正确** ：先在 `API_PROVIDERS` 中添加 `openai`

### 5. 路径错误

❌  **错误** ：

```json
"DEFAULT_OPENING": "C:/Users/.../first_message.txt"  // 绝对路径
```

✓  **正确** ：

```json
"DEFAULT_OPENING": "information/first_message.txt"  // 相对路径
```

---


### 配置验证

程序启动时会自动验证配置：

* `LENGTH_LIMIT` 格式和逻辑正确性
* `API_PROVIDERS` 结构完整性
* `DEFAULT_WORKFLOW_CONFIG` 中的 provider 存在性

如果验证失败，会抛出明确的错误信息。

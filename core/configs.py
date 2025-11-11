# ========== 用户配置区域 ==========
# 对话长度限制（最小，最大）
LENGTH_LIMIT = [500,700]

# 用户名配置（用于替换<user>标签）
USER_NAME = "布雷德"

# 决定聊天模式的参数，0代表指导式对话，LLM会将玩家的输入融入创作，聊天记录不会包含玩家输入；
# 1代表交互式对话，LLM会在玩家输入的基础上延续，聊天记录会包含玩家输入；
CHAT_METHOD = 0

# 回忆深度配置（控制历史摘要生成）
MEMORY_DEPTH = 10

# JUDGER回忆深度配置（控制历史摘要生成）
JUDGER_MEMORY_DEPTH = 10

# 预设开场模板配置（从文件读取）
DEFAULT_OPENING = "information/first_message.txt"

# API配置 - 各供应商的API密钥和URL
API_PROVIDERS = {
    "deepseek": {
        "api_key": "",  # 请替换为你的实际API密钥
        "base_url": "https://api.deepseek.com"
    },
    "kimi": {
      "api_key": "",  # 请替换为你的实际API密钥
      "base_url": "https://api.moonshot.cn/v1"
    },
    "siliconflow": {
      "api_key": "",  # 请替换为你的实际API密钥
      "base_url": "https://api.siliconflow.cn/v1"
    },
    "gemini": {
      "api_key": "",  # 请替换为你的实际API密钥
      "base_url": ""
    }
}

# ========== 工作流配置区域 ==========
# 默认工作流配置
DEFAULT_WORKFLOW_CONFIG = {
    "stages": ["pre_process", "create", "post_process"],
    "api_configs": {
        "pre_process": {
            "provider": "deepseek",
            "model": "deepseek-reasoner"
        },
        "create": {
            "provider": "deepseek",
            "model": "deepseek-reasoner"
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
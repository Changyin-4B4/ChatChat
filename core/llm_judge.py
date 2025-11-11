from __future__ import annotations
import json
import yaml
import os
import re
from typing import Dict, TYPE_CHECKING
from enum import Enum
from collections import deque

from .configs import USER_NAME, JUDGER_MEMORY_DEPTH
from .prompts import generate_history_summary
from .io_manager import global_io_manager

# 导入Variable类
if TYPE_CHECKING:
    from .variables_update import Variable

class TaskType(Enum):
    """任务类型枚举"""
    UPDATE = "update"
    RESET = "reset"

class TaskInstance:
    """任务实例类"""
    
    def __init__(self, variable_instance: Variable, txt_path: str, task_type: TaskType):
        """
        初始化任务实例
        
        Args:
            variable_instance: 变量实例（来自variables_update.py中的Variable类）
            txt_path: txt文件路径
            task_type: 任务类型
        """
        self.variable_instance = variable_instance
        
        # 解析txt文件内容
        self.task_name = ""
        self.task_description = ""
        self._parse_txt_file(txt_path)
        
        # 处理任务类型
        if isinstance(task_type, str):
            self.task_type = TaskType(task_type)
        else:
            self.task_type = task_type
            
    # 功能：解析任务定义的 txt 文件，提取任务名与描述（保持原有容忍逻辑）
    def _parse_txt_file(self, txt_path: str):
        """
        zh: 解析txt文件，提取task_name和task_description。要求 txt_path 为相对路径，
            使用 IO 管理器读取原始文本内容并进行标签解析。
        en: Parse a txt file to extract task_name and task_description. Requires
            txt_path to be a relative path; reads raw text via IO manager and parses tags.
        """
        if not isinstance(txt_path, str) or not txt_path.strip():
            raise TypeError(f"参数 txt_path 必须为非空字符串的相对路径，当前值为 {txt_path!r}；期望：'relative/path/to/file.txt'")

        if os.path.isabs(txt_path):
            raise ValueError(f"参数 txt_path 必须为相对路径，当前为绝对路径：{txt_path}；期望：'relative/path/to/file.txt'")
        
        # print(f"开始读取任务定义文件: {txt_path}")  # 调试：记录待解析的文件路径
        content = global_io_manager.read_txt(txt_path)
        # print(f"文件读取完成，长度 {len(content)} 字符")  # 调试：确认读取的内容长度
        
        # 提取<name>与</name>之间的内容并去除首尾换行符（保持原容忍逻辑：缺失标签不抛错）
        name_start = content.find('<name>')
        name_end = content.find('</name>')
        if name_start != -1 and name_end != -1:
            self.task_name = content[name_start + 6:name_end].strip()
            # print(f"解析到任务名: {self.task_name}")  # 调试：记录解析的任务名

        # 提取<description>与</description>之间的内容并去除首尾换行符（保持原容忍逻辑）
        desc_start = content.find('<description>')
        desc_end = content.find('</description>')
        if desc_start != -1 and desc_end != -1:
            self.task_description = content[desc_start + 13:desc_end].strip()
            # print("解析到任务描述")  # 调试：记录解析到任务描述

class TaskManager:
    """任务管理器类"""
    
    def __init__(self):
        """
        初始化任务管理器
        """
        self.task_queue = deque()  # 任务列表（队列）
        self.pending_update_group = []  # 待更新组
        self.assembly_list = []  # 待组装列表（txt路径列表）
        self.llm_results = {}  # LLM返回结果

    def add_task(self, task: TaskInstance):
        """添加任务到任务列表"""
        self.task_queue.append(task)
    
    def process_all_tasks(self, user_input: str, phase: str, prompt_config: str) -> Dict[str, float]:
        """
        处理所有任务的主流程
        
        Args:
            user_input: 用户输入文本，用于LLM分析
            phase: 处理阶段，"pre_update"或"post_update"
            prompt_config: 提示配置字典，包含provider、model和prompt_config
            
        Returns:
            更新结果字典 {变量名: 返回结果}
            - 对于update任务：返回结果为更新值（正负数），直接与原值相加
            - 对于reset任务：返回结果为0/1值，1表示重置为0，0表示保持原值
        """
        # 步骤一和二：组装prompt
        self._assemble_prompt_batch()
            
        # 步骤三：调用LLM处理
        messages = self._build_message(user_input, phase, prompt_config)
            
        return messages
    
    def _assemble_prompt_batch(self):
        """组装prompt批次（步骤一和二）"""
        while len(self.pending_update_group) < 5 and self.task_queue:
            # 取第一个任务实例
            task = self.task_queue.popleft()
            
            # 检查task是否已在待更新组
            if task not in self.pending_update_group:
                # 移入待更新组
                self.pending_update_group.append(task)
                
                # 获取当前值并组装为一组 (name, description, value)
                current_value = task.variable_instance.value
                task_info = (task.task_name, task.task_description, current_value)
                
                # 装入组装列表
                self.assembly_list.append(task_info)
    
    def _build_message(self, user_input: str, phase: str, prompt_config: str):
        """使用LLM处理（步骤三）- 集成DeepSeek API"""
        if not self.assembly_list:
            return {}
        
        # 组装prompt
        task_definitions_parts = []
        for i, task_info in enumerate(self.assembly_list, 1):
            # task_info是(task_name, task_description, current_value)元组
            task_name = task_info[0]
            task_description = task_info[1]
            
            # 按照指定格式拼接
            content = f"任务名：{task_name}\n{task_description}"
            task_definitions_parts.append(content)
            
        task_definitions = "\n".join(task_definitions_parts)
        
        if phase == "pre_update":
            messages = build_judger_messages(task_definitions, user_input, phase, prompt_config)
        elif phase == "post_update":
            # 组装current_values
            current_values_parts = []
            for i, task_info in enumerate(self.assembly_list, 1):
                task_name = task_info[0]
                current_value = task_info[2]
            
                # 按照指定格式拼接：任务名：（第一项），当前值：（第三项）
                value_info = f"任务名：{task_name}，当前值：{current_value}"
                current_values_parts.append(value_info)
                current_values = "\n".join(current_values_parts)
            messages = build_judger_messages(task_definitions, user_input, phase, prompt_config, current_values)
        
        return messages

    # 功能：解析 LLM 的 JSON 响应并按任务类型生成更新结果（不改变业务逻辑）
    def _parse_llm_response(self, response: str) -> Dict[str, float]:
        """解析LLM返回的JSON格式结果并应用更新逻辑"""
        if not isinstance(response, str):
            raise TypeError(f"参数 response 必须为字符串类型（JSON 格式），当前类型为 {type(response).__name__}；期望：JSON 对象字符串")
        if not response.strip():
            raise ValueError("参数 response 不能为空字符串；原因：无法进行JSON解析；期望：非空的JSON对象字符串，如 '{\"任务名\": 值}'")
        
        # 在 json.loads 之前添加预处理
        def extract_json(response: str) -> str:
            """
            从响应中提取 JSON 内容
            处理以下格式：
            1. 直接的 JSON: {...}
            2. Markdown 代码块: ```json\n{...}\n```
            3. 带其他文本的响应
            """
            response = response.strip()
            
            # 尝试匹配 markdown 代码块中的 JSON
            markdown_pattern = r'```(?:json)?\s*(\{.*?\})\s*```'
            match = re.search(markdown_pattern, response, re.DOTALL)
            if match:
                return match.group(1)
            
            # 尝试直接提取花括号包裹的内容
            brace_pattern = r'\{.*\}'
            match = re.search(brace_pattern, response, re.DOTALL)
            if match:
                return match.group(0)
            
            # 如果都没匹配到，返回原始内容（可能本身就是纯 JSON）
            return response
        
        # print("开始解析 LLM 响应 JSON")  # 调试：记录解析开始
        # 使用方法
        # print("开始解析 LLM 响应 JSON")
        cleaned_response = extract_json(response)
        parsed_data = json.loads(cleaned_response)
        
        # 打印解析后的字典内容进行检验（注释形式保留）
        # print("=" * 50)  # 调试：分隔线
        # print("解析后的字典内容:")  # 调试：提示解析完成
        # print("=" * 50)  # 调试：分隔线
        # for key, value in parsed_data.items():
        #     print(f"任务名: {key}, 值: {value}, 类型: {type(value)}")  # 调试：逐项输出解析结果
        # print("=" * 50)  # 调试：分隔线
        
        # 收集更新结果，不实际应用更新
        update_results = []
        
        while self.pending_update_group:
            # 从pending list取1个task实例
            task = self.pending_update_group.pop(0)
            
            # 检索task type
            task_type = task.task_type
            
            # 以task name为key检索字典
            task_name = task.task_name
            if task_name not in parsed_data:
                # print(f"警告：在LLM返回结果中未找到任务 '{task_name}'")  # 调试：记录缺失的任务键
                continue
            
            value = parsed_data[task_name]
            
            if task_type == TaskType.RESET:
                # 重置逻辑
                if value == 0 or value == 0.0:
                    # 返回实例和整型数据0
                    update_results.append((task.variable_instance, 0))
                    # print(f"任务 '{task_name}' 重置条件未满足 (值: {value})，记录为0")  # 调试：记录重置未满足
                elif value == 1 or value == 1.0:
                    # 返回实例和字符串"reset"
                    update_results.append((task.variable_instance, "reset"))
                    # print(f"任务 '{task_name}' 重置条件满足，记录为reset")  # 调试：记录重置满足
                else:
                    # 将警告信息作为delta值包含在二元组中（保持原逻辑）
                    warning_msg = f"警告：任务 '{task_name}' 重置值异常 (值: {value})，应为0或1"
                    update_results.append((task.variable_instance, warning_msg))
                    # print(warning_msg)  # 调试：记录异常重置值
                        
            elif task_type == TaskType.UPDATE:
                # 更新逻辑 - 返回实例和delta值
                update_results.append((task.variable_instance, value))
                # print(f"任务 '{task_name}' 更新记录：delta = {value}")  # 调试：记录更新值
            
            else:
                # print(f"警告：未知的任务类型 '{task_type}' for 任务 '{task_name}'")  # 调试：记录未知任务类型
                pass
        
        # print(f"解析完成，共生成 {len(update_results)} 条更新记录")  # 调试：记录更新结果数量
        return update_results
    
    def _clear_temporary_data(self):
        """清空临时数据（步骤五）"""
        self.task_queue.clear()
        self.assembly_list.clear()
        self.llm_results.clear()
        self.pending_update_group.clear()
    
def replace_placeholders_in_content(content, placeholders):
    """
    替换内容中的占位符
    
    Args:
        content (str): 要处理的内容
        placeholders (dict): 占位符字典
    
    Returns:
        str: 替换后的内容
    """
    if not content or not isinstance(content, str):
        return content
    
    result = content
    for key, value in placeholders.items():
        placeholder = f"{{{key}}}"
        if placeholder in result:
            result = result.replace(placeholder, str(value) if value is not None else "")
    
    return result

# 功能：构建JUDGER消息列表，加载 YAML 模板并替换占位符（保持原有阶段分支）
def build_judger_messages(task_definitions: str, current_input: str, phase: str, prompt_config: str, current_values: str = None):
    """
    构建JUDGER对话结构 - 基于不同阶段的 yaml 配置
    
    Args:
        task_definitions (str): 任务定义文本，用于填充 {task_definitions_placeholder}
        current_input (str): 当前输入文本，用于填充 {current_input_placeholder}
        phase (str): 阶段标识，'pre' 或 'post'
    
    Returns:
        list: 处理后的消息列表，每个消息包含 role 和 content 字段
        
    功能特性:
        - pre阶段：从 judger_prompt_pre.yaml 加载消息模板
        - post阶段：从 judger_prompt_post.yaml 加载消息模板，并添加额外占位符
        - 替换占位符并返回标准的消息格式供 LLM 使用
    """
    if not isinstance(task_definitions, str) or not task_definitions.strip():
        raise ValueError("参数 task_definitions 必须为非空字符串；原因：无法填充模板；期望：包含任务定义文本")
    if not isinstance(current_input, str):
        raise TypeError(f"参数 current_input 必须为字符串类型；当前类型为 {type(current_input).__name__}；期望：字符串")
    if not isinstance(phase, str) or phase not in ("pre_update", "post_update"):
        raise ValueError(f"参数 phase 必须为 'pre_update' 或 'post_update'；当前值为 {phase!r}")
    if not isinstance(prompt_config, str) or not prompt_config.strip():
        raise ValueError(f"参数 prompt_config 必须为非空字符串（文件名）；当前值为 {prompt_config!r}")
    
    # 根据 prompt_config 参数组装配置文件路径（相对路径）
    yaml_path = f"prompts/{prompt_config}"
    # print(f"开始加载 YAML 配置: {yaml_path}")  # 调试：记录配置文件路径
    
    # 加载 YAML 配置（通过 IO 管理器读取原始文本后解析）
    raw_yaml = global_io_manager.read_yaml(yaml_path)
    yaml_config = yaml.safe_load(raw_yaml)
    
    if not yaml_config:
        raise ValueError(f"配置文件 {yaml_path} 为空或解析结果为空；原因：模板内容缺失；期望：包含消息块列表")
    
    # 初始化占位符
    placeholders = {
        'task_definitions_placeholder': task_definitions,
        'current_input_placeholder': current_input,
        'user': USER_NAME
    }
    
    # post阶段添加额外占位符
    if phase == "post_update":
        placeholders['plot_history_placeholder'] = generate_history_summary(memory_depth=JUDGER_MEMORY_DEPTH)
        placeholders['current_state_placeholder'] = current_values
    
    # 处理消息块
    processed_messages = []
    
    for block in yaml_config:
        role = block.get('role', '')
        content = block.get('content', '')
        # print(f"处理消息块：role={role}")  # 调试：记录当前处理的消息块角色
        
        # 替换占位符
        content = replace_placeholders_in_content(content, placeholders)
        if not isinstance(content, str):
            raise TypeError(f"消息内容替换后必须为字符串类型；当前类型为 {type(content).__name__}；期望：字符串")
        
        # 跳过空内容
        if not content.strip():
            continue
        
        # 创建消息
        message = {
            "role": role,
            "content": content.strip()
        }
        processed_messages.append(message)
    
    # print(f"生成消息数量：{len(processed_messages)}")  # 调试：确认构建结果数量
    return processed_messages
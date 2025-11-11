from __future__ import annotations
from calendar import c
from typing import TYPE_CHECKING
import json
import yaml
import re

if TYPE_CHECKING:
    from .variables_update import VariableManager

from .configs import MEMORY_DEPTH, USER_NAME, CHAT_METHOD, LENGTH_LIMIT
from .io_manager import global_io_manager

def load_json_config(config_file="prompts_config.json"):
    """加载JSON配置文件"""
    # # print(f"开始加载 JSON 配置: {config_file}")  # 调试：记录配置文件路径
    if not isinstance(config_file, str) or not config_file.strip():
        raise ValueError(f"参数 config_file 必须为非空字符串，当前值为 {config_file!r}；期望：有效 JSON 配置文件路径")
    if not global_io_manager.exists(config_file):
        raise FileNotFoundError(f"JSON 配置文件不存在：{config_file}；原因：路径不可用或文件缺失；期望：提供存在且可读的 JSON 文件路径")
    raw_json = global_io_manager.read_json(config_file)
    if raw_json is None or (isinstance(raw_json, str) and not raw_json.strip()):
        raise ValueError(f"读取到的 JSON 内容为空；文件：{config_file}；原因：文件内容为空或读取失败；期望：包含有效 JSON 文本")
    data = json.loads(raw_json)
    # # print(f"JSON 解析成功，类型：{type(data).__name__}")  # 调试：确认解析结果
    return data

def read_text_file(file_path):
    """读取文本文件内容"""
    # # print(f"开始读取文本文件: {file_path}")  # 调试：记录目标文件路径
    if not isinstance(file_path, str) or not file_path.strip():
        raise ValueError(f"参数 file_path 必须为非空字符串，当前值为 {file_path!r}；期望：有效文件路径")
    if not global_io_manager.exists(file_path):
        raise FileNotFoundError(f"文本文件不存在：{file_path}；原因：路径不可用或文件缺失；期望：提供存在且可读的文本文件路径")
    content = global_io_manager.read_txt(file_path)
    if content is None:
        raise OSError(f"读取文本文件失败：{file_path}；原因：读取接口返回 None；期望：返回非空字符串内容")
    content = content.strip()
    # # print(f"读取完成，字符数：{len(content)}")  # 调试：确认读取结果
    return content

def load_yaml_file(yaml_file):
    """加载YAML配置文件"""
    # # print(f"开始加载 YAML 文件: {yaml_file}")  # 调试：记录配置文件路径
    if not isinstance(yaml_file, str) or not yaml_file.strip():
        raise ValueError(f"参数 yaml_file 必须为非空字符串，当前值为 {yaml_file!r}；期望：有效 YAML 文件路径")
    if not global_io_manager.exists(yaml_file):
        raise FileNotFoundError(f"YAML 配置文件不存在：{yaml_file}；原因：路径不可用或文件缺失；期望：提供存在且可读的 YAML 文件路径")
    raw_yaml = global_io_manager.read_yaml(yaml_file)
    if raw_yaml is None or (isinstance(raw_yaml, str) and not raw_yaml.strip()):
        raise ValueError(f"读取到的 YAML 内容为空；文件：{yaml_file}；原因：文件内容为空或读取失败；期望：包含有效 YAML 文本")
    data = yaml.safe_load(raw_yaml)
    # # print(f"YAML 解析成功，类型：{type(data).__name__}")  # 调试：确认解析结果
    return data

def process_message_blocks(message_blocks, placeholders):
    """
    处理消息块，支持空role拼接和enable控制，内置占位符替换功能。
    该函数用于处理聊天消息的格式化和组装，支持条件过滤、占位符替换和消息合并等功能。
    
    Args:
        message_blocks (list): 消息块列表，每个块应包含以下字段：
            - role (str, optional): 消息角色（如 'user', 'assistant'），空值表示拼接到前一消息
            - content (str): 消息内容，支持 {key} 格式的占位符
            - enable (bool, optional): 是否启用该消息块，默认为 True
        placeholders (dict): 占位符替换字典，键为占位符名称，值为替换内容
    
    Returns:
        list: 处理后的消息列表，每个消息包含：
            - role (str): 消息角色
            - content (str): 处理后的消息内容（已替换占位符和 <user> 标记）
    
    功能特性:
        - 根据 enable 字段过滤消息块（默认启用）
        - 替换内容中的 {key} 格式占位符
        - 空 role 的消息块会拼接到前一个有效消息中（用换行符连接）
        - 自动将 <user> 标记替换为 USER_NAME 常量
        - 跳过空内容的消息块
    """
    # # print(f"开始处理消息块，数量：{len(message_blocks) if message_blocks else 0}")  # 调试：记录输入块数量
    
    def replace_placeholders(text, placeholders):
        """替换文本中的占位符（内部函数）"""
        if not text or not isinstance(text, str):
            return text
        
        result = text
        for key, value in placeholders.items():
            placeholder = f"{{{key}}}"
            if placeholder in result:
                result = result.replace(placeholder, str(value) if value is not None else "")
        
        return result
    
    if not message_blocks:
        return []
    
    processed_messages = []
    current_message = None
    
    for block in message_blocks:
        # 检查enable状态，默认为True
        enable = block.get('enable', True)
        if not enable:
            continue
        
        role = block.get('role', '').strip()
        content = block.get('content', '')
        
        # 替换占位符
        content = replace_placeholders(content, placeholders)
        
        if not content.strip():
            continue
        
        if role:  # 非空role，创建新消息
            # 如果有当前消息，先保存
            if current_message:
                processed_messages.append(current_message)
            
            # 创建新消息
            current_message = {
                "role": role,
                "content": content.strip()
            }
        else:  # 空role，拼接到当前消息
            if current_message:
                # 拼接内容，用换行符连接
                current_message["content"] += "\n" + content.strip()
            else:
                # 如果没有当前消息，跳过这个空role块
                continue
    
    # 添加最后一个消息
    if current_message:
        processed_messages.append(current_message)
    
    # 在返回前进行最后的替换：<user> 替换为 USER_NAME
    for message in processed_messages:
        message['content'] = message['content'].replace('<user>', USER_NAME)
    
    # # print(f"处理完成，输出消息数：{len(processed_messages)}")  # 调试：确认输出消息数量
    return processed_messages

def get_content_by_depth(vm: VariableManager, position, history_records, depth=0):
    """根据深度获取内容，遍历simple和complex配置
    
    Args:
        position (str): "position_0" 或 "position_1"
        history_records (str): 历史记录文本，用于关键词匹配
        depth (int): 深度值
    
    Returns:
        tuple: (content_parts, hint_parts)
    """
    # print(f"\n{'='*60}")
    # print(f"[DEBUG] get_content_by_depth 调用")
    # print(f"[DEBUG] position: {position}")
    # print(f"[DEBUG] depth: {depth}")
    # print(f"[DEBUG] history_records 长度: {len(history_records) if history_records else 0}")
    # print(f"{'='*60}\n")
    
    config = load_json_config()
    position_config = config.get(position, {})
    # print(f"[DEBUG] 加载配置完成，position_config 包含: {list(position_config.keys())}")
    
    content_parts = []
    hint_parts = []
    
    # ==================== SIMPLE 配置处理 ====================
    simple_configs = position_config.get('simple', {})
    # print(f"\n[DEBUG] === 开始处理 SIMPLE 配置 ===")
    # print(f"[DEBUG] simple_configs 数量: {len(simple_configs)}")
    
    for key in sorted(simple_configs.keys()):
        item = simple_configs[key]
        # print(f"\n[DEBUG] 处理 simple 配置项: {key}")
        # print(f"[DEBUG]   depth: {item.get('depth')} (目标: {depth})")
        
        if item.get('depth') == depth:
            # print(f"[DEBUG]   ✓ depth 匹配")
            keywords = item.get('keywords', [])
            # print(f"[DEBUG]   keywords: {keywords}")
            
            if keywords:
                keyword_matched = False
                for keyword in keywords:
                    if keyword in history_records:
                        keyword_matched = True
                        # print(f"[DEBUG]   ✓ 关键词匹配: {keyword}")
                        break
                if not keyword_matched:
                    # print(f"[DEBUG]   ✗ 关键词不匹配，跳过")
                    continue
            else:
                # print(f"[DEBUG]   无关键词要求")
                continue
            
            file_path = item.get('file', '')
            # print(f"[DEBUG]   file_path: {file_path}")
            
            if not file_path or not file_path.strip():
                # print(f"[DEBUG]   ✗ 文件路径为空，跳过")
                continue
            
            if not global_io_manager.exists(file_path):
                # print(f"[DEBUG]   ✗ 文件不存在，跳过")
                continue
            
            content = read_text_file(file_path)
            if not content or not content.strip():
                # print(f"[DEBUG]   ✗ 文件内容为空，跳过")
                continue
            
            # print(f"[DEBUG]   ✓ 成功添加内容 (长度: {len(content)})")
            content_parts.append(content.strip())
        else:
            # print(f"[DEBUG]   ✗ depth 不匹配，跳过")
            continue
    
    # print(f"\n[DEBUG] === SIMPLE 配置处理完成，添加了 {len(content_parts)} 项 ===\n")
    
    # ==================== COMPLEX 配置处理 ====================
    complex_configs = position_config.get('complex', {})
    # print(f"\n[DEBUG] === 开始处理 COMPLEX 配置 ===")
    # print(f"[DEBUG] complex_configs 数量: {len(complex_configs)}")
    
    for key in sorted(complex_configs.keys()):
        item = complex_configs[key]
        # print(f"\n[DEBUG] 处理 complex 配置项: {key}")
        # print(f"[DEBUG]   depth: {item.get('depth')} (目标: {depth})")
        
        if item.get('depth') == depth:
            # print(f"[DEBUG]   ✓ depth 匹配")
            keywords = item.get('keywords', [])
            # print(f"[DEBUG]   keywords: {keywords}")
            
            if keywords:
                keyword_matched = False
                for keyword in keywords:
                    if keyword in history_records:
                        keyword_matched = True
                        # print(f"[DEBUG]   ✓ 关键词匹配: {keyword}")
                        break
                if not keyword_matched:
                    # print(f"[DEBUG]   ✗ 关键词不匹配，跳过")
                    continue
            else:
                # print(f"[DEBUG]   无关键词要求")
                continue
            
            # 第一步：读绑定变量
            variable_binding = item.get('variable_binding', '')
            # print(f"[DEBUG]   variable_binding: {variable_binding}")
            
            if not variable_binding:
                # print(f"[DEBUG]   ✗ variable_binding 为空，跳过")
                continue
            
            # 支持单个变量绑定（字符串）或多个变量绑定（数组）
            if isinstance(variable_binding, str):
                if not variable_binding.strip():
                    # print(f"[DEBUG]   ✗ variable_binding 字符串为空，跳过")
                    continue
                variable_bindings = [variable_binding]
                # print(f"[DEBUG]   单个变量绑定: {variable_bindings}")
            elif isinstance(variable_binding, list):
                variable_bindings = [vb for vb in variable_binding if vb and vb.strip()]
                if not variable_bindings:
                    # print(f"[DEBUG]   ✗ variable_binding 列表为空，跳过")
                    continue
                # print(f"[DEBUG]   多个变量绑定: {variable_bindings}")
            else:
                # print(f"[DEBUG]   ✗ variable_binding 类型错误，跳过")
                continue
            
            # 解析变量绑定并获取变量对象
            variables = []
            for vb in variable_bindings:
                # print(f"[DEBUG]   查找变量: {vb}")
                if vb in vm.variables:
                    variable = vm.variables[vb]
                    variables.append(variable)
                    # print(f"[DEBUG]     ✓ 变量找到")
                else:
                    # print(f"[DEBUG]     ✗ 变量不存在")
                    continue
            
            if not variables:
                # print(f"[DEBUG]   ✗ 没有找到有效变量，跳过")
                continue
            
            # print(f"[DEBUG]   ✓ 成功解析 {len(variables)} 个变量")
            
            # 获取每个变量的 relative_value 和 relative_current_description
            int_tuple = []
            str_tuple = []
            
            for variable in variables:
                stage_info = variable.get_stage()
                relative_value = stage_info.get('relative_value')
                relative_description = stage_info.get('relative_current_description', '')
                
                # print(f"[DEBUG]   变量 {variable.name}:")
                # print(f"[DEBUG]     relative_value: {relative_value}")
                # print(f"[DEBUG]     relative_description: {relative_description}")
                
                # relative_value 可能是单一值或元组
                if isinstance(relative_value, tuple):
                    int_tuple.extend(relative_value)
                else:
                    int_tuple.append(relative_value)
                
                # relative_current_description 可能是单一值或元组
                if isinstance(relative_description, tuple):
                    str_tuple.extend(relative_description)
                else:
                    str_tuple.append(relative_description)
            
            # print(f"[DEBUG]   int_tuple: {int_tuple}")
            # print(f"[DEBUG]   str_tuple: {str_tuple}")
            
            if not int_tuple:
                # print(f"[DEBUG]   ✗ int_tuple 为空，跳过")
                continue
            
            # 第二步：读取 variable_binding_method
            variable_binding_method = item.get('variable_binding_method', [])
            # print(f"[DEBUG]   variable_binding_method: {variable_binding_method}")
            
            if not variable_binding_method:
                # print(f"[DEBUG]   ✗ variable_binding_method 为空，跳过")
                continue
            
            # 第三步：检查 relative_is_upgrade 标签
            # print(f"[DEBUG]   检查 relative_is_upgrade...")
            upgrade_changes = {}
            
            current_index = 0
            for i, variable in enumerate(variables):
                if hasattr(variable, 'relative_is_upgrade') and variable.relative_is_upgrade is not None:
                    # print(f"[DEBUG]     变量 {variable.name} 有阶段变化")
                    old_relative_value, new_relative_value = variable.relative_is_upgrade
                    # print(f"[DEBUG]       old: {old_relative_value}, new: {new_relative_value}")
                    
                    # 处理单一值或元组的情况
                    if isinstance(old_relative_value, tuple) and isinstance(new_relative_value, tuple):
                        for j, (old_val, new_val) in enumerate(zip(old_relative_value, new_relative_value)):
                            if old_val != new_val:
                                upgrade_changes[current_index + j] = (old_val, new_val)
                        current_index += len(old_relative_value)
                    else:
                        if old_relative_value != new_relative_value:
                            upgrade_changes[current_index] = (old_relative_value, new_relative_value)
                        current_index += 1
                else:
                    # print(f"[DEBUG]     变量 {variable.name} 无阶段变化")
                    stage_info = variable.get_stage()
                    relative_value = stage_info.get('relative_value')
                    if isinstance(relative_value, tuple):
                        current_index += len(relative_value)
                    else:
                        current_index += 1
            
            # print(f"[DEBUG]   upgrade_changes: {upgrade_changes}")
            
            # 解析 variable_binding_method 并生成 stage 文件路径
            def parse_binding_method(method, part_index=0):
                """递归解析绑定方法"""
                stage_keys = []
                
                for item_m in method:
                    if isinstance(item_m, list):
                        key_parts = []
                        for idx in item_m:
                            if idx < len(int_tuple):
                                key_parts.append(str(int_tuple[idx]))
                        if key_parts:
                            stage_key = f"stage_{'_'.join(key_parts)}"
                            stage_keys.append((part_index, stage_key))
                        part_index += 1
                    else:
                        if item_m < len(int_tuple):
                            stage_key = f"stage_{int_tuple[item_m]}"
                            stage_keys.append((part_index, stage_key))
                        part_index += 1
                
                return stage_keys
            
            stage_keys = parse_binding_method(variable_binding_method)
            # print(f"[DEBUG]   stage_keys: {stage_keys}")
            
            # 获取基础文件内容并检查 XML 标签
            base_file = item.get('base_file', '')
            base_content = ''
            xml_opening_tag = None
            
            # print(f"[DEBUG]   base_file: {base_file}")
            
            if base_file and base_file.strip():
                if global_io_manager.exists(base_file):
                    base_content = read_text_file(base_file)
                    if not (base_content and base_content.strip()):
                        # print(f"[DEBUG]     base_file 内容为空")
                        base_content = ''
                    else:
                        # print(f"[DEBUG]     base_file 读取成功 (长度: {len(base_content)})")
                        # 检查开头是否有 XML 开始标签
                        xml_tag_match = re.match(r'^<([a-zA-Z_][\w\-]*)(?:\s[^>]*)?>', base_content.strip())
                        if xml_tag_match:
                            xml_opening_tag = xml_tag_match.group(1)
                            # print(f"[DEBUG]     检测到 XML 标签: <{xml_opening_tag}>")
                else:
                    # print(f"[DEBUG]     base_file 不存在，跳过整个配置项")
                    continue
            else:
                # print(f"[DEBUG]     无 base_file")
                continue
            
            # 第四步：组合提示词
            # print(f"[DEBUG]   开始组合提示词...")
            stage_content = ''
            stages = item.get('stages', {})
            
            # 检查是否有阶段变化
            has_upgrade = bool(upgrade_changes)
            # print(f"[DEBUG]   has_upgrade: {has_upgrade}")
            
            if has_upgrade:
                # print(f"[DEBUG]   处理阶段变化...")
                # 有阶段变化，需要生成新旧内容
                old_stage_contents = []
                new_stage_contents = []
                
                # 为每个受影响的 part 生成新旧 stage key
                affected_parts = set()
                for change_index in upgrade_changes.keys():
                    for part_idx, stage_key in stage_keys:
                        method_item = variable_binding_method[part_idx] if part_idx < len(variable_binding_method) else None
                        if method_item is not None:
                            if isinstance(method_item, list):
                                if change_index in method_item:
                                    affected_parts.add(part_idx)
                            else:
                                if change_index == method_item:
                                    affected_parts.add(part_idx)
                
                # print(f"[DEBUG]   affected_parts: {affected_parts}")
                
                # 为受影响的 part 生成新旧内容
                for part_idx in affected_parts:
                    part_key = f"part_{part_idx}"
                    # print(f"[DEBUG]   处理 {part_key}...")
                    if part_key in stages:
                        old_int_tuple = int_tuple.copy()
                        new_int_tuple = int_tuple.copy()
                        
                        for change_idx, (old_val, new_val) in upgrade_changes.items():
                            old_int_tuple[change_idx] = old_val
                            new_int_tuple[change_idx] = new_val
                        
                        # 根据 binding method 生成对应的 stage key
                        method_item = variable_binding_method[part_idx]
                        if isinstance(method_item, list):
                            old_key_parts = [str(old_int_tuple[idx]) for idx in method_item if idx < len(old_int_tuple)]
                            new_key_parts = [str(new_int_tuple[idx]) for idx in method_item if idx < len(new_int_tuple)]
                            old_stage_key = f"stage_{'_'.join(old_key_parts)}"
                            new_stage_key = f"stage_{'_'.join(new_key_parts)}"
                        else:
                            old_stage_key = f"stage_{old_int_tuple[method_item]}" if method_item < len(old_int_tuple) else ""
                            new_stage_key = f"stage_{new_int_tuple[method_item]}" if method_item < len(new_int_tuple) else ""
                        
                        # print(f"[DEBUG]     old_stage_key: {old_stage_key}")
                        # print(f"[DEBUG]     new_stage_key: {new_stage_key}")
                        
                        # 读取旧内容
                        if old_stage_key and old_stage_key in stages[part_key]:
                            old_file = stages[part_key][old_stage_key]
                            # print(f"[DEBUG]     读取旧内容: {old_file}")
                            if old_file and global_io_manager.exists(old_file):
                                old_content = read_text_file(old_file)
                                if old_content and old_content.strip():
                                    old_stage_contents.append(old_content.strip())
                                    # print(f"[DEBUG]       ✓ 旧内容添加 (长度: {len(old_content)})")
                        
                        # 读取新内容
                        if new_stage_key and new_stage_key in stages[part_key]:
                            new_file = stages[part_key][new_stage_key]
                            # print(f"[DEBUG]     读取新内容: {new_file}")
                            if new_file and global_io_manager.exists(new_file):
                                new_content = read_text_file(new_file)
                                if new_content and new_content.strip():
                                    new_stage_contents.append(new_content.strip())
                                    # print(f"[DEBUG]       ✓ 新内容添加 (长度: {len(new_content)})")
                
                # 组合新内容作为常规提示词
                if new_stage_contents:
                    stage_content = '\n\n'.join(new_stage_contents)
                    # print(f"[DEBUG]   组合新内容完成 (总长度: {len(stage_content)})")
                
                # 生成变化提示词
                old_content_display = '\n\n'.join(old_stage_contents) if old_stage_contents else ""
                new_content_display = '\n\n'.join(new_stage_contents) if new_stage_contents else ""
                
                if old_content_display and new_content_display:
                    if old_content_display.strip() != new_content_display.strip():
                        change_prompt = (f"【变化提示】\n注意，从\n{old_content_display}\n变为了\n{new_content_display}\n"
                            f"请在创作时对变化加以描述。")
                        hint_parts.append(change_prompt)
                        # print(f"[DEBUG]   ✓ 添加变化提示 (新旧不同)")
                elif (not old_content_display) and new_content_display:
                    hint_parts.append(f"【变化提示】\n注意，新增了以下设定：\n{new_content_display}\n"
                        f"请在创作时对变化加以描述。")
                    # print(f"[DEBUG]   ✓ 添加变化提示 (新增设定)")
                elif old_content_display and (not new_content_display):
                    hint_parts.append(f"【变化提示】\n注意，以下设定已废除：\n{old_content_display}\n"
                                      f"请在创作时对变化加以描述。")
                    # print(f"[DEBUG]   ✓ 添加变化提示 (设定废除)")
            else:
                # print(f"[DEBUG]   无阶段变化，直接组合当前内容...")
                # 没有阶段变化，直接组合当前内容
                stage_contents = []
                for part_idx, stage_key in stage_keys:
                    part_key = f"part_{part_idx}"
                    # print(f"[DEBUG]     查找 {part_key} / {stage_key}")
                    if part_key in stages and stage_key in stages[part_key]:
                        stage_file = stages[part_key][stage_key]
                        # print(f"[DEBUG]       文件: {stage_file}")
                        if stage_file and global_io_manager.exists(stage_file):
                            content = read_text_file(stage_file)
                            if content and content.strip():
                                stage_contents.append(content.strip())
                                # print(f"[DEBUG]         ✓ 内容添加 (长度: {len(content)})")
                
                if stage_contents:
                    stage_content = '\n\n'.join(stage_contents)
                    # print(f"[DEBUG]   组合内容完成 (总长度: {len(stage_content)})")
            
            # 组合 complex 内容
            combined_content = ''
            if base_content:
                combined_content = base_content.strip()
                # print(f"[DEBUG]   添加 base_content (长度: {len(base_content)})")
            if stage_content:
                if combined_content:
                    combined_content += f"\n\n\n{stage_content}"
                else:
                    combined_content = stage_content
                # print(f"[DEBUG]   添加 stage_content (总长度: {len(combined_content)})")
            
            # 如果有 XML 开始标签，添加闭合标签
            if xml_opening_tag and combined_content:
                combined_content += f"\n</{xml_opening_tag}>"
                # print(f"[DEBUG]   ✓ 添加 XML 闭合标签: </{xml_opening_tag}>")
            
            # 只有当有实际内容时才添加
            if combined_content:
                def replace_placeholder(match):
                    """替换占位符的回调函数"""
                    element_num = int(match.group(1))
                    if element_num >= len(str_tuple):
                        raise IndexError(f"占位符 {{element_{element_num}}} 超出可用范围，str_tuple 长度为 {len(str_tuple)}；请确保占位符序号小于 {len(str_tuple)}")
                    return str_tuple[element_num]
                
                # print(f"[DEBUG]   替换占位符...")
                processed_content = re.sub(r'\{element_(\d+)\}', replace_placeholder, combined_content)
                # print(f"[DEBUG]   ✓ 占位符替换完成 (最终长度: {len(processed_content)})")
                content_parts.append(processed_content)
                # print(f"[DEBUG]   ✓ 成功添加 complex 内容到 content_parts")
            else:
                # print(f"[DEBUG]   ✗ combined_content 为空，跳过")
                continue
        else:
            # print(f"[DEBUG]   ✗ depth 不匹配，跳过")
            continue
    
    # print(f"\n[DEBUG] === COMPLEX 配置处理完成 ===\n")
    # print(f"[DEBUG] 最终结果:")
    # print(f"[DEBUG]   content_parts 数量: {len(content_parts)}")
    # print(f"[DEBUG]   hint_parts 数量: {len(hint_parts)}")
    # print(f"{'='*60}\n")
    
    return content_parts, hint_parts

def get_all_content_by_depth(vm: VariableManager, position, history_records):
    """获取所有深度的内容
    
    Args:
        position (str): "position_0" 或 "position_1"
        history_records (str): 历史记录文本，用于关键词匹配
    
    Returns:
        list: 所有内容列表
    """
    # # print(f"[DEBUG] 开始计算所有深度内容，position={position}")  # 调试：记录位置标识
    config = load_json_config()
    customizable = config.get(position, {})
    
    # 自动检测最大depth
    max_depth = 0
    
    # 检查simple配置中的最大depth
    simple_configs = customizable.get('simple', {})
    for item in simple_configs.values():
        depth = item.get('depth', 0)
        max_depth = max(max_depth, depth)
    
    # 检查complex配置中的最大depth
    complex_configs = customizable.get('complex', {})
    for item in complex_configs.values():
        depth = item.get('depth', 0)
        max_depth = max(max_depth, depth)
    
    # # print(f"[DEBUG] 自动检测到最大 depth：{max_depth}")  # 调试：记录最大深度
    all_content = []
    all_hints = []
    
    for depth in range(max_depth + 1):
        depth_content, depth_hints = get_content_by_depth(vm, position, history_records, depth)
        all_content.extend(depth_content)
        all_hints.extend(depth_hints)
    
    # # print(f"[DEBUG] 汇总完成，content={len(all_content)}, hints={len(all_hints)}")  # 调试：记录汇总数量
    return all_content, all_hints

def generate_history_summary(memory_depth=MEMORY_DEPTH):
    """
    根据回忆深度生成历史摘要（忽略最新一层）
    
    变更说明：
    - 读取 data.json 后，先抛弃最后一层（最大 layer）的所有记录；
    - 其余逻辑保持不变：CHAT_METHOD=0 输出 Assistant 内容，CHAT_METHOD=1 输出完整格式。
    """
    # # print(f"[DEBUG] 开始读取历史数据 data/data.json")  # 调试：开始读取数据文件
    raw_json = global_io_manager.read_json('data/data.json')
    data = json.loads(raw_json)
    # # print(f"[DEBUG] 已读取 data.json，记录数：{len(data) if data else 0}")  # 调试：确认已加载聊天记录
    
    # 直接使用data作为chat_records，因为新结构中没有chat_records包装
    if not data:
        return ""
    
    # 获取最大layer（最新一层）
    max_layer = max(int(record.get('layer', 0)) for record in data.values())
    # 新增：抛弃最后一层layer的所有内容
    filtered_records = {rid: rec for rid, rec in data.items() if int(rec.get('layer', 0)) < max_layer}
    if not filtered_records:
        return ""
    # 过滤后的最大layer
    filtered_max_layer = max(int(record.get('layer', 0)) for record in filtered_records.values())
    # # print(f"[DEBUG] 过滤后的最大层级：{filtered_max_layer}，回忆深度：{memory_depth}")  # 调试：记录层级与深度
    
    if CHAT_METHOD == 0:
        # 新逻辑：只提取Assistant内容，无格式化外层结构
        # 如果总层数小于等于回忆深度，全部显示Assistant对话内容
        if filtered_max_layer <= memory_depth:
            result = []
            # 按layer排序
            sorted_records = sorted(filtered_records.items(), key=lambda x: int(x[1].get('layer', 0)))
            
            for record_id, record in sorted_records:
                speaker = record.get('speaker', '')
                content = record.get('content', '')
                scene = record.get('scene', '')
                if speaker == 'Assistant' and content:
                    # 格式：(scene)\n content
                    if scene:
                        result.append(f"({scene})\n{content}")
                    else:
                        result.append(content)
            
            return '\n\n'.join(result)
        
        # 否则按规则处理
        result = []
        
        # 1. 前文摘要部分（1到x-t层）
        summary_layers = filtered_max_layer - memory_depth
        # # print(f"[DEBUG] 摘要层数（summary_layers）：{summary_layers}")  # 调试：记录摘要层范围
        if summary_layers > 0:
            # 按layer排序，只取Assistant的摘要
            sorted_records = sorted(filtered_records.items(), key=lambda x: int(x[1].get('layer', 0)))
            
            for record_id, record in sorted_records:
                layer = int(record.get('layer', 0))
                if layer <= summary_layers and record.get('speaker') == 'Assistant':
                    summary = record.get('summary', '')
                    scene = record.get('scene', '')
                    if summary:
                        # 格式：(scene)\n summary
                        if scene:
                            result.append(f"({scene})\n{summary}")
                        else:
                            result.append(summary)
        
        # 2. 最后t层的Assistant内容
        sorted_records = sorted(filtered_records.items(), key=lambda x: int(x[1].get('layer', 0)))
        
        for record_id, record in sorted_records:
            layer = int(record.get('layer', 0))
            if layer > summary_layers:  # 最后t层
                speaker = record.get('speaker', '')
                content = record.get('content', '')
                scene = record.get('scene', '')
                if speaker == 'Assistant' and content:
                    # 格式：(scene)\n content
                    if scene:
                        result.append(f"({scene})\n{content}")
                    else:
                        result.append(content)
        
        return '\n\n'.join(result)
    
    elif CHAT_METHOD == 1:
        # 原有逻辑：完整格式对话
        # 如果总层数小于等于回忆深度，全部显示对话正文
        if filtered_max_layer <= memory_depth:
            result = []
            # 按layer排序
            sorted_records = sorted(filtered_records.items(), key=lambda x: int(x[1].get('layer', 0)))
            
            for record_id, record in sorted_records:
                speaker = record.get('speaker', '')
                content = record.get('content', '')
                scene = record.get('scene', '')
                if speaker == 'User':
                    result.append(f'User："{content}"')
                elif speaker == 'Assistant':
                    # 格式：(scene)\n Assistant content
                    if scene:
                        result.append(f"({scene})\nAssistant：\"{content}\"")
                    else:
                        result.append(f'Assistant："{content}"')
            
            return '\n'.join(result)
        
        # 否则按规则处理
        result = []
        
        # 1. 前文摘要部分（1到x-t层）
        summary_layers = filtered_max_layer - memory_depth
        # # print(f"[DEBUG] 摘要层数（summary_layers）：{summary_layers}")  # 调试：记录摘要层范围
        if summary_layers > 0:
            result.append("前文摘要：")
            
            # 按layer排序，只取Assistant的摘要
            sorted_records = sorted(filtered_records.items(), key=lambda x: int(x[1].get('layer', 0)))
            
            for record_id, record in sorted_records:
                layer = int(record.get('layer', 0))
                if layer <= summary_layers and record.get('speaker') == 'Assistant':
                    summary = record.get('summary', '')
                    scene = record.get('scene', '')
                    if summary:
                        # 格式：(scene)\n summary
                        if scene:
                            result.append(f"({scene})\n{summary}")
                        else:
                            result.append(summary)
        
        # 2. 最后t层的完整对话
        sorted_records = sorted(filtered_records.items(), key=lambda x: int(x[1].get('layer', 0)))
        
        for record_id, record in sorted_records:
            layer = int(record.get('layer', 0))
            if layer > summary_layers:  # 最后t层
                speaker = record.get('speaker', '')
                content = record.get('content', '')
                scene = record.get('scene', '')
                if speaker == 'User':
                    result.append(f'User："{content}"')
                elif speaker == 'Assistant':
                    # 格式：(scene)\n Assistant content
                    if scene:
                        result.append(f"({scene})\nAssistant：\"{content}\"")
                    else:
                        result.append(f'Assistant："{content}"')
        
        return '\n'.join(result)
    
    else:
        # 默认返回空字符串，如果CHAT_METHOD不是0或1
        return ""

def generate_length_limit_text():
    """
    根据全局变量 LENGTH_LIMIT 生成长度限制文本
    
    使用：
    - LENGTH_LIMIT 为长度上下限列表，形如 [x, y]，x、y 为整数
    - 若 x < 0 表示不限制下界；若 y < 0 表示不限制上界
    
    Returns:
        str: 生成的长度限制文本
    
    Raises:
        ValueError/TypeError: 当 LENGTH_LIMIT 格式不正确时抛出异常
    """
    length_limit = LENGTH_LIMIT  # 使用全局配置，不再从 config 读取
    
    # 验证配置格式
    if not isinstance(length_limit, list) or len(length_limit) != 2:
        raise ValueError(f"LENGTH_LIMIT 必须为包含 2 个元素的列表，当前值为 {length_limit}；期望格式示例：[x, y]，其中 x、y 为整数")
    
    x, y = length_limit
    
    # 验证元素类型
    if not isinstance(x, int) or not isinstance(y, int):
        raise TypeError(f"LENGTH_LIMIT 的两个元素必须为整数，当前类型为 {type(x).__name__} 和 {type(y).__name__}；请提供 int 类型的上下限")
    
    # 处理各种情况
    if x < 0 and y < 0:
        return "正式创作，剧情无字数要求"
    elif x < 0:
        # x为负数，下界失效
        return f"正式创作，剧情需满足字数要求：不得多于{y}字"
    elif y < 0:
        # y为负数，上界失效
        return f"正式创作，剧情需满足字数要求：不得少于{x}字"
    else:
        # x,y均为自然数（非负整数）
        return f"正式创作，剧情需满足字数要求：不得少于{x}字，不得多于{y}字"

def build_messages(user_input, vm: VariableManager, prompt_config):
    # 获取当前vm中的所有变量
    vm.reload_for_create()
    
    """构建对话结构 - 基于YAML配置和固定占位符"""
    # 直接使用传入的 YAML 路径参数，不再从 JSON 获取
    yaml_path = f"prompts/{prompt_config}"
    
    # 加载YAML配置（IO 管理器内部处理相对路径）
    yaml_config = load_yaml_file(yaml_path)
    if not yaml_config:
        return []
    
    # 初始化固定占位符（空内容）
    placeholders = {
        'chat_history': '',
        'user': '',
        'length_limit': '',
        'current_input': '',
        'position_0': '',
        'position_1': '',
        'temporary_hint': ''
    }
    
    # 只调用一次，获取历史摘要用于多处使用
    history_summary = generate_history_summary()
    # 填充 chat_history
    placeholders['chat_history'] = history_summary
    
    # 填充 user
    placeholders['user'] = USER_NAME
    
    # 填充 length_limit（移除 try-except，保留原逻辑）
    placeholders['length_limit'] = generate_length_limit_text()
    
    # 填充 current_input
    placeholders['current_input'] = user_input
    
    # 防止未定义提示集合
    position_0_hints = []
    position_1_hints = []
    
    # 填充 position_0
    position_0_content, position_0_hints = get_all_content_by_depth(vm, "position_0", history_summary)
    placeholders['position_0'] = "\n\n".join(position_0_content) if position_0_content else ""
    
    # 填充 position_1
    position_1_content, position_1_hints = get_all_content_by_depth(vm, "position_1", history_summary)
    placeholders['position_1'] = "\n\n".join(position_1_content) if position_1_content else ""
    
    # 填充 temporary_hint
    temporary_hint_content = "\n\n".join(position_0_hints + position_1_hints)
    placeholders['temporary_hint'] = temporary_hint_content
    # # print(f"temporary_hint_content: {temporary_hint_content}")  # 调试：记录临时提示词内容
    
    # 获取消息块并处理占位符替换
    message_blocks = yaml_config.get('message_blocks', [])
    
    # 处理消息块，替换所有占位符（包括多个相同的{user}）
    result = process_message_blocks(message_blocks, placeholders)

    # print(f"Final result from build_messages: {result}")
    if not result:
        raise ValueError(f"WARNING: Empty result! message_blocks: {message_blocks}")

    return result
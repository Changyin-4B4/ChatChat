from __future__ import annotations
import json
import os
import re
from typing import TYPE_CHECKING

from .configs import USER_NAME, DEFAULT_OPENING
from .io_manager import global_io_manager

if TYPE_CHECKING:
    from core.variables_update import VariableManager

def save_variable_snapshot_section(snapshot_entries, section_flag: str, file_path: str):
    """
    zh: 将变量快照条目写入到当前层(最大layer)的助手消息的指定section中，并保存到文件。
        读取与写入均通过 IO 管理器完成：读取使用 exists + read_json，
        写入使用 write_json（自动压缩变量快照为单行）。
        要求 file_path 为相对路径（例如 'data/data.json'）。
    en: Write variable snapshot entries into the specified section of the latest
        assistant message and save to file. Reading uses IO manager's exists + read_json,
        writing uses write_json (auto-compacts variable snapshot into one line).
        Requires file_path to be a relative path (e.g., 'data/data.json').
    """
    # 参数校验：section_flag 必须为 'pre' 或 'post'
    if section_flag not in ('pre', 'post'):
        raise ValueError(f"参数 section_flag 必须为 'pre' 或 'post'，当前为 '{section_flag}'；期望：限定在预更新或后更新两个区段。")
    # 参数校验：file_path 必须为相对路径（例如 'data/data.json'）
    if os.path.isabs(file_path):
        raise ValueError(f"参数 file_path 必须为相对路径（例如 'data/data.json'），当前为绝对路径 '{file_path}'；请提供相对路径以使用 IO 管理器。")
    # 参数校验：snapshot_entries 必须为列表/元组，且元素为包含 'name' 与 'value' 的字典
    if not isinstance(snapshot_entries, (list, tuple)):
        raise TypeError(f"参数 snapshot_entries 必须为 list 或 tuple，当前类型为 {type(snapshot_entries).__name__}；期望：变量快照条目列表。")

    # 读取文件（通过 IO 管理器）
    if global_io_manager.exists(file_path):
        raw_json = global_io_manager.read_json(file_path)
        data = json.loads(raw_json)
        # print(f"读取聊天数据文件: {file_path}")  # 调试：记录读入文件路径
    else:
        data = {}
        # print(f"文件不存在，使用空数据开始: {file_path}")  # 调试：初始化空数据

    # 查找最大layer
    max_layer = 0
    for key, record in data.items():
        if isinstance(record, dict) and 'layer' in record:
            max_layer = max(max_layer, record['layer'])
    # print(f"当前最大层为: {max_layer}")  # 调试：检查层级计算

    # 定位当前层的Assistant记录并确保 variable_snapshot 结构存在
    current_record = None
    for key, record in data.items():
        if isinstance(record, dict) and record.get('layer') == max_layer and record.get('speaker') == 'Assistant':
            current_record = record
            break
    if current_record is None:
        raise ValueError("未找到当前层的 Assistant 记录；原因：数据中不存在 layer 等于最大层且 speaker 为 'Assistant' 的条目；期望：至少存在一条最新层（最大 layer）且为助手的消息。")

    if 'variable_snapshot' not in current_record:
        current_record['variable_snapshot'] = {}
    if section_flag not in current_record['variable_snapshot']:
        current_record['variable_snapshot'][section_flag] = {}

    # 写入条目
    section_obj = current_record['variable_snapshot'][section_flag]
    for idx, entry in enumerate(snapshot_entries):
        if not isinstance(entry, dict):
            raise TypeError(f"第 {idx} 个条目类型错误：必须为 dict，当前为 {type(entry).__name__}；期望：包含 'name' 和 'value' 键的字典。")
        if 'name' not in entry or 'value' not in entry:
            raise ValueError(f"第 {idx} 个条目缺少必需键：需要 'name' 与 'value'；当前键为 {list(entry.keys())}；期望：用于标识变量名与其值的键。")
        name = entry['name']
        section_obj[name] = {
            'value': entry['value'],
            'relative_is_upgrade': entry.get('relative_is_upgrade')
        }
    # print(f"写入变量快照条目数量: {len(snapshot_entries)}")  # 调试：确认写入数量

    # 保存文件（直接调用 IO 管理器写入）
    global_io_manager.write_json(file_path, data)
    # print("保存更新后的聊天数据文件")  # 调试：确认保存动作

def create_default_chat_data(vm: VariableManager):
    """
    函数说明：
    - 创建默认的聊天数据文件（data/data.json），并写入开场助手消息与变量快照。
    - 使用 IO 管理器持有的前缀目录，将调用者提供的相对路径组装为绝对路径并确保父目录存在。
    参数：
    - vm: 变量管理器实例，需提供 get_all_variables_info(pre_update_flag: bool) 方法。
    返回：
    - bool：创建成功返回 True；若文件已存在则返回 False。
    错误：
    - TypeError：vm 未提供所需方法或返回类型不正确。
    - 其他文件/解析异常将原生抛出（不包裹）。
    """
    # 参数校验
    if vm is None or not hasattr(vm, 'get_all_variables_info'):
        raise TypeError(f"参数 vm 必须提供方法 get_all_variables_info(pre_update_flag: bool)；当前类型为 {type(vm).__name__}，未发现该方法；期望：可返回所有变量信息的管理器实例。")

    data_file = "data/data.json"

    # 如果文件已存在，不需要创建
    if global_io_manager.exists(data_file):
        # print("data.json 已存在，跳过默认数据创建")  # 调试：避免重复初始化
        return False

    # 使用 IO 管理器为目标文件创建父目录，并返回绝对路径
    abs_data_file = global_io_manager.ensure_dir_for_file(data_file)
    # print(f"数据文件绝对路径: {abs_data_file}")  # 调试：确认创建目标的绝对路径

    # 获取初始变量状态快照
    initial_variable_snapshot = vm.get_all_variables_info(True)
    if not isinstance(initial_variable_snapshot, dict):
        raise TypeError(f"vm.get_all_variables_info(True) 必须返回 dict，当前返回类型为 {type(initial_variable_snapshot).__name__}；期望：以变量名为键的字典。")
    # print(f"变量快照条目数：{len(initial_variable_snapshot)}")  # 调试：快照规模

    # 按照 pre_update 属性分组（保存变量值和 relative_is_upgrade 属性）
    variable_snapshot = {
        "pre": {
            name: {'value': info['value'], 'relative_is_upgrade': info.get('relative_is_upgrade')}
            for name, info in initial_variable_snapshot.items() if info['pre_update']
        },
        "post": {
            name: {'value': info['value'], 'relative_is_upgrade': info.get('relative_is_upgrade')}
            for name, info in initial_variable_snapshot.items() if not info['pre_update']
        }
    }
    # print("已根据 pre_update 分组构建 variable_snapshot")  # 调试：快照分组完成

    # 解析开场内容并替换 {user} 为 USER_NAME（先用 IO 管理器从路径读取内容）
    opening_text = ""
    try:
        file_path = DEFAULT_OPENING
        opening_text = global_io_manager.read_txt(file_path) if global_io_manager.exists(file_path) else ""
    except Exception:
        opening_text = ""

    scene_match = re.search(r'<scene>(.*?)</scene>', opening_text, re.DOTALL)
    main_body_match = re.search(r'<main_body>(.*?)</main_body>', opening_text, re.DOTALL)
    summary_match = re.search(r'<summary>(.*?)</summary>', opening_text, re.DOTALL)

    processed_opening_scene = (scene_match.group(1).strip() if scene_match else "").replace('{user}', USER_NAME)
    processed_opening_content = (main_body_match.group(1).strip() if main_body_match else "").replace('{user}', USER_NAME)
    processed_opening_summary = (summary_match.group(1).strip() if summary_match else "").replace('{user}', USER_NAME)

    processed_opening_scene = (scene_match.group(1).strip() if scene_match else "").replace('{user}', USER_NAME)
    processed_opening_content = (main_body_match.group(1).strip() if main_body_match else "").replace('{user}', USER_NAME)
    processed_opening_summary = (summary_match.group(1).strip() if summary_match else "").replace('{user}', USER_NAME)
    # print("已解析 DEFAULT_OPENING 并替换 {user}")  # 调试：开场内容处理

    # 组装默认数据
    default_data = {
        "1": {
            "speaker": "Assistant",
            "reasoning": "",
            "scene": processed_opening_scene,
            "content": processed_opening_content,
            "summary": processed_opening_summary,
            "layer": 1,
            "variable_snapshot": variable_snapshot
        }
    }

    # 保存到文件（统一使用 IO 管理器，自动压缩变量快照）
    global_io_manager.write_json(data_file, default_data)
    # print("写入默认开场对话到 data.json")  # 调试：保存文件结果
    # print("已创建data.json模板文件，包含默认开场对话")  # 调试：初始化完成提示
    # print("如需修改开场内容，请编辑data.json文件后重新运行程序")  # 调试：用户引导信息

    return True

def create_empty_assistant_message():
    """创建空的助手消息"""
    data_file = "data/data.json"
    # print("开始创建空的助手消息")  # 调试：方法入口
    
    if global_io_manager.exists(data_file):
        raw_json = global_io_manager.read_json(data_file)
        data = json.loads(raw_json)
        # print(f"读取数据文件成功: {data_file}")  # 调试：读取状态
    else:
        data = {}
        # print(f"数据文件不存在，初始化空数据: {data_file}")  # 调试：文件缺失状态
    
    # 获取最大ID
    if not data:
        raise ValueError("数据文件为空，无法添加助手消息；原因：无任何聊天记录可参考；期望：至少存在一条开场消息用于确定 layer。")
    
    max_id = max(int(k) for k in data.keys())
    last_record = data[str(max_id)]
    # print(f"当前最大记录 ID: {max_id}, 上一条 speaker: {last_record['speaker']}")  # 调试：上下文状态
    
    # 检查上一条消息是否为助手消息
    if last_record["speaker"] == "Assistant":
        raise ValueError("上一条消息已经是助手消息，不能连续添加助手消息；原因：同层连续助手会破坏对话结构；期望：先添加用户消息，再追加助手消息。")
    
    # 计算新的记录ID
    record_id = str(max_id + 1)
    # 助手消息的layer与上一条相同（不加1）
    layer = last_record["layer"]
    # print(f"新助手记录 ID: {record_id}, layer: {layer}")  
    
    # 创建空的Assistant记录
    assistant_record = {
        "speaker": "Assistant",
        "reasoning": "",
        "scene": "",
        "content": "",
        "summary": "",
        "layer": layer,
        "variable_snapshot": {}
    }
    
    # 保存Assistant记录
    data[record_id] = assistant_record
    
    global_io_manager.write_json(data_file, data)
    # print("空助手消息已写入文件")  # 调试：保存状态
    return record_id

def process_user_input(user_input):
    """
    处理用户输入并写入聊天记录
    - 统一括号格式
    - 将用户消息保存到 `data/data.json`
    - 创建空的助手消息占位（同层）
    Raises:
        ValueError: 当数据文件为空或上一条消息为用户消息时
    """

    if not isinstance(user_input, str):
        raise TypeError(f"参数 user_input 必须为 str 类型，当前类型为 {type(user_input).__name__}；期望：字符串形式的用户输入。")
    # print("开始处理用户输入")  # 调试：方法入口
    # 格式化操作：统一括号格式
    processed_input = user_input.replace('（', '(').replace('）', ')').replace('【', '[').replace('】', ']')
    # print(f"格式化前的输入: {user_input}")  # 调试：查看原始输入
    # print(f"格式化后的输入: {processed_input}")  # 调试：统一括号后的输入

    # 读取并校验数据文件
    data_file = "data/data.json"
    if global_io_manager.exists(data_file):
        raw_json = global_io_manager.read_json(data_file)
        data = json.loads(raw_json)
        # print(f"读取数据文件成功: {data_file}")  # 调试：读取状态
    else:
        data = {}
        # print(f"数据文件不存在，初始化空数据: {data_file}")  # 调试：文件缺失状态

    if not data:
        raise ValueError("数据文件为空，无法添加用户消息；原因：无对话上下文；期望：先创建默认开场数据。")

    max_id = max(int(k) for k in data.keys())
    last_record = data[str(max_id)]
    # print(f"当前最大记录 ID: {max_id}, 上一条 speaker: {last_record.get('speaker')}")  # 调试：上下文状态

    # 不允许连续用户消息
    if last_record.get("speaker") == "User":
        raise ValueError("上一条消息已经是用户消息，不能连续添加用户消息；原因：对话层级应交替；期望：由助手回复后再添加用户消息。")

    # 计算新的记录ID和层级（用户消息层级为上一条 + 1）
    record_id = str(max_id + 1)
    layer = last_record.get("layer", 0) + 1
    # print(f"新用户记录 ID: {record_id}, layer: {layer}")  # 调试：新记录信息

    # 组装并保存用户消息
    user_record = {
        "speaker": "User",
        "content": processed_input,
        "layer": layer
    }
    data[record_id] = user_record

    # 写回文件（统一使用 IO 管理器，自动压缩变量快照）
    global_io_manager.write_json(data_file, data)
    # print("用户消息已写入文件")  # 调试：保存状态

    # 追加空的助手消息占位（与上一条同层）
    create_empty_assistant_message()
    # print("已追加空的助手消息占位")  # 调试：后续流程状态
    return

def process_llm_output(llm_response, user_input = None):
    """
    处理 LLM 的输出（接收字典）
    - 从 llm_response 中提取 reasoning 与 content
    - 使用正则从 content 提取 <main_body>、<scene>、<summary>
    - 更新最后一条助手消息的 reasoning、scene、content、summary 字段
    Args:
        llm_response: 字典，形如 {'reasoning': str, 'content': str}
        user_input: 保留参数，当前未使用
    """

    if not isinstance(llm_response, (dict, str)):
        raise TypeError(f"参数 llm_response 必须为 dict 或 str，当前类型为 {type(llm_response).__name__}；期望：包含 'reasoning' 与 'content' 的响应对象或可转为字符串的内容。")
    # print("开始处理 LLM 输出")  # 调试：方法入口

    # 提取字典中的 reasoning 与 content
    reasoning = llm_response.get('reasoning', '') if isinstance(llm_response, dict) else ''
    content_text = llm_response.get('content', '') if isinstance(llm_response, dict) else str(llm_response)
    # print(f"解析到 reasoning 长度: {len(reasoning)}")  # 调试：推理文本规模
    # print(f"解析到 content 长度: {len(content_text)}")  # 调试：正文文本规模

    # 提取标签内容
    main_body_match = re.search(r'<main_body>(.*?)</main_body>', content_text, re.DOTALL)
    main_body = main_body_match.group(1).strip() if main_body_match else ""
    scene_match = re.search(r'<scene>(.*?)</scene>', content_text, re.DOTALL)
    scene = scene_match.group(1).strip() if scene_match else ""
    summary_match = re.search(r'<summary>(.*?)</summary>', content_text, re.DOTALL)
    summary = summary_match.group(1).strip() if summary_match else ""
    # print("提取 main_body/scene/summary 字段完成")  # 调试：标签提取状态

    # 直接写回到 data.json（整合原 update_last_assistant_record 逻辑）
    data_file = "data/data.json"
    if not global_io_manager.exists(data_file):
        raise FileNotFoundError("数据文件不存在，无法更新助手记录；原因：找不到聊天数据文件；期望：先创建默认开场数据或正确设置数据路径。")
    raw_json = global_io_manager.read_json(data_file)
    data = json.loads(raw_json)
    if not data:
        raise ValueError("数据为空，无法更新助手记录；原因：没有任何历史消息可更新；期望：至少包含一条助手消息。")

    # 获取最后一条记录并校验
    max_id = max(int(k) for k in data.keys())
    last_record = data[str(max_id)]
    # print(f"最后一条记录 ID: {max_id}, speaker: {last_record.get('speaker')}")  # 调试：最后记录类型
    if last_record.get("speaker") != "Assistant":
        raise ValueError(f"最后一条记录不是助手消息，而是 {last_record.get('speaker')} 消息；期望：在助手消息占位上进行更新。")

    # 更新助手记录的字段
    last_record["reasoning"] = reasoning
    last_record["scene"] = scene
    last_record["content"] = main_body
    last_record["summary"] = summary
    global_io_manager.write_json(data_file, data)
    # print("已更新最后一条助手消息的字段并写回文件")  # 调试：保存完成
    return

def delete_messages_from_file(count: int) -> int:
    """
    删除指定数量的消息记录（不传路径，固定使用 data/data.json）
    
    - 保留首条开场消息（ID最小的记录）
    - 从最新的消息开始删除（ID最大）
    - 写回时使用紧凑保存以保持变量快照单行
    
    Args:
        count: 要删除的消息数量；<=0 时不删除
    
    Returns:
        int: 实际删除的消息条数（可能为0）
    
    Raises:
        FileNotFoundError: 当 data/data.json 不存在
        json.JSONDecodeError: 当数据文件格式错误
    """
    if count <= 0:
        # print(f"请求删除消息数量为非正数: {count}，不执行删除")  # 调试：参数校验提示
        return 0

    data_file_path = "data/data.json"
    if not global_io_manager.exists(data_file_path):
        raise FileNotFoundError(f"数据文件不存在: {data_file_path}；原因：无法找到聊天数据源；期望：确保已创建或正确配置数据文件。")
    raw_json = global_io_manager.read_json(data_file_path)
    data = json.loads(raw_json)

    if not data:
        # print("数据为空，不执行删除")  # 调试：数据状态提示
        return 0

    # 获取所有记录ID并按数字排序
    record_ids = sorted([int(k) for k in data.keys()])
    # print(f"当前消息总数（含开场）: {len(record_ids)}")  # 调试：消息规模
    if len(record_ids) <= 1:
        # print("只有开场消息，无法删除")  # 调试：删除限制说明
        return 0

    # 计算实际可删除的数量（保留第一条开场消息）
    available_count = len(record_ids) - 1
    actual_delete_count = min(count, available_count)
    # print(f"请求删除: {count}，实际可删: {available_count}，最终删除: {actual_delete_count}")  # 调试：删除数量计算

    # 从最新的消息开始删除（从下往上删除）
    for _ in range(actual_delete_count):
        max_id = max(record_ids)
        del data[str(max_id)]
        record_ids.remove(max_id)
    global_io_manager.write_json(data_file_path, data)
    # print("删除后已保存到文件")  # 调试：保存状态
    return actual_delete_count
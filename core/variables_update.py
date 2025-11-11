from __future__ import annotations
import json
from typing import Dict, Any, Optional, Union, List, Tuple, TYPE_CHECKING
from enum import Enum
import random

# 导入TaskManager类型，使用TYPE_CHECKING避免循环导入
if TYPE_CHECKING:
    from .llm_judge import TaskManager

# 导入TaskInstance和TaskType（运行时导入）
from .llm_judge import TaskInstance, TaskType
from .message_process import save_variable_snapshot_section
from .io_manager import global_io_manager

# 修改约束条件类型定义，支持更灵活的格式
# 约束条件类型：支持以下格式
# (下界, Variable实例, 上界) - 完整约束：下界 < Variable.get_stage()['stage_value'] < 上界
# (下界, Variable实例) - 只有下界：下界 < Variable.get_stage()['stage_value']
# (Variable实例, 上界) - 只有上界：Variable.get_stage()['stage_value'] < 上界
ConstraintCondition = Union[
    Tuple[Union[int], 'Variable', Union[int]],  # 完整约束
    Tuple[Union[int], 'Variable'],  # 只有下界
    Tuple['Variable', Union[int]]   # 只有上界
]
# 或关系组：多个约束条件的或关系
OrGroup = List[ConstraintCondition]
# 约束集合：包含单个约束条件和或关系组的混合
ConstraintSet = List[Union[ConstraintCondition, OrGroup]]

class VariableType(Enum):
    """变量类型枚举"""
    RECORD = "record"  # 记录变量
    STAGE_INDEPENDENT = "stage_independent"  # 阶段自变量

class UpdateType(Enum):
    """更新规则类型枚举"""
    KEYWORD_COUNT = "keyword_count"  # 关键词计数更新
    KEYWORD_APPEAR = "keyword_appear"  # 关键词出现更新
    LLM_FUZZY = "llm_fuzzy"  # LLM模糊更新

class ResetType(Enum):
    """重置规则类型枚举"""
    KEYWORD = "keyword"  # 关键词重置
    LLM = "llm"  # LLM判断重置

class RelativeMethod(Enum):
    """相关方法枚举"""
    CYCLE = "cycle"  # 循环
    LADDER = "ladder"  # 阶梯

class Variable:
    """变量基类"""
    def __init__(self, 
                name: str,
                var_type: VariableType,
                update_type: UpdateType,
                update_config: Union[Dict, str],
                pre_update: bool = False,
                initial_value: float = 0.0,
                min_value: float = float('-inf'),
                max_value: float = float('inf'),
                update_constraint: Optional[ConstraintSet] = None,
                reset_type: Optional[ResetType] = None,
                reset_config: Optional[Union[Dict, str]] = None,
                reset_value: Optional[float] = 0.0,
                relative_name: Optional[str] = None,
                relative_method: Optional[RelativeMethod] = None,
                relative_stage_config: Optional[Tuple[Union[int, float], ...]] = None,
                relative_value: Optional[Union[int, Tuple[int, ...]]] = None,
                relative_description: Optional[Union[Tuple[str, ...], Tuple[Tuple[str, ...], ...]]] = None,
                relative_current_description: Optional[Union[str, Tuple[str, ...]]] = None,
                relative_is_upgrade: Optional[Tuple[int, int]] = None
                ):
        """
        初始化变量
        
        Args:
            name: 变量名称
            var_type: 变量类型（VariableType枚举）
            update_type: 更新规则类型（UpdateType枚举）
            update_config: 更新配置（字典或字符串）
            pre_update: 是否在更新前执行，默认True
            initial_value: 初始值，默认0.0
            min_value: 最小值，默认负无穷
            max_value: 最大值，默认正无穷
            update_constraint: 更新约束条件，可选
                格式示例: [
                    (1, variable_A, 3),  # 1 < variable_A.stage_value < 3
                    [(2, variable_B, float('inf')), (float('-inf'), variable_C, 3)],  # (variable_B.stage_value > 2) OR (variable_C.stage_value < 3)
                    (2, variable_D, 4)   # 2 < variable_D.stage_value < 4
                ]
                其中：
                - 单个元组表示与关系的约束条件
                - 列表包裹的多个元组表示或关系
                - 所有顶层元素之间是与关系
            reset_type: 重置规则类型（ResetType枚举），可选
            reset_config: 重置配置（字典或字符串），可选
            relative_name: 关联名称（阶段变量用），可选
            relative_method: 关联方法（RelativeMethod枚举，阶段变量用），可选
            relative_stage_config: 关联阶段配置（数值元组，阶段变量用），可选
            relative_value: 关联阶段值（单个整数或整数元组，如5或(1,2,3,4,5)），可选
            relative_description: 关联阶段描述（字符串元组或元组的元组，如("陌生", "熟悉")或(("陌生", "熟悉"), ("初级", "高级"))），可选
            relative_current_description: 当前关联阶段描述（单个字符串或字符串元组，如"陌生"或("陌生", "初级")），可选
            relative_is_upgrade: 阶段变化记录（元组，如(1,2)表示由阶段1到阶段2），可选
        """
        self.name = name
        self.var_type = var_type
        self.value = round(initial_value, 1)  # 保持1位小数
        self.update_type = update_type
        self.update_config = update_config
        self.pre_update = pre_update
        self.min_value = min_value
        self.max_value = max_value
        self.reset_type = reset_type
        self.reset_config = reset_config
        self.reset_value = reset_value

        # 更新约束条件
        self.update_constraint = update_constraint or []
        
        # 阶段变量特有属性
        if var_type == VariableType.STAGE_INDEPENDENT:
            if relative_name is None:
                raise ValueError("阶段自变量必须指定relative_name")
            if relative_method is None:
                raise ValueError("阶段自变量必须指定relative_method")
            if relative_stage_config is None:
                raise ValueError("阶段自变量必须指定relative_stage_config")
            
            self.relative_name = relative_name
            self.relative_method = relative_method
            self.relative_stage_config = relative_stage_config
            # 新增的因变量属性
            self.relative_value = relative_value  # 整数类型的阶段值（1,2,3,4,5）
            self.relative_description = relative_description  # 中文描述（陌生，熟悉等）
            self.relative_current_description = relative_current_description  # 当前阶段描述（如"陌生"）
            self.relative_is_upgrade = relative_is_upgrade  # 阶段变化记录（1,2），由1到2
        else:
            self.relative_name = None
            self.relative_method = None
            self.relative_stage_config = None
            self.relative_value = None
            self.relative_description = None
            self.relative_current_description = None
            self.relative_is_upgrade = None

    def check_update_constraints(self) -> bool:
        """
        检查更新约束条件是否满足
        
        Returns:
            bool: 所有约束条件都满足时返回True，否则返回False

        Raises:
            ValueError: 当约束项格式不正确（期望长度为2或3的元组）。
            TypeError: 当约束中的变量对象不具备 get_stage 方法。
        """
        # print(f"开始检查更新约束，变量: {self.name}, 约束数量: {len(self.update_constraint)}") # 调试：记录约束检查开始
        if not self.update_constraint:
            return True  # 没有约束条件时默认满足
        
        for constraint_item in self.update_constraint:
            if isinstance(constraint_item, tuple):
                # 单个约束条件（与关系）
                if len(constraint_item) == 3:
                    # 完整约束：(下界, Variable实例, 上界)
                    lower_bound, variable, upper_bound = constraint_item
                    if not hasattr(variable, 'get_stage'):
                        raise TypeError(f"更新约束中的变量缺少 get_stage 方法，收到类型为 {type(variable).__name__}。期望：具有 get_stage 方法的 Variable 实例。")
                    stage_info = variable.get_stage()
                    stage_value = stage_info.get('stage_value')
                    if stage_value is None or not (lower_bound < stage_value < upper_bound):
                        return False
                        
                elif len(constraint_item) == 2:
                    # 判断是只有下界还是只有上界
                    first, second = constraint_item
                    if hasattr(first, 'get_stage'):
                        # (Variable实例, 上界) - 只有上界
                        variable, upper_bound = first, second
                        if not hasattr(variable, 'get_stage'):
                            raise TypeError(f"更新约束中的变量缺少 get_stage 方法，收到类型为 {type(variable).__name__}。期望：具有 get_stage 方法的 Variable 实例。")
                        stage_info = variable.get_stage()
                        stage_value = stage_info.get('stage_value')
                        if stage_value is None or not (stage_value < upper_bound):
                            return False
                    else:
                        # (下界, Variable实例) - 只有下界
                        lower_bound, variable = first, second
                        if not hasattr(variable, 'get_stage'):
                            raise TypeError(f"更新约束中的变量缺少 get_stage 方法，收到类型为 {type(variable).__name__}。期望：具有 get_stage 方法的 Variable 实例。")
                        stage_info = variable.get_stage()
                        stage_value = stage_info.get('stage_value')
                        if stage_value is None or not (lower_bound < stage_value):
                            return False
                else:
                    raise ValueError(f"更新约束格式错误：{constraint_item}。原因：元组长度为 {len(constraint_item)} 不符合要求。期望：长度为 2 或 3 的元组，形如 (下界, 变量, 上界) 或 (变量, 上界)/(下界, 变量)。")
                    
            elif isinstance(constraint_item, list):
                # 或关系组
                group_satisfied = False
                for constraint in constraint_item:
                    if not isinstance(constraint, tuple):
                        raise ValueError(f"或关系约束组内元素格式错误：{constraint}。原因：元素类型为 {type(constraint).__name__}。期望：长度为 2 或 3 的元组。")
                    if len(constraint) == 3:
                        lower_bound, variable, upper_bound = constraint
                        if not hasattr(variable, 'get_stage'):
                            raise TypeError(f"或关系约束中的变量缺少 get_stage 方法，收到类型为 {type(variable).__name__}。期望：具有 get_stage 方法的 Variable 实例。")
                        stage_info = variable.get_stage()
                        stage_value = stage_info.get('stage_value')
                        if stage_value is not None and lower_bound < stage_value < upper_bound:
                            group_satisfied = True
                            break
                    elif len(constraint) == 2:
                        first, second = constraint
                        if hasattr(first, 'get_stage'):
                            variable, upper_bound = first, second
                            if not hasattr(variable, 'get_stage'):
                                raise TypeError(f"或关系约束中的变量缺少 get_stage 方法，收到类型为 {type(variable).__name__}。期望：具有 get_stage 方法的 Variable 实例。")
                            stage_info = variable.get_stage()
                            stage_value = stage_info.get('stage_value')
                            if stage_value is not None and stage_value < upper_bound:
                                group_satisfied = True
                                break
                        else:
                            lower_bound, variable = first, second
                            if not hasattr(variable, 'get_stage'):
                                raise TypeError(f"或关系约束中的变量缺少 get_stage 方法，收到类型为 {type(variable).__name__}。期望：具有 get_stage 方法的 Variable 实例。")
                            stage_info = variable.get_stage()
                            stage_value = stage_info.get('stage_value')
                            if stage_value is not None and lower_bound < stage_value:
                                group_satisfied = True
                                break
                    else:
                        raise ValueError(f"或关系约束组内元组长度错误：{constraint}。原因：长度为 {len(constraint)}。期望：长度为 2 或 3。")
                if not group_satisfied:
                    return False
            
            else:
                # print(f"跳过未知类型的约束项: {type(constraint_item).__name__}") # 调试：忽略不支持的约束类型
                continue
        
        # print(f"更新约束检查通过，变量: {self.name}") # 调试：约束全部满足
        return True

    def update(self, text: str, task_manager: Optional[TaskManager] = None) -> Optional[Tuple['Variable', Union[float, str]]]:
        """更新变量值 - 只返回更新结果，不直接应用更新
        
        Returns:
            Optional[Tuple[Variable, Union[float, str]]]: 返回(变量实例, delta值)的元组，如果无需更新则返回None
        """
        # print(f"开始更新变量: {self.name}, 更新类型: {self.update_type.value}") # 调试：记录更新入口

        def keyword_update(text: str) -> float:
            """统一的关键词更新函数，支持计数和出现两种模式"""
            # print(f"关键词更新开始，变量: {self.name}") # 调试：标记关键词处理开启
            # 直接在函数内加载关键词配置
            if isinstance(self.update_config, dict):
                keyword_mapping = self.update_config
            elif isinstance(self.update_config, str) and self.update_config.endswith('.json'):
                # 不做路径修正，按调用方给出的字符串使用
                config_file = self.update_config
                if not global_io_manager.exists(config_file):
                    raise FileNotFoundError(f"关键词配置文件不存在：'{config_file}'。原因：路径无效或文件缺失。期望：提供存在的 .json 文件且包含键 '{self.name}_keywords'。")
                raw_json = global_io_manager.read_json(config_file)
                config = json.loads(raw_json)
                # 基于变量名动态匹配 {name}_keywords
                keywords_key = f"{self.name}_keywords"
                keyword_mapping = config.get(keywords_key, {})
            else:
                keyword_mapping = {}

            total_score = 0.0
            text_lower = text.lower()
            
            for _, config in keyword_mapping.items():
                if "keywords" in config:
                    if self.update_type == UpdateType.KEYWORD_COUNT:
                        # 计数模式：统计关键词出现次数
                        group_count = 0
                        for keyword in config["keywords"]:
                            group_count += text_lower.count(keyword.lower())
                        
                        if group_count > 0:
                            score = calculate_random_value(config["min_value"], config["max_value"])
                            total_score += group_count * score
                            
                    elif self.update_type == UpdateType.KEYWORD_APPEAR:
                        # 出现模式：同组只计分一次
                        group_matched = False
                        for keyword in config["keywords"]:
                            if keyword.lower() in text_lower:
                                group_matched = True
                                break
                        
                        if group_matched:
                            score = calculate_random_value(config["min_value"], config["max_value"])
                            total_score += score
            # print(f"关键词更新完成，总得分: {total_score}") # 调试：记录关键词更新结果
            return total_score
        
        def llm_fuzzy_update(text: str):
            """LLM模糊更新（添加任务到任务管理器）"""
            # 添加LLM更新任务到任务管理器
            if task_manager is not None:
                # 从update_config中读取txt文件路径
                txt_path = self.update_config
                
                # 检查文件是否存在
                if global_io_manager.exists(txt_path):
                    # 创建更新任务
                    task = TaskInstance(
                        variable_instance=self,
                        txt_path=txt_path,
                        task_type=TaskType.UPDATE
                    )
                    task_manager.add_task(task)
                    # print(f"任务添加成功 - 变量名: {self.name}, txt路径: {txt_path}, 任务类型: UPDATE") # 调试：记录任务创建
                else:
                    raise FileNotFoundError(f"LLM 模糊更新失败：文件 '{txt_path}' 不存在。原因：路径无效或文件缺失。期望：提供存在的 .txt 文件用于任务内容。")
        
        # 检查约束条件（如果有的话）
        should_update = True
        if self.update_constraint is not None:
            should_update = self.check_update_constraints()
            if not should_update:
                # print(f"变量 '{self.name}' 的更新被约束条件阻止") # 调试：约束不满足，取消本次更新
                pass
        
        # 根据约束检查结果决定是否计算变化值
        if should_update:
            # 根据更新类型计算变化值
            if self.update_type in [UpdateType.KEYWORD_COUNT, UpdateType.KEYWORD_APPEAR]:
                change = keyword_update(text)
                if change != 0.0:  # 只有当有实际变化时才返回结果
                    # print(f"变量 '{self.name}' 更新 delta 值: {change}") # 调试：记录变更值
                    return (self, change)
            elif self.update_type == UpdateType.LLM_FUZZY:
                llm_fuzzy_update(text)
                # LLM_FUZZY类型由TaskManager处理，这里不返回结果
                return None
            else:
                return None
        
        # 无需更新
        return None

    # 函数：计算当前值的阶段信息（保持核心逻辑不变）
    def get_stage(self, value: Optional[float] = None) -> Dict[str, Any]:
        """获取当前值对应的阶段信息"""
        if self.var_type != VariableType.STAGE_INDEPENDENT:
            return {"relative_value": None, "relative_current_description": None}
        
        # 验证必要参数
        if not self.relative_method:
            raise ValueError(f"阶段自变量 '{self.name}' 必须指定 relative_method")
        if not self.relative_stage_config:
            raise ValueError(f"阶段自变量 '{self.name}' 必须指定 relative_stage_config")
        if not self.relative_description:
            raise ValueError(f"阶段自变量 '{self.name}' 必须指定 relative_description")
        
        current_value = value if value is not None else self.value
        # print(f"开始计算阶段信息：变量 '{self.name}', 当前值: {current_value}") # 调试：记录阶段计算入口
        
        if self.relative_method == RelativeMethod.CYCLE:
            # CYCLE模式处理
            N = len(self.relative_stage_config)
            # print(f"CYCLE 阶段计算：N={N}, 原始值 r={current_value}") # 调试：记录CYCLE计算参数
            if N < 2:
                raise ValueError(f"CYCLE模式下 relative_stage_config 必须至少有2个元素，当前只有{N}个")
            
            # 计算x和y数组
            r = current_value  # raw_value
            x = [0] * N
            y = [0] * (N - 1)
            
            # x0 = r / n0，取整
            x[0] = int(r // self.relative_stage_config[0])
            
            # 计算后续的x和y
            for i in range(1, N):
                x[i] = int(x[i-1] // self.relative_stage_config[i])
                y[i-1] = int(x[i-1] % self.relative_stage_config[i])
            
            # relative_value: 颠倒排序 (y(N-2), y(N-3), ..., y1, y0)
            if N == 2:
                relative_value = y[0]  # 单一int值
            else:
                relative_value = tuple(reversed(y))  # 颠倒排序的元组
            
            # 计算relative_current_description
            if N == 2:
                # 单一str值
                desc_tuple = self.relative_description[0] if isinstance(self.relative_description[0], tuple) else self.relative_description
                relative_current_description = desc_tuple[y[0]] if y[0] < len(desc_tuple) else f"阶段{y[0]}"
            else:
                # str的元组，先根据原始y值获取描述，再颠倒排序
                descriptions = []
                for i, y_val in enumerate(y):  # 使用原始y值获取描述
                    if i < len(self.relative_description):
                        desc_tuple = self.relative_description[i]
                        if y_val < len(desc_tuple):
                            descriptions.append(desc_tuple[y_val])
                        else:
                            descriptions.append(f"阶段{y_val}")
                    else:
                        descriptions.append(f"阶段{y_val}")
                relative_current_description = tuple(reversed(descriptions))  # 然后将描述列表反序
            
            # print(f"CYCLE 计算完成：relative_value={relative_value}, 描述={relative_current_description}") # 调试：记录CYCLE计算结果
            return {
                "relative_value": relative_value,
                "relative_current_description": relative_current_description
            }
            
        elif self.relative_method == RelativeMethod.LADDER:
            # LADDER模式处理
            # print(f"LADDER 阶段计算：阈值列表={self.relative_stage_config}") # 调试：记录LADDER计算参数
            if len(self.relative_stage_config) < 1:
                raise ValueError(f"LADDER模式下 relative_stage_config 必须至少有1个元素")
            
            # 确定区间
            relative_value = 0
            for i, threshold in enumerate(self.relative_stage_config):
                if current_value <= threshold:
                    relative_value = i
                    break
            else:
                # 大于所有阈值
                relative_value = len(self.relative_stage_config)
            
            # 获取描述
            desc_tuple = self.relative_description
            if isinstance(desc_tuple, tuple) and relative_value < len(desc_tuple):
                relative_current_description = desc_tuple[relative_value]
            else:
                relative_current_description = f"阶段{relative_value}"
            
            # print(f"LADDER 计算完成：relative_value={relative_value}, 描述={relative_current_description}") # 调试：记录LADDER计算结果
            return {
                "relative_value": relative_value,
                "relative_current_description": relative_current_description
            }
        else:
            raise ValueError(f"不支持的 relative_method: {self.relative_method}。原因：方法未在支持列表中。期望：RelativeMethod.CYCLE 或 RelativeMethod.LADDER。")

    # 函数：汇总变量的完整信息（保持核心逻辑不变）
    def get_info(self) -> Dict[str, Any]:
        """获取变量完整信息"""
        # print(f"收集变量信息：{self.name}") # 调试：记录信息收集入口
        info = {
            'name': self.name,
            'value': self.value,
            'var_type': self.var_type.value,
            'update_type': self.update_type.value,
            'update_config': self.update_config,
            'pre_update': self.pre_update,
            'min_value': self.min_value,
            'max_value': self.max_value,
            'update_constraint': self.update_constraint,
            'reset_type': self.reset_type.value if self.reset_type else None,
            'reset_config': self.reset_config
        }
        
        if self.var_type == VariableType.STAGE_INDEPENDENT:
            stage_info = self.get_stage()
            # print(f"阶段信息获取完成：relative_value={stage_info['relative_value']}, 描述={stage_info['relative_current_description']}") # 调试：确认阶段信息
            info.update({
                'relative_name': self.relative_name,
                'relative_method': self.relative_method.value if self.relative_method else None,
                'relative_stage_config': self.relative_stage_config,
                'relative_value': stage_info["relative_value"],
                'relative_description': self.relative_description,
                'relative_current_description': stage_info["relative_current_description"],
                'relative_is_upgrade': self.relative_is_upgrade
            })
        
        return info

    # 函数：根据关键词或 LLM 触发重置（保持核心逻辑不变）
    def reset(self, text: str, task_manager: Optional[TaskManager] = None) -> Optional[Tuple['Variable', str]]:
        """重置变量值 - 只返回重置结果，不直接应用重置
        
        Returns:
            Optional[Tuple[Variable, str]]: 返回(变量实例, "reset")的元组，如果无需重置则返回None
        """
        # print(f"开始重置变量：{self.name}, reset_type={self.reset_type}, reset_config类型={type(self.reset_config).__name__}") # 调试：记录重置入口
        # 基础检查
        if self.reset_type is None or self.reset_config is None:
            return None
        
        should_reset = False
        
        # 加载重置配置并检查条件
        if self.reset_type == ResetType.KEYWORD:
            # 加载配置
            reset_config = {}
            if isinstance(self.reset_config, dict):
                reset_config = self.reset_config
            elif isinstance(self.reset_config, str) and self.reset_config.endswith('.json'):
                # 不做路径修正，按调用方给出的字符串使用
                config_path = self.reset_config
                # print(f"尝试加载重置配置 JSON 文件：{config_path}") # 调试：记录重置配置路径
                if global_io_manager.exists(config_path):
                    raw_json = global_io_manager.read_json(config_path)
                    config = json.loads(raw_json)
                    reset_key = f"{self.name}_reset"
                    reset_config = config.get(reset_key, {})
                else:
                    reset_config = {}
            # 检查关键词
            if "keywords" in reset_config:
                text_lower = text.lower()
                should_reset = any(keyword.lower() in text_lower for keyword in reset_config["keywords"])
        elif self.reset_type == ResetType.LLM:
            # 添加LLM重置任务到任务管理器
            if task_manager is not None:
                # 从reset_config中读取txt文件路径
                txt_path = self.reset_config
                # 检查文件是否存在（使用 IO 管理器）
                # print(f"尝试创建 LLM 重置任务，文件路径: {txt_path}") # 调试：记录任务创建入口
                if global_io_manager.exists(txt_path):
                    # 创建重置任务
                    task = TaskInstance(
                        variable_instance=self,
                        txt_path=txt_path,
                        task_type=TaskType.RESET
                    )
                    task_manager.add_task(task)
                    # print(f"任务添加成功 - 变量名: {self.name}, txt路径: {txt_path}, 任务类型: RESET") # 调试：记录任务创建
            # LLM重置由TaskManager处理，这里不返回结果
            return None
        
        # 执行重置判断
        if should_reset:
            return (self, "reset")
        else:
            return None
    
class VariableManager:
    """变量管理器"""
    
    def __init__(self, save_file: str = "data/data.json"):
        self.save_file = save_file
        self.variables: Dict[str, Variable] = {}
        # 不在初始化时调用load_variables，避免循环导入
    
    def add_variable(self, variable: Variable):
        """添加变量"""
        self.variables[variable.name] = variable
    
    def recalculate_all_variables(self, text: str, pre_update: bool = True, task_manager: Optional[TaskManager] = None) -> List[Tuple['Variable', Union[float, str]]]:
        """重新计算所有变量（包含重置和更新判断）- 只返回更新结果，不直接应用更新"""
        # 函数级注释：遍历变量，依次执行重置与更新判断，收集 delta 结果，不直接写入或变更值
        update_results = []
        
        for name, variable in self.variables.items():
            # 检查变量的pre_update属性是否与传入参数相等
            if variable.pre_update != pre_update:
                continue  # 跳过不匹配的变量

            # 1. 先执行重置判断
            reset_result = variable.reset(text, task_manager)
            if reset_result is not None:
                update_results.append(reset_result)
                # print(f"变量 '{name}' 重置条件满足，记录为reset") # 调试：记录重置触发
                continue  # 如果需要重置，跳过更新判断
            
            # 2. 再执行更新判断
            update_result = variable.update(text, task_manager)
            if update_result is not None:
                update_results.append(update_result)
                # print(f"变量 '{name}' 更新记录：delta = {update_result[1]}") # 调试：记录更新的 delta 值

        return update_results
    
    def get_all_variables_info(self, is_first: bool = False) -> Dict[str, Any]:
        """获取所有变量信息"""
        # 函数级注释：按需从快照恢复当前状态，然后汇总并返回各变量的完整信息
        # 从快照重新加载变量状态
        if not is_first:
            self.reload_from_snapshot()
        
        Dict={name: var.get_info() for name, var in self.variables.items()}
        # print(f"Debug: 变量表: {Dict}") # 调试：输出当前所有变量信息
        return Dict
    
    def reload_from_snapshot(self):
        """从快照重新加载变量状态"""
        # 函数级注释：读取保存文件，合并最近的 post/pre 快照并恢复到内存；校验变量集合一致性
        if not global_io_manager.exists(self.save_file):
            raise FileNotFoundError(f"数据文件不存在：'{self.save_file}'。原因：路径无效或文件缺失。期望：提供存在的 JSON 数据文件。")
        # print(f"开始从快照文件读取: {self.save_file}") # 调试：记录读取数据文件
        raw_json = global_io_manager.read_json(self.save_file)
        data = json.loads(raw_json)

        if not data:
            return  # 没有数据，跳过重载
        
        # 获取所有消息，按层级排序
        messages = []
        for key, value in data.items():
            if key.isdigit() and isinstance(value, dict) and value.get("speaker") == "Assistant":
                messages.append(value)
        
        if not messages:
            return  # 没有助手消息，跳过重载
        
        # 按layer排序，获取最后两层的助手消息
        messages.sort(key=lambda x: x.get("layer", 0))
        
        # 获取post和pre快照
        post_snapshot = None
        pre_snapshot = None
        
        # 从最后一层开始查找post快照
        for message in reversed(messages):
            if message.get("variable_snapshot", {}).get("post"):
                post_snapshot = message["variable_snapshot"]["post"]
                break
        
        # 如果最后一层没有post快照，从倒数第二层取
        if post_snapshot is None and len(messages) >= 2:
            second_last = messages[-2]
            if second_last.get("variable_snapshot", {}).get("post"):
                post_snapshot = second_last["variable_snapshot"]["post"]
        
        # 从最后一层开始查找pre快照
        for message in reversed(messages):
            if message.get("variable_snapshot", {}).get("pre"):
                pre_snapshot = message["variable_snapshot"]["pre"]
                break
        
        # 如果最后一层没有pre快照，从倒数第二层取
        if pre_snapshot is None and len(messages) >= 2:
            second_last = messages[-2]
            if second_last.get("variable_snapshot", {}).get("pre"):
                pre_snapshot = second_last["variable_snapshot"]["pre"]
        
        # 组合post和pre快照
        combined_snapshot = {}
        if post_snapshot:
            combined_snapshot.update(post_snapshot)
        if pre_snapshot:
            combined_snapshot.update(pre_snapshot)
        
        if not combined_snapshot:
            return  # 没有可用的快照
        
        # 检查变量名称和数量是否匹配
        vm_var_names = set(self.variables.keys())
        snapshot_var_names = set(combined_snapshot.keys())
        
        if vm_var_names != snapshot_var_names:
            missing_in_vm = snapshot_var_names - vm_var_names
            missing_in_snapshot = vm_var_names - snapshot_var_names
            
            error_msg = "变量名称或数量不匹配！"
            if missing_in_vm:
                error_msg += f" VM中缺少变量: {missing_in_vm}"
            if missing_in_snapshot:
                error_msg += f" 快照中缺少变量: {missing_in_snapshot}"
            
            raise ValueError(error_msg)
        
        # 从快照加载数据覆盖VM内存中的数据
        for var_name, var_obj in self.variables.items():
            snapshot_var = combined_snapshot[var_name]
            
            # 覆盖value
            if "value" in snapshot_var:
                var_obj.value = snapshot_var["value"]
            
            # 覆盖relative_is_upgrade（仅对阶段变量）
            if (var_obj.var_type == VariableType.STAGE_INDEPENDENT and 
                "relative_is_upgrade" in snapshot_var):
                # 正确处理null值，将其转换为None
                upgrade_value = snapshot_var["relative_is_upgrade"]
                if upgrade_value is None:
                    var_obj.relative_is_upgrade = None
                else:
                    # 将JSON中的列表转换为元组结构
                    if isinstance(upgrade_value, list) and len(upgrade_value) == 2:
                        old_val, new_val = upgrade_value
                        # 如果元素是列表，转换为元组；否则保持原样
                        if isinstance(old_val, list):
                            old_val = tuple(old_val)
                        if isinstance(new_val, list):
                            new_val = tuple(new_val)
                        var_obj.relative_is_upgrade = (old_val, new_val)
                    else:
                        var_obj.relative_is_upgrade = upgrade_value

    def reload_for_create(self):
        """从快照重新加载变量状态，用于创建时恢复
        固定从倒数第二层读取post快照，最后一层读取pre快照
        """
        # 函数级注释：按固定层级读取 post/pre 快照，恢复当前内存状态并校验一致性
        if not global_io_manager.exists(self.save_file):
            raise FileNotFoundError(f"数据文件不存在：'{self.save_file}'。原因：路径无效或文件缺失。期望：提供存在的 JSON 数据文件。")
        # print(f"开始从快照文件读取(创建恢复): {self.save_file}") # 调试：记录读取数据文件
        raw_json = global_io_manager.read_json(self.save_file)
        data = json.loads(raw_json)

        if not data:
            return  # 没有数据，跳过重载
        
        # 获取所有消息，按层级排序
        messages = []
        for key, value in data.items():
            if key.isdigit() and isinstance(value, dict) and value.get("speaker") == "Assistant":
                messages.append(value)
        
        if not messages:
            return  # 没有助手消息，跳过重载
        
        # 按layer排序
        messages.sort(key=lambda x: x.get("layer", 0))
        
        if len(messages) < 2:
            raise ValueError("需要至少两层消息才能执行 reload_for_create。原因：层级数量不足。期望：提供不少于两层的 Assistant 消息记录。")
        
        # 固定从倒数第二层读取post快照
        second_last = messages[-2]
        post_snapshot = second_last.get("variable_snapshot", {}).get("post")
        if not post_snapshot:
            raise ValueError("倒数第二层消息中没有 post 快照。原因：记录缺失。期望：该层包含 variable_snapshot.post。")
        
        # 固定从最后一层读取pre快照
        last = messages[-1]
        pre_snapshot = last.get("variable_snapshot", {}).get("pre")
        if not pre_snapshot:
            raise ValueError("最后一层消息中没有 pre 快照。原因：记录缺失。期望：该层包含 variable_snapshot.pre。")
        
        # 组合post和pre快照
        combined_snapshot = {}
        combined_snapshot.update(post_snapshot)
        combined_snapshot.update(pre_snapshot)
        
        # 检查变量名称和数量是否匹配
        vm_var_names = set(self.variables.keys())
        snapshot_var_names = set(combined_snapshot.keys())
        
        if vm_var_names != snapshot_var_names:
            missing_in_vm = snapshot_var_names - vm_var_names
            missing_in_snapshot = vm_var_names - snapshot_var_names
            
            error_msg = "变量名称或数量不匹配！"
            if missing_in_vm:
                error_msg += f" VM中缺少变量: {missing_in_vm}"
            if missing_in_snapshot:
                error_msg += f" 快照中缺少变量: {missing_in_snapshot}"
            
            raise ValueError(error_msg)
        
        # 从快照加载数据覆盖VM内存中的数据
        for var_name, var_obj in self.variables.items():
            snapshot_var = combined_snapshot[var_name]
            
            # 覆盖value
            if "value" in snapshot_var:
                var_obj.value = snapshot_var["value"]
            
            # 覆盖relative_is_upgrade（仅对阶段变量）
            if (var_obj.var_type == VariableType.STAGE_INDEPENDENT and 
                "relative_is_upgrade" in snapshot_var):
                # 正确处理null值，将其转换为None
                upgrade_value = snapshot_var["relative_is_upgrade"]
                if upgrade_value is None:
                    var_obj.relative_is_upgrade = None
                else:
                    # 将JSON中的列表转换为元组结构
                    if isinstance(upgrade_value, list) and len(upgrade_value) == 2:
                        old_val, new_val = upgrade_value
                        # 如果元素是列表，转换为元组；否则保持原样
                        if isinstance(old_val, list):
                            old_val = tuple(old_val)
                        if isinstance(new_val, list):
                            new_val = tuple(new_val)
                        var_obj.relative_is_upgrade = (old_val, new_val)
                    else:
                        var_obj.relative_is_upgrade = upgrade_value
    
    def apply_variable_updates(self, variable_delta_list: List[Tuple['Variable', Union[float, str]]]):
        """
        应用变量更新（仅负责变化计算与结果组织，不直接写文件）
        - 统一校验输入变量的 `pre_update` 属性
        - 从上一层的快照恢复基准值
        - 根据 delta 应用变化、限幅、计算阶段升级(relative_is_upgrade)
        - 组织为仅包含 name/value/relative_is_upgrade 的条目列表
        - 调用专用保存函数将条目写入当前层的对应 section
        Args:
            variable_delta_list: 列表，每项为 (Variable实例, delta[float 或 'reset'])
        Returns:
            Tuple[List[Dict], str]: (snapshot_entries, section_flag)
        """
        # 函数级注释：读取上一层基准快照，恢复临时变量值后应用 delta，计算阶段升级并组织输出，最后保存到当前层
        # print(f"[DEBUG] apply_variable_updates 开始执行") # 调试：进入更新应用流程
        # print(f"[DEBUG] variable_delta_list 长度: {len(variable_delta_list) if variable_delta_list else 0}") # 调试：记录输入长度

        if not variable_delta_list:
            # print(f"[DEBUG] variable_delta_list 为空，直接返回") # 调试：空输入使用默认返回
            return [], 'pre'  # 默认返回空与默认标志

        # 打印输入的变量列表
        # for i, (var, delta) in enumerate(variable_delta_list):
        #     print(f"[DEBUG] 变量 {i}: name={var.name}, pre_update={var.pre_update}, delta={delta}") # 调试：记录输入变量明细

        # 检查所有变量的pre_update属性是否统一
        first_pre_update = variable_delta_list[0][0].pre_update
        # print(f"[DEBUG] 第一个变量的 pre_update: {first_pre_update}") # 调试：记录首项标志
        pre_update_values = {var.pre_update for var, _ in variable_delta_list}
        pre_update_check = len(pre_update_values) == 1
        if not pre_update_check:
            raise ValueError(f"一次调用中所有变量的 pre_update 属性必须统一。原因：检测到不同值集合 {pre_update_values}。期望：所有变量的 pre_update 值相同。")

        # 第一步：读取data.json得到最大的layer（用于恢复上一层的基准快照）
        # print(f"[DEBUG] 检查文件是否存在: {self.save_file}") # 调试：记录文件存在性
        if global_io_manager.exists(self.save_file):
            # print(f"[DEBUG] 文件存在，开始读取") # 调试：确认进入读取分支
            raw_json = global_io_manager.read_json(self.save_file)
            data = json.loads(raw_json)
            # print(f"[DEBUG] 成功读取 data.json，包含 {len(data)} 条记录") # 调试：记录读取条数
        else:
            # print(f"[DEBUG] 文件不存在，使用空字典") # 调试：使用空数据流程
            data = {}

        # 获取最大layer与上一层信息
        max_layer = 0
        for key, record in data.items():
            if isinstance(record, dict) and 'layer' in record:
                max_layer = max(max_layer, record['layer'])
        previous_layer = max_layer - 1
        target_section = 'pre' if first_pre_update else 'post'
        # print(f"[DEBUG] 最大layer: {max_layer}") # 调试：记录最大层级
        # print(f"[DEBUG] previous_layer: {previous_layer}") # 调试：记录上一层
        # print(f"[DEBUG] target_section: {target_section}") # 调试：记录目标区段

        # 查找上一层 Assistant 记录的对应快照作为基准
        base_snapshot = {}
        if previous_layer > 0:
            # print(f"[DEBUG] 开始查找 layer={previous_layer} 的 Assistant 记录") # 调试：开始检索上一层记录
            for key, record in data.items():
                if (isinstance(record, dict) and
                    record.get('layer') == previous_layer and
                    record.get('speaker') == 'Assistant'):
                    # print(f"[DEBUG] 找到 layer={previous_layer} 的 Assistant 记录: key={key}") # 调试：记录命中项
                    if 'variable_snapshot' in record and target_section in record['variable_snapshot']:
                        base_snapshot = record['variable_snapshot'][target_section]
                        # print(f"[DEBUG] 找到目标section '{target_section}'，包含变量: {list(base_snapshot.keys())}") # 调试：记录快照变量
                    else:
                        # print(f"[DEBUG] 记录中没有找到 section '{target_section}' 或 variable_snapshot") # 调试：快照区段缺失
                        pass
                    break
            else:
                # print(f"[DEBUG] 没有找到 layer={previous_layer} 的 Assistant 记录") # 调试：上一层记录缺失
                pass
        else:
            # print(f"[DEBUG] previous_layer <= 0，跳过基准快照查找") # 调试：无上一层，跳过
            pass

        # print(f"[DEBUG] base_snapshot 包含 {len(base_snapshot)} 个变量: {list(base_snapshot.keys())}") # 调试：记录基准快照规模

        # 从VariableManager中按变量名暂存变量实例列表（恢复值与relative_is_upgrade）
        temp_variables = {}
        for var_name in base_snapshot.keys():
            if var_name in self.variables:
                temp_var = self.variables[var_name]
                temp_var.value = base_snapshot[var_name]['value']
                temp_var.relative_is_upgrade = base_snapshot[var_name].get('relative_is_upgrade', None)
                temp_variables[var_name] = temp_var
            else:
                raise KeyError(f"基准快照引用了未注册变量 '{var_name}'。原因：VariableManager 当前没有此名称的变量。期望：先在管理器中注册该变量。")

        # 检查delta列表中的变量是否都在暂存列表中
        for variable, _ in variable_delta_list:
            if variable.name not in temp_variables:
                raise ValueError(f"变量 '{variable.name}' 不在上一层基准快照 '{target_section}' 中。原因：上一层快照缺少对应条目。期望：该变量应在上一层快照中出现。")

        # 逐条应用更新
        for i, (variable, delta) in enumerate(variable_delta_list):
            temp_var = temp_variables[variable.name]
            old_value = temp_var.value

            # 获取原阶段信息（用于阶段变量）
            old_stage_info = None
            if temp_var.var_type == VariableType.STAGE_INDEPENDENT:
                old_stage_info = temp_var.get_stage()

            # 根据delta类型进行更新
            if isinstance(delta, str):
                if delta == "reset":
                    new_value = temp_var.reset_value
                else:
                    # print(f"[ERROR] 不支持的字符串delta值: {delta}") # 调试：忽略不支持的字符串 delta
                    continue
            else:
                # 浮点数，直接相加
                new_value = old_value + delta

            # 应用值限制
            if new_value < temp_var.min_value:
                new_value = temp_var.min_value
            elif new_value > temp_var.max_value:
                new_value = temp_var.max_value

            # 更新变量值
            temp_var.value = round(new_value, 1)

            # 处理relative_is_upgrade属性逻辑
            if temp_var.var_type == VariableType.STAGE_INDEPENDENT:
                new_stage_info = temp_var.get_stage()
                old_stage_value = old_stage_info.get('relative_value') if old_stage_info else None
                new_stage_value = new_stage_info.get('relative_value') if new_stage_info else None
                if old_stage_value != new_stage_value:
                    temp_var.relative_is_upgrade = (old_stage_value, new_stage_value)
                else:
                    temp_var.relative_is_upgrade = None
            else:
                temp_var.relative_is_upgrade = None

        # 组织输出为仅包含 name/value/relative_is_upgrade 的条目列表
        snapshot_entries = [
            {
                'name': var_name,
                'value': temp_var.value,
                'relative_is_upgrade': temp_var.relative_is_upgrade
            }
            for var_name, temp_var in temp_variables.items()
        ]

        # 调用专用保存函数（文件读写逻辑已解耦）
        save_variable_snapshot_section(snapshot_entries, target_section, self.save_file)

        # print(f"[DEBUG] apply_variable_updates 执行完成（保存逻辑已解耦）") # 调试：流程完成
        return snapshot_entries, target_section

# 工具函数
def calculate_random_value(min_val: float, max_val: float) -> float:
    """计算带随机浮动的数值
    
    Args:
        min_val: 最小值
        max_val: 最大值
        
    Returns:
        float: 在min_val和max_val之间的随机值，保留一位小数
    """
    # 生成1-100的随机种子
    seed = random.randint(1, 100)
    # 将种子映射到0-1范围
    ratio = seed / 100.0
    # 计算最终值
    value = min_val + (max_val - min_val) * ratio
    # 四舍五入保留一位小数
    return round(value, 1)
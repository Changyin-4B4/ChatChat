import json
from typing import Any, Dict, List, Optional, Tuple, Union

from core.variables_update import (
    Variable,
    VariableType,
    UpdateType,
    ResetType,
    RelativeMethod,
)
from .io_manager import global_io_manager

def _parse_enum(enum_cls, raw: Optional[str], field_name: str):
    """
    函数说明：
    - 将字符串值解析为枚举实例；兼容枚举名（RECORD）或枚举值（record），大小写不敏感。
    参数：
    - enum_cls: 目标枚举类型
    - raw: 原始字符串（或 None）
    - field_name: 字段名（用于错误信息提示）
    返回：
    - 对应的枚举实例或 None
    """
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise TypeError(f"{field_name} 期望为字符串或省略，当前为 {type(raw).__name__}")
    key = raw.strip()
    if not key:
        return None
    # 优先尝试枚举名
    try:
        return enum_cls[key.upper()]
    except Exception:
        pass
    # 回退按枚举值匹配
    for e in enum_cls:
        if e.value.lower() == key.lower():
            return e
    raise ValueError(f"{field_name} 不合法：{raw!r}，期望为 {', '.join([e.name for e in enum_cls])} 或 {', '.join([e.value for e in enum_cls])}")

def _coerce_float(raw: Optional[Union[str, int, float]]) -> Optional[float]:
    """
    函数说明：
    - 将输入转为 float；支持 'inf'/'-inf' 字符串。
    参数：
    - raw: 原始值
    返回：
    - float 或 None
    """
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    if isinstance(raw, str):
        v = raw.strip().lower()
        if v in ("inf", "infinity"):
            return float("inf")
        if v in ("-inf", "-infinity"):
            return float("-inf")
        try:
            return float(raw)
        except Exception:
            raise ValueError(f"无法将数值解析为 float：{raw!r}")
    raise TypeError(f"期望数值或字符串，当前为 {type(raw).__name__}")

def _to_tuple(raw: Any) -> Optional[Tuple]:
    """
    函数说明：
    - 将 list 转为 tuple；保留 None；其他类型原样返回（用于阶段配置）。
    参数：
    - raw: 原始值
    返回：
    - tuple 或原值或 None
    """
    if raw is None:
        return None
    if isinstance(raw, tuple):
        return raw
    if isinstance(raw, list):
        return tuple(raw)
    return raw

def _to_nested_tuple(raw: Any) -> Optional[Union[Tuple[str, ...], Tuple[Tuple[str, ...], ...]]]:
    """
    函数说明：
    - 将 list/嵌套 list 转为对应的 tuple/嵌套 tuple（用于阶段描述）。
    参数：
    - raw: 原始值
    返回：
    - tuple 或嵌套 tuple 或 None
    """
    if raw is None:
        return None
    if isinstance(raw, list):
        if raw and isinstance(raw[0], list):
            return tuple(tuple(inner) for inner in raw)
        return tuple(raw)
    return raw

def _build_constraint(elem: Union[List, Tuple], name_map: Dict[str, Variable]):
    """
    函数说明：
    - 构建单个约束条件，支持以下格式：
      [下界, "变量名", 上界]，[下界, "变量名"]，["变量名", 上界]
    参数：
    - elem: 原始约束元素
    - name_map: 变量名到实例的映射
    返回：
    - 约束条件三种元组之一
    """
    if not isinstance(elem, (list, tuple)):
        raise TypeError(f"约束条件元素必须为 list/tuple，当前为 {type(elem).__name__}")

    n = len(elem)
    if n == 3:
        lb, var_name, ub = elem
        if not isinstance(var_name, str):
            raise TypeError("三元约束第二项必须为变量名字符串")
        var_obj = name_map.get(var_name)
        if var_obj is None:
            raise KeyError(f"约束引用了未定义变量：{var_name!r}")
        return (_coerce_float(lb), var_obj, _coerce_float(ub))
    if n == 2:
        a, b = elem
        if isinstance(a, (int, float)) and isinstance(b, str):
            var_obj = name_map.get(b)
            if var_obj is None:
                raise KeyError(f"约束引用了未定义变量：{b!r}")
            return (_coerce_float(a), var_obj)
        if isinstance(a, str) and isinstance(b, (int, float)):
            var_obj = name_map.get(a)
            if var_obj is None:
                raise KeyError(f"约束引用了未定义变量：{a!r}")
            return (var_obj, _coerce_float(b))
        raise ValueError(f"二元约束格式不合法：{elem!r}，期望 [下界,\"变量名\"] 或 [\"变量名\",上界]")
    raise ValueError(f"约束条件长度不合法：{elem!r}")

def _resolve_constraints(raw_constraints: Optional[List[Any]], name_map: Dict[str, Variable]) -> Optional[List]:
    """
    函数说明：
    - 解析约束集合，支持与关系的单个约束，以及字典形式的或组：{\"or\": [[...], [...]]}
    参数：
    - raw_constraints: 原始约束列表或 None
    - name_map: 变量名到实例的映射
    返回：
    - 解析后的约束集合（符合 ConstraintSet）
    """
    if not raw_constraints:
        return None
    result: List[Any] = []
    for elem in raw_constraints:
        if isinstance(elem, dict) and "or" in elem:
            group = [_build_constraint(inner, name_map) for inner in elem["or"]]
            result.append(group)
        else:
            result.append(_build_constraint(elem, name_map))
    return result

def load_variables_from_json(config_path: str = "variables_config.json") -> List[Variable]:
    """
    函数说明：
    - 从 JSON 配置文件读取变量定义并实例化为 Variable 对象列表。
    - 两阶段构建：先创建变量实例（不带约束），后解析并挂载约束。
    参数：
    - config_path: 相对路径（使用 IO 管理器），默认 'variables_config.json'
    返回：
    - Variable 实例列表
    """
    if not global_io_manager.exists(config_path):
        raise FileNotFoundError(f"变量配置文件未找到：{config_path}")

    raw_text = global_io_manager.read_json(config_path)
    data = json.loads(raw_text)

    # 支持顶层数组或包含 'variables' 字段的对象
    var_defs: List[Dict[str, Any]] = []
    if isinstance(data, list):
        var_defs = data
    elif isinstance(data, dict):
        var_defs = data.get("variables", [])
    else:
        raise ValueError("JSON 顶层结构不支持，期望为数组或含 'variables' 字段的对象")

    variables: List[Variable] = []
    name_map: Dict[str, Variable] = {}
    pending_constraints: Dict[str, Optional[List[Any]]] = {}

    # 第一阶段：创建实例（不解析约束）
    for conf in var_defs:
        name = conf.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ValueError("变量缺少合法的 'name' 字段")

        var_type = _parse_enum(VariableType, conf.get("var_type"), "var_type")
        update_type = _parse_enum(UpdateType, conf.get("update_type"), "update_type")

        # 基础数值
        pre_update = bool(conf.get("pre_update", True))
        initial_value = _coerce_float(conf.get("initial_value", 0.0)) or 0.0
        min_value = _coerce_float(conf.get("min_value", float("-inf"))) or float("-inf")
        max_value = _coerce_float(conf.get("max_value", float("inf"))) or float("inf")

        # 重置
        reset_type = _parse_enum(ResetType, conf.get("reset_type"), "reset_type")
        reset_config = conf.get("reset_config")
        reset_value = _coerce_float(conf.get("reset_value", 0.0)) or 0.0

        # 更新配置：可为 str 或 dict
        update_config = conf.get("update_config")

        # 阶段相关
        relative_name = conf.get("relative_name")
        relative_method = _parse_enum(RelativeMethod, conf.get("relative_method"), "relative_method")
        relative_stage_config = _to_tuple(conf.get("relative_stage_config"))
        rel_val_raw = conf.get("relative_value")
        if isinstance(rel_val_raw, list):
            relative_value: Optional[Union[int, Tuple[int, ...]]] = tuple(rel_val_raw)
        else:
            relative_value = rel_val_raw  # 可能为 int 或 None
        relative_description = _to_nested_tuple(conf.get("relative_description"))
        rel_desc_current_raw = conf.get("relative_current_description")
        if isinstance(rel_desc_current_raw, list):
            relative_current_description: Optional[Union[str, Tuple[str, ...]]] = tuple(rel_desc_current_raw)
        else:
            relative_current_description = rel_desc_current_raw

        # 创建变量实例（约束稍后挂载）
        var_obj = Variable(
            name=name,
            var_type=var_type,
            update_type=update_type,
            update_config=update_config,
            pre_update=pre_update,
            initial_value=initial_value,
            min_value=min_value,
            max_value=max_value,
            update_constraint=None,
            reset_type=reset_type,
            reset_config=reset_config,
            reset_value=reset_value,
            relative_name=relative_name,
            relative_method=relative_method,
            relative_stage_config=relative_stage_config,
            relative_value=relative_value,
            relative_description=relative_description,
            relative_current_description=relative_current_description,
            relative_is_upgrade=None
        )

        variables.append(var_obj)
        name_map[name] = var_obj
        pending_constraints[name] = conf.get("update_constraint")

    # 第二阶段：解析并挂载约束
    for var in variables:
        raw_constraints = pending_constraints.get(var.name)
        var.update_constraint = _resolve_constraints(raw_constraints, name_map)

    return variables

def get_variable_map(variables: Optional[List[Variable]] = None) -> Dict[str, Variable]:
    """
    函数说明：
    - 将变量列表转换为名称到实例的字典映射，便于按名称访问。
    参数：
    - variables: 可选变量列表；若省略则使用默认加载的列表
    返回：
    - 变量名到 Variable 实例的字典
    """
    source = variables if variables is not None else variable_list
    return {v.name: v for v in source}
from pathlib import Path
import json
import re

class IO_Manager:
    def __init__(self, config_directory: str = r"C:\config"):
        """
        zh: 初始化 IO 管理器。唯一属性为配置目录（config_directory），默认指向项目 config。
        en: Initialize the IO manager. The only attribute is the configuration directory,
            defaulting to the project's config folder.
        """
        self.config_directory = config_directory
        # print(f"IO_Manager 初始化完成，基础目录: {self.config_directory}")  # 调试：确认基础目录设置

    def _build_absolute_path(self, relative_path: str) -> str:
        """
        zh: 使用配置目录与提供的相对路径拼接出绝对路径。若传入绝对路径则抛错。
        en: Join the configuration directory with the given relative path to
            produce an absolute file path. Raises error if an absolute path is given.
        """
        if not isinstance(relative_path, str):
            raise TypeError(
                f"参数 relative_path 必须为 str 类型，当前为 {type(relative_path).__name__}；期望：相对路径字符串。"
            )
        p = Path(relative_path)
        if p.is_absolute():
            raise ValueError(
                f"参数 relative_path 必须为相对路径，当前提供了绝对路径 '{relative_path}'；期望：相对路径字符串。"
            )
        abs_path = str(Path(self.config_directory) / p)
        # print(f"构造绝对路径: {relative_path} -> {abs_path}")  # 调试：路径解析
        return abs_path

    def exists(self, relative_path: str) -> bool:
        """
        zh: 判断目标是否存在。基于配置目录与相对路径拼接为绝对路径，
            仅判断是否存在，不进行类型或扩展名校验；若传入绝对路径则抛错。
        en: Check whether the target exists. Joins config directory with the
            relative path to an absolute path; only checks existence without
            any type or extension validation. Raises error if path is absolute.
        """
        abs_path = self._build_absolute_path(relative_path)
        exists_flag = Path(abs_path).exists()
        # print(f"检查路径存在性: {abs_path} -> {exists_flag}")  # 调试：文件/目录是否存在
        return exists_flag

    def read_json(self, relative_path: str) -> str:
        """
        zh: 读取 JSON 文件并原样返回文本内容；仅校验扩展名为 .json。
        en: Read a JSON file and return its raw text content; validates extension is .json only.
        """
        abs_path = self._build_absolute_path(relative_path)
        if Path(abs_path).suffix.lower() != ".json":
            raise ValueError(
                f"文件类型不匹配：期望扩展名为 '.json'，实际为 '{Path(abs_path).suffix}'；请提供 JSON 文件路径。"
            )
        with open(abs_path, "r", encoding="utf-8") as f:
            content = f.read()
        # print(f"读取 JSON 文件完成: {abs_path}, 字符数: {len(content)}")  # 调试：确认读取内容长度
        return content

    def read_yaml(self, relative_path: str) -> str:
        """
        zh: 读取 YAML 文件并原样返回文本内容；仅校验扩展名为 .yaml 或 .yml。
        en: Read a YAML file and return its raw text content; validates extension is .yaml or .yml.
        """
        abs_path = self._build_absolute_path(relative_path)
        suffix = Path(abs_path).suffix.lower()
        if suffix not in {".yaml", ".yml"}:
            raise ValueError(
                f"文件类型不匹配：期望扩展名为 '.yaml' 或 '.yml'，实际为 '{suffix}'；请提供 YAML 文件路径。"
            )
        with open(abs_path, "r", encoding="utf-8") as f:
            content = f.read()
        # print(f"读取 YAML 文件完成: {abs_path}, 字符数: {len(content)}")  # 调试：确认读取内容长度
        return content

    def read_txt(self, relative_path: str) -> str:
        """
        zh: 读取 TXT 文件并原样返回文本内容；仅校验扩展名为 .txt。
        en: Read a TXT file and return its raw text content; validates extension is .txt.
        """
        abs_path = self._build_absolute_path(relative_path)
        if Path(abs_path).suffix.lower() != ".txt":
            raise ValueError(
                f"文件类型不匹配：期望扩展名为 '.txt'，实际为 '{Path(abs_path).suffix}'；请提供文本文件路径。"
            )
        with open(abs_path, "r", encoding="utf-8") as f:
            content = f.read()
        # print(f"读取 TXT 文件完成: {abs_path}, 字符数: {len(content)}")  # 调试：确认读取内容长度
        return content

    def write_json(self, relative_path: str, content: str) -> str:
        """
        zh: 写入 JSON 文件。若为对象则格式化缩进，并将包含 "value" 与 "relative_is_upgrade"
            的变量快照压缩为单行；若为字符串，尝试按 JSON 解析并处理，失败则原样写入。
            仅校验扩展名为 .json；路径必须为相对路径。
        en: Write JSON file. For Python objects, pretty-print with indentation and
            compact variable snapshots containing "value" and "relative_is_upgrade"
            into a single line; for strings, try to parse as JSON and process,
            otherwise write as-is. Validates extension is .json; path must be relative.
        """
        abs_path = self._build_absolute_path(relative_path)
        if Path(abs_path).suffix.lower() != ".json":
            raise ValueError(
                f"文件类型不匹配：期望扩展名为 '.json'，实际为 '{Path(abs_path).suffix}'；请提供 JSON 文件路径。"
            )

        # 将 content 格式化为字符串：对象 -> pretty JSON；字符串 -> 若像 JSON 则解析格式化，否则原样
        if isinstance(content, str):
            stripped = content.strip()
            # print(f"写入 JSON（字符串模式），是否疑似 JSON: {stripped[:1] in '{[' + ']'}' and stripped[-1:] in '}]'}")  # 调试：字符串是否疑似 JSON
            if (
                (stripped.startswith("{") and stripped.endswith("}")) or
                (stripped.startswith("[") and stripped.endswith("]"))
            ):
                # 无 try-except，若解析失败将直接抛出 json 的异常
                data_obj = json.loads(content)
                json_str = json.dumps(data_obj, ensure_ascii=False, indent=2)
            else:
                json_str = content
        else:
            json_str = json.dumps(content, ensure_ascii=False, indent=2)

        # 压缩包含变量快照的对象为单行（支持 [[int,...],[int,...]] 或 null）
        pattern = (
            r'{\s*\n\s*"value":\s*([^,\n]+),\s*\n\s*"relative_is_upgrade":\s*'
            r'(\[\s*\[[\s\S]*?\]\s*,\s*\[[\s\S]*?\]\s*\]|null)\s*\n\s*}'
        )

        def _compact_snapshot(m: re.Match) -> str:
            value_part = m.group(1).strip()
            rel_part = m.group(2).strip()
            if rel_part == "null":
                rel_json = "null"
            else:
                stripped_rel = rel_part.strip()
                if stripped_rel.startswith("[") and stripped_rel.endswith("]"):
                    # 无 try-except，若解析失败将直接抛出 json 的异常
                    arr = json.loads(rel_part)
                    # 压缩数组为单行：无空格的逗号与冒号分隔
                    rel_json = json.dumps(arr, ensure_ascii=False, separators=(",", ":"))
                else:
                    # 若不是标准 JSON 数组形式，尽量移除空白以单行化（适用于纯数字与逗号）
                    rel_json = re.sub(r"\s+", "", rel_part)
            return f'{{"value": {value_part}, "relative_is_upgrade": {rel_json}}}'

        compact_json = re.sub(pattern, _compact_snapshot, json_str, flags=re.DOTALL)

        with open(abs_path, "w", encoding="utf-8") as f:
            f.write(compact_json)
        # print(f"JSON 文件写入完成: {abs_path}, 字符数: {len(compact_json)}")  # 调试：确认写入内容长度
        return

    def ensure_dir_for_file(self, relative_file_path: str) -> str:
        """
        函数说明：
        - 为目标文件路径的父目录执行创建（包含多级目录），并返回该文件的绝对路径。
        参数：
        - relative_file_path: 相对文件路径（例如 'data/data.json'）
        返回：
        - 文件的绝对路径字符串
        错误：
        - TypeError：relative_file_path 不是字符串
        - ValueError：传入了绝对路径（期望相对路径）
        """
        if not isinstance(relative_file_path, str):
            raise TypeError(
                f"参数 relative_file_path 必须为 str 类型，当前为 {type(relative_file_path).__name__}；期望：相对路径字符串。"
            )
        abs_path = self._build_absolute_path(relative_file_path)
        parent_dir = Path(abs_path).parent
        parent_dir.mkdir(parents=True, exist_ok=True)
        # print(f"已创建/确认父目录存在: {parent_dir}")  # 调试：目录创建状态
        return abs_path

global_io_manager = IO_Manager()
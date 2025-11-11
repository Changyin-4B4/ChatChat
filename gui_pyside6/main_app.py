import sys
import os
# 添加项目根目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from PySide6.QtWidgets import (QApplication, QMainWindow, QDialog, QLineEdit, QPushButton, 
                               QHBoxLayout, QVBoxLayout, QFileDialog, QLabel, QListWidget,
                               QListWidgetItem, QMessageBox, QScrollArea, QWidget, QRadioButton,
                               QButtonGroup)
from PySide6.QtCore import Qt
from pathlib import Path

from core.io_manager import global_io_manager
import json
from datetime import datetime
# ⚠️ 重要：ChatWindow 延迟导入，避免在配置加载前读取 core.configs
# from chat_window import ChatWindow  # ← 移到 main() 函数内部
from modern_theme import BASIC_THEME_STYLE

# ======================== 路径历史管理 ========================

def get_appdata_config_dir() -> Path:
    """获取 AppData 配置目录路径"""
    appdata_local = os.environ.get('LOCALAPPDATA')
    if not appdata_local:
        appdata_local = Path.home() / 'AppData' / 'Local'
    return Path(appdata_local) / 'ChatChat'

def get_filepath_config() -> Path:
    """获取路径配置文件完整路径"""
    return get_appdata_config_dir() / 'Filepath.json'

def ensure_filepath_config() -> None:
    """确保配置文件存在，不存在则创建空配置"""
    config_path = get_filepath_config()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    
    if not config_path.exists():
        # 创建空配置文件（包含基本结构）
        default_config = {
            "version": "1.0",
            "paths": []  # 每个元素格式：{"path": "...", "last_used": "2025-11-11T10:30:00", "added": "..."}
        }
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(default_config, f, indent=2, ensure_ascii=False)

def load_path_history() -> list[dict]:
    """读取路径历史记录"""
    config_path = get_filepath_config()
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return data.get('paths', [])
    except Exception:
        return []

def save_path_to_history(folder_path: str) -> None:
    """保存路径到历史记录（如已存在则更新最后使用时间）"""
    config_path = get_filepath_config()
    
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception:
        data = {"version": "1.0", "paths": []}
    
    paths = data.get('paths', [])
    now = datetime.now().isoformat()
    
    # 检查路径是否已存在
    existing = None
    for item in paths:
        if item.get('path') == folder_path:
            existing = item
            break
    
    if existing:
        # 更新最后使用时间
        existing['last_used'] = now
    else:
        # 添加新路径
        paths.append({
            'path': folder_path,
            'added': now,
            'last_used': now
        })
    
    data['paths'] = paths
    
    # 保存回文件
    with open(config_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

# ======================== GUI 对话框 ========================

class PathSelectorDialog(QDialog):
    """路径选择对话框：显示历史路径列表或添加新路径"""
    
    def __init__(self, path_history: list[dict], parent=None):
        super().__init__(parent)
        self.setWindowTitle("选择工作路径")
        self.setModal(True)
        self.resize(650, 500)
        
        self.selected_path = None
        self.path_history = path_history
        
        # 应用黑底白字样式
        dialog_style = """
            QDialog {
                background-color: #2b2b2b;
                color: #ffffff;
            }
            QLabel {
                color: #ffffff;
                font-size: 14px;
                margin: 8px 0;
            }
            QPushButton {
                background-color: #404040;
                color: #ffffff;
                border: 1px solid #606060;
                padding: 10px 20px;
                font-size: 14px;
                border-radius: 4px;
                min-width: 100px;
            }
            QPushButton:hover {
                background-color: #505050;
            }
            QPushButton:pressed {
                background-color: #303030;
            }
            QRadioButton {
                color: #ffffff;
                font-size: 13px;
                padding: 8px;
                spacing: 8px;
            }
            QRadioButton::indicator {
                width: 18px;
                height: 18px;
            }
            QRadioButton::indicator:unchecked {
                background-color: #1a1a1a;
                border: 2px solid #606060;
                border-radius: 9px;
            }
            QRadioButton::indicator:checked {
                background-color: #4a9eff;
                border: 2px solid #4a9eff;
                border-radius: 9px;
            }
            QScrollArea {
                background-color: #1a1a1a;
                border: 1px solid #606060;
                border-radius: 4px;
            }
            QWidget#scrollContent {
                background-color: #1a1a1a;
            }
        """
        self.setStyleSheet(dialog_style)
        
        self._setup_ui()
    
    def _setup_ui(self):
        """构建 UI"""
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        
        # 标题
        title_label = QLabel("请选择一个工作路径：")
        title_label.setStyleSheet("font-size: 16px; font-weight: bold; margin-bottom: 5px;")
        layout.addWidget(title_label)
        
        # 滚动区域（显示历史路径）
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setMinimumHeight(300)
        
        scroll_content = QWidget()
        scroll_content.setObjectName("scrollContent")
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        scroll_layout.setSpacing(5)
        
        # 单选按钮组
        self.button_group = QButtonGroup(self)
        
        if self.path_history:
            # 按最后使用时间排序（最近使用的在前）
            sorted_paths = sorted(
                self.path_history,
                key=lambda x: x.get('last_used', ''),
                reverse=True
            )
            
            for idx, item in enumerate(sorted_paths):
                path_str = item.get('path', '')
                last_used = item.get('last_used', '')
                
                # 格式化显示时间
                try:
                    dt = datetime.fromisoformat(last_used)
                    time_str = dt.strftime('%Y-%m-%d %H:%M')
                except Exception:
                    time_str = '未知时间'
                
                radio = QRadioButton(f"{path_str}\n    (最后使用: {time_str})")
                radio.setProperty("path", path_str)
                self.button_group.addButton(radio, idx)
                scroll_layout.addWidget(radio)
                
                # 默认选中第一个（最近使用的）
                if idx == 0:
                    radio.setChecked(True)
        else:
            # 无历史记录提示
            no_history_label = QLabel("暂无历史路径，请添加新路径")
            no_history_label.setStyleSheet("color: #999999; font-style: italic; padding: 20px;")
            no_history_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            scroll_layout.addWidget(no_history_label)
        
        scroll_area.setWidget(scroll_content)
        layout.addWidget(scroll_area)
        
        # 按钮区域
        button_layout = QHBoxLayout()
        button_layout.addStretch(1)
        
        add_new_button = QPushButton("➕ 添加新路径")
        confirm_button = QPushButton("✓ 确定")
        cancel_button = QPushButton("✗ 取消")
        
        # 如果没有历史路径,禁用确定按钮
        if not self.path_history:
            confirm_button.setEnabled(False)
        
        button_layout.addWidget(add_new_button)
        button_layout.addWidget(confirm_button)
        button_layout.addWidget(cancel_button)
        layout.addLayout(button_layout)
        
        # 信号连接
        add_new_button.clicked.connect(self._on_add_new_path)
        confirm_button.clicked.connect(self._on_confirm)
        cancel_button.clicked.connect(self.reject)
    
    def _on_add_new_path(self):
        """添加新路径：打开文件夹选择器"""
        folder_path = QFileDialog.getExistingDirectory(
            self, 
            "选择工作文件夹", 
            os.path.expanduser("~")
        )
        
        if folder_path:
            self.selected_path = folder_path
            self.accept()
    
    def _on_confirm(self):
        """确认选择：获取选中的单选按钮对应的路径"""
        checked_button = self.button_group.checkedButton()
        if checked_button:
            self.selected_path = checked_button.property("path")
            self.accept()
    
    def get_selected_path(self) -> str | None:
        """获取用户选择的路径"""
        return self.selected_path


class FolderInputDialog(QDialog):
    """文件夹输入对话框：允许浏览选择或直接输入路径"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("选择工作文件夹")
        self.setModal(True)
        self.resize(550, 160)
        
        # 黑底白字样式
        dialog_style = """
            QDialog {
                background-color: #2b2b2b;
                color: #ffffff;
            }
            QLabel {
                color: #ffffff;
                font-size: 14px;
                margin: 8px 0;
            }
            QLineEdit {
                background-color: #000000;
                color: #ffffff;
                border: 1px solid #606060;
                border-radius: 4px;
                padding: 8px;
                font-size: 13px;
                font-family: 'Consolas', 'Monaco', monospace;
            }
            QPushButton {
                background-color: #404040;
                color: #ffffff;
                border: 1px solid #606060;
                padding: 8px 16px;
                font-size: 14px;
                border-radius: 4px;
                min-width: 80px;
            }
            QPushButton:hover {
                background-color: #505050;
            }
            QPushButton:pressed {
                background-color: #303030;
            }
        """
        self.setStyleSheet(dialog_style)
        
        self.input_edit = QLineEdit()
        self.input_edit.setPlaceholderText("输入或选择文件夹路径")
        
        browse_button = QPushButton("📁 浏览...")
        ok_button = QPushButton("✓ 确定")
        cancel_button = QPushButton("✗ 取消")
        
        layout = QVBoxLayout(self)
        label = QLabel("请选择或输入工作文件夹路径：")
        layout.addWidget(label)
        
        top_line = QHBoxLayout()
        top_line.addWidget(self.input_edit, stretch=1)
        top_line.addWidget(browse_button)
        layout.addLayout(top_line)
        
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(ok_button)
        buttons.addWidget(cancel_button)
        layout.addLayout(buttons)
        
        browse_button.clicked.connect(self._on_browse_clicked)
        ok_button.clicked.connect(self._on_confirm)
        cancel_button.clicked.connect(self.reject)
    
    def _on_browse_clicked(self):
        """浏览文件夹"""
        directory = QFileDialog.getExistingDirectory(
            self, 
            "选择工作文件夹", 
            os.path.expanduser("~")
        )
        if directory:
            self.input_edit.setText(directory)
    
    def _on_confirm(self):
        """确认输入"""
        path = self.input_edit.text().strip()
        if not path:
            QMessageBox.warning(self, "输入错误", "路径不能为空！")
            return
        
        # 简单验证路径格式（不要求路径必须存在，保留灵活性）
        self.accept()
    
    def get_path(self) -> str:
        """获取输入的路径"""
        return self.input_edit.text().strip()


# ======================== 启动路径选择逻辑 ========================

def prompt_workspace_path(app: QApplication) -> str | None:
    """
    启动时的路径选择流程：
    1. 确保配置文件存在
    2. 读取历史路径
    3. 如果有历史，显示选择界面；否则直接进入文件夹选择
    4. 保存选择的路径到历史
    
    返回：
    - str: 用户选择的路径
    - None: 用户取消
    """
    # 1. 确保配置文件存在
    ensure_filepath_config()
    
    # 2. 读取历史路径
    path_history = load_path_history()
    
    selected_path = None
    
    # 3. 显示路径选择界面
    if path_history:
        # 有历史记录：显示选择界面
        selector = PathSelectorDialog(path_history)
        result = selector.exec()
        
        if result == QDialog.DialogCode.Accepted:
            selected_path = selector.get_selected_path()
        else:
            return None  # 用户取消
    else:
        # 无历史记录：直接进入文件夹选择
        folder_dialog = FolderInputDialog()
        result = folder_dialog.exec()
        
        if result == QDialog.DialogCode.Accepted:
            selected_path = folder_dialog.get_path()
        else:
            return None  # 用户取消
    
    # 4. 保存到历史记录
    if selected_path:
        save_path_to_history(selected_path)
    
    return selected_path


# ======================== 原有代码部分 ========================

def load_and_apply_core_configs(config_path: str = "core_configs.json") -> None:
    """
    读取并应用核心全局配置（在进入 GUI 前执行）
    - 要求 JSON 顶层包含所有核心配置的键：
      ["LENGTH_LIMIT","USER_NAME","CHAT_METHOD","MEMORY_DEPTH","JUDGER_MEMORY_DEPTH","DEFAULT_OPENING","API_PROVIDERS","DEFAULT_WORKFLOW_CONFIG"]
    - 覆写规则：若某键的值为空（None、""、{}、[]），则保留默认；否则用 JSON 值覆盖 core.configs 中的同名变量。
    """
    # 延迟导入，以确保此函数可以在 GUI 模块前运行
    import core.configs as core_configs

    if not global_io_manager.exists(config_path):
        # JSON 不存在：直接使用默认配置
        return

    raw = global_io_manager.read_json(config_path)
    conf = json.loads(raw)

    required_keys = {
        "LENGTH_LIMIT",
        "USER_NAME",
        "CHAT_METHOD",
        "MEMORY_DEPTH",
        "JUDGER_MEMORY_DEPTH",
        "DEFAULT_OPENING",
        "API_PROVIDERS",
        "DEFAULT_WORKFLOW_CONFIG",
    }
    missing = required_keys - set(conf.keys())
    if missing:
        raise KeyError(f"核心配置 JSON 缺少必需键：{missing}")

    def is_empty(val):
        return val is None or (isinstance(val, str) and val.strip() == "") or (isinstance(val, (list, dict)) and len(val) == 0)

    # 逐项应用覆盖
    for key in required_keys:
        val = conf.get(key)
        if is_empty(val):
            continue
        
        # 特殊处理：LENGTH_LIMIT 需要验证格式
        if key == "LENGTH_LIMIT":
            if not isinstance(val, list) or len(val) != 2:
                raise ValueError(f"LENGTH_LIMIT 必须是包含两个数值的列表（[最小值, 最大值]），当前值: {val}")
            if not all(isinstance(x, (int, float)) for x in val):
                raise ValueError(f"LENGTH_LIMIT 的元素必须是数值类型，当前值: {val}")
            if val[0] >= val[1]:
                raise ValueError(f"LENGTH_LIMIT 的最小值必须小于最大值，当前值: {val}")
        
        setattr(core_configs, key, val)
        # print(f"应用配置：{key} = {val}")

# ⚠️ ChatApp 定义移到这里，但不导入 ChatWindow
class ChatApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("💬 ChatChat")
        self.resize(1600, 900)
        # 固定窗口大小，不可拉伸
        self.setFixedSize(1600, 900)
        
        # ✅ 在实例化时才导入 ChatWindow，确保配置已加载
        from chat_window import ChatWindow
        self.chat_window = ChatWindow()
        self.setCentralWidget(self.chat_window)


def main():
    app = RobustApplication(sys.argv)
    install_global_handlers(app)
    app.setStyleSheet(BASIC_THEME_STYLE)

    # 1️⃣ 启动路径选择流程（取消则退出）
    workspace_path = prompt_workspace_path(app)
    if workspace_path is None:
        return 0
    
    app.setProperty("startupInput", workspace_path)
    global_io_manager.config_directory = workspace_path

    # 2️⃣ 加载配置（必须在创建 ChatApp 之前！）
    load_and_apply_core_configs()

    # 3️⃣ 创建主窗口（此时 ChatWindow 才会被导入和实例化）
    window = ChatApp()
    window.show()

    # 应用即将退出兜底：确保线程收到停止信号（双保险）
    def _shutdown():
        try:
            if hasattr(window, "chat_window") and hasattr(window.chat_window, "processor_worker"):
                worker = window.chat_window.processor_worker
                if worker and worker.isRunning():
                    worker.request_stop()
                    worker.wait(3000)
        except Exception as e:
            try:
                window.chat_window._on_error_occurred(
                    f"应用退出时停止线程失败：{type(e).__name__}: {e}"
                )
            except Exception:
                pass

    app.aboutToQuit.connect(_shutdown)

    return app.exec()

class RobustApplication(QApplication):
    """QApplication 子类：兜底捕获 Qt 事件循环中的未处理异常，写日志并提示用户。"""
    def notify(self, receiver, event):
        """捕获所有事件处理阶段抛出的异常，避免进程直接崩溃并记录详细堆栈。"""
        try:
            return super().notify(receiver, event)
        except Exception as e:
            import traceback
            from pathlib import Path
            msg = f"Unhandled exception in Qt event loop: {type(e).__name__}: {e}\n{traceback.format_exc()}"
            try:
                log_dir = _resolve_log_dir()
                log_dir.mkdir(parents=True, exist_ok=True)
                with open(log_dir / "crash.log", "a", encoding="utf-8") as f:
                    f.write(msg + "\n")
            except Exception:
                pass
            try:
                QMessageBox.critical(None, "ChatChat 错误", msg)
            except Exception:
                pass
            return False

def _resolve_runtime_base() -> Path:
    """返回运行时基目录：打包态为可执行文件目录，开发态为项目根目录。"""
    import sys
    from pathlib import Path
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent

def _resolve_log_dir() -> Path:
    """返回日志目录路径：统一写入 logs/ 下，便于无控制台模式排查。"""
    # ✨ 改进：日志也写入 AppData
    appdata_local = os.environ.get('LOCALAPPDATA')
    if not appdata_local:
        appdata_local = Path.home() / 'AppData' / 'Local'
    log_dir = Path(appdata_local) / 'ChatChat' / 'logs'
    return log_dir

def install_global_handlers(app: QApplication) -> None:
    """安装全局异常与 Qt 消息处理器：捕获主线程/子线程异常与 Qt 警告，写入日志并提示。"""
    import sys, threading, traceback
    from PySide6.QtCore import qInstallMessageHandler, QtMsgType
    # 确保日志目录存在
    log_dir = _resolve_log_dir()
    log_dir.mkdir(parents=True, exist_ok=True)

    # 捕获未处理的 Python 异常
    def excepthook(exc_type, exc, tb):
        msg = "".join(traceback.format_exception(exc_type, exc, tb))
        with open(log_dir / "crash.log", "a", encoding="utf-8") as f:
            f.write("Unhandled exception (sys.excepthook):\n" + msg + "\n")
        try:
            QMessageBox.critical(app.activeWindow() or None, "ChatChat 错误", msg)
        except Exception:
            pass
    sys.excepthook = excepthook

    # 捕获非 QThread 的 Python 线程异常
    def threading_excepthook(args: threading.ExceptHookArgs):
        msg = "".join(traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback))
        with open(log_dir / "crash.log", "a", encoding="utf-8") as f:
            f.write("Unhandled exception (threading.excepthook):\n" + msg + "\n")
        try:
            QMessageBox.critical(app.activeWindow() or None, "ChatChat 错误", msg)
        except Exception:
            pass
    threading.excepthook = threading_excepthook

    # 启用 faulthandler，尽量抓取原生崩溃
    try:
        import faulthandler
        fh_file = open(log_dir / "faulthandler.log", "a", encoding="utf-8")
        faulthandler.enable(file=fh_file, all_threads=True)
    except Exception:
        pass

    # 捕获 Qt 消息（警告/致命）
    def qt_message_handler(mode, context, message):
        level = {
            QtMsgType.QtDebugMsg: "DEBUG",
            QtMsgType.QtInfoMsg: "INFO",
            QtMsgType.QtWarningMsg: "WARNING",
            QtMsgType.QtCriticalMsg: "CRITICAL",
            QtMsgType.QtFatalMsg: "FATAL",
        }.get(mode, str(mode))
        line = f"[{level}] {context.file}:{context.line} {context.function}: {message}\n"
        with open(log_dir / "qt.log", "a", encoding="utf-8") as f:
            f.write(line)
    qInstallMessageHandler(qt_message_handler)

if __name__ == '__main__':
    main()

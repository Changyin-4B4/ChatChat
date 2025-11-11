from queue import Queue, Empty
from PySide6.QtWidgets import QWidget, QHBoxLayout, QFrame, QVBoxLayout, QScrollArea, QTextEdit, QToolButton, QLabel, QSizePolicy, QProgressBar, QStackedWidget, QPushButton, QDialog, QLineEdit, QMessageBox
from PySide6.QtCore import Qt, QThread, Signal, QTimer
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QIcon, QTextCursor
from pathlib import Path
import sys
import os
import json
import traceback  # 新增：用于捕获并格式化堆栈信息

from core.message_process import create_default_chat_data
from core.ApplicationProcessor import AIRPCycleProcessor
from core.variables_update import VariableManager
from core.variables_loader import load_variables_from_json
from core.io_manager import global_io_manager

class ProcessorWorker(QThread):
    """统一处理中心工作线程，负责调用ApplicationProcessor"""
    
    # 定义信号 - 保留原有的create阶段信号
    create_content_received = Signal(str)  # 接收到过滤后的文本块 (create阶段)
    create_reasoning_received = Signal(str)  # 接收到思考内容 (create阶段)
    # # 新增 - Pre-judge阶段信号
    pre_judge_received = Signal(str)      # Pre-judge文本块
    # # 新增 - Post-judge阶段信号
    post_judge_received = Signal(str)     # Post-judge文本块

    pre_information = Signal(str)  # Pre-judge信息尾部
    create_information = Signal(str)  # Create信息尾部
    post_information = Signal(str)  # Post-judge信息尾部

    process_finished = Signal(str)  # 流式传输完成，传递完整响应 (create阶段)
    process_stopped = Signal()  # 流式传输被停止信号
    error_occurred = Signal(str)  # 发生错误

    def __init__(self, command_queue, vm: VariableManager):
        """
        初始化ProcessorWorker
        
        Args:
        command_queue: 命令队列，用于接收用户输入
        workflow_config: 工作流配置，如果为None则使用DEFAULT_WORKFLOW_CONFIG
        """
        super().__init__()
        self.command_queue = command_queue
        self._stop_requested = False  # 停止标志
        self.vm = vm
        self.main_processor = AIRPCycleProcessor(
            self.vm,
            on_create_content=self.on_create_content,
            on_create_reasoning=self.on_create_reasoning,
            on_pre_judge=self.on_pre_judge,
            on_post_judge=self.on_post_judge
        )
        self.processed_input = ""

    def stop_stream(self):
        """请求停止流式传输"""
        self.main_processor.stop_stream()

    def send_command_handle(self, data):
        """
        处理发送命令
        """
        self.main_processor.send_command(data)
        # 推送 pre_command 命令
        pre_command = ("pre_command", "")
        self.command_queue.put(pre_command)
    
    def pre_command_handle(self, data):
        """
        处理pre命令
        """
        returns = self.main_processor.pre_command()
        if returns == "stop":
            self.process_stopped.emit()
        else:
            # 格式化 info_tails 列表为中文信息
            if isinstance(returns, list) and len(returns) > 0:
                if len(returns) == 1:
                    info_text = f"pre-变量更新token消耗：{returns[0]}"
                else:
                    lines = ["pre-变量更新token消耗："]
                    for idx, elem in enumerate(returns, start=1):
                        lines.append(f"第{idx}轮：{elem}")
                    info_text = "\n".join(lines)
            else:
                # 兜底：非列表或空列表的返回统一字符串化
                info_text = ""
            # 发送信息尾部
            self.pre_information.emit(info_text)

            if data == "only":
                self.process_finished.emit("完成")
                return
            else:
                create_command = ("create_command", "")
                self.command_queue.put(create_command)

    def create_command_handle(self, data):
        """
        处理创建命令
        """
        returns = self.main_processor.create_command()
        if returns == "stop":
            self.process_stopped.emit()
        else:
            # returns 预期为单个字符串/数值
            info_text = f"正文内容token消耗：{returns}"
            self.create_information.emit(info_text)

            if data == "only":
                self.process_finished.emit("完成")
                return
            else:
                post_command = ("post_command", "")
                self.command_queue.put(post_command)

    def post_command_handle(self, data):
        """
        处理post命令
        """
        returns = self.main_processor.post_command()
        if returns == "stop":
            self.process_stopped.emit()
        else:
            # 格式化 info_tails 列表为中文信息
            if isinstance(returns, list) and len(returns) > 0:
                if len(returns) == 1:
                    info_text = f"post-变量更新token消耗：{returns[0]}"
                else:
                    lines = ["post-变量更新token消耗："]
                    for idx, elem in enumerate(returns, start=1):
                        lines.append(f"第{idx}轮：{elem}")
                    info_text = "\n".join(lines)
            else:
                # 兜底：非列表或空列表的返回统一字符串化
                info_text = ""
            # 发送信息尾部
            self.post_information.emit(info_text)
            # 完成整个流式流程
            self.process_finished.emit("完成")
    
    def request_stop(self) -> None:
        """请求停止工作线程
        - 设置内部停止标志，提示 run 循环尽快退出
        - 向队列投递哨兵命令以唤醒阻塞的 get()
        """
        self._stop_requested = True
        try:
            self.command_queue.put_nowait(("_stop", None))
        except Exception:
            # print("停止线程：哨兵投递失败（队列可能已不可用）")  # 调试：停止唤醒失败不影响退出
            pass    
    
    def run(self):
        """工作线程主循环
        - 使用阻塞 get() 等待命令（不再抛出 Empty）
        - 收到哨兵命令时退出循环
        - 捕获真实异常并上报类型 + 消息 + 堆栈
        """
        # print("工作线程启动")  # 调试：线程启动
        while not self._stop_requested:
            try:
                command, data = self.command_queue.get()  # 阻塞等待，无 timeout
                if command == "_stop":
                    # print("收到停止哨兵，准备退出")  # 调试：接收到停止哨兵
                    break

                if command == "send_command":
                    # print(f"收到命令: {command}, 数据: {data}")  # 调试：收到发送命令
                    self.send_command_handle(data)

                if command == "pre_command":
                    # print(f"收到命令: {command}, 数据: {data}")  # 调试：收到pre命令
                    self.pre_command_handle(data)

                if command == "create_command":
                    # print(f"收到命令: {command}, 数据: {data}")  # 调试：收到create命令
                    self.create_command_handle(data)

                if command == "post_command":
                    # print(f"收到命令: {command}, 数据: {data}")  # 调试：收到post命令
                    self.post_command_handle(data)

            except Exception as e:
                # 捕获真实异常：补充类型与堆栈，避免空 message 导致“发生错误:”无详情
                exc_type = type(e).__name__
                exc_msg = str(e).strip() or "异常对象未提供消息文本；期望：包含清晰的错误说明。"
                tb_text = traceback.format_exc()
                composite_msg = f"发生错误: {exc_type}: {exc_msg}\n{tb_text}"
                self.error_occurred.emit(composite_msg)
                continue
        # print("工作线程结束")  # 调试：线程退出
    
    def on_create_content(self, content):
        self.create_content_received.emit(content)

    def on_create_reasoning(self, reasoning):
        self.create_reasoning_received.emit(reasoning)

    def on_pre_judge(self, pre_judge):
        self.pre_judge_received.emit(pre_judge)

    def on_post_judge(self, post_judge):
        self.post_judge_received.emit(post_judge)

    def delete_messages(self, count=0):
        """删除指定数量的消息"""
        self.main_processor.delete_messages(count)
        return

class ChatWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.current_ai_message_widget = None
        self.current_ai_content_widget = None
        self.current_reasoning_widget = None
        self._stick_to_bottom = True
        

        self.is_streaming = False  # 新增：流式传输状态标志
        self.statu:str = None  #加入初始化时的判断逻辑进行赋值；

        self.vm = VariableManager()
        # 默认导出：供 GUI 或主程序直接使用
        try:
            variable_list: List[Variable] = load_variables_from_json()
        except Exception as e:
            # 若加载失败，暴露空列表并让调用方通过 UI 报错
            variable_list = []
        for var in variable_list:
            self.vm.add_variable(var)

        # 在创建聊天窗口前初始化默认数据
        create_default_chat_data(self.vm)

        # 聊天记录加载配置
        self.max_history_messages = 9999  # 默认加载最新9999条消息
        self.loaded_variables = {}  # 存储从data.json加载的变量
        
        self.setup_ui()
        # 在UI设置完成后加载聊天记录
        self.load_chat_history()

        self.worker_command_queue = Queue()
        self.processor_worker = ProcessorWorker(self.worker_command_queue, self.vm)
        
        # 连接信号
        self.processor_worker.create_content_received.connect(self._on_create_content_received)
        self.processor_worker.create_reasoning_received.connect(self._on_create_reasoning_received)  # 新增：思考内容信号
        self.processor_worker.pre_judge_received.connect(self._on_pre_judge_received)  # 新增：Pre-judge文本块信号
        self.processor_worker.post_judge_received.connect(self._on_post_judge_received)  # 新增：Post-judge文本块信号

        self.processor_worker.pre_information.connect(self._on_information_received)  # Pre-judge信息尾部
        self.processor_worker.create_information.connect(self._on_information_received)  # Create信息尾部
        self.processor_worker.post_information.connect(self._on_information_received)  # Post-judge信息尾部


        self.processor_worker.process_finished.connect(self._on_process_finished)
        self.processor_worker.process_stopped.connect(self._on_process_stopped)

        self.processor_worker.error_occurred.connect(self._on_error_occurred)

        # 启动线程
        self.processor_worker.start()
        self.switch_to_idle_state()

    def statu_check(self):
        """
        检查 data.json 中最新 layer 的 Assistant 消息的快照状态，并设置相应的 statu 值

        新增：
        - 若仅存在一条消息，则将该条消息的 snapshot（pre+post 合并）与 self.vm 的变量名进行一一对应校验；
        完整则 statu = "init"，不完整则抛出错误。
        - 若不止一条消息，继续执行原有逻辑。

        原有逻辑回顾：
        - pre/content/post 三者都空 → "send_done"
        - 仅 pre 存在 → "pre_done"
        - pre 和 content 存在 → "create_done"
        - pre/content/post 都存在 → "post_done"

        错误处理：异常统一通过 _on_error_occurred 上报（仅使用内置异常）。
        """
        # print("开始执行状态检查")  # 调试：记录状态检查起点

        try:
            # 使用 IO 管理器的相对路径
            data_file = "data/data.json"
            # print(f"目标数据文件路径: {data_file}")  # 调试：确认读取目标

            if not global_io_manager.exists(data_file):
                self.statu = "send_done"  # 默认状态
                # print("data.json 不存在，状态置为 send_done")  # 调试：默认状态
                return

            raw_json = global_io_manager.read_json(data_file)
            data = json.loads(raw_json)
            # print(f"数据读取成功，记录数：{len(data)}")  # 调试：确认数据量

            # 仅统计包含 speaker 字段的消息条目
            messages = [v for v in data.values() if isinstance(v, dict) and 'speaker' in v]
            # print(f"有效消息条目数：{len(messages)}")  # 调试：过滤后的消息数量

            # —— 新增首要判断：仅存在一条消息时，校验快照完整性 ——
            if len(messages) == 1:
                only_record = messages[0]
                # print(f"仅一条消息，speaker={only_record.get('speaker')}")  # 调试：单条消息的角色

                variable_snapshot = only_record.get('variable_snapshot', {})
                pre_snapshot = variable_snapshot.get('pre', {}) or {}
                post_snapshot = variable_snapshot.get('post', {}) or {}

                # 合并 pre 与 post 为完整列表
                combined_snapshot = {}
                combined_snapshot.update(pre_snapshot)
                combined_snapshot.update(post_snapshot)

                # 从 vm 获取期望的变量名集合（使用 get_all_variables_info(True) 以避免触发快照重载）
                expected_var_names = set(self.vm.get_all_variables_info(True).keys())
                snapshot_var_names = set(combined_snapshot.keys())
                # print(f"期望变量数={len(expected_var_names)}，快照变量数={len(snapshot_var_names)}")  # 调试：变量数量对比

                if not combined_snapshot:
                    raise ValueError(
                        "初始消息的 variable_snapshot 为空（pre/post 均为空）；原因：没有提供任何变量快照；"
                        "期望：至少包含一个 pre 或 post 快照字典，其键集合应与 self.vm.get_all_variables_info(True).keys() 完全一致"
                    )

                # 名字一一对应校验：集合必须完全一致
                if snapshot_var_names != expected_var_names:
                    missing_in_snapshot = expected_var_names - snapshot_var_names
                    extra_in_snapshot = snapshot_var_names - expected_var_names
                    raise ValueError(
                        f"初始快照变量名不完整或不匹配；原因：快照键集合与期望变量集合不一致；"
                        f"缺失={missing_in_snapshot}，多余={extra_in_snapshot}；"
                        "期望：快照键集合应与 self.vm.get_all_variables_info(True).keys() 完全一致"
                    )

                # 校验通过，置为 init 并返回
                self.statu = "init"
                # print(f"状态检查完成（初始化）：statu={self.statu}")  # 调试：初始化完成
                return

            # —— 若不止一条消息：执行原有逻辑 ——
            # 找到最后一条消息（最大 layer，如果 layer 相同则取最后一个）
            latest_record = None
            max_layer = -1
            for record_id, record_data in data.items():
                if isinstance(record_data, dict):
                    layer = record_data.get('layer', 0)
                    if layer >= max_layer:  # 改为 >= 以确保相同 layer 时取最后一个
                        max_layer = layer
                        latest_record = record_data

            # print(f"最大 layer = {max_layer}")  # 调试：确认选用的最新层级

            # 如果没有找到任何消息，设置为默认状态
            if not latest_record:
                self.statu = "send_done"
                # print("没有找到任何记录，状态设置为 send_done")  # 调试：空记录处理
                return

            # print(f"最新记录的 speaker = {latest_record.get('speaker')}")  # 调试：确认最新记录的角色

            # 如果最后一条消息是用户消息，说明还没开始处理，状态为 send_done
            if latest_record.get('speaker') == 'User':
                self.statu = "send_done"
                # print("最新记录为 User 消息，状态设置为 send_done")  # 调试：用户消息不触发处理
                return

            # 如果最后一条消息是助手消息，根据其内容判断状态
            if latest_record.get('speaker') == 'Assistant':
                # print("最新记录为 Assistant 消息，开始分析状态")  # 调试：进入助手消息状态判定

                # 获取 variable_snapshot
                variable_snapshot = latest_record.get('variable_snapshot', {})
                pre_snapshot = variable_snapshot.get('pre', {})
                post_snapshot = variable_snapshot.get('post', {})
                content = latest_record.get('content', '')

                # print(f"pre_snapshot={pre_snapshot}")  # 调试：前置变量快照内容
                # print(f"post_snapshot={post_snapshot}")  # 调试：后置变量快照内容
                # print(f"content='{content}'")  # 调试：助手消息正文

                # 判断各部分是否为空
                pre_empty = not pre_snapshot or len(pre_snapshot) == 0
                content_empty = not content or content.strip() == ''
                post_empty = not post_snapshot or len(post_snapshot) == 0

                # print(f"pre_empty={pre_empty}, content_empty={content_empty}, post_empty={post_empty}")  # 调试：三段内容为空性判断

                # 根据逻辑设置 statu
                if pre_empty and content_empty and post_empty:
                    self.statu = "send_done"
                elif not pre_empty and content_empty and post_empty:
                    self.statu = "pre_done"
                elif not pre_empty and not content_empty and post_empty:
                    self.statu = "create_done"
                elif not pre_empty and not content_empty and not post_empty:
                    self.statu = "post_done"
                else:
                    # 其他情况，设置为默认状态
                    self.statu = "send_done"

            # print(f"状态检查完成：statu={self.statu}")  # 调试：最终状态输出

        except (ValueError, TypeError, KeyError, json.JSONDecodeError) as e:
            self.statu = "send_done"  # 出错时设置为默认状态
            # print(f"状态检查异常：{e}")  # 调试：捕获到的异常信息
            self._on_error_occurred(f"状态检查失败：{e}")
    
    def load_chat_history(self):
        """加载聊天记录从 data.json 文件
        - 加载并渲染历史消息
        - 渲染完成后异步滚动到底部，避免初始化时滚动条位置被重置
        错误处理：异常统一通过 _on_error_occurred 上报（仅使用内置异常）。
        """
        data_file = "data/data.json"

        try:
            if global_io_manager.exists(data_file):
                # print(f"开始加载聊天记录：{data_file}")  # 调试：记录当前处理的文件名

                raw_json = global_io_manager.read_json(data_file)
                data = json.loads(raw_json)
                # print(f"数据加载完成，共 {len(data)} 条记录")  # 调试：确认数据加载状态

                # 加载变量
                self.update_variables_display()

                # 加载并显示聊天记录
                chat_records = data  # 现在 data 直接就是聊天记录字典
                if chat_records:
                    # 按 layer 排序获取最新的消息
                    sorted_records = sorted(
                        chat_records.items(),
                        key=lambda x: int(x[1].get('layer', 0))
                    )

                    # 只取最新的指定条数
                    recent_records = (
                        sorted_records[-self.max_history_messages:]
                        if len(sorted_records) > self.max_history_messages
                        else sorted_records
                    )
                    # print(f"准备渲染 {len(recent_records)} 条记录")  # 调试：确认渲染数量

                    for record_id, record_data in recent_records:
                        speaker = record_data.get('speaker', '')
                        content = record_data.get('content', '')

                        if speaker == 'User':
                            self.add_message(content, "user")
                        elif speaker == 'Assistant':
                            reasoning = record_data.get('reasoning', '')
                            # 将 reasoning 和 content 作为元组传递
                            self.add_message((reasoning, content), "ai")

                    # 异步滚动到底部（避免启动阶段布局重算覆盖滚动位置）
                    QTimer.singleShot(0, self._refresh_scroll_area)

                    # 重新绑定到最新的 AI 消息块
                    self._rebind_to_latest_ai_message()

        except (json.JSONDecodeError, TypeError, KeyError) as e:
            # print(f"加载聊天记录失败：{e}")  # 调试：捕获到的解析或类型错误
            self._on_error_occurred(f"加载聊天记录失败：{e}")
        except Exception as e:
            # print(f"加载聊天记录发生未知错误：{e}")  # 调试：兜底异常信息
            self._on_error_occurred(f"加载聊天记录发生未知错误：{e}")
    
    def _rebind_to_latest_ai_message(self):
        """重新绑定到最新的 AI 消息块
        - 绑定当前 AI 容器、正文控件与思考控件
        - 同步绑定“思考过程”开关按钮（不定义内部函数）
        错误处理：异常统一通过 _on_error_occurred 上报（仅使用内置异常）。
        """
        # print("开始重新绑定最新 AI 消息组件")  # 调试：方法入口

        try:
            # 首先检查最后一条消息是否是 AI 消息
            latest_ai_widget = None
            latest_ai_content_widget = None
            latest_reasoning_widget = None
            latest_toggle_button = None

            # 检查最后一条消息（排除最后的 stretch）
            if self.message_layout.count() > 1:
                last_item = self.message_layout.itemAt(self.message_layout.count() - 2)
                if last_item and last_item.widget():
                    last_widget = last_item.widget()
                    # 仅当最后一条为 AI 消息时进行绑定
                    if hasattr(last_widget, 'message_type') and last_widget.message_type == "ai":
                        latest_ai_widget = last_widget

                        # 优先使用容器已挂载的直接引用
                        if hasattr(last_widget, 'reasoning_widget') and hasattr(last_widget, 'ai_content_widget'):
                            latest_reasoning_widget = last_widget.reasoning_widget
                            latest_ai_content_widget = last_widget.ai_content_widget
                        else:
                            # 递归查找所有 QTextEdit（使用 Qt 提供的 API）
                            try:
                                text_edits = last_widget.findChildren(QTextEdit)
                            except Exception:
                                text_edits = []

                            # 简化判断：通常第一个是思考框，第二个是正文框
                            if len(text_edits) >= 2:
                                latest_reasoning_widget = text_edits[0]
                                latest_ai_content_widget = text_edits[1]
                            elif len(text_edits) == 1:
                                latest_ai_content_widget = text_edits[0]

                        # 查找“思考过程”开关按钮（可勾选的 QPushButton，文本包含“💭”或“思考”）
                        try:
                            queue = [last_widget]
                            while queue:
                                w = queue.pop(0)
                                if isinstance(w, QPushButton):
                                    try:
                                        if w.isCheckable():
                                            txt = w.text() or ""
                                            if ("💭" in txt) or ("思考" in txt):
                                                latest_toggle_button = w
                                                break
                                    except RuntimeError:
                                        # 子对象可能已销毁，忽略该节点
                                        pass
                                for c in getattr(w, "children", lambda: [])():
                                    if isinstance(c, QWidget):
                                        queue.append(c)
                        except Exception:
                            latest_toggle_button = None

            # 更新引用
            self.current_ai_message_widget = latest_ai_widget if latest_ai_widget else None
            self.current_ai_content_widget = latest_ai_content_widget if latest_ai_content_widget else None
            self.current_reasoning_widget = latest_reasoning_widget if latest_reasoning_widget else None
            self.reasoning_toggle_button = latest_toggle_button if latest_toggle_button else None

            # 刷新滚动区域（保持与现有逻辑一致）
            self._refresh_scroll_area()

            # print("重新绑定最新 AI 消息组件完成")  # 调试：方法出口

        except Exception as e:
            # print(f"绑定最新 AI 消息时发生错误：{e}")  # 调试：捕获到的异常信息
            self._on_error_occurred(f"绑定最新 AI 消息失败：{e}")
    
    def setup_ui(self):
        # 创建主布局（横向）
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)  # 去除边距
        main_layout.setSpacing(8)  # 减少间距为8px，为分割线留出空间
        
        # 创建左侧Frame
        left_frame = QFrame()
        left_frame.setStyleSheet("""
            QFrame {
                background-color: rgba(255, 255, 255, 0.1);
                border: 1px solid rgba(255, 255, 255, 0.2);
                border-radius: 8px;
            }
        """)
        
        # 为左侧Frame创建垂直布局
        left_layout = QVBoxLayout(left_frame)
        left_layout.setContentsMargins(8, 8, 8, 8)  # 8px边距，避开圆角
        left_layout.setSpacing(8)  # 8px间距
        
        # 创建滚动区域
        self.message_area = QScrollArea()
        self.message_area.setStyleSheet("""
            QScrollArea {
                background-color: transparent;
                border: none;
            }
        """)
        self.message_area.setWidgetResizable(True)
        
        # 创建消息容器Widget
        self.message_container = QWidget()
        self.message_container.setStyleSheet("""
            QWidget {
                background-color: transparent;
                border: none;
            }
        """)
        
        # 为消息容器创建垂直布局
        self.message_layout = QVBoxLayout(self.message_container)
        self.message_layout.setContentsMargins(8, 8, 8, 8)
        self.message_layout.setSpacing(12)
        self.message_layout.addStretch()  # 添加弹性空间，使消息从底部开始
        
        # 将消息容器设置到滚动区域
        self.message_area.setWidget(self.message_container)
        # 绑定滚动事件，维护“粘底”状态（接近底部才自动下滑）
        self.message_area.verticalScrollBar().valueChanged.connect(self._on_main_scroll_value_changed)
        
        # 创建横向分割线
        horizontal_separator_left_frame = QFrame()
        horizontal_separator_left_frame.setFixedHeight(2)  # 分割线高度2px
        horizontal_separator_left_frame.setStyleSheet("""
            QFrame {
                background-color: rgba(255, 255, 255, 0.6);
                border: none;
            }
        """)
        
        # 创建底部透明Widget
        user_bottom_widget = QWidget()
        user_bottom_widget.setFixedHeight(150)  # 固定高度150px
        user_bottom_widget.setStyleSheet("""
            QWidget {
                background-color: rgba(255, 255, 255, 0.0);
                border: none;
            }
        """)
        
        # 为底部Widget创建横向布局
        user_bottom_layout = QHBoxLayout(user_bottom_widget)
        user_bottom_layout.setContentsMargins(0, 0, 0, 0)  # 边距0
        user_bottom_layout.setSpacing(8)  # 间距8px
        
        # 创建文本输入框
        self.text_input = QTextEdit()  # 改为实例变量
        self.text_input.setStyleSheet("""
            QTextEdit {
                background-color: rgba(255, 255, 255, 0.1);
                border: 1px solid rgba(255, 255, 255, 0.2);
                border-radius: 0px;
                color: white;
                font-size: 14px;
                padding: 8px;
            }
        """)
        
        # 创建按钮区域Widget
        button_area = QWidget()
        button_area.setFixedWidth(150)  # 固定宽度150px
        button_area.setStyleSheet("""
            QWidget {
                background-color: rgba(255, 255, 255, 0.05);
                border: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: 0px;
            }
        """)
        
        # 为按钮区域创建垂直布局
        button_layout = QVBoxLayout(button_area)
        button_layout.setContentsMargins(0, 0, 0, 0)  # 边距0
        button_layout.setSpacing(8)  # 间距8px
        
        # 创建上方Widget（横向布局区域）
        button_top_widget = QWidget()
        button_top_widget.setFixedHeight(71)  # 设置固定高度为71px
        button_top_widget.setStyleSheet("""
            QWidget {
                background-color: transparent;
                border: none;
            }
        """)
        
        # 为上方Widget创建横向布局
        button_top_layout = QHBoxLayout(button_top_widget)
        button_top_layout.setContentsMargins(0, 0, 0, 0)  # 无边距
        button_top_layout.setSpacing(8)  # 间距8px
        
        # 创建第一个QToolButton（绿色HUD - Reroll）
        self.reroll_button = QToolButton()
        self.reroll_button.setIcon(QIcon(get_asset_path("assets/reroll.png")))
        self.reroll_button.setFixedHeight(71)  # 设置固定高度为71px
        self.reroll_button.setFixedWidth(71)  # 固定宽度71px
        self.reroll_button.setStyleSheet("""
            QToolButton {
                background-color: rgba(0, 255, 0, 0.45);
                border: 1px solid rgba(0, 255, 0, 0.3);
                padding: 4px;
            }
            QToolButton:hover {
                background-color: rgba(0, 255, 0, 0.25);
                border: 1px solid rgba(0, 255, 0, 0.4);
            }
            QToolButton:pressed {
                background-color: rgba(0, 255, 0, 0.1);
            }
        """)
        
        # 创建第二个QToolButton（红色HUD - Delete）
        self.delete_button = QToolButton()
        self.delete_button.setIcon(QIcon(get_asset_path("assets/delete.png")))
        self.delete_button.setFixedHeight(71)  # 设置固定高度为71px
        self.delete_button.setFixedWidth(71)  # 固定宽度71px
        self.delete_button.setStyleSheet("""
            QToolButton {
                background-color: rgba(180, 0, 0, 0.45);
                border: 1px solid rgba(180, 0, 0, 0.3);
                padding: 4px;
            }
            QToolButton:hover {
                background-color: rgba(180, 0, 0, 0.25);
                border: 1px solid rgba(180, 0, 0, 0.4);
            }
            QToolButton:pressed {
                background-color: rgba(180, 0, 0, 0.1);
            }
        """)
        
        # 添加按钮到横向布局
        button_top_layout.addWidget(self.reroll_button)
        button_top_layout.addWidget(self.delete_button)

        # 为reroll按钮绑定点击事件
        self.reroll_button.clicked.connect(self.handle_reroll_message)
        # 为删除按钮绑定点击事件
        self.delete_button.clicked.connect(self.handle_delete_messages)
        
        # 创建下方QToolButton按钮（蓝色HUD - Send，支持双形态）
        self.send_button = QToolButton()  # 改为实例变量
        self.send_button.setIcon(QIcon(get_asset_path("assets/send.png")))  # 默认形态：发送图标
        self.send_button.setFixedHeight(71)  # 设置固定高度为71px
        self.send_button.setFixedWidth(150)  # 设置固定宽度为150px，占据全部宽度
        self.send_button.setStyleSheet("""
            QToolButton {
                background-color: rgba(0, 100, 255, 0.45);
                border: 1px solid rgba(0, 100, 255, 0.3);
                padding: 8px 16px;
                min-height: 32px;
            }
            QToolButton:hover {
                background-color: rgba(0, 100, 255, 0.25);
                border: 1px solid rgba(0, 100, 255, 0.4);
            }
            QToolButton:pressed {
                background-color: rgba(0, 100, 255, 0.1);
            }
        """)

        # 绑定发送按钮的点击事件
        self.send_button.clicked.connect(self.handle_button_click)  # 修改为新的处理函数

        # 添加组件到按钮区域垂直布局
        button_layout.addWidget(button_top_widget)  # 上方Widget（自动扩展）
        button_layout.addWidget(self.send_button)  # 下方按钮（固定高度）
        
        # 添加组件到底部横向布局
        user_bottom_layout.addWidget(self.text_input)  # 文本输入框（自动扩展）
        user_bottom_layout.addWidget(button_area)  # 按钮区域（固定150px宽度）
        
        # 添加组件到左侧垂直布局
        left_layout.addWidget(self.message_area)  # 消息区域（滚动）（自动扩展）
        left_layout.addWidget(horizontal_separator_left_frame)  # 横向分割线
        left_layout.addWidget(user_bottom_widget)  # 底部透明Widget（自动扩展）
        
        # 创建主分割线
        separator_main = QFrame()
        separator_main.setFixedWidth(2)  # 分割线宽度2px
        separator_main.setStyleSheet("""
            QFrame {
                background-color: rgba(255, 255, 255, 0.6);
                border: none;
                border-radius: 1px;
            }
        """)
        
        # 创建右侧Widget
        right_widget = QWidget()
        right_widget.setFixedWidth(341)  # 固定宽度341px
        right_widget.setStyleSheet("""
            QWidget {
                background-color: rgba(255, 255, 255, 0.0);
                border: 1px solid rgba(255, 255, 255, 0.0);
                border-radius: 8px;
            }
        """)

        # 创建右侧垂直布局
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)  # 0边距
        right_layout.setSpacing(8)  # 8间距
        
        # 第一个：标题按钮（替换原 QLabel）
        self.right_title_button = QPushButton("角色信息")
        self.right_title_button.setCheckable(True)
        self.right_title_button.setChecked(False)  # 默认图片页
        self.right_title_button.setFixedHeight(20)
        self.right_title_button.setStyleSheet("""
            QPushButton {
                background-color: rgba(255, 255, 255, 0.1);
                color: #FFFFFF;
                font-size: 14px;
                font-weight: bold;
                padding: 2px 8px;
                border-radius: 4px;
                border: 1px solid rgba(255, 255, 255, 0.2);
                text-align: left;
            }
            QPushButton:hover {
                background-color: rgba(255, 255, 255, 0.15);
            }
            QPushButton:checked {
                background-color: rgba(255, 255, 255, 0.2);
            }
        """)
        right_layout.addWidget(self.right_title_button)

        # 第二个：图片/文本栈区域（0边距、0边框）
        self.right_image_text_stack = QStackedWidget()
        # 固定高度，避免与下方主栈共同扩展导致约 60px 额外空隙
        self.right_image_text_stack.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.right_image_text_stack.setFixedHeight(240)
        self.right_image_text_stack.setContentsMargins(0, 0, 0, 0)
        self.right_image_text_stack.setStyleSheet("""
            QStackedWidget {
                background-color: transparent;
                border: none;
            }
        """)

        # Page 0：图片页（居中）
        image_page = QWidget()
        image_layout = QHBoxLayout(image_page)
        image_layout.setContentsMargins(0, 0, 0, 0)
        image_layout.setSpacing(0)

        image_widget = QWidget()
        image_widget.setFixedSize(320, 240)  # 固定尺寸320x240
        image_widget.setStyleSheet("""
            QWidget {
                background-color: rgba(255, 255, 255, 0.05);
                border: 1px solid rgba(255, 255, 255, 0.1);
            }
        """)
        image_layout.addStretch()
        image_layout.addWidget(image_widget)
        image_layout.addStretch()
        self.right_image_text_stack.addWidget(image_page)  # index 0

        # Page 1：文本页（只读，样式与图片区一致）
        text_page = QWidget()
        text_layout = QHBoxLayout(text_page)
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(0)

        self.right_text_area = QTextEdit()
        self.right_text_area.setReadOnly(True)
        self.right_text_area.setFixedSize(320, 240)  # 与图片区一致
        self.right_text_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.right_text_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.right_text_area.setStyleSheet("""
            QTextEdit {
                background-color: rgba(255, 255, 255, 0.05);
                border: 1px solid rgba(255, 255, 255, 0.1);
                color: #FFFFFF;
                font-size: 14px;
                padding: 0px;
                margin: 0px;
            }
            QScrollBar:vertical {
                background-color: rgba(255, 255, 255, 0.1);
                width: 8px;
                border-radius: 4px;
            }
            QScrollBar::handle:vertical {
                background-color: rgba(255, 255, 255, 0.4);
                border-radius: 4px;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0;
            }
        """)
        text_layout.addStretch()
        text_layout.addWidget(self.right_text_area)
        text_layout.addStretch()
        self.right_image_text_stack.addWidget(text_page)  # index 1

        # 默认显示图片页
        self.right_image_text_stack.setCurrentIndex(0)
        # 顶部对齐，防止高度分配
        right_layout.addWidget(self.right_image_text_stack, 0, Qt.AlignmentFlag.AlignTop)

        # 点击标题按钮：切换到文本页并更新标题内容；再次点击切回图片区
        self.right_title_button.toggled.connect(self._on_right_title_toggled)

        # 第三个：横向分割线
        separator_horizontal = QFrame()
        separator_horizontal.setFrameShape(QFrame.HLine)
        separator_horizontal.setFixedHeight(2)  # 宽度2px
        separator_horizontal.setStyleSheet("""
            QFrame {
                background-color: rgba(255, 255, 255, 0.2);
                border: none;
            }
        """)
        right_layout.addWidget(separator_horizontal)

        # === 新增：横向按钮区域 ===
        button_row_widget = QWidget()
        button_row_widget.setFixedHeight(35)  # 固定高度35px
        button_row_widget.setStyleSheet("""
            QWidget {
                background-color: rgba(255, 255, 255, 0.0);
                border: 0px solid rgba(255, 255, 255, 0.0);
            }
        """)

        # 为按钮行创建横向布局
        button_row_layout = QHBoxLayout(button_row_widget)
        button_row_layout.setContentsMargins(12, 0, 12, 0)  # 左右12px，上下0px
        button_row_layout.setSpacing(10)  # 按钮之间间距10px

        # 按钮样式（参考reroll按钮样式）
        button_style = """
            QPushButton {
                background-color: rgba(0, 255, 0, 0.45);
                border: 1px solid rgba(0, 255, 0, 0.3);
                border-radius: 0px;
                padding: 4px;
            }
            QPushButton:hover {
                background-color: rgba(0, 255, 0, 0.25);
                border: 1px solid rgba(0, 255, 0, 0.4);
                border-radius: 0px;
            }
            QPushButton:pressed {
                background-color: rgba(0, 255, 0, 0.1);
                border-radius: 0px;
            }
        """
        
        # 创建三个按钮（不设置大小，自动平均分配）
        self.reroll_pre_button = QPushButton("reroll-前置更新")
        self.reroll_create_button = QPushButton("reroll-正文")
        self.reroll_post_button = QPushButton("reroll-后置更新")

        # 应用按钮样式
        self.reroll_pre_button.setStyleSheet(button_style)
        self.reroll_create_button.setStyleSheet(button_style)
        self.reroll_post_button.setStyleSheet(button_style)

        # 连接按钮点击事件
        self.reroll_pre_button.clicked.connect(self.reroll_pre_only)
        self.reroll_create_button.clicked.connect(self.reroll_create_only)
        self.reroll_post_button.clicked.connect(self.reroll_post_only)

        # 添加按钮到横向布局
        button_row_layout.addWidget(self.reroll_pre_button)
        button_row_layout.addWidget(self.reroll_create_button)
        button_row_layout.addWidget(self.reroll_post_button)

        # 将按钮行添加到右侧布局
        right_layout.addWidget(button_row_widget)

        # 第四个：创建QStackedWidget（边距0px）
        self.stacked_widget = QStackedWidget()
        self.stacked_widget.setContentsMargins(0, 0, 0, 0)
        
        # === 第一个页面：原有的变量状态布局 ===
        variables_page = QWidget()
        variables_layout = QVBoxLayout(variables_page)
        variables_layout.setContentsMargins(0, 0, 0, 0)
        variables_layout.setSpacing(1)
        
        # 变量状态标题
        title_label_2 = QLabel("变量状态")
        title_label_2.setFixedHeight(20)  # 固定高度20
        title_label_2.setStyleSheet("""
            QLabel {
                background-color: rgba(255, 255, 255, 0.1);
                color: #FFFFFF;
                font-size: 14px;
                font-weight: bold;
                padding: 2px 8px;
                border-radius: 4px;
                border: 1px solid rgba(255, 255, 255, 0.2);
            }
        """)
        variables_layout.addWidget(title_label_2)

        # 变量状态滚动区域
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll_area.setStyleSheet("""
            /* 使滚动区域及其视口、内部容器完全透明并移除边框 */
            QScrollArea,
            QScrollArea > QWidget,
            QScrollArea > QWidget > QWidget {
                background: transparent;
                border: none;
            }

            /* 保留滚动条样式（可按需调整或删除） */
            QScrollBar:vertical {
                background-color: rgba(255, 255, 255, 0.1);
                width: 8px;
                border-radius: 4px;
            }
            QScrollBar::handle:vertical {
                background-color: rgba(255, 255, 255, 0.3);
                border-radius: 4px;
                min-height: 20px;
            }
            QScrollBar::handle:vertical:hover {
                background-color: rgba(255, 255, 255, 0.5);
            }
        """)

        # 创建滚动区域内的容器widget
        self.variables_scroll_content = QWidget()
        self.variables_scroll_layout = QVBoxLayout(self.variables_scroll_content)
        self.variables_scroll_layout.setContentsMargins(0, 0, 0, 0)  # 边距0
        self.variables_scroll_layout.setSpacing(8)  # 间距8
        self.variables_scroll_layout.addStretch()  # 添加弹性空间，内容稍后添加

        scroll_area.setWidget(self.variables_scroll_content)
        variables_layout.addWidget(scroll_area)  # 占用剩余所有高度
        
        # === 第二个页面：双文本栏布局 ===
        text_page = QWidget()
        text_layout = QVBoxLayout(text_page)
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(0)
        
        # 第一个标题栏
        title_text_1 = QLabel("幕后-pre")
        title_text_1.setFixedHeight(20)
        title_text_1.setStyleSheet("""
            QLabel {
                background-color: rgba(255, 255, 255, 0.1);
                color: #FFFFFF;
                font-size: 14px;
                font-weight: bold;
                padding: 2px 8px;
                border-radius: 4px;
                border: 1px solid rgba(255, 255, 255, 0.2);
            }
        """)
        text_layout.addWidget(title_text_1)
        text_layout.addSpacing(4)  # ← 标题和内容只隔4px
        
        # 第一个可滚动文本栏
        self.text_area_1 = QTextEdit()
        self.text_area_1.setReadOnly(True)  # 默认只读，可根据需要修改
        self.text_area_1.setStyleSheet("""
            QTextEdit {
                background-color: rgba(255, 255, 255, 0.02);
                border: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: 4px;
                color: #FFFFFF;
                font-size: 12px;
                padding: 4px;
            }
            QScrollBar:vertical {
                background-color: rgba(255, 255, 255, 0.1);
                width: 8px;
                border-radius: 4px;
            }
            QScrollBar::handle:vertical {
                background-color: rgba(255, 255, 255, 0.3);
                border-radius: 4px;
                min-height: 20px;
            }
            QScrollBar::handle:vertical:hover {
                background-color: rgba(255, 255, 255, 0.5);
            }
        """)
        text_layout.addWidget(self.text_area_1)
        text_layout.addSpacing(8)  # ← 两组之间隔8px
        
        # 第二个标题栏
        title_text_2 = QLabel("幕后-post")
        title_text_2.setFixedHeight(20)
        title_text_2.setStyleSheet("""
            QLabel {
                background-color: rgba(255, 255, 255, 0.1);
                color: #FFFFFF;
                font-size: 14px;
                font-weight: bold;
                padding: 2px 8px;
                border-radius: 4px;
                border: 1px solid rgba(255, 255, 255, 0.2);
            }
        """)
        text_layout.addWidget(title_text_2)
        text_layout.addSpacing(4)  # ← 标题和内容只隔4px
        
        # 第二个可滚动文本栏
        self.text_area_2 = QTextEdit()
        self.text_area_2.setReadOnly(True)  # 默认只读，可根据需要修改
        self.text_area_2.setStyleSheet("""
            QTextEdit {
                background-color: rgba(255, 255, 255, 0.02);
                border: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: 4px;
                color: #FFFFFF;
                font-size: 12px;
                padding: 4px;
            }
            QScrollBar:vertical {
                background-color: rgba(255, 255, 255, 0.1);
                width: 8px;
                border-radius: 4px;
            }
            QScrollBar::handle:vertical {
                background-color: rgba(255, 255, 255, 0.3);
                border-radius: 4px;
                min-height: 20px;
            }
            QScrollBar::handle:vertical:hover {
                background-color: rgba(255, 255, 255, 0.5);
            }
        """)
        text_layout.addWidget(self.text_area_2)
        
        # 将两个页面添加到StackedWidget
        self.stacked_widget.addWidget(variables_page)  # 索引0：变量状态页面
        self.stacked_widget.addWidget(text_page)       # 索引1：双文本栏页面
        
        # 默认显示变量状态页面
        self.stacked_widget.setCurrentIndex(0)
        
        # 将StackedWidget添加到右侧布局（占用剩余所有高度）
        right_layout.addWidget(self.stacked_widget)

        # 添加到主布局
        main_layout.addWidget(left_frame)  # 左侧自适应
        main_layout.addWidget(separator_main)   # 分割线
        main_layout.addWidget(right_widget)  # 右侧固定宽度

    def switch_to_idle_state(self):
        """将按钮切换回发送模式"""
        # 功能：切换界面到空闲模式并刷新控件可用性
        try:
            # print("切换至空闲模式：开始")  # 调试：入口日志
            self.send_button.setIcon(QIcon(get_asset_path("assets/send.png")))
            self.send_button.setStyleSheet("""
                QToolButton {
                    background-color: rgba(0, 122, 255, 0.45);
                    border: 1px solid rgba(0, 122, 255, 0.3);
                    padding: 8px 16px;
                    min-height: 32px;
                }
                QToolButton:hover {
                    background-color: rgba(0, 122, 255, 0.25);
                    border: 1px solid rgba(0, 122, 255, 0.4);
                }
                QToolButton:pressed {
                    background-color: rgba(0, 122, 255, 0.1);
                }
            """)
            self.stacked_widget.setCurrentIndex(0)
            
            # 清空幕后区内容
            self.text_area_1.clear()  # 清空幕后-pre区域
            self.text_area_2.clear()  # 清空幕后-post区域
            
            # 检查并更新状态
            self.statu_check()
            # print(f"切换到空闲模式后状态：{self.statu}")  # 调试：确认状态值
            
            # 根据状态设置按钮可用性
            if self.statu == "send_done":
                # send_done下，只有reroll、reroll-pre、delete可用
                self.send_button.setEnabled(False)
                self.reroll_button.setEnabled(True)
                self.reroll_pre_button.setEnabled(True)
                self.reroll_create_button.setEnabled(False)
                self.reroll_post_button.setEnabled(False)
                self.delete_button.setEnabled(True)
                
            elif self.statu == "pre_done":
                # pre_done，只有reroll、reroll-pre、reroll-create、delete可用
                self.send_button.setEnabled(False)
                self.reroll_button.setEnabled(True)
                self.reroll_pre_button.setEnabled(True)
                self.reroll_create_button.setEnabled(True)
                self.reroll_post_button.setEnabled(False)
                self.delete_button.setEnabled(True)
                
            elif self.statu == "create_done":
                # create_done，只有reroll、reroll-pre、reroll-create、reroll-post、delete可用
                self.send_button.setEnabled(False)
                self.reroll_button.setEnabled(True)
                self.reroll_pre_button.setEnabled(True)
                self.reroll_create_button.setEnabled(True)
                self.reroll_post_button.setEnabled(True)
                self.delete_button.setEnabled(True)
                
            elif self.statu == "post_done":
                # post_done，全可用
                self.send_button.setEnabled(True)
                self.reroll_button.setEnabled(True)
                self.reroll_pre_button.setEnabled(True)
                self.reroll_create_button.setEnabled(True)
                self.reroll_post_button.setEnabled(True)
                self.delete_button.setEnabled(True)

            elif self.statu == "init":
                # init，全可用，仅可send
                self.send_button.setEnabled(True)
                self.reroll_button.setEnabled(False)
                self.reroll_pre_button.setEnabled(False)
                self.reroll_create_button.setEnabled(False)
                self.reroll_post_button.setEnabled(False)
                self.delete_button.setEnabled(False)
                
            else:
                # 默认情况，全部启用
                self.send_button.setEnabled(False)
                self.reroll_button.setEnabled(False)
                self.reroll_pre_button.setEnabled(False)
                self.reroll_create_button.setEnabled(False)
                self.reroll_post_button.setEnabled(False)
                self.delete_button.setEnabled(False)

            # print("空闲模式控件状态更新完成")  # 调试：确认按钮可用性已更新
        except Exception as e:
            self._on_error_occurred(
                f"切换到空闲模式失败：更新界面控件状态时发生异常。可能原因：控件未初始化或资源路径无效；期望值：所有控件为有效实例、资源文件存在。错误详情：{e}"
            )

    def switch_to_running_state(self):
        """将发送按钮切换为暂停模式"""
        # 功能：切换界面到运行模式并禁用非必要按钮
        try:
            # print("切换至运行模式：开始")  # 调试：入口日志
            self.statu = "running"
            self.send_button.setIcon(QIcon(get_asset_path("assets/pause.png")))
            self.send_button.setStyleSheet("""
                QToolButton {
                    background-color: rgba(255, 165, 0, 0.45);
                    border: 1px solid rgba(255, 165, 0, 0.3);
                    padding: 8px 16px;
                    min-height: 32px;
                }
                QToolButton:hover {
                    background-color: rgba(255, 165, 0, 0.25);
                    border: 1px solid rgba(255, 165, 0, 0.4);
                }
                QToolButton:pressed {
                    background-color: rgba(255, 165, 0, 0.1);
                }
            """)
            self.stacked_widget.setCurrentIndex(1)
            
            # running状态下，只有pause(send)按钮可用，其他全部禁用
            self.send_button.setEnabled(True)  # pause按钮保持可用
            self.reroll_button.setEnabled(False)
            self.reroll_pre_button.setEnabled(False)
            self.reroll_create_button.setEnabled(False)
            self.reroll_post_button.setEnabled(False)
            self.delete_button.setEnabled(False)
            # print("运行模式控件状态更新完成")  # 调试：确认按钮禁用状态
            return
        except Exception as e:
            self._on_error_occurred(
                f"切换到运行模式失败：更新界面控件状态时发生异常。可能原因：控件未初始化或资源路径无效；期望值：所有控件为有效实例、资源文件存在。错误详情：{e}"
            )
    
    def send_message(self):
        """发送消息的处理函数 - 修改为支持流式输出"""
        # 功能：读取输入并以流式方式触发消息处理与界面更新
        try:
            # 1、获取文本输入框的内容
            input_content = self.text_input.toPlainText().strip()
            # print(f"读取到用户输入，长度：{len(input_content)}")  # 调试：输入长度
            
            # 检查消息是否为空
            if not input_content:
                # print("发送消息：输入为空，跳过发送")  # 调试：输入校验失败
                return  # 如果消息为空，不执行任何操作
            
            # 2、将用户消息添加到聊天区
            self.add_message(input_content, "user")
            # 调整：清空输入区
            self.text_input.clear()
            # print("用户消息已添加并清空输入框")  # 调试：确认界面状态
            
            # 3、创建空的AI消息容器，准备接收流式内容
            self._create_streaming_ai_message()
            # print("已创建AI消息容器（流式）")  # 调试：确认容器创建
            
            # 4、切换按钮为运行模式
            self.switch_to_running_state()
            # 强制刷新界面以确保切换立即生效
            self.stacked_widget.repaint()
            self.repaint()
            # print("已切换到运行模式并刷新界面")  # 调试：确认UI刷新
            
            # 5、向命令队列发送命令
            command = ("send_command", input_content)
            self.worker_command_queue.put(command)
            # print("已将发送命令加入队列")  # 调试：确认命令入队
            
            # 6、焦点设置为输入区
            self.text_input.setFocus()
            # print("已将焦点设置回输入框")  # 调试：确认焦点
            # 无条件将聊天区滚动至最下方，确保最新消息可见
            sb = self.message_area.verticalScrollBar()
            sb.setValue(sb.maximum())
            QTimer.singleShot(0, lambda: self.message_area.verticalScrollBar().setValue(
                self.message_area.verticalScrollBar().maximum()
            ))
        except Exception as e:
            self._on_error_occurred(
                f"发送消息失败：组织流式输出或更新界面时发生异常。可能原因：输入控件/队列未初始化或消息容器创建失败；期望值：有效的文本输入控件、命令队列与消息容器。错误详情：{e}"
            )

    def handle_button_click(self):
        """处理按钮点击事件 - 根据当前状态决定是发送还是暂停"""
        # 功能：根据当前状态决定执行暂停或发送
        try:
            # print(f"按钮点击，当前状态：{self.statu}")  # 调试：记录当前状态
            if self.statu == "running":
                # 当前正在流式传输，执行暂停操作
                self.processor_worker.stop_stream()
                # print("已请求停止流式传输")  # 调试：确认停止请求
            else:
                # 当前未在流式传输，执行发送操作
                self.send_message()
                # print("已触发发送操作")  # 调试：确认发送路径
        except Exception as e:
            self._on_error_occurred(
                f"处理按钮点击失败：触发暂停或发送时发生异常。可能原因：处理器或控件未初始化；期望值：有效的处理器与界面控件。错误详情：{e}"
            )

    def _on_process_stopped(self):
        """处理流式传输被停止
        - 读取 config/data/data.json，获取最后一条消息
        - 若最后一条不是 AI（speaker != 'Assistant'），抛错
        - 若 reasoning 为空：沿用旧逻辑，正文区末尾追加“已停止生成”
        - 若 reasoning 不为空：清空当前思考区和正文区，填入 reasoning 与 content
        - 最后切回空闲模式
        """
        # 功能：在停止流式传输后根据最后一条AI消息的内容，追加停止标记或回填最新 reasoning/content
        try:
            # 读取最新数据（相对 config/ 目录）
            raw_json = global_io_manager.read_json("data/data.json")
            data_obj = json.loads(raw_json)
            if not isinstance(data_obj, dict) or not data_obj:
                raise ValueError("数据集为空或格式错误，无法读取最后一条消息")

            # 取最后一条记录（键为数字字符串）
            try:
                last_key = str(max(int(k) for k in data_obj.keys()))
            except Exception:
                raise ValueError("数据集键格式异常，无法确定最后一条消息")

            last_record = data_obj.get(last_key, {})
            speaker = last_record.get("speaker", "")
            if speaker != "Assistant":
                raise ValueError("最后一条消息不是AI消息，停止流程显示逻辑不适用")

            reasoning = last_record.get("reasoning", "") or ""
            content = last_record.get("content", "") or ""

            if not reasoning.strip():
                # 原有逻辑：追加“已停止生成”
                if self.current_ai_content_widget:
                    stop_message = "已停止生成"
                    stop_html = f'<br><span style="font-size: 10px; color: #000000; font-style: italic; text-align: right;">{stop_message}</span>'
                    # print("准备在AI内容区域插入停止标记")  # 调试：插入前状态

                    cursor = self.current_ai_content_widget.textCursor()
                    cursor.movePosition(QTextCursor.End)
                    self.current_ai_content_widget.setTextCursor(cursor)
                    self.current_ai_content_widget.insertHtml(stop_html)

                    # 调整高度以适应新内容
                    document = self.current_ai_content_widget.document()
                    height = document.size().height()
                    self.current_ai_content_widget.setFixedHeight(int(height) + 10)
                    # print(f"已插入停止标记并调整高度：{int(height) + 10}")  # 调试：确认高度调整

                    # 刷新滚动区域
                    self._refresh_scroll_area()
                    # print("滚动区域已刷新")  # 调试：确认滚动刷新

                # 切换回空闲模式
                self.switch_to_idle_state()
                return
            else:
                # 新逻辑：清空并填入 reasoning 与 content
                if hasattr(self, 'current_reasoning_widget') and self.current_reasoning_widget:
                    self.current_reasoning_widget.clear()
                    self.current_reasoning_widget.setVisible(True)
                    self.current_reasoning_widget.setPlainText(reasoning.strip())
                    # 调整思考区域高度
                    reasoning_doc = self.current_reasoning_widget.document()
                    reasoning_height = reasoning_doc.size().height()
                    self.current_reasoning_widget.setFixedHeight(int(reasoning_height) + 10)

                if self.current_ai_content_widget:
                    self.current_ai_content_widget.clear()
                    self.current_ai_content_widget.setPlainText(content.strip())
                    # 调整正文区域高度
                    content_doc = self.current_ai_content_widget.document()
                    content_height = content_doc.size().height()
                    self.current_ai_content_widget.setFixedHeight(int(content_height) + 10)

                    # 刷新滚动区域
                    self._refresh_scroll_area()

                # 切换回空闲模式
                self.switch_to_idle_state()
                return
        except Exception as e:
            self._on_error_occurred(
                f"停止处理流程失败：更新AI内容或界面状态时发生异常。错误详情：{e}"
            )

    def _on_process_finished(self, full_response):
        """流式传输完成"""
        # 功能：完成后处理并恢复空闲模式，同时刷新变量显示
        try:
            # 处理完整响应 - 复刻chat.py的后处理逻辑
            # print("完整输出开始")  # 调试：标记完整响应开始
            # print(full_response)  # 调试：输出完整响应内容
            # print("完整输出结束")  # 调试：标记完整响应结束
            
            # 切换回空闲模式
            self.switch_to_idle_state()
            # print("已切换回空闲模式（完成后）")  # 调试：确认模式切换

            # 更新变量状态
            self.update_variables_display()
            # print("变量状态已刷新")  # 调试：确认变量更新
        except Exception as e:
            self._on_error_occurred(
                f"完成处理流程失败：后处理或界面更新时发生异常。可能原因：控件未初始化或响应处理逻辑出错；期望值：有效控件与稳定的后处理逻辑。错误详情：{e}"
            )
        
    def handle_reroll_message(self):
        """处理reroll-all操作"""
        # 功能：清空当前内容（如存在）、准备容器、切至运行模式并派发预处理命令
        try:
            # 1、如果存在当前AI消息引用，清空其内容以供新信息传入
            if self.current_ai_content_widget:
                self.current_ai_content_widget.clear()
                # print("清空当前AI内容区域")  # 调试：为新内容腾空显示区域
            
            if hasattr(self, 'current_reasoning_widget') and self.current_reasoning_widget:
                self.current_reasoning_widget.clear()
                self.current_reasoning_widget.setVisible(True)  # 显示思考区域
                # print("清空当前思考内容区域")  # 调试：重置思考区域以显示新的推理
            
            # 如果没有当前引用，则创建新的AI消息容器
            if not self.current_ai_message_widget or not self.current_ai_content_widget:
                # print("当前无AI消息引用，创建新的消息容器")  # 调试：首次或引用丢失时构建容器
                self._create_streaming_ai_message()
            
            # 2、切换按钮为暂停模式，切换右侧面板到双文本栏页面
            self.switch_to_running_state()
            
            # 强制刷新界面以确保切换立即生效
            self.stacked_widget.repaint()
            self.repaint()
            # print("已切换到运行模式并刷新界面")  # 调试：确认UI刷新
            
            # 5、向命令队列发送命令
            command = ("pre_command", "")
            self.worker_command_queue.put(command)
            # print("已向队列派发 pre_command")  # 调试：确认命令入队
            
            # 6、焦点设置为输入区
            self.text_input.setFocus()
            # print("焦点已设置到输入框")  # 调试：确认焦点
        except Exception as e:
            self._on_error_occurred(
                f"reroll-all处理失败：更新消息容器或界面状态时发生异常。可能原因：内容控件未初始化或命令队列不可用；期望值：有效的内容控件、思考区域与命令队列。错误详情：{e}"
            )

    def _on_right_title_toggled(self, checked: bool):
        """
        切换右侧“角色信息”区域显示模式（图片/文本）并更新按钮标题。
        Args:
            checked (bool): True 显示文本页；False 显示图片页
        """
        # 功能：根据按钮选中状态切换右侧堆栈页与标题文字
        try:
            # print(f"右侧标题切换，checked={checked}")  # 调试：记录切换状态
            if checked:
                self.right_image_text_stack.setCurrentIndex(1)
                self.right_title_button.setText("调用监控")
            else:
                self.right_image_text_stack.setCurrentIndex(0)
                self.right_title_button.setText("角色信息")
            # print("右侧区域切换完成")  # 调试：确认索引与标题更新
        except Exception as e:
            self._on_error_occurred(
                f"右侧标题切换失败：更新堆栈页或按钮标题时发生异常。可能原因：控件未初始化；期望值：有效的堆栈与按钮控件。错误详情：{e}"
            )
    
    def reroll_pre_only(self):
        """处理reroll-前置更新按钮点击"""
        # 功能：确保容器可接收内容、切至运行模式并派发仅前置更新命令
        try:
            # 如果没有当前引用，则创建新的AI消息容器
            if not self.current_ai_message_widget or not self.current_ai_content_widget:
                # print("当前无AI消息引用，创建新的消息容器")  # 调试：首次或引用丢失时构建容器
                self._create_streaming_ai_message()
            
            # print("reroll_pre_only 按钮被点击")  # 调试：记录触发动作
            self.switch_to_running_state()
            # 向命令队列发送命令
            command = ("pre_command", "only")
            self.worker_command_queue.put(command)
            # print("已向队列派发 pre_command(only)")  # 调试：确认命令入队
        except Exception as e:
            self._on_error_occurred(
                f"reroll-pre处理失败：准备容器或派发命令时发生异常。可能原因：控件未初始化或队列不可用；期望值：有效的消息容器与命令队列。错误详情：{e}"
            )
    
    def reroll_create_only(self):
        """处理reroll-正文按钮点击"""
        # 功能：清空当前显示区域、切至运行模式并派发仅正文生成命令
        try:
            # 1、如果存在当前AI消息引用，清空其内容以供新信息传入
            self.current_ai_content_widget.clear()
            # print("清空当前AI内容区域")  # 调试：为新内容腾空显示区域
            self.current_reasoning_widget.clear()
            self.current_reasoning_widget.setVisible(True)  # 显示思考区域
            # print("清空当前思考内容区域")  # 调试：重置思考区域以显示新的推理
            # print("reroll_create_only 按钮被点击")  # 调试：记录触发动作
            
            self.switch_to_running_state()
            # 向命令队列发送命令
            command = ("create_command", "only")
            self.worker_command_queue.put(command)
            # print("已向队列派发 create_command(only)")  # 调试：确认命令入队
        except Exception as e:
            self._on_error_occurred(
                f"reroll-create处理失败：清空显示区域或派发命令时发生异常。可能原因：内容控件未初始化或队列不可用；期望值：有效的内容控件与命令队列。错误详情：{e}"
            )
    
    def reroll_post_only(self):
        """处理reroll-后置更新按钮点击"""
        # 功能：切至运行模式并派发仅后置更新命令
        try:
            # print("reroll_post_only 按钮被点击")  # 调试：记录触发动作
            self.switch_to_running_state()
            # 向命令队列发送命令
            command = ("post_command", "")
            self.worker_command_queue.put(command)
            # print("已向队列派发 post_command")  # 调试：确认命令入队
        except Exception as e:
            self._on_error_occurred(
                f"reroll-post处理失败：切换状态或派发命令时发生异常。可能原因：控件未初始化或队列不可用；期望值：有效的界面控件与命令队列。错误详情：{e}"
            )

    def handle_delete_messages(self):
        """处理删除消息按钮点击事件"""
        # 功能：弹出输入对话框，校验数量，确认后删除并刷新界面与变量
        try:
            if self.statu == "running":
                return
            
            # 通用对话框样式
            dialog_style = """
                QDialog, QMessageBox {
                    background-color: #2b2b2b;
                    color: white;
                }
                QLabel {
                    color: white;
                    font-size: 14px;
                    margin: 10px 0;
                    min-width: 300px;
                    padding: 10px;
                }
                QLineEdit {
                    background-color: #404040;
                    color: white;
                    border: 1px solid #606060;
                    padding: 8px;
                    font-size: 14px;
                    border-radius: 4px;
                }
                QLineEdit:focus {
                    border: 2px solid #0078d4;
                }
                QPushButton {
                    background-color: #404040;
                    color: white;
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
            
            # 获取删除数量
            dialog = QDialog(self)
            dialog.setWindowTitle("删除消息")
            dialog.setModal(True)
            dialog.resize(300, 150)
            dialog.setStyleSheet(dialog_style)
            
            layout = QVBoxLayout(dialog)
            layout.addWidget(QLabel("请输入要从下往上删除的消息数量："))
            
            input_field = QLineEdit()
            input_field.setText("1")
            input_field.setPlaceholderText("请输入1-100之间的数字")
            layout.addWidget(input_field)
            
            button_layout = QHBoxLayout()
            ok_button = QPushButton("确定")
            cancel_button = QPushButton("取消")
            ok_button.clicked.connect(dialog.accept)
            cancel_button.clicked.connect(dialog.reject)
            button_layout.addWidget(ok_button)
            button_layout.addWidget(cancel_button)
            layout.addLayout(button_layout)
            
            input_field.setFocus()
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            
            # 验证输入
            try:
                num_to_delete = int(input_field.text().strip())
                if not 1 <= num_to_delete <= 100:
                    warning_box = QMessageBox(self)
                    warning_box.setWindowTitle("输入错误")
                    warning_box.setText("请输入1-100之间的数字！")
                    warning_box.setIcon(QMessageBox.Icon.Warning)
                    warning_box.setStyleSheet(dialog_style)
                    warning_box.exec()
                    # print(f"输入校验失败：{num_to_delete}")  # 调试：提示范围不合法
                    self._on_error_occurred(
                        f"删除数量输入错误：期望为 1-100 的整数，实际为 {num_to_delete}。请提供有效的删除条数。"
                    )
                    return
            except ValueError:
                warning_box = QMessageBox(self)
                warning_box.setWindowTitle("输入错误")
                warning_box.setText("请输入有效的数字！")
                warning_box.setIcon(QMessageBox.Icon.Warning)
                warning_box.setStyleSheet(dialog_style)
                warning_box.exec()
                # print("输入解析失败：非数字")  # 调试：提示类型错误
                self._on_error_occurred(
                    f"删除数量格式错误：期望输入为整数数字字符串，收到内容为 '{input_field.text().strip()}'; 请输入 1-100 的整数。"
                )
                return
            
            # 确认删除
            confirm_box = QMessageBox(self)
            confirm_box.setWindowTitle("确认删除")
            confirm_box.setText(f"确定要删除最后 {num_to_delete} 条消息吗？此操作不可撤销。")
            confirm_box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            confirm_box.setDefaultButton(QMessageBox.StandardButton.No)
            confirm_box.setStyleSheet(dialog_style)
            
            if confirm_box.exec() != QMessageBox.StandardButton.Yes:
                return
            
            # 执行删除
            try:
                # 获取当前消息数量（排除最后的stretch）
                total_messages = self.message_layout.count() - 1
                if total_messages <= 0:
                    info_box = QMessageBox(self)
                    info_box.setWindowTitle("提示")
                    info_box.setText("没有可删除的消息。")
                    info_box.setIcon(QMessageBox.Icon.Information)
                    info_box.setStyleSheet(dialog_style)
                    info_box.exec()
                    # print("没有可删除的消息")  # 调试：列表为空
                    return
                
                # 计算实际删除数量
                actual_delete_count = min(num_to_delete, total_messages)
                # print(f"将删除消息数量：{actual_delete_count}")  # 调试：确认最终删除数量
                
                # 从GUI中删除消息组件（从下往上删除）
                deleted_widgets = []
                for i in range(actual_delete_count):
                    # 获取倒数第二个item（最后一个是stretch）
                    item_index = self.message_layout.count() - 2
                    if item_index >= 0:
                        item = self.message_layout.takeAt(item_index)
                        if item and item.widget():
                            widget = item.widget()
                            deleted_widgets.append(widget)
                            widget.setParent(None)  # 从界面中移除
                
                # 调用ProcessorWorker删除数据文件中的消息
                self.processor_worker.delete_messages(actual_delete_count)
                # print("已删除数据文件中的消息")  # 调试：确认数据层删除
                
                # 重新绑定到最新的AI消息
                self._rebind_to_latest_ai_message()
                
                # 刷新界面和变量显示
                self._refresh_scroll_area()
                self.update_variables_display()
                
                # 重新检查状态并更新按钮状态
                self.switch_to_idle_state()
                
                # 显示成功消息
                msg_box = QMessageBox(self)
                msg_box.setWindowTitle("删除成功")
                msg_box.setText(f"已成功删除 {actual_delete_count} 条消息。")
                msg_box.setStyleSheet(dialog_style)
                msg_box.exec()
                # print("删除操作已完成")  # 调试：确认用户提示
            except Exception as e:
                # print(f"删除过程出现异常：{e}")  # 调试：记录异常详情
                error_box = QMessageBox(self)
                error_box.setWindowTitle("删除失败")
                error_box.setText(f"删除消息时发生错误：{str(e)}")
                error_box.setIcon(QMessageBox.Icon.Critical)
                error_box.setStyleSheet(dialog_style)
                error_box.exec()
                self._on_error_occurred(
                    f"删除消息失败：执行删除或界面刷新时发生异常。可能原因：布局项无效、处理器未初始化或消息不存在；期望值：有效的消息布局与处理器实例。错误详情：{e}"
                )
        except Exception as e:
            self._on_error_occurred(
                f"删除消息流程失败：打开对话或读取输入时发生异常。可能原因：控件未初始化或样式设置错误；期望值：有效的对话框控件与样式。错误详情：{e}"
            )
    
    def _on_pre_judge_received(self, pre_judge_content):
        """
        处理 pre-judge 信号，将内容显示在第一个文本栏。
        - 使用文档光标在末尾插入，避免改变可视光标导致视图跳动；
        - 仅在用户原本接近底部时自动滚动到底。
        Args:
            pre_judge_content (str): pre-judge 返回的字符串内容
        """
        # 功能：将 pre-judge 内容追加到第一个文本栏，保持用户滚动位置
        try:
            # print("pre-judge 接收：开始处理")  # 调试：入口日志
            if hasattr(self, 'text_area_1'):
                sb = self.text_area_1.verticalScrollBar()
                was_near_bottom = (sb.maximum() - sb.value()) <= 20

                # 文档末尾插入，不设置控件光标
                doc_cursor = QTextCursor(self.text_area_1.document())
                doc_cursor.movePosition(QTextCursor.End)
                doc_cursor.insertText(pre_judge_content)
                # print(f"pre_judge_content 长度：{len(pre_judge_content)}")  # 调试：内容长度

                # 保持到底仅在接近底部时
                if was_near_bottom:
                    sb.setValue(sb.maximum())
        except Exception as e:
            self._on_error_occurred(
                f"pre-judge 显示失败：在文本栏1追加内容时发生异常。可能原因：控件未初始化或内容类型错误；期望值：已创建的 QTextEdit 与 str 类型内容。错误详情：{e}"
            )
    
    def _on_create_reasoning_received(self, reasoning_content):
        """接收到思考内容"""
        # 功能：将推理内容追加到思考区域，并在需要时展开与自适应高度
        try:
            if hasattr(self, 'current_reasoning_widget') and self.current_reasoning_widget:
                # 将思考内容追加到思考区域
                # 记录追加前滚动位置是否接近底部（≤20px）
                sb = self.current_reasoning_widget.verticalScrollBar()
                was_near_bottom = (sb.maximum() - sb.value()) <= 20

                # 使用“文档光标”在末尾插入，避免改变可视光标位置
                doc_cursor = QTextCursor(self.current_reasoning_widget.document())
                doc_cursor.movePosition(QTextCursor.End)
                doc_cursor.insertText(reasoning_content)
                # print(f"接收到思考内容长度：{len(reasoning_content)}")  # 调试：内容长度

                # 调整思考区域高度
                document = self.current_reasoning_widget.document()
                height = min(document.size().height() + 20, 200)  # 限制最大高度为200px
                self.current_reasoning_widget.setFixedHeight(int(height))

                # 若原本接近底部，保持到底；否则尊重用户位置
                if was_near_bottom:
                    sb.setValue(sb.maximum())

                # 如果有思考内容，自动展开思考区域
                if hasattr(self, 'reasoning_toggle_button') and not self.reasoning_toggle_button.isChecked():
                    self.reasoning_toggle_button.setChecked(True)

                # 刷新滚动区域（外层滚动区只在“粘底”时自动到底）
                QTimer.singleShot(0, self._refresh_scroll_area)
        except Exception as e:
            self._on_error_occurred(
                f"思考内容显示失败：在推理区域追加或调整高度时发生异常。可能原因：控件未初始化或内容类型错误；期望值：有效的 QTextEdit 与 str 类型内容。错误详情：{e}"
            )
    
    def _on_create_content_received(self, content):
        """接收到新的文本块"""
        # 功能：将正文内容追加到 AI 内容区域，并自适应高度与滚动
        try:
            if self.current_ai_content_widget:
                # 使用“文档光标”在末尾插入，避免改变可视光标位置
                doc_cursor = QTextCursor(self.current_ai_content_widget.document())
                doc_cursor.movePosition(QTextCursor.End)
                doc_cursor.insertText(content)
                # print(f"接收到正文块长度：{len(content)}")  # 调试：内容长度

                # 调整QTextEdit高度以适应内容
                document = self.current_ai_content_widget.document()
                height = document.size().height()
                self.current_ai_content_widget.setFixedHeight(int(height) + 10)

                # 刷新滚动区域，保持在底部（仅在“粘底”状态时）
                QTimer.singleShot(0, self._refresh_scroll_area)
        except Exception as e:
            self._on_error_occurred(
                f"正文内容显示失败：在 AI 内容区域追加或调整高度时发生异常。可能原因：控件未初始化或内容类型错误；期望值：有效的 QTextEdit 与 str 类型内容。错误详情：{e}"
            )
    
    def _on_post_judge_received(self, post_judge_content):
        """
        处理 post-judge 信号，将内容显示在第二个文本栏。
        - 使用文档光标在末尾插入，避免改变可视光标导致视图跳动；
        - 仅在用户原本接近底部时自动滚动到底。
        Args:
            post_judge_content (str): post-judge 返回的字符串内容
        """
        # 功能：将 post-judge 内容追加到第二个文本栏，保持用户滚动位置
        try:
            # print("post-judge 接收：开始处理")  # 调试：入口日志
            if hasattr(self, 'text_area_2'):
                sb = self.text_area_2.verticalScrollBar()
                was_near_bottom = (sb.maximum() - sb.value()) <= 20

                # 文档末尾插入，不设置控件光标
                doc_cursor = QTextCursor(self.text_area_2.document())
                doc_cursor.movePosition(QTextCursor.End)
                doc_cursor.insertText(post_judge_content)
                # print(f"post_judge_content 长度：{len(post_judge_content)}")  # 调试：内容长度

                # 保持到底仅在接近底部时
                if was_near_bottom:
                    sb.setValue(sb.maximum())
        except Exception as e:
            self._on_error_occurred(
                f"post-judge 显示失败：在文本栏2追加内容时发生异常。可能原因：控件未初始化或内容类型错误；期望值：已创建的 QTextEdit 与 str 类型内容。错误详情：{e}"
            )
    
    def _on_information_received(self, info: str):
        """
        处理任意阶段的信息尾部（pre/create/post）
        - 空字符串不处理；
        - 非空追加到右侧滚动文本页（right_text_area）；
        - 使用文档光标在末尾插入，避免控件光标变动导致视图错位；
        - 允许上滚，仅在接近底部时自动保持到底；
        Args:
            info (str): 信息尾部文本
        """
        # 功能：将信息尾部追加到右侧文本页，保持用户滚动位置
        try:
            if not isinstance(info, str) or info.strip() == "":
                # print("信息尾部为空或类型非字符串，忽略追加")  # 调试：输入为空或类型错误
                return
            if hasattr(self, 'right_text_area'):
                sb = self.right_text_area.verticalScrollBar()
                was_near_bottom = (sb.maximum() - sb.value()) <= 20

                # 文档末尾插入，不设置控件光标
                doc_cursor = QTextCursor(self.right_text_area.document())
                doc_cursor.movePosition(QTextCursor.End)
                doc_cursor.insertText(info)
                doc_cursor.insertText("\n")
                # print(f"信息尾部追加长度：{len(info)}")  # 调试：内容长度

                # 保持到底仅在接近底部时
                if was_near_bottom:
                    sb.setValue(sb.maximum())
        except Exception as e:
            self._on_error_occurred(
                f"信息尾部显示失败：在右侧文本页追加或滚动时发生异常。可能原因：控件未初始化或内容类型错误；期望值：有效的 QTextEdit 与 str 类型内容。错误详情：{e}"
            )

    def show_ephemeral_error(self, message: str) -> None:
        """
        zh: 显示一次性错误弹窗，不记录到任何控件或历史。
        参数：
        - message (str): 要显示的错误信息字符串（可包含 traceback）
        返回：
        - None
        错误：
        - TypeError：当 message 不是字符串时抛出，说明当前类型与期望不符
        
        en: Show a one-off error dialog that does not persist or record.
        Args:
        - message (str): Error message to display (may include traceback)
        Returns:
        - None
        Raises:
        - TypeError: If message is not a string, indicating type mismatch
        """
        # 功能：以黑底白字弹窗显示错误摘要，并提供可滚动文本区完整呈现错误详情
        if not isinstance(message, str):
            raise TypeError(
                f"参数 message 必须为 str 类型，当前为 {type(message).__name__}；期望：错误信息字符串。"
            )

        # 规范化并兜底空消息
        raw = (message or "").strip()
        if not raw:
            raw = (
                "发生错误，但未提供任何错误信息；原因：错误消息为空或仅空白；"
                "期望：传入清晰、具体的错误说明文本。"
            )
        # 根据是否包含 traceback 构造摘要与详细文本
        has_traceback = "Traceback" in raw
        if has_traceback:
            lines = raw.splitlines()
            summary = lines[0] if lines else "发生错误（详情请展开查看）"
            detail = raw
        else:
            summary = raw
            detail = raw  # 始终在滚动区完整展示当前错误信息

        # print(f"显示错误弹窗：{summary}")  # 调试：记录最终展示的错误摘要

        # 参考删除消息弹窗样式，统一黑底白字
        dialog_style = """
            QDialog {
                background-color: #2b2b2b;
                color: #ffffff;
            }
            QLabel {
                color: #ffffff;
                font-size: 14px;
                margin: 8px 0;
                padding: 0;
            }
            QTextEdit {
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

        # 自定义弹窗，带可滚动文本区
        error_dialog = QDialog(self)
        error_dialog.setWindowTitle("错误")
        error_dialog.setModal(True)
        error_dialog.resize(640, 420)
        error_dialog.setStyleSheet(dialog_style)

        layout = QVBoxLayout(error_dialog)
        summary_label = QLabel(summary)
        summary_label.setWordWrap(True)
        layout.addWidget(summary_label)

        text_area = QTextEdit()
        text_area.setReadOnly(True)
        text_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        text_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        text_area.setText(detail)
        layout.addWidget(text_area)

        buttons_layout = QHBoxLayout()
        ok_button = QPushButton("确定")
        ok_button.clicked.connect(error_dialog.accept)
        buttons_layout.addStretch(1)
        buttons_layout.addWidget(ok_button)
        layout.addLayout(buttons_layout)

        error_dialog.exec()
    
    def _on_error_occurred(self, error_message):
        """统一错误处理入口
        - 接收任意错误信息，规范化为可读字符串
        - 若仅为“发生错误:”或冒号结尾无实质内容，补充明确说明
        - 若包含 traceback，交由弹窗的详细信息显示
        """
        try:
            msg = "" if error_message is None else str(error_message)
        except Exception:
            msg = ""

        display_msg = msg.strip()
        if not display_msg:
            display_msg = (
                "发生未知错误（未提供错误详情）；原因：错误消息为空或无法转为字符串；"
                "期望：提供清晰、具体的错误说明文本以便排查。"
            )
        if display_msg.endswith(":") or display_msg in {"发生错误", "错误", "Error", "ERROR"}:
            display_msg = (
                display_msg
                + " 未提供错误详情；原因：异常消息为空或未格式化；"
                "期望：包含异常类型名与详细说明（例如 ValueError: 参数 x 不合法）。"
            )

        # print(f"错误上报：{display_msg}")  # 调试：记录统一错误入口的消息
        self.show_ephemeral_error(display_msg)

        self.switch_to_idle_state()
    
    
    
    def _create_message_widget(self, content, message_type, sender_name):
        """创建消息组件 - 简化版本，只支持用户消息和历史AI消息"""
        # 功能：根据消息类型创建基础消息框架并设置样式与尺寸策略
        try:
            # print(f"创建消息组件：type={message_type}")  # 调试：记录消息类型
            message_widget = QFrame()
            
            # 添加消息类型属性，用于后续识别
            message_widget.message_type = message_type

            # 设置尺寸策略，确保能够根据内容自适应高度
            message_widget.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.MinimumExpanding)
            
            # 计算最大宽度
            max_width = 1024
            message_widget.setMaximumWidth(max_width)
            
            # 根据消息类型设置不同的宽度策略
            if message_type == "ai":
                # AI消息设置固定宽度为最大宽度，确保充分利用空间
                message_widget.setFixedWidth(max_width)
            else:
                # 用户消息保持内容自适应宽度
                message_widget.setMinimumWidth(0)
            
            # 确保高度能够自适应内容
            message_widget.setMinimumHeight(0)
            
            # 根据消息类型设置样式
            if message_type == "user":
                message_widget.setStyleSheet("""
                    QFrame {
                        background-color: rgba(100, 150, 255, 0.15);
                        border: 1px solid rgba(100, 150, 255, 0.3);
                        border-radius: 8px;
                        margin: 4px;
                        padding: 8px;
                    }
                """)
            elif message_type == "ai":
                # AI消息样式（用于历史记录加载）
                message_widget.setStyleSheet("""
                    QFrame {
                        background-color: rgba(150, 255, 150, 0.15);
                        border: 1px solid rgba(150, 255, 150, 0.3);
                        border-radius: 8px;
                        margin: 4px;
                        padding: 8px;
                    }
                """)
            
            return message_widget
        except Exception as e:
            self._on_error_occurred(
                f"消息组件创建失败：设置尺寸或样式时发生异常。可能原因：参数 message_type 无效或控件初始化失败；期望值：message_type 为 'user' 或 'ai'，控件能正常创建。错误详情：{e}"
            )
    
    def _create_ai_message_widget(self):
        """创建标准的AI消息组件，支持思考内容和正式回复
        - 内联整合了折叠/展开时的高度控制，以及内容变化时的高度自适应
        - 空内容时固定最小高度 40；非空内容按文档高度计算，最大不超过 200
        """
        # 功能：构建包含思考内容与正式回复的 AI 消息组件
        try:
            # 设置固定宽度
            FIXED_WIDTH = 1024  # 固定宽度
            
            # 创建消息组件
            ai_message_widget = self._create_message_widget("", "ai", None)
            
            # 设置消息组件固定宽度
            ai_message_widget.setFixedWidth(FIXED_WIDTH)
            
            # 为消息组件创建垂直布局
            message_layout = QVBoxLayout(ai_message_widget)
            message_layout.setContentsMargins(0, 0, 0, 0)
            message_layout.setSpacing(2)
            
            # 创建发送者标签
            sender_label = QLabel("AI助手")
            sender_label.setAlignment(Qt.AlignmentFlag.AlignLeft)
            sender_label.setStyleSheet("""
                QLabel {
                    background-color: transparent;
                    color: rgba(255, 255, 255, 0.8);
                    font-size: 12px;
                    font-weight: bold;
                    margin: 0px;
                    padding: 0px;
                    border: none;
                }
            """)
            message_layout.addWidget(sender_label)
            
            # 创建可折叠的思考内容区域
            # 主容器
            reasoning_container = QWidget()
            reasoning_container.setFixedWidth(FIXED_WIDTH - 20)
            container_layout = QVBoxLayout(reasoning_container)
            container_layout.setContentsMargins(0, 0, 0, 0)
            container_layout.setSpacing(0)
            
            # 标题按钮（可点击折叠/展开）
            self.reasoning_toggle_button = QPushButton("💭 思考过程")
            self.reasoning_toggle_button.setCheckable(True)
            self.reasoning_toggle_button.setChecked(False)  # 默认折叠
            self.reasoning_toggle_button.setStyleSheet("""
                QPushButton {
                    background-color: rgba(255, 255, 255, 0.1);
                    color: rgba(255, 255, 255, 0.8);
                    border: 1px solid rgba(255, 255, 255, 0.2);
                    border-radius: 4px;
                    padding: 4px 8px;
                    font-size: 14px;
                    text-align: left;
                }
                QPushButton:hover {
                    background-color: rgba(255, 255, 255, 0.15);
                }
                QPushButton:checked {
                    background-color: rgba(255, 255, 255, 0.2);
                }
            """)
            
            # 内容区域（思考内容）
            reasoning_widget = QTextEdit()
            reasoning_widget.setReadOnly(True)
            reasoning_widget.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            reasoning_widget.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            reasoning_widget.setMaximumHeight(200)  # 限制最大高度
            reasoning_widget.setVisible(False)  # 默认隐藏
            reasoning_widget.setStyleSheet("""
                QTextEdit {
                    background-color: rgba(0, 0, 0, 0.2);
                    color: rgba(255, 255, 255, 0.7);
                    font-size: 14px;
                    font-family: 'Consolas', 'Monaco', monospace;
                    border: 1px solid rgba(255, 255, 255, 0.1);
                    border-radius: 4px;
                    padding: 8px;
                    margin: 0px;
                }
            """)
            # 统一推理区域宽度到容器宽度，避免宽度异常
            reasoning_widget.setFixedWidth(FIXED_WIDTH - 20)
            # 水平/垂直固定（水平与容器一致，垂直由下方逻辑控制）
            reasoning_widget.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

            # 折叠/展开事件：进入时自适应高度；空内容显示最小高度
            self.reasoning_toggle_button.toggled.connect(
                lambda checked: (
                    reasoning_widget.setVisible(checked),
                    (
                        # 空内容：最小高度
                        (reasoning_widget.setFixedHeight(40), reasoning_widget.updateGeometry())
                        if not reasoning_widget.toPlainText().strip()
                        else (
                            # 非空内容：按文档高度计算（使用稳定的文本宽度）
                            reasoning_widget.document().setTextWidth((FIXED_WIDTH - 20) - 10),
                            reasoning_widget.setFixedHeight(
                                max(40, min(int(
                                    reasoning_widget.document().size().height()
                                    + reasoning_widget.document().documentMargin() * 2
                                ), 200))
                            ),
                            reasoning_widget.updateGeometry()
                        )
                    ) if checked else None
                )
            )

            # 内容变化时自适应高度（仅在可见时调整，避免折叠状态抖动）
            reasoning_widget.textChanged.connect(
                lambda: None if not reasoning_widget.isVisible() else (
                    (reasoning_widget.setFixedHeight(40), reasoning_widget.updateGeometry())
                    if not reasoning_widget.toPlainText().strip()
                    else (
                        reasoning_widget.document().setTextWidth((FIXED_WIDTH - 20) - 10),
                        reasoning_widget.setFixedHeight(
                            max(40, min(int(
                                reasoning_widget.document().size().height()
                                + reasoning_widget.document().documentMargin() * 2
                            ), 200))
                        ),
                        reasoning_widget.updateGeometry()
                    )
                )
            )
            
            container_layout.addWidget(self.reasoning_toggle_button)
            container_layout.addWidget(reasoning_widget)
            
            message_layout.addWidget(reasoning_container)
            
            # 创建QTextEdit用于AI正式回复内容
            ai_content_widget = QTextEdit()
            ai_content_widget.setReadOnly(True)  # 只读模式
            ai_content_widget.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            ai_content_widget.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            ai_content_widget.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.MinimumExpanding)
            
            # 设置QTextEdit固定宽度（减去padding和margin）
            content_width = FIXED_WIDTH - 20  # 减去padding
            ai_content_widget.setFixedWidth(content_width)
            
            # 设置文档的固定宽度
            ai_content_widget.document().setTextWidth(content_width - 10)
            
            # 设置QTextEdit样式
            ai_content_widget.setStyleSheet("""
                QTextEdit {
                    background-color: transparent;
                    color: white;
                    font-size: 14px;
                    border: none;
                    margin: 0px;
                    padding: 0px;
                    width: %dpx;
                }
            """ % content_width)
            
            # 设置文档样式
            ai_content_widget.document().setDefaultStyleSheet("""
                body {
                    margin: 0;
                    padding: 0;
                    line-height: 1.4;
                    font-family: inherit;
                    width: %dpx;
                    word-wrap: break-word;
                    overflow-wrap: break-word;
                }
            """ % (content_width - 10))
            
            message_layout.addWidget(ai_content_widget)
            
            # print("AI消息组件创建完成")  # 调试：组件创建结束
            # 返回组件和子组件的引用
            return ai_message_widget, reasoning_widget, ai_content_widget
        except Exception as e:
            self._on_error_occurred(
                f"AI消息组件创建失败：构建子组件或绑定事件时发生异常。可能原因：控件初始化失败或样式/宽度设置不合法；期望值：成功实例化的控件与有效参数。错误详情：{e}"
            )

    def _create_streaming_ai_message(self):
        """创建用于流式输出的AI消息容器，支持思考内容和正式回复"""
        # 功能：创建并插入流式AI消息组件，然后刷新滚动区域；异常统一通过 _on_error_occurred 显示
        try:
            # print("开始创建流式AI消息组件")  # 调试：跟踪组件创建流程
            self.current_ai_message_widget, self.current_reasoning_widget, self.current_ai_content_widget = self._create_ai_message_widget()
            # print("AI消息组件已创建，准备插入布局")  # 调试：组件创建完成

            self.message_layout.insertWidget(self.message_layout.count() - 1, self.current_ai_message_widget)
            # print("AI消息组件插入布局完成")  # 调试：布局插入成功

            self._refresh_scroll_area()
            # print("滚动区域刷新完成")  # 调试：滚动区已更新
        except AttributeError as e:
            self._on_error_occurred(
                f"创建流式AI消息组件失败：缺少必要属性或方法。原因：{type(e).__name__}，详情：{e}。"
                f"期望：存在可调用的 _create_ai_message_widget() 方法与有效的 message_layout。"
            )
        except Exception as e:
            self._on_error_occurred(
                f"创建流式AI消息组件时发生未预期错误：{type(e).__name__}：{e}。"
                f"期望：有效的消息组件与布局状态。"
            )
    
    def _populate_message_content(self, message_widget, content, message_type, sender_name):
        """填充消息内容到组件 - 支持AI消息的思考区和内容区"""
        # 功能：按类型填充消息组件内容；异常统一通过 _on_error_occurred 显示
        try:
            # print(f"填充消息内容开始，类型: {message_type}, 发送者: {sender_name}")  # 调试：记录入口参数
            if message_type == "ai":
                # AI消息：填充到思考区和内容区
                if hasattr(message_widget, 'reasoning_widget') and hasattr(message_widget, 'ai_content_widget'):
                    reasoning_widget = message_widget.reasoning_widget
                    ai_content_widget = message_widget.ai_content_widget

                    # print(f"AI内容类型: {type(content)}")  # 调试：了解内容格式（tuple或str）
                    # content现在是一个元组 (reasoning, main_content)
                    if isinstance(content, tuple) and len(content) == 2:
                        reasoning_content, main_content = content

                        # 填充思考区域（如果有思考内容）
                        if reasoning_content:
                            reasoning_widget.setPlainText(reasoning_content)
                            # 调整思考区域高度
                            reasoning_doc = reasoning_widget.document()
                            reasoning_height = reasoning_doc.size().height()
                            reasoning_widget.setFixedHeight(int(reasoning_height) + 10)
                            # print("AI思考区域填充并调整高度完成")  # 调试：思考区更新

                        # 填充主要内容区域
                        ai_content_widget.setPlainText(main_content)
                        # print("AI主要内容区域填充完成")  # 调试：内容区更新
                    else:
                        # 兼容旧格式，将所有内容放入主要回复区域
                        ai_content_widget.setPlainText(str(content))
                        # print("采用旧格式填充AI内容")  # 调试：旧格式兼容路径

                    # 调整内容区域高度
                    def adjust_height():
                        document = ai_content_widget.document()
                        height = document.size().height()
                        ai_content_widget.setFixedHeight(int(height) + 10)
                        message_widget.updateGeometry()
                        self.message_container.updateGeometry()

                    QTimer.singleShot(10, adjust_height)
                    # print("已安排内容高度调整")  # 调试：UI更新排队
            else:
                # 用户消息：使用原有逻辑
                # 为消息组件创建垂直布局
                message_layout = QVBoxLayout(message_widget)
                message_layout.setContentsMargins(0, 0, 0, 0)
                message_layout.setSpacing(2)

                # 创建发送者标签（如果需要）
                if sender_name:
                    sender_label = QLabel(sender_name)
                    sender_label.setAlignment(Qt.AlignmentFlag.AlignLeft)
                    sender_label.setStyleSheet("""
                        QLabel {
                            background-color: transparent;
                            color: rgba(255, 255, 255, 0.8);
                            font-size: 12px;
                            font-weight: bold;
                            margin: 0px;
                            padding: 0px;
                            border: none;
                        }
                    """)
                    message_layout.addWidget(sender_label)
                    # print(f"已添加发送者标签: {sender_name}")  # 调试：用户消息显示发送者

                # 用户消息使用QLabel（轻量级，适合短文本）
                content_widget = QLabel(content)
                content_widget.setWordWrap(True)
                content_widget.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.MinimumExpanding)
                content_widget.setMaximumHeight(16777215)
                content_widget.setMinimumHeight(0)
                content_widget.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
                content_widget.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
                content_widget.setStyleSheet("""
                    QLabel {
                        background-color: transparent;
                        color: white;
                        font-size: 14px;
                        line-height: 1.4;
                        margin: 0px;
                        padding: 0px;
                        border: none;
                    }
                """)

                message_layout.addWidget(content_widget)

                # 确保布局能够自适应内容高度
                message_layout.setSizeConstraint(QVBoxLayout.SizeConstraint.SetMinimumSize)
                message_widget.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.MinimumExpanding)
                # print("用户消息内容填充完成")  # 调试：用户消息UI更新
        except TypeError as e:
            self._on_error_occurred(
                f"填充消息内容失败：参数类型不符合要求。原因：{type(e).__name__}：{e}。"
                f"期望：content 为 str 或 (reasoning, main_content) 元组，message_widget 具备必要子组件。"
            )
        except Exception as e:
            self._on_error_occurred(
                f"填充消息内容时发生未预期错误：{type(e).__name__}：{e}。"
                f"期望：有效的消息组件和内容格式。"
            )

    def add_message(self, content, message_type="user", sender_name=None):
        """
        添加消息函数 - 仅用于用户消息和加载聊天记录
        
        Args:
            content (str): 消息内容
            message_type (str): 消息类型 - 仅支持 "user" 和 "ai"（用于加载历史记录）
            sender_name (str): 发送者名称（可选，用于自定义显示）
        """
        # 功能：将消息按类型创建、填充并插入布局，然后刷新滚动区；异常统一通过 _on_error_occurred 显示
        # 只处理用户消息和历史AI消息
        if message_type not in ["user", "ai"]:
            # print(f"忽略不支持的消息类型: {message_type}")  # 调试：过滤非法类型
            return

        try:
            if message_type == "ai":
                # AI消息使用通用的AI消息组件
                ai_message_widget, reasoning_widget, ai_content_widget = self._create_ai_message_widget()
                # print("已创建AI消息组件")  # 调试：AI组件创建

                # 将消息添加到布局
                item_count = self.message_layout.count()
                if item_count > 0:
                    # 移除最后的弹性空间
                    stretch_item = self.message_layout.takeAt(item_count - 1)
                    # 添加消息组件
                    self.message_layout.addWidget(ai_message_widget)
                    # 重新添加弹性空间
                    self.message_layout.addStretch()
                    # print("AI消息插入布局（存在弹性空间）")  # 调试：布局插入路径A
                else:
                    self.message_layout.addWidget(ai_message_widget)
                    self.message_layout.addStretch()
                    # print("AI消息插入布局（无弹性空间）")  # 调试：布局插入路径B

                # 设置对齐方式
                self.message_layout.setAlignment(ai_message_widget, Qt.AlignmentFlag.AlignLeft)

                # 存储组件引用以便填充内容
                ai_message_widget.reasoning_widget = reasoning_widget
                ai_message_widget.ai_content_widget = ai_content_widget

                # 填充内容到组件
                self._populate_message_content(ai_message_widget, content, message_type, sender_name)
            else:
                # 用户消息使用原有逻辑
                # 创建消息组件
                message_widget = self._create_message_widget(content, message_type, sender_name)
                # print("已创建用户消息组件")  # 调试：用户组件创建

                # 填充内容到组件
                self._populate_message_content(message_widget, content, message_type, sender_name)

                # 推入布局
                item_count = self.message_layout.count()
                if item_count > 0:
                    # 移除最后的弹性空间
                    stretch_item = self.message_layout.takeAt(item_count - 1)
                    # 添加消息组件
                    self.message_layout.addWidget(message_widget)
                    # 重新添加弹性空间
                    self.message_layout.addStretch()
                    # print("用户消息插入布局（存在弹性空间）")  # 调试：布局插入路径A
                else:
                    self.message_layout.addWidget(message_widget)
                    self.message_layout.addStretch()
                    # print("用户消息插入布局（无弹性空间）")  # 调试：布局插入路径B

                # 设置对齐方式
                self.message_layout.setAlignment(message_widget, Qt.AlignmentFlag.AlignRight)

            # 刷新滚动区
            self._refresh_scroll_area()
            # print("消息添加完成并刷新滚动区")  # 调试：总流程完成
        except Exception as e:
            self._on_error_occurred(
                f"添加消息失败：{type(e).__name__}：{e}。"
                f"期望：message_type 为 'user' 或 'ai'，content 为可显示文本，布局与组件有效。"
            )

    def _refresh_scroll_area(self):
        """
        刷新滚动区域。
        - 总是刷新布局与几何；
        - 若处于“粘底”状态，仅在接近底部时自动滚到最底；
        - 避免用户向上滚动时被强制拉回底部。
        """
        # 功能：刷新消息容器几何，并在需要时自动滚动到底部；异常统一通过 _on_error_occurred 显示
        try:
            # 刷新布局
            self.message_container.adjustSize()
            self.message_container.updateGeometry()
            self.message_area.updateGeometry()
            QApplication.processEvents()
            # print("已刷新消息容器与滚动区几何")  # 调试：布局刷新

            # 根据“粘底”状态决定是否自动到底
            if getattr(self, "_stick_to_bottom", True):
                sb = self.message_area.verticalScrollBar()
                # 再次确认当前是否接近底部（防止布局重算时误判）
                if (sb.maximum() - sb.value()) <= 20:
                    sb.setValue(sb.maximum())
                    QTimer.singleShot(0, lambda: self.message_area.verticalScrollBar().setValue(
                        self.message_area.verticalScrollBar().maximum()
                    ))
                    # print("自动滚动到最底部")  # 调试：粘底触发
        except AttributeError as e:
            self._on_error_occurred(
                f"刷新滚动区域失败：缺少必要属性或方法。原因：{type(e).__name__}：{e}。"
                f"期望：存在有效的 message_container、message_area 及其滚动条。"
            )
        except Exception as e:
            self._on_error_occurred(
                f"刷新滚动区域时发生未预期错误：{type(e).__name__}：{e}。"
                f"期望：滚动条状态可访问，几何更新成功。"
            )
        try:
            # 防重入：同一刷新过程内直接返回
            if getattr(self, "_refreshing_scroll", False):
                return
            self._refreshing_scroll = True

            # 刷新布局几何（无需强制 processEvents）
            self.message_container.adjustSize()
            self.message_container.updateGeometry()
            self.message_area.updateGeometry()

            # 根据“粘底”状态决定是否自动到底
            if getattr(self, "_stick_to_bottom", True):
                sb = self.message_area.verticalScrollBar()
                # 再次确认当前是否接近底部（防止布局重算时误判）
                if (sb.maximum() - sb.value()) <= 20:
                    sb.setValue(sb.maximum())
                    QTimer.singleShot(0, lambda: self.message_area.verticalScrollBar().setValue(
                        self.message_area.verticalScrollBar().maximum()
                    ))
        finally:
            # 释放防重入标志
            self._refreshing_scroll = False

    def _on_main_scroll_value_changed(self, value):
        """
        维护外层滚动区的“粘底”状态：
        - 当滚动条接近底部（<=20px）时，启用粘底（自动到底）；
        - 当用户向上滚动超过阈值时，关闭粘底（不自动拉回底部）。
        Args:
            value (int): 当前滚动条值
        """
        # 功能：根据滚动条位置维护 _stick_to_bottom 标志；异常统一通过 _on_error_occurred 显示
        try:
            # print(f"滚动值变化: {value}")  # 调试：跟踪滚动条当前值
            sb = self.message_area.verticalScrollBar()
            self._stick_to_bottom = (sb.maximum() - value) <= 20
            # print(f"粘底状态: {self._stick_to_bottom}")  # 调试：粘底状态更新
        except Exception as e:
            self._on_error_occurred(
                f"更新粘底状态失败：{type(e).__name__}：{e}。"
                f"期望：value 为整数，滚动条可访问。"
            )

    

    def update_variables_display(self):
        """更新变量显示区域"""
        # 功能：从 vm 拉取变量数据并刷新展示区域；异常统一通过 _on_error_occurred 显示
        try:
            if not hasattr(self, 'variables_scroll_layout'):
                # print("变量显示布局不存在，跳过更新")  # 调试：缺少变量展示布局
                return

            # 直接从vm获取最新的变量数据（get_all_variables_info会自动加载快照）
            all_variables_info = self.vm.get_all_variables_info()
            self.loaded_variables = all_variables_info
            # print(f"加载变量数量: {len(self.loaded_variables)}")  # 调试：变量加载数量

            # 清空现有的变量显示
            # 移除所有widget，但保留最后的弹性空间
            while self.variables_scroll_layout.count() > 1:
                child = self.variables_scroll_layout.takeAt(0)
                if child.widget():
                    child.widget().deleteLater()

            # 遍历所有变量并显示
            for var_name, var_info in self.loaded_variables.items():
                try:
                    var_widget = self.create_variable_widget(var_info)
                    # 在弹性空间之前插入变量widget
                    self.variables_scroll_layout.insertWidget(
                        self.variables_scroll_layout.count() - 1, var_widget
                    )
                    # print(f"变量插入完成: {var_name}")  # 调试：单个变量插入
                except Exception as e_item:
                    self._on_error_occurred(
                        f"插入变量展示失败：{type(e_item).__name__}：{e_item}。"
                        f"变量名：{var_name}。期望：var_info 为包含必要键的字典。"
                    )
                    # 不中断整个更新流程，继续后续变量
        except Exception as e:
            self._on_error_occurred(
                f"更新变量显示区域失败：{type(e).__name__}：{e}。"
                f"期望：vm 返回有效变量信息，variables_scroll_layout 可用。"
            )

    def create_variable_widget(self, var_info):
        """创建单个变量的显示widget"""
        # 功能：根据变量类型创建并返回展示组件；异常统一通过 _on_error_occurred 显示
        try:
            var_widget = QFrame()
            var_widget.setStyleSheet("""
                QFrame {
                    background-color: rgba(255, 255, 255, 0.05);
                    border: 1px solid rgba(255, 255, 255, 0.1);
                    border-radius: 4px;
                    padding: 8px;
                    margin: 2px;
                }
            """)

            var_layout = QVBoxLayout(var_widget)
            var_layout.setContentsMargins(4, 4, 4, 4)
            var_layout.setSpacing(4)

            var_type = var_info.get('var_type', 'record')
            # print(f"创建变量组件，类型: {var_type}")  # 调试：变量类型

            if var_type == 'record':
                # 记录变量：name: value
                self.create_record_variable_display(var_layout, var_info)
            elif var_type == 'stage_independent':
                # 阶段变量：三行显示
                self.create_stage_variable_display(var_layout, var_info)

            return var_widget
        except Exception as e:
            self._on_error_occurred(
                f"创建变量展示组件失败：{type(e).__name__}：{e}。"
                f"期望：var_info 为包含 'var_type'、'name'、'value' 等键的字典。"
            )
            # 出错时返回一个空组件以避免中断后续流程
            fallback = QWidget()
            fallback.setFixedHeight(0)
            return fallback

    def create_record_variable_display(self, layout, var_info):
        """创建记录变量的显示"""
        # 功能：以“name: value”格式将记录型变量添加到布局；异常统一通过 _on_error_occurred 显示
        try:
            name = var_info.get('name', '未知')
            value = var_info.get('value', 0)

            # name: value 格式
            label = QLabel(f"{name}: {value}")
            label.setStyleSheet("""
                QLabel {
                    color: #FFFFFF;
                    font-size: 12px;
                    background-color: transparent;
                    border: none;
                    padding: 2px;
                }
            """)
            layout.addWidget(label)
            # print(f"记录变量显示完成: {name}={value}")  # 调试：记录变量添加
        except Exception as e:
            self._on_error_occurred(
                f"创建记录变量显示失败：{type(e).__name__}：{e}。"
                f"期望：var_info 至少包含 'name' 与 'value'。"
            )

    def create_stage_variable_display(self, layout, var_info):
        """创建阶段变量的显示"""
        # 功能：以三行形式展示阶段型变量（名称、经验条、相对描述）；异常统一通过 _on_error_occurred 显示
        try:
            name = var_info.get('name', '未知')
            value = var_info.get('value', 0)
            relative_name = var_info.get('relative_name', '')
            relative_value = var_info.get('relative_value', 0)
            relative_current_description = var_info.get('relative_current_description', '未知')

            # 格式化显示值 - 直接在此处处理
            def format_value(val):
                if isinstance(val, tuple):
                    return "-".join(str(item) for item in val)
                elif isinstance(val, (list, set)):
                    return "-".join(str(item) for item in val)
                else:
                    return str(val)

            formatted_relative_value = format_value(relative_value)
            formatted_description = format_value(relative_current_description)

            # 第一行：name: value
            name_label = QLabel(f"{name}: {value}")
            name_label.setStyleSheet("""
                QLabel {
                    color: #FFFFFF;
                    font-size: 12px;
                    font-weight: bold;
                    background-color: transparent;
                    border: none;
                    padding: 2px;
                }
            """)
            layout.addWidget(name_label)

            # 第二行：经验条
            progress_widget = self.create_experience_bar(var_info)
            layout.addWidget(progress_widget)

            # 第三行：relative_name: relative_current_description (relative_value)
            relative_label = QLabel(f"{relative_name}: {formatted_description} ({formatted_relative_value})")
            relative_label.setStyleSheet("""
                QLabel {
                    color: rgba(255, 255, 255, 0.8);
                    font-size: 11px;
                    background-color: transparent;
                    border: none;
                    padding: 2px;
                }
            """)
            layout.addWidget(relative_label)
            # print(f"阶段变量显示完成: {name}, 阶段值: {relative_value}")  # 调试：阶段变量添加
        except Exception as e:
            self._on_error_occurred(
                f"创建阶段变量显示失败：{type(e).__name__}：{e}。"
                f"期望：var_info 包含 name、value、relative_* 等键的有效数据。"
            )

    def create_experience_bar(self, var_info):
        """创建经验条 - 只有LADDER模式的阶段变量才显示经验条"""
        # 功能：根据相对阶段配置创建 QProgressBar；异常统一通过 _on_error_occurred 显示
        try:
            # 检查是否为阶段变量且为LADDER模式
            relative_method = var_info.get('relative_method')
            if relative_method != 'ladder':  # 只有ladder模式才显示经验条
                empty_widget = QWidget()
                empty_widget.setFixedHeight(0)  # 设置高度为0，不占用空间
                return empty_widget

            # 获取必要的数据
            current_value = var_info.get('value', 0)
            relative_value = var_info.get('relative_value', 0)
            relative_stage_config = var_info.get('relative_stage_config', ())

            if not relative_stage_config:
                # 没有配置数据，返回空widget
                empty_widget = QWidget()
                empty_widget.setFixedHeight(0)
                return empty_widget

            # 判断是否为最后阶段：超过所有阈值的阶段
            is_last_stage = relative_value == len(relative_stage_config)

            # 计算经验条的最大值
            if is_last_stage:
                # 最后阶段：使用最后一个阈值的十倍作为"无限"显示
                stage_exp_max = relative_stage_config[-1] * 10
                display_max = "∞"
            else:
                # 普通阶段：使用当前阶段对应的阈值
                if relative_value < len(relative_stage_config):
                    stage_exp_max = relative_stage_config[relative_value]
                    display_max = f"{stage_exp_max:.1f}"
                else:
                    stage_exp_max = 100.0
                    display_max = "100.0"

            # 创建经验条容器
            exp_widget = QWidget()
            exp_layout = QHBoxLayout(exp_widget)
            exp_layout.setContentsMargins(0, 0, 0, 0)
            exp_layout.setSpacing(4)

            # 创建进度条
            progress_bar = QProgressBar()
            progress_bar.setMinimum(0)
            progress_bar.setMaximum(int(stage_exp_max * 10))  # 乘以10支持小数精度
            progress_bar.setValue(int(current_value * 10))
            progress_bar.setFixedHeight(16)

            # 设置进度条样式
            if is_last_stage:
                # 最后阶段使用金色
                progress_bar.setStyleSheet("""
                    QProgressBar {
                        border: 1px solid rgba(255, 255, 255, 0.3);
                        border-radius: 8px;
                        background-color: rgba(0, 0, 0, 0.3);
                        text-align: center;
                        font-size: 10px;
                        color: white;
                    }
                    QProgressBar::chunk {
                        background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                            stop:0 #FFD700, stop:1 #FFA500);
                        border-radius: 7px;
                    }
                """)
            else:
                # 普通阶段使用绿色
                progress_bar.setStyleSheet("""
                    QProgressBar {
                        border: 1px solid rgba(255, 255, 255, 0.3);
                        border-radius: 8px;
                        background-color: rgba(0, 0, 0, 0.3);
                        text-align: center;
                        font-size: 10px;
                        color: white;
                    }
                    QProgressBar::chunk {
                        background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                            stop:0 #4CAF50, stop:1 #8BC34A);
                        border-radius: 7px;
                    }
                """)

            # 设置进度条显示文本
            progress_bar.setFormat(f"{current_value:.1f}/{display_max}")

            exp_layout.addWidget(progress_bar)
            return exp_widget
        except (TypeError, ValueError) as e:
            self._on_error_occurred(
                f"创建经验条失败：数值或配置不正确。原因：{type(e).__name__}：{e}。"
                f"期望：'value' 为数值，'relative_stage_config' 为阶段阈值序列。"
            )
            empty_widget = QWidget()
            empty_widget.setFixedHeight(0)
            return empty_widget
        except Exception as e:
            self._on_error_occurred(
                f"创建经验条时发生未预期错误：{type(e).__name__}：{e}。"
                f"期望：有效的阶段配置与可用的进度条组件。"
            )
            empty_widget = QWidget()
            empty_widget.setFixedHeight(0)
            return empty_widget

    def closeEvent(self, event) -> None:
        """窗口关闭事件
        - 请求工作线程优雅停止并等待退出
        - 避免 `QThread: Destroyed while thread is still running` 报错
        """
        # 功能：在窗口关闭前尝试优雅停止工作线程；异常统一通过 _on_error_occurred 显示
        try:
            # print("开始处理窗口关闭事件，检查工作线程状态")  # 调试：关闭流程入口
            if hasattr(self, "processor_worker") and self.processor_worker.isRunning():
                self.processor_worker.request_stop()
                self.processor_worker.wait(3000)  # 最多等待3秒
                # print("已请求并等待工作线程停止")  # 调试：线程停止请求
        except Exception as e:
            # print(f"关闭窗口时停止线程失败：{e}")  # 调试：停止失败详情（已注释）
            self._on_error_occurred(f"关闭窗口时停止线程失败：{type(e).__name__}: {e}。期望：processor_worker 可用且可优雅终止。")
        finally:
            super().closeEvent(event)

def get_runtime_base() -> Path:
    """
    返回运行时基目录：
    - 打包态：返回可执行文件所在目录
    - 开发态：返回项目根目录（gui_pyside6 的上级）
    """
    import sys
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent

def get_asset_path(relative_path: str) -> str:
    """
    返回资源文件的绝对路径。
    - 优先兼容 PyInstaller 单文件模式的临时目录 `sys._MEIPASS`
    - 其次兼容 onedir 模式的可执行文件所在目录
    - 开发态使用项目根目录
    参数:
        relative_path: 例如 'assets/send.png'
    返回:
        资源的绝对路径字符串
    """
    import sys
    base = Path(getattr(sys, "_MEIPASS", get_runtime_base()))
    return str(base / relative_path)
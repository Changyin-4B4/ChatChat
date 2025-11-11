from __future__ import annotations
from typing import Dict, List, TYPE_CHECKING, Callable, Optional
import json
from openai import OpenAI
from datetime import datetime
from .configs import DEFAULT_WORKFLOW_CONFIG, CHAT_METHOD, API_PROVIDERS
from .message_process import process_user_input, process_llm_output, create_empty_assistant_message, delete_messages_from_file
from .llm_judge import TaskManager
from .stream_filter import StreamFilterOptimized
from .prompts import build_messages
from .io_manager import global_io_manager
from google import genai
from google.genai import types

if TYPE_CHECKING:
    from core.variables_update import VariableManager

class AIRPCycleProcessor:
    """统一的LLM请求处理器"""

    def __init__(self, vm: VariableManager,
                 on_create_content=None,
                 on_create_reasoning=None,
                 on_pre_judge=None,
                 on_post_judge=None
                 ):
        """
        初始化统一LLM请求处理器

        Args:
            vm: 变量管理器
            on_create_content: 创作内容回调函数
            on_create_reasoning: 创作推理内容回调函数
            on_pre_judge: 预判断流回调函数
            on_post_judge: 后判断流回调函数
        """
        self.llm_client = LLM_Client(API_PROVIDERS)
        self.task_manager = TaskManager()
        self.vm = vm

        # 回调函数存储
        self.on_create_content = on_create_content
        self.on_create_reasoning = on_create_reasoning
        self.on_pre_judge = on_pre_judge
        self.on_post_judge = on_post_judge

        self.workflow_config = DEFAULT_WORKFLOW_CONFIG
        self.stream_statu = False

        # 解析 DEFAULT_WORKFLOW_CONFIG 获得三个任务的配置
        self.pre_process_config = {
            "provider": self.workflow_config["api_configs"]["pre_process"]["provider"],
            "model": self.workflow_config["api_configs"]["pre_process"]["model"],
            "prompt_config": self.workflow_config["prompt_configs"]["pre_process"]
        }

        self.create_config = {
            "provider": self.workflow_config["api_configs"]["create"]["provider"],
            "model": self.workflow_config["api_configs"]["create"]["model"],
            "prompt_config": self.workflow_config["prompt_configs"]["create"]
        }

        self.post_process_config = {
            "provider": self.workflow_config["api_configs"]["post_process"]["provider"],
            "model": self.workflow_config["api_configs"]["post_process"]["model"],
            "prompt_config": self.workflow_config["prompt_configs"]["post_process"]
        }

    def send_command(self, data):
        """
        发送数据到LLM
        """
        process_user_input(data)

    # 功能：预命令处理，读取用户最后输入并更新变量与任务队列
    def pre_command(self):
        """
        预命令处理
        """

        # 读取data.json中最后一条user消息的content
        processed_input = ""

        raw_json = global_io_manager.read_json(r"data\data.json")
        data = json.loads(raw_json)

        # 找到最后一条user消息
        last_user_content = ""
        max_layer = 0
        for key, message in data.items():
            if message.get('speaker') == 'User' and message.get('layer', 0) > max_layer:
                max_layer = message.get('layer', 0)
                last_user_content = message.get('content', '')

        processed_input = last_user_content
        # print(f"读取到最后一条用户消息: {processed_input}") # 调试：确认提取到的用户消息

        # 检测最后一条消息是否为助手消息，如果不是则创建空的助手消息容器
        if data:
            max_id = max(int(k) for k in data.keys())
            last_message = data[str(max_id)]

            if last_message.get('speaker') != 'Assistant':
                # print("检测到最后一条消息不是助手消息，创建空的助手消息容器...") # 调试：确保助手消息容器存在
                create_empty_assistant_message()
                # print("成功创建空的助手消息容器") # 调试：确认容器创建成功

        # 第一步：使用变量管理器更新所有变量，传入任务管理器实例
        keyword_update_results = self.vm.recalculate_all_variables(processed_input, pre_update=True, task_manager=self.task_manager)

        # 打印当前所有变量信息（调试用，默认注释）
        # print("\n=== 变量状态更新 ===") # 调试：变量更新开始
        # all_variables_info = self.vm.get_all_variables_info()
        # for var_name, info in all_variables_info.items():
        #     if info['var_type'] == 'stage_independent':
        #         print(f"{var_name}: 值={info['value']}, 阶段={info['relative_current_description']} (阶段值={info['relative_value']})")
        #     else:
        #         print(f"{var_name}: 值={info['value']}")
        # print("========================\n") # 调试：变量更新结束

        # 初始化更新结果列表，用于收集所有轮次的更新
        all_update_results = []
        # 新增：收集信息尾部的列表（每次 LLM 调用都会追加）
        info_tails = []

        # 将关键词更新结果添加到总列表中
        all_update_results.extend(keyword_update_results)

        # print(self.task_manager.task_queue) # 调试：查看任务队列

        while self.task_manager.task_queue:
            # print("我进循环啦") # 调试：进入任务循环
            # 执行任务管理器process_all_tasks函数
            if CHAT_METHOD == 0:
                pre_messages = self.task_manager.process_all_tasks(processed_input, phase="pre_update", prompt_config=self.pre_process_config["prompt_config"])
            else:
                pre_messages = self.task_manager.process_all_tasks(processed_input, phase="post_update", prompt_config=self.post_process_config["prompt_config"])

            # for pre_message in pre_messages:
            #     print(pre_message["content"]) # 调试：查看预处理消息内容

            pre_output = self.llm_client.request_llm(pre_messages, self.pre_process_config["provider"], self.pre_process_config["model"], self.on_pre_judge)
            if pre_output == "stop":
                self.task_manager._clear_temporary_data()
                return pre_output
            else:
                # 统一取 content 字符串
                pre_content = pre_output.get("content", "") if isinstance(pre_output, dict) else str(pre_output)
                # 新增：收集信息尾部
                info_tail = pre_output.get("information", "") if isinstance(pre_output, dict) else ""
                if info_tail:
                    info_tails.append(info_tail)
                round_update_results = self.task_manager._parse_llm_response(pre_content)
                all_update_results.extend(round_update_results)

        if all_update_results:
            self.vm.apply_variable_updates(all_update_results)

        self.task_manager._clear_temporary_data()
        return info_tails

    # 功能：创作命令处理，构建消息并请求模型生成内容
    def create_command(self):
        """
        创建命令处理
        """
        # 读取data.json中最后一条user消息的content
        processed_input = ""

        raw_json = global_io_manager.read_json(r"data\data.json")
        data = json.loads(raw_json)

        # 找到最后一条user消息
        last_user_content = ""
        max_layer = 0
        for key, message in data.items():
            if message.get('speaker') == 'User' and message.get('layer', 0) > max_layer:
                max_layer = message.get('layer', 0)
                last_user_content = message.get('content', '')

        processed_input = last_user_content
        # print(f"读取到最后一条用户消息: {processed_input}") # 调试：确认提取到的用户消息

        create_messages = build_messages(processed_input, self.vm, prompt_config = self.create_config["prompt_config"])
        # for create_message in create_messages:
        #     print(create_message["content"]) # 调试：查看创作消息内容

        create_output = self.llm_client.request_llm(create_messages, self.create_config["provider"], self.create_config["model"], self.on_create_reasoning, self.on_create_content)
        if create_output == "stop":
            return create_output
        else:
            # 新增：仅传入 reasoning 与 content 给 process_llm_output
            trimmed = {
                "reasoning": create_output.get("reasoning", "") if isinstance(create_output, dict) else "",
                "content": create_output.get("content", "") if isinstance(create_output, dict) else str(create_output),
            }
            process_llm_output(trimmed)
            # 新增：返回信息尾部
            info_tail = create_output.get("information", "") if isinstance(create_output, dict) else ""
            return info_tail

    # 功能：后处理命令，基于助手输出更新变量并执行后置任务
    def post_command(self):
        """
        后处理命令
        """
        # 读取data.json中最后一条助手消息的scene和content
        processed_output = ""

        raw_json = global_io_manager.read_json(r"data\data.json")
        data = json.loads(raw_json)

        # 找到最后一条助手消息
        last_assistant_scene = ""
        last_assistant_content = ""
        max_layer = 0
        for key, message in data.items():
            if message.get('speaker') == 'Assistant' and message.get('layer', 0) > max_layer:
                max_layer = message.get('layer', 0)
                last_assistant_scene = message.get('scene', '')
                last_assistant_content = message.get('content', '')

        # 组合成（scene）content格式
        if last_assistant_scene and last_assistant_content:
            processed_output = f"（{last_assistant_scene}）{last_assistant_content}"
        elif last_assistant_content:
            processed_output = last_assistant_content
        else:
            processed_output = ""

        # print(f"读取到最后一条助手消息: {processed_output}") # 调试：确认提取到的助手消息

        # 第一步：使用变量管理器更新所有变量，传入任务管理器实例
        keyword_update_results = self.vm.recalculate_all_variables(processed_output, pre_update=False, task_manager=self.task_manager)

        # 打印当前所有变量信息（调试用，默认注释）
        # print("\n=== 变量状态更新 ===") # 调试：变量更新开始
        # all_variables_info = self.vm.get_all_variables_info()
        # for var_name, info in all_variables_info.items():
        #     if info['var_type'] == 'stage_independent':
        #         print(f"{var_name}: 值={info['value']}, 阶段={info['relative_current_description']} (阶段值={info['relative_value']})")
        #     else:
        #         print(f"{var_name}: 值={info['value']}")
        # print("========================\n") # 调试：变量更新结束

        # 初始化更新结果列表，用于收集所有轮次的更新
        all_update_results = []
        # 新增：收集信息尾部的列表
        info_tails = []

        # 将关键词更新结果添加到总列表中
        all_update_results.extend(keyword_update_results)

        # print(self.task_manager.task_queue) # 调试：查看任务队列

        while self.task_manager.task_queue:
            # print("我进循环啦") # 调试：进入任务循环
            # 执行任务管理器process_all_tasks函数
            post_messages = self.task_manager.process_all_tasks(processed_output, phase="post_update", prompt_config=self.post_process_config["prompt_config"])
            # print(post_messages) # 调试：查看后处理消息列表
            # print("Whatsup?") # 调试：占位调试输出
            # for post_message in post_messages:
            #     print(f"后处理消息: {post_message['content']}") # 调试：查看后处理消息内容

            post_output = self.llm_client.request_llm(post_messages, self.post_process_config["provider"], self.post_process_config["model"], self.on_post_judge)
            if post_output == "stop":
                self.task_manager._clear_temporary_data()
                return post_output
            else:
                # 统一取 content 字符串
                post_content = post_output.get("content", "") if isinstance(post_output, dict) else str(post_output)
                # 新增：收集信息尾部
                info_tail = post_output.get("information", "") if isinstance(post_output, dict) else ""
                if info_tail:
                    info_tails.append(info_tail)
                round_update_results = self.task_manager._parse_llm_response(post_content)
                all_update_results.extend(round_update_results)

        if all_update_results:
            self.vm.apply_variable_updates(all_update_results)

        # 打印当前所有变量信息（调试用，默认注释）
        # print("\n=== 变量状态更新 ===") # 调试：变量更新开始
        # all_variables_info = self.vm.get_all_variables_info()
        # for var_name, info in all_variables_info.items():
        #     if info['var_type'] == 'stage_independent':
        #         print(f"{var_name}: 值={info['value']}, 阶段={info['relative_current_description']} (阶段值={info['relative_value']})")
        #     else:
        #         print(f"{var_name}: 值={info['value']}")
        # print("========================\n") # 调试：变量更新结束

        self.task_manager._clear_temporary_data()
        return info_tails

    def stop_stream(self):
        """处理停止请求"""
        self.llm_client.stop_stream()
        return

    # 功能：删除指定数量的最新消息记录（入口函数）
    def delete_messages(self, count: int = 0):
        """
        删除指定数量的消息记录（入口函数）

        - 参数与反馈由入口方法负责
        - 具体的文件读写与删除逻辑在 message_process.py 中
        Args:
            count: 要删除的消息数量，从最新的消息开始删除
        """
        if count <= 0:
            raise ValueError(f"删除数量必须大于 0，当前值为 {count}；期望：正整数")

        # 调用专用删除函数（不再传入路径，固定作用于 data/data.json）
        deleted = delete_messages_from_file(count)

        if deleted == 0:
            # print("没有可删除的消息或仅剩开场消息") # 调试：确认删除结果为零
            return
        else:
            # print(f"成功删除 {deleted} 条消息") # 调试：记录成功删除数量
            return

class LLM_Client:
    def __init__(self, api_providers: Dict):
        self.api_providers = api_providers
        self.stream_statu = False
        self._response_stream = None  # 新增：保存响应流引用

    # 功能：请求停止流式传输并关闭响应流
    def stop_stream(self):
        """请求停止流式传输"""
        self.stream_statu = False
        # 如果有活跃的响应流，尝试关闭
        if self._response_stream:
            # print("开始关闭活跃响应流") # 调试：标记释放流资源
            self._response_stream.close()
            # print("响应流已关闭") # 调试：确认资源释放

    # 功能：向指定供应商的LLM模型发送请求，统一进行提示词调整与状态标记
    def request_llm(self, prompt: List[Dict[str, str]], provider: str, model: str, reasoning_callback, content_callback=None):
        """
        向指定供应商的LLM模型发送请求
        
        Args:
            prompt: 输入提示词
            provider: API供应商名称
            model: 模型名称
            
        Returns:
            LLM模型的响应内容
        """
        # 检查供应商是否存在
        if provider not in self.api_providers:
            raise ValueError(f"API供应商名称无效：{provider}；原因：未在配置中找到；期望：在 api_providers 中已配置的供应商名称")

        # print(f"开始请求LLM：provider={provider}, model={model}") # 调试：记录请求入口
        base_url, api_key = self.api_providers[provider]["base_url"], self.api_providers[provider]["api_key"]
        self.stream_statu = True

        if provider == "deepseek":
            return self._stream_deepseek(prompt, model, base_url, api_key, reasoning_callback, content_callback)
        elif provider == "siliconflow":
            return self._stream_siliconflow(prompt, model, base_url, api_key, reasoning_callback, content_callback)
        elif provider == "gemini":
            return self._stream_gemini(prompt, model, base_url, api_key, reasoning_callback, content_callback)
        elif provider == "kimi":
            return self._stream_kimi(prompt, model, base_url, api_key, reasoning_callback, content_callback)
        else:
            raise ValueError(f"不支持的API供应商：{provider}；原因：未实现流式请求方法；期望：在 LLM_Client 中添加对应实现")

    def _stream_deepseek(self, prompt: List[Dict[str, str]], model: str, base_url: str, api_key: str, reasoning_callback, content_callback=None):
        """
        DeepSeek 流式请求与增量输出处理（统一返回字典格式）
        - 始终返回: {'reasoning': str, 'content': str, 'information': str}
        - information 尾部包含 created、usage、finish_reason
        Args:
            prompt: LLM消息序列
            model: 模型名称
            base_url: API 基础地址
            api_key: API Key
            reasoning_callback: 推理内容的流式回调
            content_callback: 主内容的流式回调（用于创作阶段）。为空时启用JSON输出
        Returns:
            dict: {'reasoning': str, 'content': str, 'information': str} 或 "stop"
        """
        client = OpenAI(api_key=api_key, base_url=base_url)
        if content_callback:
            stream_filter = StreamFilterOptimized(output_callback=content_callback)
        else:
            stream_filter = None

        try:
            # 构建请求参数
            request_params = {
                "model": model,
                "messages": prompt,
                "stream": True,
                "stream_options": {"include_usage": True}
            }
            
            # 当 content_callback 为空时，启用 JSON 输出模式
            if content_callback is None:
                request_params["response_format"] = {"type": "json_object"}
            
            self._response_stream = client.chat.completions.create(**request_params)
            
            full_response = ""
            full_reasoning = ""
            reasoning_ended = False
            finish_reason_last = None
            created_ts = None
            usage_final = None

            for chunk in self._response_stream:
                if getattr(chunk, "created", None) is not None:
                    created_ts = chunk.created

                choices = getattr(chunk, "choices", [])
                if isinstance(choices, list) and choices:
                    fr = getattr(choices[0], "finish_reason", None)
                    if fr is not None:
                        finish_reason_last = fr

                if getattr(chunk, "usage", None):
                    usage_final = chunk.usage

                if self.stream_statu:
                    if hasattr(choices[0].delta, 'reasoning_content') and choices[0].delta.reasoning_content is not None:
                        reasoning = choices[0].delta.reasoning_content
                        reasoning_callback(reasoning)
                        full_reasoning += reasoning
                    if choices[0].delta.content is not None:
                        content = choices[0].delta.content
                        full_response += content
                        if content_callback:
                            stream_filter.process_chunk(content)
                        else:
                            if not reasoning_ended:
                                reasoning_callback("\n")
                                reasoning_ended = True
                            reasoning_callback(content)
                else:
                    return "stop"

            # 统一组装信息尾部（末位键）
            info_parts = []
            if created_ts is not None:
                human = datetime.fromtimestamp(created_ts).isoformat(timespec="seconds")
                info_parts.append(f"time:{human}")
            if usage_final is not None:
                if isinstance(usage_final, dict):
                    ct = usage_final.get("completion_tokens")
                    hit = usage_final.get("prompt_cache_hit_tokens")
                    miss = usage_final.get("prompt_cache_miss_tokens")
                else:
                    ct = getattr(usage_final, "completion_tokens", None)
                    hit = getattr(usage_final, "prompt_cache_hit_tokens", None)
                    miss = getattr(usage_final, "prompt_cache_miss_tokens", None)
                info_parts.append(f"output_tokens={ct}\ninput_cache_hit_tokens={hit}\ninput_cache_miss_tokens={miss}\n")
            if finish_reason_last is not None and str(finish_reason_last).lower() != "stop":
                info_parts.append(f"finish_reason={finish_reason_last}")
            info_tail = "\n".join(info_parts) if info_parts else ""

            return {"reasoning": full_reasoning, "content": full_response, "information": info_tail}

        except Exception as e:
            if self.stream_statu == False:
                return "stop"
            else:
                raise ValueError(f"DeepSeek stream failed: {e}") from e

        finally:
            self._response_stream = None
            self.stream_statu = False

    def _stream_siliconflow(self, prompt: List[Dict[str, str]], model: str, base_url: str, api_key: str, reasoning_callback: Callable, content_callback: Optional[Callable] = None):
        """
        硅基流动 API 流式请求与增量输出处理（统一返回字典格式）
        
        - 始终返回: {'reasoning': str, 'content': str, 'information': str}
        - information 尾部包含 created、usage、finish_reason
        
        Args:
            prompt: LLM消息序列
            model: 模型名称
            base_url: API 基础地址（硅基流动）
            api_key: API Key
            reasoning_callback: 推理内容的流式回调
            content_callback: 主内容的流式回调（用于创作阶段）。为空时启用JSON输出
            
        Returns:
            dict: {'reasoning': str, 'content': str, 'information': str} 或 "stop"
        """
        
        # 定义支持思考功能的模型列表（基于硅基流动文档）
        THINKING_SUPPORTED_MODELS = {
            "zai-org/GLM-4.6",
            "Qwen/Qwen3-8B",
            "Qwen/Qwen3-14B",
            "Qwen/Qwen3-32B",
            "Qwen/Qwen3-30B-A3B",
            "Qwen/Qwen3-235B-A22B",
            "tencent/Hunyuan-A13B-Instruct",
            "zai-org/GLM-4.5V",
            "deepseek-ai/DeepSeek-V3.1-Terminus",
            "Pro/deepseek-ai/DeepSeek-V3.1-Terminus",
            "deepseek-ai/DeepSeek-R1",
            "Pro/deepseek-ai/DeepSeek-R1",
            "deepseek-ai/DeepSeek-R1-0528-Qwen3-8B",
            "deepseek-ai/DeepSeek-R1-Distill-Qwen-32B",
            "deepseek-ai/DeepSeek-R1-Distill-Qwen-14B",
            "deepseek-ai/DeepSeek-R1-Distill-Qwen-7B",
            "Pro/deepseek-ai/DeepSeek-R1-Distill-Qwen-7B",
            "Qwen/QwQ-32B",
            "Qwen/Qwen3-30B-A3B-Thinking",
            "Qwen/Qwen3-235B-A22B-Thinking-2507",
            "Qwen/Qwen3-30B-A3B-Thinking-2507",
            "Qwen/Qwen3-Next-80B-A3B-Thinking",
        }
        
        enable_thinking = model in THINKING_SUPPORTED_MODELS
        
        client = OpenAI(api_key=api_key, base_url=base_url)
        
        if content_callback:
            stream_filter = StreamFilterOptimized(output_callback=content_callback)
        else:
            stream_filter = None
        
        try:
            # 构建请求参数
            request_params = {
                "model": model,
                "messages": prompt,
                "stream": True,
                "max_tokens": 65536,
                "temperature": 0.7,
                "top_p": 0.95,
                "frequency_penalty": 0.5,
            }
            
            # 当 content_callback 为空时，启用 JSON 输出模式
            if content_callback is None:
                request_params["response_format"] = {"type": "json_object"}
            
            # 如果模型支持思考功能，通过 extra_body 添加思考相关参数
            if enable_thinking:
                request_params["extra_body"] = {
                    "enable_thinking": True,
                    "thinking_budget": 32768
                }
            
            self._response_stream = client.chat.completions.create(**request_params)
            
            full_response = ""
            full_reasoning = ""
            reasoning_ended = False
            finish_reason_last = None
            created_ts = None
            usage_final = None
            
            for chunk in self._response_stream:
                if getattr(chunk, "created", None) is not None:
                    created_ts = chunk.created
                
                choices = getattr(chunk, "choices", [])
                if isinstance(choices, list) and choices:
                    fr = getattr(choices[0], "finish_reason", None)
                    if fr is not None:
                        finish_reason_last = fr
                
                if getattr(chunk, "usage", None):
                    usage_final = chunk.usage
                
                if self.stream_statu:
                    if (hasattr(choices[0].delta, 'reasoning_content') and 
                        choices[0].delta.reasoning_content is not None):
                        reasoning = choices[0].delta.reasoning_content
                        reasoning_callback(reasoning)
                        full_reasoning += reasoning
                    
                    if choices[0].delta.content is not None:
                        content = choices[0].delta.content
                        full_response += content
                        if content_callback:
                            stream_filter.process_chunk(content)
                        else:
                            if not reasoning_ended:
                                reasoning_callback("\n")
                                reasoning_ended = True
                            reasoning_callback(content)
                else:
                    return "stop"
            
            # 统一组装信息尾部
            info_parts = []
            if created_ts is not None:
                human = datetime.fromtimestamp(created_ts).isoformat(timespec="seconds")
                info_parts.append(f"time:{human}")
            
            if usage_final is not None:
                if isinstance(usage_final, dict):
                    ct = usage_final.get("completion_tokens")
                    pt = usage_final.get("prompt_tokens")
                else:
                    ct = getattr(usage_final, "completion_tokens", None)
                    pt = getattr(usage_final, "prompt_tokens", None)
                
                info_parts.append(
                    f"output_tokens={ct}\n"
                    f"input_cache_hit_tokens=0\n"
                    f"input_cache_miss_tokens={pt}"
                )
            
            if finish_reason_last is not None and str(finish_reason_last).lower() != "stop":
                info_parts.append(f"finish_reason={finish_reason_last}")
            
            info_tail = "\n".join(info_parts) if info_parts else ""
            
            return {
                "reasoning": full_reasoning,
                "content": full_response,
                "information": info_tail
            }
        
        except Exception as e:
            if self.stream_statu == False:
                return "stop"
            else:
                raise ValueError(f"SiliconFlow stream failed: {e}") from e
        
        finally:
            self._response_stream = None
            self.stream_statu = False

    def _stream_gemini(self, prompt: List[Dict[str, str]], model: str, base_url: str, api_key: str, reasoning_callback: Callable, content_callback: Optional[Callable] = None):
        """
        Gemini API 流式请求与增量输出处理（统一返回字典格式）
        
        - 始终返回: {'reasoning': str, 'content': str, 'information': str}
        - information 尾部包含 created、usage、finish_reason
        - 不再因 finish_reason 抛错；仅对真实异常抛出异常
        
        Args:
            prompt: LLM消息序列（OpenAI格式）
            model: 模型名称（如 "gemini-2.5-pro", "gemini-2.5-flash"）
            base_url: API 基础地址（Gemini 不使用）
            api_key: API Key
            reasoning_callback: 推理内容的流式回调
            content_callback: 主内容的流式回调（用于创作阶段）。为空时启用JSON输出
            
        Returns:
            dict: {'reasoning': str, 'content': str, 'information': str} 或 "stop"
        """
        # 定义支持思考功能的模型列表
        THINKING_SUPPORTED_MODELS = {
            "gemini-2.5-pro",
            "gemini-2.5-flash",
            "gemini-2.5-flash-lite",
            "gemini-2.0-flash-thinking-exp",
        }
        
        enable_thinking = any(supported in model.lower() for supported in THINKING_SUPPORTED_MODELS)
        
        client = genai.Client(api_key=api_key)
        
        if content_callback:
            stream_filter = StreamFilterOptimized(output_callback=content_callback)
        else:
            stream_filter = None
        
        try:
            # 将 OpenAI 格式的消息转换为 Gemini 格式，同时提取 system 消息
            gemini_contents = []
            extracted_system = None
            
            for msg in prompt:
                role = msg.get("role", "user")
                content = msg.get("content", "")
                
                if role == "system":
                    extracted_system = content
                    continue
                
                if role == "assistant":
                    role = "model"
                
                gemini_contents.append(
                    types.Content(
                        role=role,
                        parts=[types.Part(text=content)]
                    )
                )
            
            # 构建生成配置
            config_params = {
                "temperature": 0.7,
                "max_output_tokens": 65536,
                "top_p": 0.95,
            }
            
            # 当 content_callback 为空时，启用 JSON 输出模式
            if content_callback is None:
                config_params["response_mime_type"] = "application/json"
            
            # 添加思考配置
            if enable_thinking:
                config_params["thinking_config"] = types.ThinkingConfig(
                    thinking_budget=32768,
                    include_thoughts=True
                )
            
            # 添加系统指令（如果提供）
            if extracted_system:
                config_params["system_instruction"] = extracted_system
            
            config = types.GenerateContentConfig(**config_params)
            
            # 创建流式请求
            self._response_stream = client.models.generate_content_stream(
                model=model,
                contents=gemini_contents,
                config=config
            )
            
            full_response = ""
            full_reasoning = ""
            reasoning_ended = False
            finish_reason_last = None
            created_ts = None
            usage_final = None
            
            for chunk in self._response_stream:
                if hasattr(chunk, 'usage_metadata') and chunk.usage_metadata:
                    usage_final = chunk.usage_metadata
                
                if hasattr(chunk, 'candidates') and chunk.candidates:
                    candidate = chunk.candidates[0]
                    if hasattr(candidate, 'finish_reason') and candidate.finish_reason:
                        finish_reason_last = candidate.finish_reason
                
                if not self.stream_statu:
                    return "stop"
                
                if hasattr(chunk, 'candidates') and chunk.candidates:
                    candidate = chunk.candidates[0]
                    if hasattr(candidate, 'content') and candidate.content:
                        if hasattr(candidate.content, 'parts') and candidate.content.parts:
                            for part in candidate.content.parts:
                                if not hasattr(part, 'text') or not part.text:
                                    continue
                                
                                is_thought = hasattr(part, 'thought') and part.thought
                                
                                if is_thought:
                                    reasoning = part.text
                                    reasoning_callback(reasoning)
                                    full_reasoning += reasoning
                                else:
                                    content = part.text
                                    full_response += content
                                    
                                    if content_callback:
                                        stream_filter.process_chunk(content)
                                    else:
                                        if not reasoning_ended and full_reasoning:
                                            reasoning_callback("\n")
                                            reasoning_ended = True
                                        reasoning_callback(content)
            
            # 统一组装信息尾部
            info_parts = []
            
            current_time = datetime.now().isoformat(timespec="seconds")
            info_parts.append(f"time:{current_time}")
            
            if usage_final is not None:
                ct = getattr(usage_final, "candidates_token_count", 0)
                tt = getattr(usage_final, "thoughts_token_count", 0)
                pt = getattr(usage_final, "prompt_token_count", 0)
                
                if tt > 0:
                    info_parts.append(f"thoughts_tokens={tt}")

                info_parts.append(
                    f"output_tokens={ct}\n"
                    f"input_cache_hit_tokens=0\n"
                    f"input_cache_miss_tokens={pt}\n"
                )
                
            if finish_reason_last is not None:
                fr_str = str(finish_reason_last)
                if "STOP" not in fr_str.upper():
                    info_parts.append(f"finish_reason={fr_str}")
            
            info_tail = "\n".join(info_parts) if info_parts else ""
            
            return {
                "reasoning": full_reasoning,
                "content": full_response,
                "information": info_tail
            }
        
        except Exception as e:
            if self.stream_statu == False:
                return "stop"
            else:
                raise ValueError(f"Gemini stream failed: {e}") from e
        
        finally:
            self._response_stream = None
            self.stream_statu = False

    def _stream_kimi(self, prompt: List[Dict[str, str]], model: str, base_url: str, api_key: str, reasoning_callback: Callable, content_callback: Optional[Callable] = None):
            """
            Kimi API 流式请求与增量输出处理（统一返回字典格式）
            
            - 始终返回: {'reasoning': str, 'content': str, 'information': str}
            - information 尾部包含 created、usage、finish_reason
            
            Args:
                prompt: LLM消息序列
                model: 模型名称
                base_url: API 基础地址（Kimi）
                api_key: API Key
                reasoning_callback: 推理内容的流式回调
                content_callback: 主内容的流式回调（用于创作阶段）。为空时启用JSON输出
                
            Returns:
                dict: {'reasoning': str, 'content': str, 'information': str} 或 "stop"
            """
            import os
            
            # 清除可能冲突的环境变量
            for key in ['OPENAI_API_KEY', 'MOONSHOT_API_KEY']:
                if key in os.environ:
                    del os.environ[key]
            
            # 清理 API Key 和 Base URL（去除空格和换行）
            api_key = api_key.strip()
            base_url = base_url.strip()
            
            # 显式传递 API Key，不依赖环境变量
            client = OpenAI(api_key=api_key, base_url=base_url)
            
            if content_callback:
                stream_filter = StreamFilterOptimized(output_callback=content_callback)
            else:
                stream_filter = None
            
            try:
                # 构建请求参数
                request_params = {
                    "model": model,
                    "messages": prompt,
                    "stream": True,
                    "max_tokens": 32 * 1024,  # Kimi 推荐 ≥ 16,000
                    "temperature": 1.0,  # Kimi 推荐 temperature = 1.0
                }
                
                # 当 content_callback 为空时，启用 JSON 输出模式
                if content_callback is None:
                    request_params["response_format"] = {"type": "json_object"}
                
                self._response_stream = client.chat.completions.create(**request_params)
                
                full_response = ""
                full_reasoning = ""
                reasoning_ended = False
                finish_reason_last = None
                created_ts = None
                usage_final = None
                
                for chunk in self._response_stream:
                    # 提取时间戳
                    if getattr(chunk, "created", None) is not None:
                        created_ts = chunk.created
                    
                    choices = getattr(chunk, "choices", [])
                    if isinstance(choices, list) and choices:
                        # 提取 finish_reason
                        fr = getattr(choices[0], "finish_reason", None)
                        if fr is not None:
                            finish_reason_last = fr
                        
                        # ⚠️ Kimi 特殊：usage 可能在 choices[0] 中
                        choice_usage = getattr(choices[0], "usage", None)
                        if choice_usage is not None:
                            usage_final = choice_usage
                    
                    # ⚠️ Kimi 也可能在顶层 chunk.usage
                    chunk_usage = getattr(chunk, "usage", None)
                    if chunk_usage is not None:
                        usage_final = chunk_usage
                    
                    if self.stream_statu:
                        # Kimi 使用 reasoning_content 字段（与 DeepSeek 相同）
                        if (hasattr(choices[0].delta, 'reasoning_content') and 
                            choices[0].delta.reasoning_content is not None):
                            reasoning = choices[0].delta.reasoning_content
                            reasoning_callback(reasoning)
                            full_reasoning += reasoning
                        
                        if choices[0].delta.content is not None:
                            content = choices[0].delta.content
                            full_response += content
                            if content_callback:
                                stream_filter.process_chunk(content)
                            else:
                                if not reasoning_ended:
                                    reasoning_callback("\n")
                                    reasoning_ended = True
                                reasoning_callback(content)
                    else:
                        return "stop"
                
                # 统一组装信息尾部
                info_parts = []
                if created_ts is not None:
                    human = datetime.fromtimestamp(created_ts).isoformat(timespec="seconds")
                    info_parts.append(f"time:{human}")
                
                if usage_final is not None:
                    # 处理 usage 可能是对象或字典
                    if isinstance(usage_final, dict):
                        pt = usage_final.get("prompt_tokens", 0)
                        ct = usage_final.get("completion_tokens", 0)
                        tt = usage_final.get("total_tokens", 0)
                    else:
                        pt = getattr(usage_final, "prompt_tokens", 0)
                        ct = getattr(usage_final, "completion_tokens", 0)
                        tt = getattr(usage_final, "total_tokens", 0)
                    
                    # Kimi 不提供 cache 信息，统一格式输出
                    info_parts.append(
                        f"output_tokens={ct}\n"
                        f"input_cache_hit_tokens=0\n"
                        f"input_cache_miss_tokens={pt}\n"
                        f"total_tokens={tt}"
                    )
                else:
                    # 如果没有 usage 信息，添加警告
                    info_parts.append(
                        f"output_tokens=unknown\n"
                        f"input_cache_hit_tokens=0\n"
                        f"input_cache_miss_tokens=unknown\n"
                        f"total_tokens=unknown"
                    )
                
                if finish_reason_last is not None and str(finish_reason_last).lower() != "stop":
                    info_parts.append(f"finish_reason={finish_reason_last}")
                
                info_tail = "\n".join(info_parts) if info_parts else ""
                
                return {
                    "reasoning": full_reasoning,
                    "content": full_response,
                    "information": info_tail
                }
            
            except Exception as e:
                if self.stream_statu == False:
                    return "stop"
                else:
                    raise ValueError(f"Kimi stream failed: {e}") from e
            
            finally:
                self._response_stream = None
                self.stream_statu = False
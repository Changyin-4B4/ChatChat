class StreamFilterOptimized:
    """流式过滤器"""
    
    # 系统内核标签 - 硬编码
    SYSTEM_TAGS = {"preparation", "main_body", "scene", "summary"}
    
    def __init__(self, output_callback=None):
        # 核心状态变量
        self.tag_flag = False           # 标签检测标志
        self.output_flag = False        # 放行标志
        self.tag_content = ""           # 标签内容寄存器（不含<>）
        
        # 配置参数
        self.output_callback = output_callback or default_print
        
        # 标签栈（处理嵌套）
        self.tag_stack = []

    def process_chunk(self, chunk):
        """逐字符状态机处理"""
        for char in chunk:
            self._process_char(char)
    
    def _process_char(self, char):
        """单字符状态机核心逻辑"""
        if char == '<':
            # 检测到标签开始
            self.tag_flag = True
            self.tag_content = ""  # 直接存储标签内容
            
        elif char == '>' and self.tag_flag:
            # 标签结束，触发比较事件
            self._handle_complete_tag()
            self.tag_flag = False
            self.tag_content = ""
            
        elif self.tag_flag:
            # 标签内容，存入寄存器
            self.tag_content += char
            
        else:
            # 普通字符处理
            if self.output_flag:
                self._output_char(char)
    
    def _handle_complete_tag(self):
        """完整标签处理逻辑"""
        if self.tag_content.startswith("/"):
            # 终止符处理
            end_tag = self.tag_content[1:]  # 去掉/
            if end_tag in self.SYSTEM_TAGS and self.tag_stack:
                if self.tag_stack[-1] == end_tag:
                    self.tag_stack.pop()
                    if not self.tag_stack:
                        self.output_flag = False  # 关闭放行
                        self._output_char('\n')  # 新增：输出换行符
        else:
            # 开始符处理
            if self.tag_content in self.SYSTEM_TAGS:
                self.tag_stack.append(self.tag_content)
                self.output_flag = True  # 开启放行
                
                # 新增：特殊标签的额外输出处理
                if self.tag_content == "preparation":
                    self._output_string("构思：\n")
                elif self.tag_content == "main_body":
                    self._output_string("正文：\n")
            else:
                # 新增：处理不匹配的标签
                if self.output_flag:
                    # 放行状态：输出完整标签
                    self._output_string(f"<{self.tag_content}>")
                # 不放行状态：丢弃（不做任何操作）

    def _output_string(self, text):
        """输出字符串的辅助方法"""
        for char in text:
            self._output_char(char)
    
    def _output_char(self, char):
        """字符输出"""
        self.output_callback(char)

def default_print(char):
    print(char, end='', flush=True)
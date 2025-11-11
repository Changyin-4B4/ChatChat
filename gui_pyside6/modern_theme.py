# 极简基础主题 - 只有配色
BASIC_THEME_STYLE = """
/* 主窗口背景渐变 */
QMainWindow {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 rgba(75, 90, 154, 0.95), 
        stop:0.5 rgba(154, 106, 154, 0.95), 
        stop:1 rgba(232, 168, 168, 0.95));
}

/* 全局字体 */
QWidget {
    font-family: 'Microsoft YaHei';
    color: #ffffff;
}
"""
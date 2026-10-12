# src/nodes/chat_control.py
def should_continue_chat() -> str:
    """
    檢查使用者是否希望繼續對話
    """
    res = input("要繼續對話嗎?(y/n) ")
    return "continue" if res.upper() == 'Y' else "stop"
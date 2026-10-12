# src/app/router.py
from typing import Literal, Dict, Any
from services.llm_client import answer_mode
import json
from app.logging_config import get_logger


logger = get_logger(__name__)

def answer_route(state: Dict[str, Any]) -> Literal["vector", "sql"]:
    """
    根據使用者問題決定回答方式(資料庫SQL查詢或向量資料庫向量相似性搜尋)
    """
    route_obj = answer_mode.invoke(f"""根據使用者問題判斷回答方式要走資料庫SQL查詢還是向量資料庫向量相似性搜尋
                                   
                                        規則：
                                        - 問到統計、次數、排名、平均值等需要計算的問題 → SQL
                                        - 問到觀點、看法、立場、主張或尋找相似內容 → Vector
                                        - 問題包含日期 → SQL

                                        範例：
                                        - 使用者問題: 「黃國昌委員總共發言幾次?」 -> SQL
                                        - 使用者問題: 「哪位委員提到要加強對青少年職場安全的保護？」 -> Vector
                                        - 使用者問題: 「總結蔡易餘委員在 2025-07-21 的發言內容」 -> SQL

                                        請根據以下問題進行判斷：
                                        使用者問題: {state["input_query"]}""")
    logger.info("問答路由判斷完成：mode=%s", route_obj.mode)
    if route_obj.mode == 'Vector':
        return "vector"
    elif route_obj.mode == 'SQL':
        return "sql"
    else:
        return "vector"
    
def should_continue_tool_calls(state: Dict[str, Any]) -> Literal["action", "stop"]:
    """
    根據最後一個訊息判斷是否需要繼續執行工具調用。
    """
    last = state["messages"][-1]
    return "action" if getattr(last, "tool_calls", None) else "stop"

def sql_search_success_or_fail(state: Dict[str, Any]):
    """
    根據 SQL 查詢結果判斷是否成功。若查詢結果為空或無效，則返回 "vector"，表示轉向向量相似性搜尋。
    若查詢結果是有效的資料（list），則返回 "sql"，表示使用 SQL 查詢的結果。
    """
    try:
        data = json.loads(state.get("sql_query", "[]"))
    except json.JSONDecodeError:
        logger.warning("SQL 查詢結果無法解析為 JSON，改走向量搜尋")
        data = []
    return "sql" if isinstance(data, list) and len(data) > 0 else "vector"

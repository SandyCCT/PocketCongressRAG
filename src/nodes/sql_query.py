# src/nodes/sql_query.py
from typing import Dict, Any
from services.sql_tools import build_db_schema, llm_with_tools, tools_by_name
from langchain_core.messages import HumanMessage, SystemMessage
import json
from services.llm_client import llm
from app.logging_config import get_logger


logger = get_logger(__name__)

def generate_sql_query(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    根據使用者問題與過濾條件生成 SQL 查詢語句
    """
    schema_json = build_db_schema(state)
    ai_msg = llm_with_tools.invoke(
        [
            SystemMessage(
                content=(
                    "你是 SQL 查詢產生器，請根據使用者問題與過濾條件產生 SQL。"
                    "只能產生一個唯讀 SELECT 查詢；允許使用 WITH，"
                    "但最終操作必須是 SELECT。"
                    "禁止 INSERT、UPDATE、DELETE、DROP、ALTER、CREATE、"
                    "REPLACE、ATTACH、DETACH、PRAGMA，以及任何資料或 schema 修改。"
                    "產生查詢後，使用 sql_query 工具執行。"
                )
            ),
            HumanMessage(
                content=f"""
                            結構(JSON 格式)：
                            {schema_json}

                            使用者問題：
                            {state["input_query"]}

                            過濾條件為 Mongo-style：
                            {json.dumps(state["search_filter"], ensure_ascii=False)}
                            
                            請輸出完整 SQL query（包含 SELECT、WHERE、GROUP BY、ORDER BY...如需要）。
                            注意如果使用者問題只包含月份而沒有年份，使用`strftime` 函式來篩選月份，不要隨意編造年份！！
                    
                            產生完整 SQL query 後，呼叫 `sql_query` 工具執行查詢。
                            """)
        ])
    return {"messages": [ai_msg]}

def tool_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    執行 SQL 查詢工具，並返回查詢結果
    """
    last = state["messages"][-1]
    for tool_call in getattr(last, "tool_calls", []) or []:
        tool = tools_by_name[tool_call["name"]]
        observation = tool.invoke(tool_call["args"])
        return {"sql_query": json.dumps(observation, ensure_ascii=False)}
    return {"sql_query": "[]"}

def llm_call(state: Dict[str, Any]):
    """
    使用 LLM 根據使用者問題與SQL查詢結果生成最終回答
    """
    logger.info("使用 SQL 查詢結果產生回答")
    final_answer = llm.invoke(f"""
                    你是立法院問答系統，請根據使用者問題與SQL查詢結果提供精確的回應。
                    如果回答包含筆數或人數，輸出前必須逐筆核對 SQL 查詢結果，
                    確認統計數字與實際列出的項目數量完全一致，不可估算或省略項目。
                
                    使用者問題:
                    {state["input_query"]}
                
                    SQL查詢結果:
                    {state["sql_query"]}
                    """
            )
    return {"response": final_answer.content}

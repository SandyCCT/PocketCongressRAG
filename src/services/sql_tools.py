# src/services/sql_tool.py
import sqlite3
import pandas as pd
from pathlib import Path
import re
from typing import Dict, Any
import json
from langchain_core.tools import tool
from services.llm_client import llm
import app.config as config
from app.logging_config import get_logger


logger = get_logger(__name__)


READ_ONLY_QUERY_PATTERN = re.compile(r"^\s*(SELECT|WITH)\b", re.IGNORECASE)

BLOCKED_SQLITE_ACTIONS = {
    sqlite3.SQLITE_INSERT,
    sqlite3.SQLITE_UPDATE,
    sqlite3.SQLITE_DELETE,
    sqlite3.SQLITE_CREATE_INDEX,
    sqlite3.SQLITE_CREATE_TABLE,
    sqlite3.SQLITE_CREATE_TEMP_INDEX,
    sqlite3.SQLITE_CREATE_TEMP_TABLE,
    sqlite3.SQLITE_CREATE_TEMP_TRIGGER,
    sqlite3.SQLITE_CREATE_TEMP_VIEW,
    sqlite3.SQLITE_CREATE_TRIGGER,
    sqlite3.SQLITE_CREATE_VIEW,
    sqlite3.SQLITE_DROP_INDEX,
    sqlite3.SQLITE_DROP_TABLE,
    sqlite3.SQLITE_DROP_TEMP_INDEX,
    sqlite3.SQLITE_DROP_TEMP_TABLE,
    sqlite3.SQLITE_DROP_TEMP_TRIGGER,
    sqlite3.SQLITE_DROP_TEMP_VIEW,
    sqlite3.SQLITE_DROP_TRIGGER,
    sqlite3.SQLITE_DROP_VIEW,
    sqlite3.SQLITE_ALTER_TABLE,
    sqlite3.SQLITE_REINDEX,
    sqlite3.SQLITE_ANALYZE,
    sqlite3.SQLITE_ATTACH,
    sqlite3.SQLITE_DETACH,
    sqlite3.SQLITE_TRANSACTION,
    sqlite3.SQLITE_SAVEPOINT,
    sqlite3.SQLITE_PRAGMA,
}


def is_read_only_query(query: str) -> bool:
    """只接受以 SELECT 或 WITH 開頭的查詢。"""
    return bool(READ_ONLY_QUERY_PATTERN.match(query))


def authorize_read_only(
    action_code: int,
    argument_1: str | None,
    argument_2: str | None,
    database_name: str | None,
    trigger_name: str | None,
) -> int:
    """拒絕 SQLite 寫入、schema 變更與連接其他資料庫。"""
    if action_code in BLOCKED_SQLITE_ACTIONS:
        return sqlite3.SQLITE_DENY

    if (
        action_code == sqlite3.SQLITE_FUNCTION
        and (argument_2 or "").lower() == "load_extension"
    ):
        return sqlite3.SQLITE_DENY

    return sqlite3.SQLITE_OK


def create_read_only_connection(database_path: str) -> sqlite3.Connection:
    """以 SQLite URI 唯讀模式建立查詢連線。"""
    database_uri = f"{Path(database_path).resolve().as_uri()}?mode=ro"
    connection = sqlite3.connect(database_uri, uri=True)
    connection.execute("PRAGMA query_only = ON")
    connection.set_authorizer(authorize_read_only)
    return connection


def execute_read_only_query(query: str, database_path: str) -> list[dict]:
    """驗證並執行唯讀 SQL；失敗時回傳空清單供 workflow fallback。"""
    if not is_read_only_query(query):
        logger.warning("已拒絕非唯讀 SQL：只允許 SELECT 或 WITH 查詢")
        return []

    try:
        with create_read_only_connection(database_path) as connection:
            return pd.read_sql_query(query, connection).to_dict(orient="records")
    except (sqlite3.Error, pd.errors.DatabaseError) as exc:
        logger.warning("唯讀 SQL 查詢失敗：error_type=%s", type(exc).__name__)
        return []

def rebuild_db(df: pd.DataFrame, choose_session: str):
    """
    用 DataFrame 重建 SQLite 資料表
    """
    connection = sqlite3.connect(config.DB_PATH)
    df.to_sql(choose_session, connection, if_exists="replace")
    connection.close()

def build_db_schema(state: Dict[str, Any]):
    """
    動態建立資料庫 schema 的 JSON 結構
    """
    schema = {
        "database_schema": [
            {
                "table": state["choose_session"],
                "columns": [
                    {"name": "委員名字", "type": "string"},
                    {"name": "原本發言內容", "type": "string"},
                    {"name": "日期", "type": "string"},
                    {"name": "議題分類", "type": "string"},
                    {"name": "會期", "type": "string"},
                ],
            }
        ]
    }
    
    schema["database_schema"][0]["columns"].extend(
        [{"name": f"所屬委員會{i+1}", "type": "string"} for i in range(state['max_committee_count'])]
    )
    schema["database_schema"][0]["columns"].extend(
        [{"name": f"涵蓋層級{i+1}", "type": "string"} for i in range(state['max_geographical_scope_count'])]
    )
    
    schema_json = json.dumps(schema, ensure_ascii=False, indent=2)
    return schema_json


# === LangChain Tool 定義 ===
@tool
def sql_query(query: str) -> list[dict]:
    """
    在 SQLite 資料庫上執行單一唯讀 SELECT 查詢並返回結果。
    """
    return execute_read_only_query(query, config.DB_PATH)
# 工具列表與映射
tools = [sql_query]
tools_by_name = {t.name: t for t in tools}
# 綁定工具的 LLM
llm_with_tools = llm.bind_tools(tools)

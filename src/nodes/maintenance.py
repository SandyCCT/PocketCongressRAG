# src/nodes/maintenance.py
import hashlib
from typing import Dict, Any
from datetime import datetime
import pandas as pd
from services.history_store import load_row_count_history, save_row_count_history
from services.sql_tools import rebuild_db
from services.vector_store import rebuild_vector_db
from services.llm_client import EMBEDDING_MODEL, EMBEDDING_PROVIDER
from pathlib import Path
import app.config as config
import shutil
from app.logging_config import get_logger


INDEX_SCHEMA_VERSION = 1
logger = get_logger(__name__)


def calculate_data_fingerprint(dataframe: pd.DataFrame) -> str:
    """計算處理後資料的穩定 SHA-256 fingerprint。"""
    normalized_df = dataframe.reindex(
        sorted(dataframe.columns, key=str),
        axis=1,
    )
    row_hashes = pd.util.hash_pandas_object(
        normalized_df,
        index=False,
        categorize=True,
    )

    hasher = hashlib.sha256()
    for column_name, dtype in normalized_df.dtypes.items():
        hasher.update(str(column_name).encode("utf-8"))
        hasher.update(b"\0")
        hasher.update(str(dtype).encode("utf-8"))
        hasher.update(b"\0")
    hasher.update(row_hashes.to_numpy().tobytes())
    return hasher.hexdigest()

def get_row_count(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    取得資料筆數、處理後資料 fingerprint 與歷史紀錄
    """
    row_count_history = load_row_count_history(config.ROW_COUNT_HISTORY_PATH)
    data_fingerprint = calculate_data_fingerprint(state["final_merged_df"])
    return {
        "counts": state["counts"],
        "data_fingerprint": data_fingerprint,
        "row_count_history": row_count_history,
    }

def rebuild(state: Dict[str, Any]):
    """
    偵測到更新時，重建 vector db 與 db，並更新歷史紀錄 JSON 檔
    保留最新的 chroma uuid 資料夾，刪除舊的
    """
    choose_session = state["choose_session"]
    logger.info(
        "偵測到更新，開始重建：session=%s previous_rows=%s current_rows=%s",
        choose_session,
        state["row_count_history"].get(choose_session, {}).get("total_rows", 0),
        state.get("counts", {}).get("total", 0),
    )
    # 重建 vector db
    rebuild_vector_db(state['final_merged_df'], choose_session)
    # 重建 db
    rebuild_db(state['final_merged_df'], choose_session)

    chroma_dir_path = Path(config.CHROMA_DIR) 
    dirs = [d for d in chroma_dir_path.iterdir() if d.is_dir()]
    # 取得最新產生的資料夾
    latest = max(dirs, key=lambda d: d.stat().st_mtime)

    if choose_session not in state["row_count_history"]:
        state["row_count_history"][choose_session] = {}
    state["row_count_history"][choose_session].update({
        "total_rows": state["counts"]["total"],
        "per_sheet": state["counts"]["per_sheet"],
        "data_fingerprint": state["data_fingerprint"],
        "embedding_provider": EMBEDDING_PROVIDER,
        "embedding_model": EMBEDDING_MODEL,
        "index_schema_version": INDEX_SCHEMA_VERSION,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "source_file": Path(state["excel_path"]).name,
        "chroma_uuid_dir_name": latest.name}) 
    save_row_count_history(config.ROW_COUNT_HISTORY_PATH, state["row_count_history"]) 

    # 紀錄目前向量資料庫中各個collection對應的uuid資料夾，將舊的刪除
    keep_uuids = [v["chroma_uuid_dir_name"] for v in state["row_count_history"].values() if "chroma_uuid_dir_name" in v]
    for d in dirs:
        if d.name not in keep_uuids:
            shutil.rmtree(f'{config.CHROMA_DIR}/{d.name}')
            logger.info("已刪除舊的 Chroma UUID 資料夾：%s", d.name)
        else:
            logger.debug("保留目前 Chroma UUID 資料夾：%s", d.name)

def need_rebuild(state: Dict[str, Any]) -> str:
    """
    根據資料 fingerprint、embedding model 與索引版本判斷是否重建
    """
    session = state["row_count_history"].get(state["choose_session"])
    if session is None:
        logger.info("此會期尚未建立索引，需要重建：session=%s", state["choose_session"])
        return "rebuild"

    if session.get("data_fingerprint") != state["data_fingerprint"]:
        logger.info(
            "資料內容已變更或尚未記錄 fingerprint，需要重建：session=%s",
            state["choose_session"],
        )
        return "rebuild"

    if session.get("embedding_provider") != EMBEDDING_PROVIDER:
        logger.info(
            "Embedding provider 已變更 "
            "(%s → %s)，需要重建向量庫：session=%s",
            session.get("embedding_provider", "未記錄"),
            EMBEDDING_PROVIDER,
            state["choose_session"],
        )
        return "rebuild"

    if session.get("embedding_model") != EMBEDDING_MODEL:
        logger.info(
            "Embedding model 已變更 "
            "(%s → %s)，需要重建向量庫：session=%s",
            session.get("embedding_model", "未記錄"),
            EMBEDDING_MODEL,
            state["choose_session"],
        )
        return "rebuild"

    if session.get("index_schema_version") != INDEX_SCHEMA_VERSION:
        logger.info(
            "索引版本已變更 "
            "(%s → %s)，需要重建：session=%s",
            session.get("index_schema_version", "未記錄"),
            INDEX_SCHEMA_VERSION,
            state["choose_session"],
        )
        return "rebuild"

    logger.info(
        "資料內容、Embedding provider、Embedding model 與索引版本皆無更新，"
        "略過重建："
        "session=%s total_rows=%s",
        state["choose_session"],
        state["counts"]["total"],
    )
    return "not rebuild"

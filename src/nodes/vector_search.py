# src/nodes/vector_search.py
from typing import Dict, Any
from services.llm_client import llm, embeddings
from langchain_chroma import Chroma
from chromadb.errors import ChromaError
import app.config as config
from app.logging_config import get_logger


logger = get_logger(__name__)

def vector_search(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    使用向量資料庫進行相似性搜尋，並返回相關文件內容
    llm 根據使用者問題與相關文件內容生成最終回答
    """
    logger.info("開始向量相似性搜尋：session=%s", state["choose_session"])
    try:
        vector_db = Chroma(
            embedding_function=embeddings,
            persist_directory=config.CHROMA_DIR,
            collection_name=state["choose_session"],
        )
        retriever = vector_db.as_retriever(
            search_kwargs={
                "k": 20,
                "filter": state["search_filter"]}
        )
        filtered_docs = retriever.invoke(state["input_query"])
        # for d in filtered_docs:
        #     print(d.metadata, d.page_content)
    except (ChromaError, ValueError, TypeError) as exc:
        logger.warning(
            "向量相似性搜尋失敗：session=%s error_type=%s",
            state["choose_session"],
            type(exc).__name__,
        )
        msg = "向量檢索失敗，請稍後再試。"
        return {"response": msg}

    if not filtered_docs:
        msg = "資料集中找不到跟問題有關的資訊！"
        return {"response": msg}

    combined = "\n\n".join(f"{doc.metadata}\n{doc.page_content}" for doc in filtered_docs)
    final_answer = llm.invoke(f"""
                你是立法院問答系統，請遵守以下回答規則：
                1. 基於資料回答問題，提供詳細的結論。
                2. 列出支持該結論的主要依據。
                3. 若資料中無法回答該問題，回覆：「此問題的答案在資料集中找不到無法回答」。

                問題：
                {state["input_query"]}

                資料：
                {combined}
                """)
    return {"response": final_answer.content}

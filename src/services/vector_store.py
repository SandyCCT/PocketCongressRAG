# src/services/vector_store.py
import os
import pandas as pd
from langchain_chroma import Chroma
from services.doc_converter import convert_df_to_docs
from services.document_ids import build_document_ids
from services.llm_client import embeddings
from chromadb import PersistentClient
from chromadb.errors import NotFoundError
import app.config as config
from app.logging_config import get_logger


logger = get_logger(__name__)

def rebuild_vector_db(df: pd.DataFrame, choose_session: str):
    """
    如果已存在舊的 collection，先刪除再建立新的(每個會期一個collection)
    """
    os.makedirs(config.CHROMA_DIR, exist_ok=True)
    client = PersistentClient(path=config.CHROMA_DIR)
    try:
        client.delete_collection(choose_session)
        logger.info("已刪除舊的 Chroma collection：session=%s", choose_session)
    except NotFoundError:
        logger.info("Chroma collection 不存在，略過刪除：session=%s", choose_session)

    langchain_docs = convert_df_to_docs(df)
    # print(langchain_docs)
    Chroma.from_documents(
        documents=langchain_docs,
        embedding=embeddings,
        collection_name=choose_session,
        persist_directory=config.CHROMA_DIR,
        ids=build_document_ids(choose_session, len(langchain_docs)),
    )

# src/services/doc_converter.py
import pandas as pd
from langchain_core.documents import Document

def convert_df_to_docs(df: pd.DataFrame):
    """
    將 DataFrame 轉換成 LangChain Document 物件清單
    """
    rag_docs = []

    for _, row in df.iterrows():
        metadata = {
            "委員名字": row['委員名字'].strip()
        }
        for col in df.columns:
            if col.startswith('所屬委員會') or col.startswith('涵蓋層級'):
                metadata[col] = row[col]
        content = f"日期: {row['日期'].strip()}\n會期: {row['會期'].strip()}\n議題分類: {row['議題分類'].strip()}\n發言內容: {row['原本發言內容'].strip()}"
        if content.strip():
            rag_docs.append(Document(page_content=content, metadata=metadata))
    return rag_docs
# src/services/llm_client.py
import app.config as config
from pydantic import BaseModel, Field
from services.provider_factory import create_chat_model, create_embeddings
from typing import Literal

CHAT_MODEL = (
    config.OPENAI_CHAT_MODEL
    if config.CHAT_PROVIDER == "openai"
    else config.VERTEX_CHAT_MODEL
)
EMBEDDING_PROVIDER = config.EMBEDDING_PROVIDER
EMBEDDING_MODEL = (
    config.OPENAI_EMBEDDING_MODEL
    if config.EMBEDDING_PROVIDER == "openai"
    else config.VERTEX_EMBEDDING_MODEL
)

# 初始化 LLM
llm = create_chat_model()

# 初始化 Embeddings
embeddings = create_embeddings()


# === Routing 專用 ===
class Route(BaseModel):
    mode: Literal["SQL", "Vector"] = Field(
        description="根據使用者問題判斷回答方式要走資料庫SQL查詢還是向量資料庫向量相似性搜尋",
    )

# LLM 包裝成結構化輸出器
answer_mode = llm.with_structured_output(Route)

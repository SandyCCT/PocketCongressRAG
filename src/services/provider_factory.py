import app.config as config
from langchain_core.embeddings import Embeddings
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from services.vertex_embeddings import VertexAIEmbeddings


def create_chat_model() -> BaseChatModel:
    """依設定建立聊天模型 client。"""
    if config.CHAT_PROVIDER == "openai":
        return ChatOpenAI(
            api_key=config.OPENAI_API_KEY,
            model=config.OPENAI_CHAT_MODEL,
            timeout=config.AI_REQUEST_TIMEOUT_SECONDS,
            max_retries=config.AI_MAX_RETRIES,
        )
    if config.CHAT_PROVIDER == "vertexai":
        from services.vertex_chat import TimeoutChatVertexAI

        return TimeoutChatVertexAI(
            model=config.VERTEX_CHAT_MODEL,
            project=config.GOOGLE_CLOUD_PROJECT,
            location=config.GOOGLE_CLOUD_LOCATION,
            # 2.0.28 的 max_retries 是總嘗試次數，需包含首次請求。
            max_retries=config.AI_MAX_RETRIES + 1,
            request_timeout_seconds=config.AI_REQUEST_TIMEOUT_SECONDS,
        )
    raise ValueError(f"不支援的 chat provider：{config.CHAT_PROVIDER}")


def create_embeddings() -> Embeddings:
    """依設定建立 embedding model client。"""
    if config.EMBEDDING_PROVIDER == "openai":
        return OpenAIEmbeddings(
            api_key=config.OPENAI_API_KEY,
            model=config.OPENAI_EMBEDDING_MODEL,
            timeout=config.AI_REQUEST_TIMEOUT_SECONDS,
            max_retries=config.AI_MAX_RETRIES,
        )
    if config.EMBEDDING_PROVIDER == "vertexai":
        return VertexAIEmbeddings(
            model=config.VERTEX_EMBEDDING_MODEL,
            project=config.GOOGLE_CLOUD_PROJECT,
            location=config.GOOGLE_CLOUD_LOCATION,
            request_timeout_seconds=config.AI_REQUEST_TIMEOUT_SECONDS,
            max_retries=config.AI_MAX_RETRIES,
        )
    raise ValueError(
        f"不支援的 embedding provider：{config.EMBEDDING_PROVIDER}"
    )

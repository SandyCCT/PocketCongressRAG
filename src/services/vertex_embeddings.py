import time

from google import genai
from google.genai.errors import ClientError, ServerError
from google.genai.types import EmbedContentConfig, HttpOptions, HttpRetryOptions
from langchain_core.embeddings import Embeddings

from app.exceptions import AIProviderError, RetryableAIProviderError


DEFAULT_BATCH_SIZE = 20
DEFAULT_REQUEST_INTERVAL_SECONDS = 1.0
DEFAULT_REQUEST_TIMEOUT_SECONDS = 60.0
DEFAULT_MAX_RETRIES = 2
RETRYABLE_CLIENT_STATUS_CODES = {408, 429}


class VertexAIEmbeddings(Embeddings):
    """使用 Google Gen AI SDK 呼叫 Vertex AI text embeddings。"""

    def __init__(
        self,
        model: str,
        project: str,
        location: str,
        batch_size: int = DEFAULT_BATCH_SIZE,
        request_interval_seconds: float = DEFAULT_REQUEST_INTERVAL_SECONDS,
        request_timeout_seconds: float = DEFAULT_REQUEST_TIMEOUT_SECONDS,
        max_retries: int = DEFAULT_MAX_RETRIES,
    ) -> None:
        if batch_size < 1:
            raise ValueError("batch_size 必須是正整數")
        if request_interval_seconds < 0:
            raise ValueError("request_interval_seconds 不可小於 0")
        if request_timeout_seconds <= 0:
            raise ValueError("request_timeout_seconds 必須大於 0")
        if max_retries < 0:
            raise ValueError("max_retries 不可小於 0")
        self.model = model
        self.batch_size = batch_size
        self.request_interval_seconds = request_interval_seconds
        self.client = genai.Client(
            vertexai=True,
            project=project,
            location=location,
            http_options=HttpOptions(
                api_version="v1",
                timeout=int(request_timeout_seconds * 1000),
                retry_options=HttpRetryOptions(attempts=max_retries + 1),
            ),
        )

    def _embed(self, texts: list[str], task_type: str) -> list[list[float]]:
        vectors: list[list[float]] = []
        for start in range(0, len(texts), self.batch_size):
            batch = texts[start:start + self.batch_size]
            try:
                response = self.client.models.embed_content(
                    model=self.model,
                    contents=batch,
                    config=EmbedContentConfig(task_type=task_type),
                )
            except ServerError as exc:
                raise RetryableAIProviderError(
                    "Vertex AI embedding request failed"
                ) from exc
            except ClientError as exc:
                status_code = exc.code or 0
                error_type = (
                    RetryableAIProviderError
                    if status_code in RETRYABLE_CLIENT_STATUS_CODES
                    or status_code >= 500
                    else AIProviderError
                )
                raise error_type(
                    "Vertex AI embedding request failed"
                ) from exc
            embeddings = response.embeddings
            if embeddings is None or len(embeddings) != len(batch):
                raise AIProviderError("Vertex AI embedding 回傳數量不一致")
            for embedding in embeddings:
                if not embedding.values:
                    raise AIProviderError("Vertex AI embedding 回傳空白向量")
                vectors.append(list(embedding.values))
            if start + self.batch_size < len(texts):
                time.sleep(self.request_interval_seconds)
        return vectors

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """建立供 Chroma 儲存的文件向量。"""
        return self._embed(texts, "RETRIEVAL_DOCUMENT")

    def embed_query(self, text: str) -> list[float]:
        """建立向量搜尋使用的查詢向量。"""
        return self._embed([text], "RETRIEVAL_QUERY")[0]

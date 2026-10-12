from typing import Any

from langchain_core.callbacks import (
    AsyncCallbackManagerForLLMRun,
    CallbackManagerForLLMRun,
)
from langchain_core.messages import BaseMessage
from langchain_core.outputs import ChatResult
from langchain_google_vertexai import ChatVertexAI
from pydantic import Field


class TimeoutChatVertexAI(ChatVertexAI):
    """為 Gemini 非串流請求提供共用 timeout，包含工具與結構化輸出。"""

    request_timeout_seconds: float = Field(default=60.0, gt=0)

    # langchain-google-vertexai 2.0.28 只將呼叫端的 timeout 傳給 SDK。
    def _generate_gemini(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        kwargs.setdefault("timeout", self.request_timeout_seconds)
        return super()._generate_gemini(
            messages=messages,
            stop=stop,
            run_manager=run_manager,
            **kwargs,
        )

    async def _agenerate_gemini(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        kwargs.setdefault("timeout", self.request_timeout_seconds)
        return await super()._agenerate_gemini(
            messages=messages,
            stop=stop,
            run_manager=run_manager,
            **kwargs,
        )

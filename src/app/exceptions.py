class IndexNotReadyError(RuntimeError):
    """部署資料與既有索引不一致。"""


class AIProviderError(RuntimeError):
    """外部 AI provider 無法完成請求。"""


class RetryableAIProviderError(AIProviderError):
    """外部 AI provider 發生可重試的暫時性錯誤。"""

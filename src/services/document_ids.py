def build_document_ids(session_id: str, document_count: int) -> list[str]:
    """建立同一會期內可重現的 Chroma 文件 ID。"""
    normalized_session_id = session_id.strip()
    if not normalized_session_id:
        raise ValueError("session_id 不得為空")
    if document_count < 0:
        raise ValueError("document_count 不得小於 0")

    return [
        f"{normalized_session_id}:{index:08d}"
        for index in range(document_count)
    ]

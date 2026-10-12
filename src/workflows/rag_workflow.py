# src/workflows/rag_workflow.py
from typing import Any, Dict

from google.api_core.exceptions import GoogleAPIError
from langgraph.graph import StateGraph, START, END
from openai import APIError as OpenAIAPIError
import app.config as config
from app.exceptions import AIProviderError, IndexNotReadyError
from app.state import State
from nodes.maintenance import (
    INDEX_SCHEMA_VERSION,
    get_row_count,
    rebuild,
    need_rebuild,
)
from nodes.input_transform import user_input_and_transform
from nodes.vector_search import vector_search
from nodes.sql_query import generate_sql_query, tool_node, llm_call
from app.router import answer_route, should_continue_tool_calls, sql_search_success_or_fail
from services.deployment_metadata import RuntimeMetadata, validate_runtime_metadata
from services.filter_utils import build_filter_options
from services.llm_client import EMBEDDING_MODEL, EMBEDDING_PROVIDER
from services.preprocessing import preprocess_and_merge

# === 建立 workflow ===
rag_builder = StateGraph(State)

# Add nodes
rag_builder.add_node("user_input_and_transform", user_input_and_transform)
rag_builder.add_node("vector_search", vector_search)
rag_builder.add_node("generate_sql_query", generate_sql_query)
rag_builder.add_node("tool_node", tool_node)
rag_builder.add_node("llm_call", llm_call)

# Add edges (nodes 之間的連線)
rag_builder.add_edge(START, "user_input_and_transform")
rag_builder.add_conditional_edges("user_input_and_transform", answer_route, {
    "vector": "vector_search",
    "sql": "generate_sql_query",
})
rag_builder.add_conditional_edges("generate_sql_query", should_continue_tool_calls, {
    "action": "tool_node",
    "stop": "vector_search",
})
rag_builder.add_conditional_edges("tool_node", sql_search_success_or_fail, {
    "sql": "llm_call",
    "vector": "vector_search",
})
rag_builder.add_edge("llm_call", END)
rag_builder.add_edge("vector_search", END)

# Compile workflow
optimizer_workflow = rag_builder.compile()


def prepare_local_session(excel_path: str, choose_session: str) -> Dict[str, Any]:
    """從本機 Excel 前處理會期資料，並檢查是否需要重建索引。"""
    (
        final_merged_df,
        max_committee_count,
        max_geographical_scope_count,
        counts,
    ) = preprocess_and_merge(excel_path)
    state = {
        "excel_path": excel_path,
        "choose_session": choose_session,
        "final_merged_df": final_merged_df,
        "max_committee_count": max_committee_count,
        "max_geographical_scope_count": max_geographical_scope_count,
        "filter_options": build_filter_options(final_merged_df),
        "counts": counts,
    }
    state.update(get_row_count(state))
    if need_rebuild(state) == "rebuild":
        if config.INDEX_REBUILD_POLICY == "verify_only":
            raise IndexNotReadyError(
                f"索引與部署資料不一致：session={choose_session}"
            )
        rebuild(state)
    return state


def prepare_runtime_session(
    runtime_metadata: RuntimeMetadata,
    choose_session: str,
) -> Dict[str, Any]:
    """從已建置的 runtime metadata 準備唯讀問答狀態。"""
    metadata = validate_runtime_metadata(runtime_metadata)
    if metadata["embedding_provider"] != EMBEDDING_PROVIDER:
        raise IndexNotReadyError(
            f"Embedding provider 與部署資料不一致：session={choose_session}"
        )
    if metadata["embedding_model"] != EMBEDDING_MODEL:
        raise IndexNotReadyError(
            f"Embedding model 與部署資料不一致：session={choose_session}"
        )
    if metadata["index_schema_version"] != INDEX_SCHEMA_VERSION:
        raise IndexNotReadyError(
            f"索引版本與部署資料不一致：session={choose_session}"
        )

    session_metadata = metadata["sessions"].get(choose_session)
    if session_metadata is None:
        raise ValueError(f"找不到指定的會期：session={choose_session}")

    return {
        "choose_session": choose_session,
        "max_committee_count": session_metadata["max_committee_count"],
        "max_geographical_scope_count": session_metadata[
            "max_geographical_scope_count"
        ],
        "filter_options": {
            field_name: list(values)
            for field_name, values in session_metadata["filter_options"].items()
        },
    }


def run_one_question(
    prepared_state: Dict[str, Any],
    user_inputs: Dict[str, str],
) -> str:
    """執行一次問答並回傳答案。"""
    try:
        state = optimizer_workflow.invoke({
            **prepared_state,
            "user_inputs": user_inputs,
        })
    except AIProviderError:
        raise
    except (OpenAIAPIError, GoogleAPIError) as exc:
        raise AIProviderError("AI provider request failed") from exc
    return state["response"]

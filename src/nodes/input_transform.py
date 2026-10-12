# src/nodes/input_transform.py
from typing import Dict, Any
from services.normalizers import normalize_filters_with_llm
from services.filters import parse_llm_response_to_dict, build_final_filter

def user_input_and_transform(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    將使用者輸入的篩選條件和問題轉換為查詢格式
    """
    user_inputs = state["user_inputs"]
    unprocessed_search_answer = normalize_filters_with_llm(
        state["filter_options"],
        user_inputs,
    )
    processed_search_answer = parse_llm_response_to_dict(unprocessed_search_answer)
    search_filter = build_final_filter(processed_search_answer, state)
    return {"search_filter": search_filter, "input_query": user_inputs["問題"]}

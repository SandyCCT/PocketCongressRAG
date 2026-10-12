# src/services/filters.py
from typing import Dict, Any
from services.filter_utils import build_multi_value_filter, build_multi_field_filter
from app.logging_config import get_logger


logger = get_logger(__name__)

def parse_llm_response_to_dict(unprocessed_search_answer: str) -> Dict[str, str]:
    """
    把 LLM 回傳的 "key:value、key:value..." 字串解析成 dict
    """
    pairs = unprocessed_search_answer.split('、')
    processed_search_answer = {}
    for pair in pairs:
        k, v = pair.split(':', 1)
        k, v = k.strip(), v.strip()
        if k in processed_search_answer:
            if processed_search_answer[k] != v:
                processed_search_answer[k] = processed_search_answer[k] + ',' + v
        else:
            processed_search_answer[k] = v
    logger.debug(
        "已解析 LLM 篩選條件：fields=%s",
        sorted(processed_search_answer),
    )
    return processed_search_answer

def build_final_filter(processed_search_answer: Dict[str, str], state: Dict[str, Any]):
    """
    把 dict 轉換成 Mongo-style 篩選條件
    """
    filter_conditions = []
    for k, v in processed_search_answer.items():
        # 不用篩選
        if v == 'all' or v == '':
            continue
        if k == '所屬委員會':
            committee_value_filter = build_multi_value_filter(v, k, True, state['max_committee_count'])
            if committee_value_filter:
                filter_conditions.append(committee_value_filter)
            else:
                committee_filter = build_multi_field_filter(v, state['max_committee_count'], k)
                filter_conditions.append(committee_filter)
        elif k == '涵蓋層級':
            geographical_scope_filter = build_multi_field_filter(v, state['max_geographical_scope_count'], k)
            filter_conditions.append(geographical_scope_filter)
        elif k == '委員名字':
            name_filter = build_multi_value_filter(v, k)
            if name_filter:
                filter_conditions.append(name_filter)
            else:
                filter_conditions.append({k: v})
    
    if len(filter_conditions) > 1:
        search_filter = {"$and": filter_conditions}
    elif filter_conditions:
        search_filter = filter_conditions[0]   
    else:
        search_filter = None
    return search_filter

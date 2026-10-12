# src/app/state.py
from langgraph.graph import MessagesState
from typing import Any

class State(MessagesState):
    excel_path: str
    choose_session: str
    final_merged_df: Any
    counts: dict
    data_fingerprint: str
    row_count_history: dict
    max_committee_count: int
    max_geographical_scope_count: int
    filter_options: dict
    user_inputs: dict
    input_query: str
    search_filter: Any
    vector_db: Any
    response: str
    sql_query: str

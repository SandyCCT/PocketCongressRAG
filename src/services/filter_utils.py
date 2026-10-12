# src/services/filter_utils.py
import pandas as pd
from typing import Optional


def _multi_cols_get_unique_value(
    final_merged_df: pd.DataFrame,
    prefix: str,
) -> list[str]:
    """
    從 DataFrame 中所有以 prefix 開頭的欄位取值，合併後回傳唯一值列表
    """
    specific_cols = [col for col in final_merged_df.columns if col.startswith(prefix)]
    if not specific_cols:
        return []
    combined = pd.concat([final_merged_df[col] for col in specific_cols])
    return sorted({
        value
        for value in combined.dropna().tolist()
        if isinstance(value, str) and value.strip()
    })


def build_filter_options(final_merged_df: pd.DataFrame) -> dict[str, list[str]]:
    """從前處理後的 DataFrame 建立一致的篩選選項。"""
    member_names = sorted({
        value
        for value in final_merged_df["委員名字"].dropna().tolist()
        if isinstance(value, str) and value.strip()
    })
    return {
        "member_names": member_names,
        "committees": _multi_cols_get_unique_value(
            final_merged_df,
            "所屬委員會",
        ),
        "geographical_scopes": _multi_cols_get_unique_value(
            final_merged_df,
            "涵蓋層級",
        ),
    }

def build_multi_field_filter(selected_value: str, max_count: int, field_name: str):
    """
    建立多欄位 OR 條件，例如 所屬委員會1..n, 涵蓋層級1..n
    """
    field_filters = [
        {f"{field_name}{i}": selected_value}
        for i in range(1, max_count + 1)
    ]
    if not field_filters:
        raise ValueError("找不到可用的篩選欄位")
    if len(field_filters) == 1:
        return field_filters[0]
    return {"$or": field_filters}

def build_multi_value_filter(selected_value: str, field_name: str, multi_field: bool = False, max_count: Optional[int] = None):
    """
    建立多值 OR 條件，例如 委員名字:A,B
    """
    value_list = selected_value.split(',')
    if len(value_list) == 1:
        return None
    elif len(value_list) > 1:
        if multi_field:
            return {
                "$or": [
                    build_multi_field_filter(value_list[i], max_count, field_name)
                    for i in range(len(value_list))
                ]
            }
        return {
            "$or": [
                {field_name: value_list[i]}
                for i in range(len(value_list))
            ]
        }

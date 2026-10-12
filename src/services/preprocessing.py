# src/services/preprocessing.py
import pandas as pd
from typing import Tuple

def preprocess_and_merge(path: str) -> Tuple[pd.DataFrame, int, int, dict]:
    """
    前處理並合併多個 Excel sheet
    """
    xls = pd.read_excel(path, sheet_name=None, engine="openpyxl")

    dfs = []
    per_sheet = {}
    total_rows = 0
    for sheet_name, df in xls.items():
        row_count = len(df.dropna(how="all"))
        per_sheet[sheet_name] = int(row_count)
        total_rows += row_count
        # 日期轉成字串型態
        df['日期'] = df['日期'].astype(str)
        dfs.append(df)
    # 合併工作表
    merged_df = pd.concat(dfs, ignore_index=True)

    # 排除欄位
    cols_to_exclude = ['議題分類', '所屬委員會', '地區性／全國性']
    cols_to_process = [col for col in merged_df.columns if col not in cols_to_exclude]
    for col in cols_to_process:
        # 處理空值或純空白字串
        if col == '原本發言內容':
            merged_df[col] = merged_df[col].apply(lambda x: '無資料' if pd.isna(x) or str(x).strip() == '' else x)
        else:
            merged_df[col] = merged_df[col].apply(lambda x: 'N/A' if pd.isna(x) or str(x).strip() == '' else x)

    # 處理多值組成的字串，轉成list
    def labels_to_list(unprocessed_str: str) -> list:
        # 處理空值或純空白字串
        if pd.isna(unprocessed_str) or unprocessed_str.strip() == '':
            return []
        unprocessed_str = unprocessed_str.strip().replace('\n', '')
        processed_str = unprocessed_str.replace('；', '、').replace('／', '、')
        return [label.strip() for label in processed_str.split('、') if label.strip()]
    merged_df['committees_list'] = merged_df['所屬委員會'].apply(labels_to_list)
    merged_df['geographical_scopes_list'] = merged_df['地區性／全國性'].apply(labels_to_list)
    
    # list轉多欄位
    def list_to_multi_cols(df: pd.DataFrame, col_name: str, final_prefix_col_name: str) -> Tuple[pd.DataFrame, int]:
        max_count = df[col_name].apply(len).max()
        for i in range(max_count):
            df[f'{final_prefix_col_name}{i+1}'] = df[col_name].apply(lambda x: x[i].strip() if i < len(x) else None)
        return df, max_count
    merged_df, max_committee_count = list_to_multi_cols(merged_df, 'committees_list', '所屬委員會')
    merged_df, max_geographical_scope_count = list_to_multi_cols(merged_df, 'geographical_scopes_list', '涵蓋層級')

    # 處理多值組成的字串
    def labels_to_str(unprocessed_str: str) -> str:
        # 處理空值或純空白字串
        if pd.isna(unprocessed_str) or unprocessed_str.strip() == '':
            return '無資料'
        unprocessed_str = unprocessed_str.strip().replace('\n', '')
        processed_str = unprocessed_str.replace('；', '、').replace('／', '、')
        return processed_str
    merged_df['topics_str'] = merged_df['議題分類'].apply(labels_to_str)

    # 刪除欄位
    final_merged_df = merged_df.drop(columns=["所屬委員會", "議題分類", "地區性／全國性", "committees_list", "geographical_scopes_list"])
    # 重新命名
    final_merged_df = final_merged_df.rename(columns={'topics_str': '議題分類'})

    counts = {"per_sheet": per_sheet, "total": int(total_rows)}
    return (
        final_merged_df,
        max_committee_count,
        max_geographical_scope_count,
        counts,
    )

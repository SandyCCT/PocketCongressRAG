# src/services/history_store.py
import os
import json
from pathlib import Path

def load_row_count_history(path: str) -> dict:
    """
    讀取歷史紀錄 JSON 檔（若不存在回傳 {}）
    """
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8-sig") as f:
        return json.load(f)
    
def save_row_count_history(path: str, row_count_history: dict):
    """
    儲存最新的紀錄到歷史紀錄 JSON 檔
    """
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8-sig") as f:
        json.dump(row_count_history, f, ensure_ascii=False, indent=2)
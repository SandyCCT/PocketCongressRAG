# src/adapters/cli_inputs.py
from typing import Dict, Any, Tuple
from pathlib import Path
import re


def _session_sort_key(file_path: Path) -> Tuple[int, int, int, str]:
    """依屆次與會期排序；無法解析的檔名排在最後。"""
    match = re.match(r"第(\d+)屆第(\d+)會期", file_path.stem)
    if match:
        return 0, int(match.group(1)), int(match.group(2)), file_path.name
    return 1, 0, 0, file_path.name

def get_query_conditions_cli(state: Dict[str, Any]) -> Tuple[Dict[str, str], list, list]:
    """
    從命令列互動取得篩選條件和問題
    """
    unique_committees = state["filter_options"]["committees"]
    unique_geographical_scopes = state["filter_options"][
        "geographical_scopes"
    ]
    
    inputs = {}
    inputs["委員名字"] = input("輸入查詢的委員名字(沒有指定按enter或輸入all): ")
    inputs["涵蓋層級"] = input(f"輸入查詢的涵蓋層級(沒有指定按enter或輸入all，選項有{unique_geographical_scopes}): ")
    inputs["所屬委員會"] = input("輸入查詢的委員會(沒有指定按enter或輸入all): ")
    inputs["問題"] = input("輸入問題: ")

    return inputs, unique_committees, unique_geographical_scopes

def select_session_cli(data_folder_path: str) -> Tuple[str, str]:
    """
    從命令列互動取得要問答的會期檔案
    """
    folder_path = Path(data_folder_path)
    files = sorted(
        (f for f in folder_path.iterdir() if f.is_file() and not f.name.startswith('~$')),
        key=_session_sort_key,
    )
    file_names = [f.stem for f in files]

    options = ', '.join(f'({i}) {name}' for i, name in enumerate(file_names, start=1))
    while(True):
        choose = input(f'請選擇要問答的會期 {options}: ')
        if choose.isdigit():
            choose = int(choose)
            if 1 <= choose <= len(files):
                break
        print(f"無效輸入，請輸入1~{len(files)}的數字")
    excel_path = f'{data_folder_path}/{files[choose-1].name}'

    match = re.match(r"第(\d+)屆第(\d+)會期",file_names[choose-1])
    if match:
        choose_session = f'S_{match.group(1)}_{match.group(2)}'
    else:
        print("無法從檔名解析會期，請確認檔名格式為 '第X屆第Y會期'")
        choose_session = None
    return excel_path, choose_session

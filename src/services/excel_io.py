# src/services/excel_io.py
import pandas as pd

def read_all_sheets_total_rows(path: str) -> dict:
    """
    讀取 Excel 全部 sheet，回傳每個 sheet 的筆數與總筆數
    """
    sheets = pd.read_excel(path, sheet_name=None)
    per_sheet = {}
    total = 0
    for name, df in sheets.items():
        df = df.dropna(how="all")
        n = len(df)
        per_sheet[name] = int(n)
        total += n
    return {"per_sheet": per_sheet, "total": int(total)}
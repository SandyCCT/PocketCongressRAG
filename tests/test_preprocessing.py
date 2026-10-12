import unittest
from unittest.mock import patch

import pandas as pd

from services.preprocessing import preprocess_and_merge


class PreprocessingTests(unittest.TestCase):
    @patch("services.preprocessing.pd.read_excel")
    def test_reads_excel_once_and_returns_sheet_counts(self, read_excel) -> None:
        read_excel.return_value = {
            "Sheet1": pd.DataFrame([{
                "日期": "2025-01-01",
                "委員名字": "王育敏",
                "原本發言內容": "發言一",
                "議題分類": "教育",
                "所屬委員會": "教育及文化委員會",
                "地區性／全國性": "全國性",
            }]),
            "Sheet2": pd.DataFrame([{
                "日期": "2025-01-02",
                "委員名字": "黃國昌",
                "原本發言內容": "發言二",
                "議題分類": "司法",
                "所屬委員會": "司法及法制委員會",
                "地區性／全國性": "全國性",
            }]),
        }

        dataframe, _, _, counts = preprocess_and_merge("session.xlsx")

        read_excel.assert_called_once_with(
            "session.xlsx",
            sheet_name=None,
            engine="openpyxl",
        )
        self.assertEqual(len(dataframe), 2)
        self.assertEqual(counts, {
            "per_sheet": {"Sheet1": 1, "Sheet2": 1},
            "total": 2,
        })


if __name__ == "__main__":
    unittest.main()

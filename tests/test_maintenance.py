import unittest
from unittest.mock import patch
import pandas as pd

from nodes.maintenance import (
    EMBEDDING_MODEL,
    EMBEDDING_PROVIDER,
    INDEX_SCHEMA_VERSION,
    calculate_data_fingerprint,
    get_row_count,
    need_rebuild,
)


class DataFingerprintTests(unittest.TestCase):
    def setUp(self) -> None:
        self.dataframe = pd.DataFrame(
            [
                {
                    "委員名字": "王育敏",
                    "原本發言內容": "關注學童營養午餐。",
                    "日期": "2025-03-17",
                },
                {
                    "委員名字": "黃國昌",
                    "原本發言內容": "關注政府資訊公開。",
                    "日期": "2025-03-18",
                },
            ]
        )

    def test_same_data_produces_same_fingerprint(self) -> None:
        original = calculate_data_fingerprint(self.dataframe)
        copied = calculate_data_fingerprint(self.dataframe.copy())

        self.assertEqual(original, copied)

    def test_column_order_does_not_change_fingerprint(self) -> None:
        original = calculate_data_fingerprint(self.dataframe)
        reordered = calculate_data_fingerprint(
            self.dataframe[["日期", "原本發言內容", "委員名字"]]
        )

        self.assertEqual(original, reordered)

    def test_content_change_with_same_row_count_changes_fingerprint(self) -> None:
        changed = self.dataframe.copy()
        changed.loc[0, "原本發言內容"] = "改為關注校園食品安全。"

        self.assertNotEqual(
            calculate_data_fingerprint(self.dataframe),
            calculate_data_fingerprint(changed),
        )

    @patch("nodes.maintenance.calculate_data_fingerprint", return_value="fingerprint")
    @patch("nodes.maintenance.load_row_count_history", return_value={})
    def test_row_count_uses_preprocessed_counts(
        self, load_history, calculate_fingerprint
    ) -> None:
        state = {
            "counts": {"total": 2},
            "final_merged_df": self.dataframe,
        }

        result = get_row_count(state)

        load_history.assert_called_once()
        calculate_fingerprint.assert_called_once_with(self.dataframe)
        self.assertEqual(result["counts"], {"total": 2})
        self.assertEqual(result["data_fingerprint"], "fingerprint")


class RebuildDecisionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.current_fingerprint = "current-fingerprint"
        self.state = {
            "choose_session": "S_11_1",
            "counts": {"total": 2},
            "data_fingerprint": self.current_fingerprint,
            "row_count_history": {
                "S_11_1": {
                    "total_rows": 2,
                    "data_fingerprint": self.current_fingerprint,
                    "embedding_provider": EMBEDDING_PROVIDER,
                    "embedding_model": EMBEDDING_MODEL,
                    "index_schema_version": INDEX_SCHEMA_VERSION,
                }
            },
        }

    def test_matching_metadata_skips_rebuild(self) -> None:
        self.assertEqual(need_rebuild(self.state), "not rebuild")

    def test_selected_session_uses_its_own_history(self) -> None:
        self.state["row_count_history"]["S_11_2"] = {
            "data_fingerprint": "old-fingerprint",
            "embedding_provider": EMBEDDING_PROVIDER,
            "embedding_model": EMBEDDING_MODEL,
            "index_schema_version": INDEX_SCHEMA_VERSION,
        }

        self.assertEqual(need_rebuild(self.state), "not rebuild")
        self.state["choose_session"] = "S_11_2"
        self.assertEqual(need_rebuild(self.state), "rebuild")

    def test_same_row_count_but_changed_content_rebuilds(self) -> None:
        self.state["data_fingerprint"] = "changed-fingerprint"

        self.assertEqual(need_rebuild(self.state), "rebuild")

    def test_missing_fingerprint_rebuilds_existing_session(self) -> None:
        del self.state["row_count_history"]["S_11_1"]["data_fingerprint"]

        self.assertEqual(need_rebuild(self.state), "rebuild")

    def test_embedding_model_change_rebuilds(self) -> None:
        self.state["row_count_history"]["S_11_1"]["embedding_model"] = "old-model"

        self.assertEqual(need_rebuild(self.state), "rebuild")

    def test_embedding_provider_change_rebuilds(self) -> None:
        self.state["row_count_history"]["S_11_1"]["embedding_provider"] = (
            "vertexai"
        )

        self.assertEqual(need_rebuild(self.state), "rebuild")

    def test_missing_embedding_provider_rebuilds(self) -> None:
        del self.state["row_count_history"]["S_11_1"]["embedding_provider"]

        self.assertEqual(need_rebuild(self.state), "rebuild")

    def test_index_schema_version_change_rebuilds(self) -> None:
        self.state["row_count_history"]["S_11_1"]["index_schema_version"] = 0

        self.assertEqual(need_rebuild(self.state), "rebuild")


if __name__ == "__main__":
    unittest.main()

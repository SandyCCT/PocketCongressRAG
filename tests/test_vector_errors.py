import unittest
from unittest.mock import ANY, patch

import pandas as pd
from chromadb.errors import InvalidArgumentError, NotFoundError
from openai import APIError

from nodes.vector_search import vector_search
from services.vector_store import rebuild_vector_db


class VectorSearchErrorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.state = {
            "choose_session": "S_11_1",
            "search_filter": None,
            "input_query": "學童營養午餐",
        }

    @patch("nodes.vector_search.llm")
    @patch("nodes.vector_search.Chroma")
    def test_empty_result_reports_no_data(self, chroma, llm) -> None:
        chroma.return_value.as_retriever.return_value.invoke.return_value = []

        result = vector_search(self.state)

        self.assertEqual(result["response"], "資料集中找不到跟問題有關的資訊！")
        llm.invoke.assert_not_called()

    @patch("nodes.vector_search.Chroma")
    def test_each_request_uses_its_own_collection(self, chroma) -> None:
        chroma.return_value.as_retriever.return_value.invoke.return_value = []

        vector_search(self.state)
        vector_search({**self.state, "choose_session": "S_11_2"})

        self.assertEqual(
            [item.kwargs["collection_name"] for item in chroma.call_args_list],
            ["S_11_1", "S_11_2"],
        )

    @patch("nodes.vector_search.llm")
    @patch("nodes.vector_search.Chroma")
    def test_chroma_error_reports_retrieval_failure(self, chroma, llm) -> None:
        chroma.return_value.as_retriever.return_value.invoke.side_effect = (
            InvalidArgumentError("篩選條件無效")
        )

        with self.assertLogs(
            "pocket_congress.nodes.vector_search",
            level="WARNING",
        ) as logs:
            result = vector_search(self.state)

        self.assertEqual(result["response"], "向量檢索失敗，請稍後再試。")
        self.assertIn("InvalidArgumentError", logs.output[0])
        self.assertNotIn("篩選條件無效", logs.output[0])
        llm.invoke.assert_not_called()

    @patch("nodes.vector_search.llm")
    @patch("nodes.vector_search.Chroma")
    def test_openai_error_propagates_to_workflow(self, chroma, llm) -> None:
        chroma.return_value.as_retriever.return_value.invoke.side_effect = APIError(
            "Embedding API 連線失敗",
            request=None,
            body=None,
        )

        with self.assertRaises(APIError):
            vector_search(self.state)

        llm.invoke.assert_not_called()

    @patch("nodes.vector_search.llm")
    @patch("nodes.vector_search.Chroma")
    def test_invalid_filter_reports_retrieval_failure(self, chroma, llm) -> None:
        chroma.return_value.as_retriever.side_effect = TypeError("篩選格式錯誤")

        result = vector_search(self.state)

        self.assertEqual(result["response"], "向量檢索失敗，請稍後再試。")
        llm.invoke.assert_not_called()


class VectorStoreErrorTests(unittest.TestCase):
    @patch("services.vector_store.os.makedirs")
    @patch("services.vector_store.Chroma")
    @patch("services.vector_store.convert_df_to_docs", return_value=[])
    @patch("services.vector_store.PersistentClient")
    def test_missing_collection_is_skipped(
        self, client, convert_docs, chroma, makedirs
    ) -> None:
        client.return_value.delete_collection.side_effect = NotFoundError(
            "collection 不存在"
        )

        rebuild_vector_db(pd.DataFrame(), "S_11_1")

        client.return_value.delete_collection.assert_called_once_with("S_11_1")
        chroma.from_documents.assert_called_once_with(
            documents=[],
            embedding=ANY,
            collection_name="S_11_1",
            persist_directory=ANY,
            ids=[],
        )

    @patch("services.vector_store.os.makedirs")
    @patch("services.vector_store.Chroma")
    @patch("services.vector_store.PersistentClient")
    def test_other_delete_error_stops_rebuild(self, client, chroma, makedirs) -> None:
        client.return_value.delete_collection.side_effect = InvalidArgumentError(
            "Chroma 刪除失敗"
        )

        with self.assertRaises(InvalidArgumentError):
            rebuild_vector_db(pd.DataFrame(), "S_11_1")

        chroma.from_documents.assert_not_called()


if __name__ == "__main__":
    unittest.main()

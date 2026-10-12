import unittest

from app.router import sql_search_success_or_fail


class SqlSearchRouteTests(unittest.TestCase):
    def test_nonempty_result_uses_sql(self) -> None:
        self.assertEqual(
            sql_search_success_or_fail({"sql_query": '[{"count": 2}]'}),
            "sql",
        )

    def test_empty_result_uses_vector(self) -> None:
        self.assertEqual(sql_search_success_or_fail({"sql_query": "[]"}), "vector")

    def test_invalid_json_logs_reason_and_uses_vector(self) -> None:
        with self.assertLogs("pocket_congress.app.router", level="WARNING") as logs:
            result = sql_search_success_or_fail({"sql_query": "invalid json"})

        self.assertEqual(result, "vector")
        self.assertIn("SQL 查詢結果無法解析為 JSON", logs.output[0])

    def test_unexpected_result_type_is_not_silenced(self) -> None:
        with self.assertRaises(TypeError):
            sql_search_success_or_fail({"sql_query": None})


if __name__ == "__main__":
    unittest.main()

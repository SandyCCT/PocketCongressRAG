import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from services.sql_tools import (
    build_db_schema,
    execute_read_only_query,
    is_read_only_query,
    rebuild_db,
)


class ReadOnlySqlTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp_dir.name) / "test.db"

        with sqlite3.connect(self.database_path) as connection:
            connection.execute(
                "CREATE TABLE speeches (id INTEGER PRIMARY KEY, member_name TEXT)"
            )
            connection.execute(
                "INSERT INTO speeches (member_name) VALUES (?)",
                ("王育敏",),
            )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_select_query_is_allowed(self) -> None:
        result = execute_read_only_query(
            "SELECT member_name FROM speeches",
            str(self.database_path),
        )

        self.assertEqual(result, [{"member_name": "王育敏"}])

    def test_with_select_query_is_allowed(self) -> None:
        result = execute_read_only_query(
            "WITH selected AS (SELECT member_name FROM speeches) "
            "SELECT member_name FROM selected",
            str(self.database_path),
        )

        self.assertEqual(result, [{"member_name": "王育敏"}])

    def test_write_query_is_rejected(self) -> None:
        result = execute_read_only_query(
            "DELETE FROM speeches",
            str(self.database_path),
        )

        self.assertEqual(result, [])
        self.assertEqual(self._row_count(), 1)

    def test_with_write_query_is_blocked_by_database(self) -> None:
        result = execute_read_only_query(
            "WITH selected AS (SELECT id FROM speeches) "
            "DELETE FROM speeches WHERE id IN (SELECT id FROM selected) RETURNING id",
            str(self.database_path),
        )

        self.assertEqual(result, [])
        self.assertEqual(self._row_count(), 1)

    def test_multiple_statements_are_rejected(self) -> None:
        result = execute_read_only_query(
            "SELECT member_name FROM speeches; DELETE FROM speeches",
            str(self.database_path),
        )

        self.assertEqual(result, [])
        self.assertEqual(self._row_count(), 1)

    def test_query_prefix_validation(self) -> None:
        self.assertTrue(is_read_only_query("SELECT 1"))
        self.assertTrue(is_read_only_query("  with data AS (SELECT 1) SELECT * FROM data"))
        self.assertFalse(is_read_only_query("UPDATE speeches SET member_name = 'x'"))
        self.assertFalse(is_read_only_query("PRAGMA table_info(speeches)"))

    def test_rebuild_uses_explicit_session_name(self) -> None:
        first = pd.DataFrame([{"member_name": "王育敏"}])
        second = pd.DataFrame([{"member_name": "黃國昌"}])

        with patch("services.sql_tools.config.DB_PATH", str(self.database_path)):
            rebuild_db(first, "S_11_1")
            rebuild_db(second, "S_11_2")

        with sqlite3.connect(self.database_path) as connection:
            first_name = connection.execute(
                'SELECT member_name FROM "S_11_1"'
            ).fetchone()[0]
            second_name = connection.execute(
                'SELECT member_name FROM "S_11_2"'
            ).fetchone()[0]
        self.assertEqual((first_name, second_name), ("王育敏", "黃國昌"))

    def test_schema_uses_request_session(self) -> None:
        first = build_db_schema({
            "choose_session": "S_11_1",
            "max_committee_count": 0,
            "max_geographical_scope_count": 0,
        })
        second = build_db_schema({
            "choose_session": "S_11_2",
            "max_committee_count": 0,
            "max_geographical_scope_count": 0,
        })

        self.assertIn('"table": "S_11_1"', first)
        self.assertIn('"table": "S_11_2"', second)

    def _row_count(self) -> int:
        with sqlite3.connect(self.database_path) as connection:
            return connection.execute("SELECT COUNT(*) FROM speeches").fetchone()[0]


if __name__ == "__main__":
    unittest.main()

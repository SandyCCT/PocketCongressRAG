import unittest

from services.document_ids import build_document_ids


class DocumentIdsTests(unittest.TestCase):
    def test_builds_reproducible_session_document_ids(self) -> None:
        self.assertEqual(
            build_document_ids("S_11_3", 3),
            [
                "S_11_3:00000000",
                "S_11_3:00000001",
                "S_11_3:00000002",
            ],
        )

    def test_rejects_negative_document_count(self) -> None:
        with self.assertRaisesRegex(ValueError, "不得小於 0"):
            build_document_ids("S_11_3", -1)

    def test_rejects_empty_session_id(self) -> None:
        with self.assertRaisesRegex(ValueError, "不得為空"):
            build_document_ids("  ", 1)


if __name__ == "__main__":
    unittest.main()

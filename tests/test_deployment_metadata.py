import copy
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from services.deployment_metadata import (
    RUNTIME_METADATA_SCHEMA_VERSION,
    RuntimeMetadataValidationError,
    load_runtime_metadata,
    validate_runtime_metadata,
)


class DeploymentMetadataTests(unittest.TestCase):
    def setUp(self) -> None:
        self.metadata = {
            "metadata_schema_version": RUNTIME_METADATA_SCHEMA_VERSION,
            "created_at": "2026-09-25T10:30:00+08:00",
            "embedding_provider": "openai",
            "embedding_model": "text-embedding-3-small",
            "index_schema_version": 1,
            "sessions": {
                "S_11_1": {
                    "display_name": "第11屆第1會期 (202402 ~ 202407)",
                    "source_file": "第11屆第1會期 (202402 ~ 202407).xlsx",
                    "source_file_sha256": "a" * 64,
                    "total_rows": 1961,
                    "data_fingerprint": "b" * 64,
                    "max_committee_count": 1,
                    "max_geographical_scope_count": 2,
                    "filter_options": {
                        "member_names": ["王育敏", "黃國昌"],
                        "committees": ["交通委員會", "教育及文化委員會"],
                        "geographical_scopes": ["全國性", "地區性"],
                    },
                }
            },
        }

    def test_accepts_valid_runtime_metadata(self) -> None:
        result = validate_runtime_metadata(self.metadata)

        self.assertIs(result, self.metadata)

    def test_loads_runtime_metadata_from_json(self) -> None:
        with patch.object(
            Path,
            "read_text",
            return_value=json.dumps(self.metadata, ensure_ascii=False),
        ):
            result = load_runtime_metadata(Path("runtime_metadata.json"))

        self.assertEqual(result, self.metadata)

    def test_rejects_missing_required_field(self) -> None:
        metadata = copy.deepcopy(self.metadata)
        del metadata["sessions"]["S_11_1"]["filter_options"]

        with self.assertRaisesRegex(
            RuntimeMetadataValidationError,
            "欄位不完整",
        ):
            validate_runtime_metadata(metadata)

    def test_rejects_unsupported_metadata_schema_version(self) -> None:
        metadata = copy.deepcopy(self.metadata)
        metadata["metadata_schema_version"] = (
            RUNTIME_METADATA_SCHEMA_VERSION + 1
        )

        with self.assertRaisesRegex(
            RuntimeMetadataValidationError,
            "schema version",
        ):
            validate_runtime_metadata(metadata)

    def test_rejects_unsupported_embedding_provider(self) -> None:
        metadata = copy.deepcopy(self.metadata)
        metadata["embedding_provider"] = "unsupported"

        with self.assertRaisesRegex(
            RuntimeMetadataValidationError,
            "embedding provider",
        ):
            validate_runtime_metadata(metadata)

    def test_rejects_invalid_session_id(self) -> None:
        metadata = copy.deepcopy(self.metadata)
        metadata["sessions"]["session-1"] = metadata["sessions"].pop("S_11_1")

        with self.assertRaisesRegex(
            RuntimeMetadataValidationError,
            "不合法的會期 ID",
        ):
            validate_runtime_metadata(metadata)

    def test_rejects_unsorted_or_duplicate_filter_options(self) -> None:
        metadata = copy.deepcopy(self.metadata)
        metadata["sessions"]["S_11_1"]["filter_options"]["member_names"] = [
            "黃國昌",
            "王育敏",
            "王育敏",
        ]

        with self.assertRaisesRegex(
            RuntimeMetadataValidationError,
            "必須排序且不可重複",
        ):
            validate_runtime_metadata(metadata)

    def test_rejects_source_path_instead_of_file_name(self) -> None:
        metadata = copy.deepcopy(self.metadata)
        metadata["sessions"]["S_11_1"]["source_file"] = (
            "/private/data/第11屆第1會期.xlsx"
        )

        with self.assertRaisesRegex(
            RuntimeMetadataValidationError,
            "必須是 Excel 檔名",
        ):
            validate_runtime_metadata(metadata)


if __name__ == "__main__":
    unittest.main()

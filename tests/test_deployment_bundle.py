import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from services.deployment_bundle import (
    BundleValidationError,
    calculate_file_hash,
    package_deployment_bundle,
    validate_deployment_sources,
    verify_deployment_bundle,
    verify_runtime_bundle_v2,
)
from services.deployment_metadata import load_runtime_metadata


class DeploymentBundleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)
        self.data_dir = self.root / "data" / "sessions"
        self.instance_dir = self.root / "instance"
        self.chroma_dir = self.instance_dir / "chroma_db"
        self.data_dir.mkdir(parents=True)
        self.chroma_dir.mkdir(parents=True)

        self.excel_path = self.data_dir / "第11屆第1會期.xlsx"
        self.excel_path.write_bytes(b"excel")
        (self.chroma_dir / "chroma.sqlite3").write_bytes(b"chroma")
        uuid_dir = self.chroma_dir / "collection-uuid"
        uuid_dir.mkdir()
        (uuid_dir / "index.bin").write_bytes(b"index")
        (self.instance_dir / "logs").mkdir()
        (self.instance_dir / "logs" / "app.log").write_text(
            "do not package", encoding="utf-8"
        )

        with sqlite3.connect(self.instance_dir / "legislature.db") as connection:
            connection.execute(
                'CREATE TABLE "S_11_1" ('
                '"委員名字" TEXT, '
                '"原本發言內容" TEXT, '
                '"日期" TEXT, '
                '"議題分類" TEXT, '
                '"會期" TEXT, '
                '"所屬委員會1" TEXT, '
                '"所屬委員會2" TEXT, '
                '"涵蓋層級1" TEXT, '
                '"涵蓋層級2" TEXT)'
            )
            connection.executemany(
                'INSERT INTO "S_11_1" VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
                [
                    (
                        "黃國昌",
                        "發言一",
                        "2025-01-01",
                        "交通",
                        "第11屆第1會期",
                        "交通委員會",
                        None,
                        "全國性",
                        None,
                    ),
                    (
                        "王育敏",
                        "發言二",
                        "2025-01-02",
                        "教育",
                        "第11屆第1會期",
                        "教育及文化委員會",
                        "交通委員會",
                        "地區性",
                        "全國性",
                    ),
                ],
            )

        history = {
            "S_11_1": {
                "total_rows": 2,
                "data_fingerprint": "b" * 64,
                "embedding_provider": "openai",
                "embedding_model": "embedding-model",
                "index_schema_version": 1,
                "source_file": "/private/source/第11屆第1會期.xlsx",
                "chroma_uuid_dir_name": "collection-uuid",
            }
        }
        with (self.instance_dir / "row_count_tracker.json").open(
            "w", encoding="utf-8-sig"
        ) as file:
            json.dump(history, file, ensure_ascii=False)

        self.collection = MagicMock()
        self.collection.name = "S_11_1"
        self.collection.count.return_value = 2
        client = MagicMock()
        client.list_collections.return_value = [self.collection]
        self.client_patcher = patch(
            "services.deployment_bundle.PersistentClient",
            return_value=client,
        )
        self.client_patcher.start()
        self.addCleanup(self.client_patcher.stop)

    def _package_bundle(self, name: str) -> Path:
        output_dir = self.root / "deployment_bundles" / name
        return package_deployment_bundle(
            data_dir=self.data_dir,
            instance_dir=self.instance_dir,
            output_dir=output_dir,
            embedding_provider="openai",
            embedding_model="embedding-model",
            index_schema_version=1,
        )

    def _assert_bundle_verification_fails(self, output_dir: Path) -> None:
        with self.assertRaisesRegex(BundleValidationError, "manifest"):
            verify_deployment_bundle(output_dir)

    def test_packages_only_required_files_and_writes_manifest(self) -> None:
        output_dir = self._package_bundle("v2")

        self.assertTrue((output_dir / "manifest.json").is_file())
        self.assertTrue((output_dir / "runtime_metadata.json").is_file())
        self.assertTrue((output_dir / "instance" / "legislature.db").is_file())
        self.assertTrue(
            (
                output_dir
                / "instance"
                / "chroma_db"
                / "collection-uuid"
                / "index.bin"
            ).is_file()
        )
        self.assertFalse((output_dir / "data").exists())
        self.assertFalse(
            (output_dir / "instance" / "row_count_tracker.json").exists()
        )
        self.assertFalse((output_dir / "instance" / "logs").exists())

        runtime_metadata = load_runtime_metadata(
            output_dir / "runtime_metadata.json"
        )
        self.assertEqual(runtime_metadata["embedding_provider"], "openai")
        session_metadata = runtime_metadata["sessions"]["S_11_1"]
        self.assertEqual(
            session_metadata["source_file"],
            "第11屆第1會期.xlsx",
        )
        self.assertEqual(
            session_metadata["source_file_sha256"],
            calculate_file_hash(self.excel_path),
        )
        self.assertEqual(session_metadata["max_committee_count"], 2)
        self.assertEqual(session_metadata["max_geographical_scope_count"], 2)
        self.assertEqual(
            session_metadata["filter_options"],
            {
                "member_names": ["王育敏", "黃國昌"],
                "committees": ["交通委員會", "教育及文化委員會"],
                "geographical_scopes": ["全國性", "地區性"],
            },
        )

        manifest = json.loads(
            (output_dir / "manifest.json").read_text(encoding="utf-8")
        )
        self.assertEqual(manifest["bundle_version"], 2)
        self.assertIn("runtime_metadata.json", manifest["files"])
        self.assertIn("instance/legislature.db", manifest["files"])
        self.assertFalse(
            any(path.endswith(".xlsx") for path in manifest["files"])
        )
        self.assertNotIn("instance/row_count_tracker.json", manifest["files"])
        self.assertNotIn("instance/logs/app.log", manifest["files"])

        verify_deployment_bundle(output_dir)
        runtime_metadata = verify_runtime_bundle_v2(
            instance_dir=output_dir / "instance",
            metadata_path=output_dir / "runtime_metadata.json",
            manifest_path=output_dir / "manifest.json",
        )
        self.assertEqual(set(runtime_metadata["sessions"]), {"S_11_1"})

        (output_dir / "instance" / "legislature.db").write_bytes(b"changed")
        self._assert_bundle_verification_fails(output_dir)

    def test_runtime_verification_rejects_chroma_count_mismatch(self) -> None:
        output_dir = self._package_bundle("chroma-count-mismatch")
        self.collection.count.return_value = 1

        with self.assertRaisesRegex(BundleValidationError, "Chroma 筆數"):
            verify_runtime_bundle_v2(
                instance_dir=output_dir / "instance",
                metadata_path=output_dir / "runtime_metadata.json",
                manifest_path=output_dir / "manifest.json",
            )

    def test_runtime_verification_allows_chroma_catalog_updates(self) -> None:
        output_dir = self._package_bundle("updated-chroma-catalog")
        chroma_database = (
            output_dir / "instance" / "chroma_db" / "chroma.sqlite3"
        )
        chroma_database.write_bytes(b"runtime-updated-chroma")

        runtime_metadata = verify_runtime_bundle_v2(
            instance_dir=output_dir / "instance",
            metadata_path=output_dir / "runtime_metadata.json",
            manifest_path=output_dir / "manifest.json",
        )

        self.assertEqual(set(runtime_metadata["sessions"]), {"S_11_1"})

    def test_runtime_verification_rejects_modified_chroma_index(self) -> None:
        output_dir = self._package_bundle("modified-runtime-index")
        index_path = (
            output_dir
            / "instance"
            / "chroma_db"
            / "collection-uuid"
            / "index.bin"
        )
        index_path.write_bytes(b"changed")

        with self.assertRaisesRegex(BundleValidationError, "manifest"):
            verify_runtime_bundle_v2(
                instance_dir=output_dir / "instance",
                metadata_path=output_dir / "runtime_metadata.json",
                manifest_path=output_dir / "manifest.json",
            )

    def test_runtime_verification_rejects_modified_sqlite(self) -> None:
        output_dir = self._package_bundle("modified-runtime-sqlite")
        database_path = output_dir / "instance" / "legislature.db"
        database_path.write_bytes(b"changed")

        with self.assertRaisesRegex(BundleValidationError, "manifest"):
            verify_runtime_bundle_v2(
                instance_dir=output_dir / "instance",
                metadata_path=output_dir / "runtime_metadata.json",
                manifest_path=output_dir / "manifest.json",
            )

    def test_rejects_modified_runtime_metadata(self) -> None:
        output_dir = self._package_bundle("modified-metadata")

        metadata_path = output_dir / "runtime_metadata.json"
        metadata_path.write_text("{}", encoding="utf-8")

        self._assert_bundle_verification_fails(output_dir)

    def test_rejects_missing_runtime_metadata(self) -> None:
        output_dir = self._package_bundle("missing-metadata")

        metadata_path = output_dir / "runtime_metadata.json"
        metadata_path.rename(self.root / "missing-runtime-metadata.json")

        self._assert_bundle_verification_fails(output_dir)

    def test_rejects_modified_chroma_index(self) -> None:
        output_dir = self._package_bundle("modified-chroma")

        index_path = (
            output_dir
            / "instance"
            / "chroma_db"
            / "collection-uuid"
            / "index.bin"
        )
        index_path.write_bytes(b"changed")

        self._assert_bundle_verification_fails(output_dir)

    def test_rejects_missing_manifest_file(self) -> None:
        output_dir = self._package_bundle("missing-file")

        index_path = (
            output_dir
            / "instance"
            / "chroma_db"
            / "collection-uuid"
            / "index.bin"
        )
        index_path.rename(self.root / "missing-index.bin")

        self._assert_bundle_verification_fails(output_dir)

    def test_rejects_unexpected_bundle_file(self) -> None:
        output_dir = self._package_bundle("unexpected-file")

        (output_dir / "instance" / "unexpected.txt").write_text(
            "unexpected",
            encoding="utf-8",
        )

        self._assert_bundle_verification_fails(output_dir)

    def test_existing_bundle_is_not_overwritten(self) -> None:
        output_dir = self.root / "deployment_bundles" / "v1"
        output_dir.mkdir(parents=True)

        with self.assertRaises(FileExistsError):
            package_deployment_bundle(
                data_dir=self.data_dir,
                instance_dir=self.instance_dir,
                output_dir=output_dir,
                embedding_provider="openai",
                embedding_model="embedding-model",
                index_schema_version=1,
            )

    def test_rejects_non_contiguous_dynamic_columns(self) -> None:
        with sqlite3.connect(self.instance_dir / "legislature.db") as connection:
            connection.execute(
                'ALTER TABLE "S_11_1" ADD COLUMN "所屬委員會4" TEXT'
            )

        with self.assertRaisesRegex(
            BundleValidationError,
            "動態欄位編號不連續",
        ):
            self._package_bundle("invalid-columns")

    def test_rejects_incompatible_embedding_model(self) -> None:
        with self.assertRaisesRegex(BundleValidationError, "Embedding model"):
            validate_deployment_sources(
                data_dir=self.data_dir,
                instance_dir=self.instance_dir,
                embedding_provider="openai",
                embedding_model="different-model",
                index_schema_version=1,
            )

    def test_rejects_incompatible_embedding_provider(self) -> None:
        with self.assertRaisesRegex(BundleValidationError, "Embedding provider"):
            validate_deployment_sources(
                data_dir=self.data_dir,
                instance_dir=self.instance_dir,
                embedding_provider="vertexai",
                embedding_model="embedding-model",
                index_schema_version=1,
            )

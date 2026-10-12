import argparse
import importlib.util
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import Mock, patch

from app.exceptions import AIProviderError, RetryableAIProviderError


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "rebuild_vertex_embedding_index.py"
SPEC = importlib.util.spec_from_file_location(
    "rebuild_vertex_embedding_index",
    SCRIPT_PATH,
)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("無法載入 Vertex embedding index 建立腳本")
rebuild_script = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(rebuild_script)


class RebuildVertexEmbeddingIndexTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)
        self.instance_dir = self.root / "instance"
        self.data_dir = self.root / "data" / "sessions"
        self.instance_dir.mkdir(parents=True)
        self.data_dir.mkdir(parents=True)
        self.excel_path = self.data_dir / "第11屆第1會期.xlsx"
        self.excel_path.touch()

    @staticmethod
    def _args(
        output_dir: Path,
        *,
        dry_run: bool,
        resume: bool,
    ) -> argparse.Namespace:
        return argparse.Namespace(
            output_dir=output_dir,
            project="project-id",
            location="global",
            model="gemini-embedding-001",
            resume=resume,
            dry_run=dry_run,
        )

    def _run_main(self, args: argparse.Namespace) -> str:
        session_files = {"S_11_1": self.excel_path}
        stdout = StringIO()
        with (
            patch.object(rebuild_script, "PROJECT_ROOT", self.root),
            patch.object(rebuild_script, "SRC_DIR", PROJECT_ROOT / "src"),
            patch.object(rebuild_script, "parse_args", return_value=args),
            patch.object(rebuild_script.os, "chdir"),
            patch.object(
                rebuild_script.sys,
                "path",
                rebuild_script.sys.path.copy(),
            ),
            patch.dict(os.environ, {}, clear=False),
            patch(
                "services.deployment_bundle.discover_session_files",
                return_value=session_files,
            ),
            patch.object(rebuild_script, "_build_session") as build_session,
            redirect_stdout(stdout),
        ):
            rebuild_script.main()

        build_session.assert_not_called()
        return stdout.getvalue()

    def test_parse_args_uses_google_cloud_project(self) -> None:
        with (
            patch.dict(
                os.environ,
                {"GOOGLE_CLOUD_PROJECT": "project-from-environment"},
            ),
            patch.object(
                rebuild_script.sys,
                "argv",
                ["rebuild_vertex_embedding_index.py", "--dry-run"],
            ),
        ):
            args = rebuild_script.parse_args()

        self.assertEqual(args.project, "project-from-environment")

    def test_missing_project_is_rejected(self) -> None:
        args = self._args(
            self.instance_dir / "new-index",
            dry_run=True,
            resume=False,
        )
        args.project = None

        with self.assertRaisesRegex(
            ValueError,
            "--project 或 GOOGLE_CLOUD_PROJECT",
        ):
            self._run_main(args)

    def test_dry_run_allows_existing_output_directory(self) -> None:
        output_dir = self.instance_dir / "existing-index"
        output_dir.mkdir()

        output = self._run_main(
            self._args(output_dir, dry_run=True, resume=False)
        )

        self.assertIn(f"輸出目錄：{output_dir.resolve()}", output)
        self.assertIn("S_11_1: 第11屆第1會期.xlsx", output)

    def test_dry_run_does_not_create_output_directory(self) -> None:
        output_dir = self.instance_dir / "new-index"

        self._run_main(
            self._args(output_dir, dry_run=True, resume=False)
        )

        self.assertFalse(output_dir.exists())

    def test_real_run_rejects_existing_directory_without_resume(self) -> None:
        output_dir = self.instance_dir / "existing-index"
        output_dir.mkdir()

        with self.assertRaisesRegex(FileExistsError, "拒絕覆寫"):
            self._run_main(
                self._args(output_dir, dry_run=False, resume=False)
            )

    def test_output_directory_must_remain_inside_instance(self) -> None:
        output_dir = self.root / "outside-instance"

        with self.assertRaisesRegex(ValueError, "必須位於專案 instance"):
            self._run_main(
                self._args(output_dir, dry_run=True, resume=False)
            )

    def test_complete_compatible_index_accepts_existing_random_ids(
        self,
    ) -> None:
        metadata = {
            "total_rows": 3,
            "data_fingerprint": "fingerprint",
            "embedding_provider": "vertexai",
            "embedding_model": "gemini-embedding-001",
            "index_schema_version": 1,
        }

        result = rebuild_script._is_complete_compatible_index(
            existing_document_count=3,
            expected_document_count=3,
            metadata=metadata,
            expected_total_rows=3,
            expected_data_fingerprint="fingerprint",
            expected_embedding_provider="vertexai",
            expected_embedding_model="gemini-embedding-001",
            expected_schema_version=1,
        )

        self.assertTrue(result)

    def test_complete_index_rejects_different_data_fingerprint(self) -> None:
        metadata = {
            "total_rows": 3,
            "data_fingerprint": "old-fingerprint",
            "embedding_provider": "vertexai",
            "embedding_model": "gemini-embedding-001",
            "index_schema_version": 1,
        }

        result = rebuild_script._is_complete_compatible_index(
            existing_document_count=3,
            expected_document_count=3,
            metadata=metadata,
            expected_total_rows=3,
            expected_data_fingerprint="new-fingerprint",
            expected_embedding_provider="vertexai",
            expected_embedding_model="gemini-embedding-001",
            expected_schema_version=1,
        )

        self.assertFalse(result)

    def test_changed_fingerprint_requires_full_rebuild(self) -> None:
        metadata = {
            "total_rows": 2,
            "data_fingerprint": "old-fingerprint",
            "embedding_provider": "vertexai",
            "embedding_model": "gemini-embedding-001",
            "index_schema_version": 1,
        }

        result = rebuild_script._requires_full_rebuild(
            existing_ids={"S_11_3:00000000", "S_11_3:00000001"},
            expected_ids={"S_11_3:00000000", "S_11_3:00000001"},
            metadata=metadata,
            expected_total_rows=2,
            expected_data_fingerprint="new-fingerprint",
            expected_embedding_provider="vertexai",
            expected_embedding_model="gemini-embedding-001",
            expected_schema_version=1,
        )

        self.assertTrue(result)

    def test_compatible_partial_fixed_ids_can_resume(self) -> None:
        metadata = {
            "status": "building",
            "total_rows": 2,
            "data_fingerprint": "fingerprint",
            "embedding_provider": "vertexai",
            "embedding_model": "gemini-embedding-001",
            "index_schema_version": 1,
        }

        result = rebuild_script._requires_full_rebuild(
            existing_ids={"S_11_3:00000000"},
            expected_ids={"S_11_3:00000000", "S_11_3:00000001"},
            metadata=metadata,
            expected_total_rows=2,
            expected_data_fingerprint="fingerprint",
            expected_embedding_provider="vertexai",
            expected_embedding_model="gemini-embedding-001",
            expected_schema_version=1,
        )

        self.assertFalse(result)

    def test_unknown_document_ids_require_full_rebuild(self) -> None:
        result = rebuild_script._requires_full_rebuild(
            existing_ids={"random-id"},
            expected_ids={"S_11_3:00000000"},
            metadata=None,
            expected_total_rows=1,
            expected_data_fingerprint="fingerprint",
            expected_embedding_provider="vertexai",
            expected_embedding_model="gemini-embedding-001",
            expected_schema_version=1,
        )

        self.assertTrue(result)

    def test_rebuild_pending_status_requires_full_rebuild(self) -> None:
        metadata = {
            "status": "rebuild_pending",
            "total_rows": 1,
            "data_fingerprint": "fingerprint",
            "embedding_provider": "vertexai",
            "embedding_model": "gemini-embedding-001",
            "index_schema_version": 1,
        }

        result = rebuild_script._requires_full_rebuild(
            existing_ids={"S_11_3:00000000"},
            expected_ids={"S_11_3:00000000"},
            metadata=metadata,
            expected_total_rows=1,
            expected_data_fingerprint="fingerprint",
            expected_embedding_provider="vertexai",
            expected_embedding_model="gemini-embedding-001",
            expected_schema_version=1,
        )

        self.assertTrue(result)

    def test_building_status_is_not_treated_as_complete(self) -> None:
        metadata = {
            "status": "building",
            "total_rows": 1,
            "data_fingerprint": "fingerprint",
            "embedding_provider": "vertexai",
            "embedding_model": "gemini-embedding-001",
            "index_schema_version": 1,
        }

        result = rebuild_script._is_complete_compatible_index(
            existing_document_count=1,
            expected_document_count=1,
            metadata=metadata,
            expected_total_rows=1,
            expected_data_fingerprint="fingerprint",
            expected_embedding_provider="vertexai",
            expected_embedding_model="gemini-embedding-001",
            expected_schema_version=1,
        )

        self.assertFalse(result)

    def test_rebuild_pending_status_is_not_treated_as_complete(self) -> None:
        metadata = {
            "status": "rebuild_pending",
            "total_rows": 1,
            "data_fingerprint": "fingerprint",
            "embedding_provider": "vertexai",
            "embedding_model": "gemini-embedding-001",
            "index_schema_version": 1,
        }

        result = rebuild_script._is_complete_compatible_index(
            existing_document_count=1,
            expected_document_count=1,
            metadata=metadata,
            expected_total_rows=1,
            expected_data_fingerprint="fingerprint",
            expected_embedding_provider="vertexai",
            expected_embedding_model="gemini-embedding-001",
            expected_schema_version=1,
        )

        self.assertFalse(result)

    def test_build_session_reuses_complete_compatible_random_id_index(
        self,
    ) -> None:
        output_dir = self.instance_dir / "vertex-index"
        metadata = {
            "total_rows": 2,
            "data_fingerprint": "fingerprint",
            "embedding_provider": "vertexai",
            "embedding_model": "gemini-embedding-001",
            "index_schema_version": 1,
        }
        vector_store = Mock()
        vector_store.get.return_value = {"ids": ["random-a", "random-b"]}

        with (
            patch(
                "services.preprocessing.preprocess_and_merge",
                return_value=(Mock(), None, None, {"total": 2}),
            ),
            patch(
                "services.doc_converter.convert_df_to_docs",
                return_value=[Mock(), Mock()],
            ),
            patch(
                "nodes.maintenance.calculate_data_fingerprint",
                return_value="fingerprint",
            ),
            patch(
                "services.history_store.load_row_count_history",
                return_value={"S_11_3": metadata},
            ),
            patch("services.llm_client.EMBEDDING_PROVIDER", "vertexai"),
            patch(
                "services.llm_client.EMBEDDING_MODEL",
                "gemini-embedding-001",
            ),
            patch("langchain_chroma.Chroma", return_value=vector_store),
        ):
            result = rebuild_script._build_session(
                self.excel_path,
                "S_11_3",
                output_dir,
            )

        self.assertEqual(result, metadata)
        vector_store.add_documents.assert_not_called()

    def test_build_session_rebuilds_only_changed_session(self) -> None:
        output_dir = self.instance_dir / "vertex-index"
        chroma_dir = output_dir / "chroma_db"
        (chroma_dir / "new-uuid").mkdir(parents=True)
        existing_store = Mock()
        existing_store.get.return_value = {
            "ids": ["S_11_3:00000000", "S_11_3:00000001"]
        }
        rebuilt_store = Mock()
        rebuilt_store._collection.count.return_value = 2
        chroma_client = Mock()
        chroma_client.get_collection.return_value.count.return_value = 2
        old_metadata = {
            "status": "complete",
            "total_rows": 2,
            "data_fingerprint": "old-fingerprint",
            "embedding_provider": "vertexai",
            "embedding_model": "gemini-embedding-001",
            "index_schema_version": 1,
        }

        with (
            patch(
                "services.preprocessing.preprocess_and_merge",
                return_value=(
                    Mock(),
                    None,
                    None,
                    {"total": 2, "per_sheet": {"202508": 2}},
                ),
            ),
            patch(
                "services.doc_converter.convert_df_to_docs",
                return_value=[Mock(), Mock()],
            ),
            patch(
                "nodes.maintenance.calculate_data_fingerprint",
                return_value="new-fingerprint",
            ),
            patch(
                "services.history_store.load_row_count_history",
                return_value={"S_11_3": old_metadata},
            ),
            patch("services.history_store.save_row_count_history") as save,
            patch("services.llm_client.EMBEDDING_PROVIDER", "vertexai"),
            patch(
                "services.llm_client.EMBEDDING_MODEL",
                "gemini-embedding-001",
            ),
            patch(
                "langchain_chroma.Chroma",
                side_effect=[existing_store, rebuilt_store],
            ),
            patch("chromadb.PersistentClient", return_value=chroma_client),
            patch("services.sql_tools.rebuild_db") as rebuild_db,
            patch.object(rebuild_script, "_add_documents_with_retry") as add,
        ):
            result = rebuild_script._build_session(
                self.excel_path,
                "S_11_3",
                output_dir,
            )

        chroma_client.delete_collection.assert_called_once_with("S_11_3")
        add.assert_called_once()
        rebuild_db.assert_called_once()
        self.assertEqual(save.call_count, 3)
        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["data_fingerprint"], "new-fingerprint")

    @patch.object(rebuild_script.time, "sleep")
    def test_batch_retry_retries_retryable_provider_error(self, sleep) -> None:
        vector_store = Mock()
        vector_store.add_documents.side_effect = [
            RetryableAIProviderError("temporary"),
            None,
        ]

        rebuild_script._add_documents_with_retry(
            vector_store,
            ["document"],
            ["document-id"],
        )

        self.assertEqual(vector_store.add_documents.call_count, 2)
        sleep.assert_called_once_with(15)

    @patch.object(rebuild_script.time, "sleep")
    def test_batch_retry_does_not_retry_permanent_provider_error(
        self,
        sleep,
    ) -> None:
        vector_store = Mock()
        vector_store.add_documents.side_effect = AIProviderError("permanent")

        with self.assertRaises(AIProviderError):
            rebuild_script._add_documents_with_retry(
                vector_store,
                ["document"],
                ["document-id"],
            )

        vector_store.add_documents.assert_called_once()
        sleep.assert_not_called()


if __name__ == "__main__":
    unittest.main()

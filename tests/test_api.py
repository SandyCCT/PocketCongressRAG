import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from httpx import Response

import api
from app.exceptions import AIProviderError, IndexNotReadyError
from services.deployment_bundle import (
    BundleValidationError,
    collect_file_hashes,
)


app = api.app


class ApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.data_folder = Path(self.temp_dir.name)
        (self.data_folder / "第11屆第10會期.xlsx").touch()
        (self.data_folder / "第11屆第2會期.xlsx").touch()
        (self.data_folder / "~$第11屆第3會期.xlsx").touch()
        (self.data_folder / "其他檔案.xlsx").touch()
        self.path_patcher = patch.multiple(
            api,
            DATA_FOLDER_PATH=str(self.data_folder),
            RUNTIME_METADATA_PATH=None,
            DEPLOYMENT_MANIFEST_PATH=None,
        )
        self.path_patcher.start()
        self.addCleanup(self.path_patcher.stop)
        api._get_local_prepared_session.cache_clear()
        self.addCleanup(api._get_local_prepared_session.cache_clear)
        api._get_runtime_prepared_session.cache_clear()
        self.addCleanup(api._get_runtime_prepared_session.cache_clear)
        api._load_runtime_metadata.cache_clear()
        self.addCleanup(api._load_runtime_metadata.cache_clear)
        api._validate_readiness.cache_clear()
        self.addCleanup(api._validate_readiness.cache_clear)
        self.client = TestClient(app)

    def _create_runtime_bundle(
        self,
        name: str,
    ) -> tuple[Path, Path, Path]:
        runtime_dir = self.data_folder / name
        data_dir = runtime_dir / "data" / "sessions"
        instance_dir = runtime_dir / "instance"
        chroma_dir = instance_dir / "chroma_db"
        data_dir.mkdir(parents=True)
        chroma_dir.mkdir(parents=True)

        (data_dir / "第11屆第1會期.xlsx").write_bytes(b"excel")
        (instance_dir / "legislature.db").write_bytes(b"sqlite")
        (instance_dir / "row_count_tracker.json").write_text(
            "{}",
            encoding="utf-8",
        )
        (chroma_dir / "chroma.sqlite3").write_bytes(b"chroma")
        uuid_dir = chroma_dir / "collection-uuid"
        uuid_dir.mkdir()
        (uuid_dir / "index.bin").write_bytes(b"index")

        expected_hashes = {
            f"data/sessions/{path}": digest
            for path, digest in collect_file_hashes(data_dir).items()
        }
        expected_hashes.update({
            f"instance/{path}": digest
            for path, digest in collect_file_hashes(instance_dir).items()
        })
        manifest_path = runtime_dir / "manifest.json"
        manifest_path.write_text(
            json.dumps({
                "files": {
                    path: {"sha256": digest}
                    for path, digest in expected_hashes.items()
                }
            }),
            encoding="utf-8",
        )
        return data_dir, instance_dir, manifest_path

    def _request_runtime_readiness(
        self,
        data_dir: Path,
        instance_dir: Path,
        manifest_path: Path,
    ) -> Response:
        with patch.multiple(
            api,
            DATA_FOLDER_PATH=str(data_dir),
            DB_PATH=str(instance_dir / "legislature.db"),
            ROW_COUNT_HISTORY_PATH=str(
                instance_dir / "row_count_tracker.json"
            ),
            CHROMA_DIR=str(instance_dir / "chroma_db"),
            DEPLOYMENT_MANIFEST_PATH=str(manifest_path),
        ):
            api._validate_readiness.cache_clear()
            return self.client.get("/health/ready")

    def _create_runtime_metadata(self, name: str) -> tuple[Path, dict]:
        metadata = {
            "metadata_schema_version": 2,
            "created_at": "2026-09-26T10:00:00+08:00",
            "embedding_provider": "openai",
            "embedding_model": "embedding-model",
            "index_schema_version": 1,
            "sessions": {
                "S_11_2": {
                    "display_name": "第11屆第2會期",
                    "source_file": "第11屆第2會期.xlsx",
                    "source_file_sha256": "a" * 64,
                    "total_rows": 2,
                    "data_fingerprint": "b" * 64,
                    "max_committee_count": 2,
                    "max_geographical_scope_count": 1,
                    "filter_options": {
                        "member_names": ["王育敏"],
                        "committees": ["交通委員會"],
                        "geographical_scopes": ["全國性"],
                    },
                },
                "S_11_10": {
                    "display_name": "第11屆第10會期",
                    "source_file": "第11屆第10會期.xlsx",
                    "source_file_sha256": "c" * 64,
                    "total_rows": 1,
                    "data_fingerprint": "d" * 64,
                    "max_committee_count": 1,
                    "max_geographical_scope_count": 1,
                    "filter_options": {
                        "member_names": ["測試委員"],
                        "committees": ["教育及文化委員會"],
                        "geographical_scopes": ["地區性"],
                    },
                },
            },
        }
        metadata_path = self.data_folder / name / "runtime_metadata.json"
        metadata_path.parent.mkdir()
        metadata_path.write_text(
            json.dumps(metadata, ensure_ascii=False),
            encoding="utf-8",
        )
        return metadata_path, metadata

    def test_list_sessions_uses_numeric_order(self) -> None:
        response = self.client.get("/api/v1/sessions")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [
            {"id": "S_11_2", "name": "第11屆第2會期"},
            {"id": "S_11_10", "name": "第11屆第10會期"},
        ])

    def test_list_sessions_uses_runtime_metadata_without_excel(self) -> None:
        metadata_path, _ = self._create_runtime_metadata("session-catalog")

        with patch.multiple(
            api,
            DATA_FOLDER_PATH=None,
            RUNTIME_METADATA_PATH=str(metadata_path),
        ):
            response = self.client.get("/api/v1/sessions")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [
            {"id": "S_11_2", "name": "第11屆第2會期"},
            {"id": "S_11_10", "name": "第11屆第10會期"},
        ])

    def test_web_page_and_assets_are_served(self) -> None:
        page = self.client.get("/")
        script = self.client.get("/static/app.js")
        stylesheet = self.client.get("/static/style.css")

        self.assertEqual(page.status_code, 200)
        self.assertIn('id="question-form"', page.text)
        self.assertIn('/static/app.js', page.text)
        self.assertEqual(script.status_code, 200)
        self.assertIn('/api/v1/questions', script.text)
        self.assertEqual(stylesheet.status_code, 200)

    def test_liveness_returns_ok(self) -> None:
        response = self.client.get("/health/live")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

    def test_readiness_returns_ready(self) -> None:
        instance_dir = self.data_folder / "instance"
        chroma_dir = instance_dir / "chroma_db"
        chroma_dir.mkdir(parents=True)
        database_path = instance_dir / "legislature.db"
        history_path = instance_dir / "row_count_tracker.json"
        database_path.touch()
        history_path.touch()
        (chroma_dir / "chroma.sqlite3").touch()

        with patch.multiple(
            api,
            DB_PATH=str(database_path),
            ROW_COUNT_HISTORY_PATH=str(history_path),
            CHROMA_DIR=str(chroma_dir),
            DEPLOYMENT_MANIFEST_PATH=None,
        ):
            api._validate_readiness.cache_clear()
            response = self.client.get("/health/ready")
        api._validate_readiness.cache_clear()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ready"})

    def test_readiness_validates_complete_manifest(self) -> None:
        data_dir, instance_dir, manifest_path = self._create_runtime_bundle(
            "valid-runtime",
        )

        response = self._request_runtime_readiness(
            data_dir,
            instance_dir,
            manifest_path,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ready"})

    def test_readiness_rejects_modified_runtime_files(self) -> None:
        cases = {
            "excel": Path("data/sessions/第11屆第1會期.xlsx"),
            "sqlite": Path("instance/legislature.db"),
            "history": Path("instance/row_count_tracker.json"),
            "chroma": Path(
                "instance/chroma_db/collection-uuid/index.bin"
            ),
        }

        for name, relative_path in cases.items():
            with self.subTest(file_type=name):
                data_dir, instance_dir, manifest_path = (
                    self._create_runtime_bundle(f"modified-{name}")
                )
                runtime_dir = manifest_path.parent
                changed_path = runtime_dir / relative_path
                changed_path.write_bytes(b"changed")

                response = self._request_runtime_readiness(
                    data_dir,
                    instance_dir,
                    manifest_path,
                )

                self.assertEqual(response.status_code, 503)
                self.assertEqual(
                    response.json(),
                    {"detail": "服務尚未就緒"},
                )
                self.assertNotIn(str(changed_path), response.text)

    def test_readiness_rejects_missing_runtime_file(self) -> None:
        data_dir, instance_dir, manifest_path = self._create_runtime_bundle(
            "missing-runtime-file",
        )
        chroma_database = instance_dir / "chroma_db" / "chroma.sqlite3"
        chroma_database.rename(self.data_folder / "missing-chroma.sqlite3")

        response = self._request_runtime_readiness(
            data_dir,
            instance_dir,
            manifest_path,
        )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"detail": "服務尚未就緒"})
        self.assertNotIn(str(chroma_database), response.text)

    @patch("api.prepare_runtime_session")
    @patch("api.verify_runtime_bundle_v2")
    def test_v2_readiness_uses_metadata_bundle(
        self,
        verify_runtime_bundle_v2,
        prepare_runtime_session,
    ) -> None:
        metadata_path, metadata = self._create_runtime_metadata("v2-readiness")
        manifest_path = metadata_path.parent / "manifest.json"
        manifest_path.touch()
        verify_runtime_bundle_v2.return_value = metadata

        with patch.multiple(
            api,
            DATA_FOLDER_PATH=None,
            ROW_COUNT_HISTORY_PATH=None,
            RUNTIME_METADATA_PATH=str(metadata_path),
            DEPLOYMENT_MANIFEST_PATH=str(manifest_path),
        ):
            api._validate_readiness.cache_clear()
            response = self.client.get("/health/ready")
        api._validate_readiness.cache_clear()

        self.assertEqual(response.status_code, 200)
        verify_runtime_bundle_v2.assert_called_once_with(
            instance_dir=Path(api.DB_PATH).parent,
            metadata_path=metadata_path,
            manifest_path=manifest_path,
        )
        self.assertEqual(prepare_runtime_session.call_count, 2)

    @patch("api.verify_runtime_bundle_v2")
    def test_v2_readiness_requires_manifest(
        self,
        verify_runtime_bundle_v2,
    ) -> None:
        metadata_path, _ = self._create_runtime_metadata("missing-manifest")

        with patch.multiple(
            api,
            DATA_FOLDER_PATH=None,
            ROW_COUNT_HISTORY_PATH=None,
            RUNTIME_METADATA_PATH=str(metadata_path),
            DEPLOYMENT_MANIFEST_PATH=None,
        ):
            api._validate_readiness.cache_clear()
            response = self.client.get("/health/ready")
        api._validate_readiness.cache_clear()

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"detail": "服務尚未就緒"})
        verify_runtime_bundle_v2.assert_not_called()

    @patch(
        "api._validate_readiness",
        side_effect=BundleValidationError("private path"),
    )
    def test_readiness_error_does_not_expose_details(
        self,
        validate_readiness,
    ) -> None:
        response = self.client.get("/health/ready")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"detail": "服務尚未就緒"})
        self.assertNotIn("private path", response.text)
        validate_readiness.assert_called_once_with()

    @patch("api.run_one_question", return_value="**查詢結果**\n第二行")
    @patch(
        "api.prepare_local_session",
        return_value={"choose_session": "S_11_2"},
    )
    def test_question_runs_once(
        self,
        prepare_local_session,
        run_one_question,
    ) -> None:
        response = self.client.post("/api/v1/questions", json={
            "session_id": "S_11_2",
            "question": "  總共發言幾次？  ",
            "member_name": "王育敏",
        })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"answer": "**查詢結果**\n第二行"})
        prepare_local_session.assert_called_once_with(
            str(self.data_folder / "第11屆第2會期.xlsx"), "S_11_2"
        )
        run_one_question.assert_called_once_with({"choose_session": "S_11_2"}, {
            "委員名字": "王育敏",
            "涵蓋層級": "all",
            "所屬委員會": "all",
            "問題": "總共發言幾次？",
        })

    @patch("api.prepare_local_session")
    @patch("api.run_one_question", return_value="metadata 查詢結果")
    @patch(
        "api.prepare_runtime_session",
        return_value={"choose_session": "S_11_2"},
    )
    def test_question_uses_runtime_metadata_without_excel(
        self,
        prepare_runtime_session,
        run_one_question,
        prepare_local_session,
    ) -> None:
        metadata_path, metadata = self._create_runtime_metadata(
            "runtime-question"
        )

        with patch.multiple(
            api,
            DATA_FOLDER_PATH=None,
            RUNTIME_METADATA_PATH=str(metadata_path),
        ):
            response = self.client.post("/api/v1/questions", json={
                "session_id": "S_11_2",
                "question": "問題",
            })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"answer": "metadata 查詢結果"})
        prepare_local_session.assert_not_called()
        prepare_runtime_session.assert_called_once_with(metadata, "S_11_2")

    @patch("api.run_one_question", return_value="metadata 查詢結果")
    @patch(
        "api.prepare_runtime_session",
        return_value={"choose_session": "S_11_2"},
    )
    def test_runtime_metadata_change_refreshes_prepared_session(
        self,
        prepare_runtime_session,
        run_one_question,
    ) -> None:
        metadata_path, metadata = self._create_runtime_metadata(
            "updated-runtime-metadata"
        )

        with patch.multiple(
            api,
            DATA_FOLDER_PATH=None,
            RUNTIME_METADATA_PATH=str(metadata_path),
        ):
            first_response = self.client.post("/api/v1/questions", json={
                "session_id": "S_11_2",
                "question": "第一題",
            })
            metadata["sessions"]["S_11_2"]["display_name"] += "（更新）"
            metadata_path.write_text(
                json.dumps(metadata, ensure_ascii=False),
                encoding="utf-8",
            )
            second_response = self.client.post("/api/v1/questions", json={
                "session_id": "S_11_2",
                "question": "第二題",
            })

        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(second_response.status_code, 200)
        self.assertEqual(prepare_runtime_session.call_count, 2)
        self.assertEqual(run_one_question.call_count, 2)

    @patch("api.run_one_question", return_value="查詢結果")
    @patch("api.prepare_local_session", return_value={"choose_session": "S_11_2"})
    def test_questions_reuse_prepared_session(
        self,
        prepare_local_session,
        run_one_question,
    ) -> None:
        first_response = self.client.post("/api/v1/questions", json={
            "session_id": "S_11_2", "question": "第一題"
        })
        second_response = self.client.post("/api/v1/questions", json={
            "session_id": "S_11_2", "question": "第二題"
        })

        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(second_response.status_code, 200)
        prepare_local_session.assert_called_once_with(
            str(self.data_folder / "第11屆第2會期.xlsx"),
            "S_11_2",
        )
        self.assertEqual(run_one_question.call_count, 2)

    @patch("api.run_one_question", return_value="查詢結果")
    @patch("api.prepare_local_session", return_value={"choose_session": "S_11_2"})
    def test_excel_change_refreshes_prepared_session(
        self,
        prepare_local_session,
        run_one_question,
    ) -> None:
        excel_path = self.data_folder / "第11屆第2會期.xlsx"
        first_response = self.client.post("/api/v1/questions", json={
            "session_id": "S_11_2", "question": "第一題"
        })
        excel_path.write_bytes(b"changed")
        second_response = self.client.post("/api/v1/questions", json={
            "session_id": "S_11_2", "question": "第二題"
        })

        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(second_response.status_code, 200)
        self.assertEqual(prepare_local_session.call_count, 2)
        self.assertEqual(run_one_question.call_count, 2)

    @patch("api.run_one_question", return_value="查詢結果")
    @patch("api.prepare_local_session")
    def test_different_sessions_are_prepared_separately(
        self,
        prepare_local_session,
        run_one_question,
    ) -> None:
        prepare_local_session.side_effect = [
            {"choose_session": "S_11_2"},
            {"choose_session": "S_11_10"},
        ]

        first_response = self.client.post("/api/v1/questions", json={
            "session_id": "S_11_2", "question": "第一題"
        })
        second_response = self.client.post("/api/v1/questions", json={
            "session_id": "S_11_10", "question": "第二題"
        })

        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(second_response.status_code, 200)
        self.assertEqual(prepare_local_session.call_count, 2)
        self.assertEqual(run_one_question.call_count, 2)

    @patch("api.run_one_question", return_value="查詢結果")
    @patch("api.prepare_local_session")
    def test_failed_preparation_is_not_cached(
        self,
        prepare_local_session,
        run_one_question,
    ) -> None:
        prepare_local_session.side_effect = [
            OSError("temporary error"),
            {"choose_session": "S_11_2"},
        ]

        first_response = self.client.post("/api/v1/questions", json={
            "session_id": "S_11_2", "question": "第一題"
        })
        second_response = self.client.post("/api/v1/questions", json={
            "session_id": "S_11_2", "question": "第二題"
        })

        self.assertEqual(first_response.status_code, 503)
        self.assertEqual(second_response.status_code, 200)
        self.assertEqual(prepare_local_session.call_count, 2)
        run_one_question.assert_called_once()

    def test_blank_question_is_rejected(self) -> None:
        response = self.client.post("/api/v1/questions", json={
            "session_id": "S_11_2", "question": "   "
        })

        self.assertEqual(response.status_code, 422)

    def test_unknown_session_is_rejected(self) -> None:
        response = self.client.post("/api/v1/questions", json={
            "session_id": "S_12_1", "question": "問題"
        })

        self.assertEqual(response.status_code, 404)

    @patch("api.prepare_local_session")
    def test_question_does_not_accept_a_file_path(self, prepare_local_session) -> None:
        response = self.client.post("/api/v1/questions", json={
            "session_id": "../other.xlsx", "question": "問題"
        })

        self.assertEqual(response.status_code, 404)
        prepare_local_session.assert_not_called()

    def test_missing_data_folder_returns_service_unavailable(self) -> None:
        with patch("api.DATA_FOLDER_PATH", str(self.data_folder / "missing")):
            sessions = self.client.get("/api/v1/sessions")
            question = self.client.post("/api/v1/questions", json={
                "session_id": "S_11_2", "question": "問題"
            })

        self.assertEqual(sessions.status_code, 503)
        self.assertEqual(question.status_code, 503)
        self.assertEqual(sessions.json(), {"detail": "目前無法讀取會期資料"})
        self.assertEqual(question.json(), {"detail": "目前無法讀取會期資料"})

    @patch("api.prepare_local_session", side_effect=OSError("private path"))
    def test_processing_error_does_not_expose_details(
        self,
        prepare_local_session,
    ) -> None:
        response = self.client.post("/api/v1/questions", json={
            "session_id": "S_11_2", "question": "問題"
        })

        self.assertEqual(response.status_code, 503)
        self.assertNotIn("private path", response.text)
        prepare_local_session.assert_called_once()

    @patch(
        "api.prepare_local_session",
        side_effect=IndexNotReadyError("private path"),
    )
    def test_index_not_ready_returns_service_unavailable(
        self,
        prepare_local_session,
    ) -> None:
        response = self.client.post("/api/v1/questions", json={
            "session_id": "S_11_2", "question": "問題"
        })

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"detail": "目前資料索引尚未就緒"})
        self.assertNotIn("private path", response.text)
        prepare_local_session.assert_called_once()

    @patch(
        "api.run_one_question",
        side_effect=AIProviderError("private provider detail"),
    )
    @patch("api.prepare_local_session", return_value={"prepared": True})
    def test_ai_provider_error_returns_service_unavailable(
        self,
        prepare_local_session,
        run_one_question,
    ) -> None:
        response = self.client.post("/api/v1/questions", json={
            "session_id": "S_11_2", "question": "問題"
        })

        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.json(),
            {"detail": "AI 服務暫時無法使用，請稍後再試"},
        )
        self.assertNotIn("private provider detail", response.text)
        prepare_local_session.assert_called_once()
        run_one_question.assert_called_once()


if __name__ == "__main__":
    unittest.main()

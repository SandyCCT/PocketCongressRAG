import os
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.config import (
    _get_instance_dir,
    _read_non_negative_int_env,
    _read_optional_text_env,
    _read_path_env,
    _read_positive_float_env,
    _read_provider_env,
    _read_text_env,
    _validate_provider_settings,
)


class ProviderConfigTests(unittest.TestCase):
    def test_request_timeout_must_be_positive_number(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(
                _read_positive_float_env("AI_REQUEST_TIMEOUT_SECONDS", "60"),
                60.0,
            )

        for value in ("0", "invalid"):
            with self.subTest(value=value), patch.dict(
                os.environ,
                {"AI_REQUEST_TIMEOUT_SECONDS": value},
            ):
                with self.assertRaises(ValueError):
                    _read_positive_float_env(
                        "AI_REQUEST_TIMEOUT_SECONDS",
                        "60",
                    )

    def test_max_retries_must_be_non_negative_integer(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(
                _read_non_negative_int_env("AI_MAX_RETRIES", "2"),
                2,
            )

        for value in ("-1", "1.5"):
            with self.subTest(value=value), patch.dict(
                os.environ,
                {"AI_MAX_RETRIES": value},
            ):
                with self.assertRaises(ValueError):
                    _read_non_negative_int_env("AI_MAX_RETRIES", "2")

    def test_provider_defaults_to_openai(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(
                _read_provider_env("CHAT_PROVIDER", "openai"),
                "openai",
            )

    def test_provider_is_normalized(self) -> None:
        with patch.dict(os.environ, {"CHAT_PROVIDER": " VertexAI "}):
            self.assertEqual(
                _read_provider_env("CHAT_PROVIDER", "openai"),
                "vertexai",
            )

    def test_unsupported_provider_is_rejected(self) -> None:
        with patch.dict(os.environ, {"CHAT_PROVIDER": "gemini"}):
            with self.assertRaisesRegex(ValueError, "CHAT_PROVIDER 必須是"):
                _read_provider_env("CHAT_PROVIDER", "openai")

    def test_blank_model_uses_default(self) -> None:
        with patch.dict(os.environ, {"VERTEX_CHAT_MODEL": "  "}):
            self.assertEqual(
                _read_text_env("VERTEX_CHAT_MODEL", "gemini-2.5-flash"),
                "gemini-2.5-flash",
            )

    def test_blank_optional_value_is_not_configured(self) -> None:
        with patch.dict(os.environ, {"GOOGLE_CLOUD_PROJECT": "  "}):
            self.assertIsNone(_read_optional_text_env("GOOGLE_CLOUD_PROJECT"))

    def test_openai_uses_default_instance_directory(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(_get_instance_dir("openai"), Path("../instance"))

    def test_vertex_uses_isolated_instance_directory(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(
                _get_instance_dir("vertexai"),
                Path("../instance/vertexai-gemini-embedding-001"),
            )

    def test_instance_directory_can_be_overridden(self) -> None:
        with patch.dict(os.environ, {"INSTANCE_DIR": "/tmp/custom-instance"}):
            self.assertEqual(
                _get_instance_dir("vertexai"),
                Path("/tmp/custom-instance"),
            )

    def test_provider_path_can_be_overridden(self) -> None:
        with patch.dict(os.environ, {"CHROMA_DIR": "/tmp/custom-chroma"}):
            self.assertEqual(
                _read_path_env("CHROMA_DIR", Path("../instance/chroma_db")),
                Path("/tmp/custom-chroma"),
            )

    def test_openai_provider_requires_api_key(self) -> None:
        settings = SimpleNamespace(
            CHAT_PROVIDER="openai",
            EMBEDDING_PROVIDER="openai",
            OPENAI_API_KEY=None,
            GOOGLE_CLOUD_PROJECT=None,
        )

        with self.assertRaisesRegex(ValueError, "必須設定 OPENAI_API_KEY"):
            _validate_provider_settings(settings)

    def test_vertex_provider_requires_google_cloud_project(self) -> None:
        settings = SimpleNamespace(
            CHAT_PROVIDER="vertexai",
            EMBEDDING_PROVIDER="vertexai",
            OPENAI_API_KEY=None,
            GOOGLE_CLOUD_PROJECT=None,
        )

        with self.assertRaisesRegex(ValueError, "必須設定 GOOGLE_CLOUD_PROJECT"):
            _validate_provider_settings(settings)

    def test_provider_matrix_accepts_required_credentials(self) -> None:
        provider_combinations = (
            ("openai", "openai", "openai-key", None),
            ("vertexai", "openai", "openai-key", "project-id"),
            ("openai", "vertexai", "openai-key", "project-id"),
            ("vertexai", "vertexai", None, "project-id"),
        )

        for (
            chat_provider,
            embedding_provider,
            openai_api_key,
            google_cloud_project,
        ) in provider_combinations:
            with self.subTest(
                chat_provider=chat_provider,
                embedding_provider=embedding_provider,
            ):
                settings = SimpleNamespace(
                    CHAT_PROVIDER=chat_provider,
                    EMBEDDING_PROVIDER=embedding_provider,
                    OPENAI_API_KEY=openai_api_key,
                    GOOGLE_CLOUD_PROJECT=google_cloud_project,
                )

                _validate_provider_settings(settings)

    def test_mixed_provider_matrix_rejects_missing_credentials(self) -> None:
        invalid_combinations = (
            ("vertexai", "openai", None, "project-id", "OPENAI_API_KEY"),
            ("openai", "vertexai", "openai-key", None, "GOOGLE_CLOUD_PROJECT"),
        )

        for (
            chat_provider,
            embedding_provider,
            openai_api_key,
            google_cloud_project,
            expected_error,
        ) in invalid_combinations:
            with self.subTest(
                chat_provider=chat_provider,
                embedding_provider=embedding_provider,
            ):
                settings = SimpleNamespace(
                    CHAT_PROVIDER=chat_provider,
                    EMBEDDING_PROVIDER=embedding_provider,
                    OPENAI_API_KEY=openai_api_key,
                    GOOGLE_CLOUD_PROJECT=google_cloud_project,
                )

                with self.assertRaisesRegex(ValueError, expected_error):
                    _validate_provider_settings(settings)


if __name__ == "__main__":
    unittest.main()

import unittest
from unittest.mock import patch, sentinel

from services.provider_factory import create_chat_model, create_embeddings


class ProviderFactoryTests(unittest.TestCase):
    @patch("services.provider_factory.ChatOpenAI")
    def test_create_openai_chat_model(self, chat_openai) -> None:
        chat_openai.return_value = sentinel.chat_model

        with patch.multiple(
            "services.provider_factory.config",
            CHAT_PROVIDER="openai",
            OPENAI_API_KEY="openai-key",
            OPENAI_CHAT_MODEL="gpt-4o-mini",
            AI_REQUEST_TIMEOUT_SECONDS=60.0,
            AI_MAX_RETRIES=2,
        ):
            result = create_chat_model()

        self.assertIs(result, sentinel.chat_model)
        chat_openai.assert_called_once_with(
            api_key="openai-key",
            model="gpt-4o-mini",
            timeout=60.0,
            max_retries=2,
        )

    @patch("services.vertex_chat.TimeoutChatVertexAI")
    def test_create_vertex_chat_model(self, chat_vertex_ai) -> None:
        chat_vertex_ai.return_value = sentinel.chat_model

        with patch.multiple(
            "services.provider_factory.config",
            CHAT_PROVIDER="vertexai",
            GOOGLE_CLOUD_PROJECT="project-id",
            GOOGLE_CLOUD_LOCATION="global",
            VERTEX_CHAT_MODEL="gemini-2.5-flash",
            AI_REQUEST_TIMEOUT_SECONDS=45.0,
            AI_MAX_RETRIES=2,
        ):
            result = create_chat_model()

        self.assertIs(result, sentinel.chat_model)
        chat_vertex_ai.assert_called_once_with(
            model="gemini-2.5-flash",
            project="project-id",
            location="global",
            max_retries=3,
            request_timeout_seconds=45.0,
        )

    @patch("services.provider_factory.OpenAIEmbeddings")
    def test_create_openai_embeddings(self, openai_embeddings) -> None:
        openai_embeddings.return_value = sentinel.embeddings

        with patch.multiple(
            "services.provider_factory.config",
            EMBEDDING_PROVIDER="openai",
            OPENAI_API_KEY="openai-key",
            OPENAI_EMBEDDING_MODEL="text-embedding-3-small",
            AI_REQUEST_TIMEOUT_SECONDS=60.0,
            AI_MAX_RETRIES=2,
        ):
            result = create_embeddings()

        self.assertIs(result, sentinel.embeddings)
        openai_embeddings.assert_called_once_with(
            api_key="openai-key",
            model="text-embedding-3-small",
            timeout=60.0,
            max_retries=2,
        )

    @patch("services.provider_factory.VertexAIEmbeddings")
    def test_create_vertex_embeddings(self, vertex_ai_embeddings) -> None:
        vertex_ai_embeddings.return_value = sentinel.embeddings

        with patch.multiple(
            "services.provider_factory.config",
            EMBEDDING_PROVIDER="vertexai",
            GOOGLE_CLOUD_PROJECT="project-id",
            GOOGLE_CLOUD_LOCATION="global",
            VERTEX_EMBEDDING_MODEL="gemini-embedding-001",
            AI_REQUEST_TIMEOUT_SECONDS=60.0,
            AI_MAX_RETRIES=2,
        ):
            result = create_embeddings()

        self.assertIs(result, sentinel.embeddings)
        vertex_ai_embeddings.assert_called_once_with(
            model="gemini-embedding-001",
            project="project-id",
            location="global",
            request_timeout_seconds=60.0,
            max_retries=2,
        )

    def test_unsupported_chat_provider_is_rejected(self) -> None:
        with patch(
            "services.provider_factory.config.CHAT_PROVIDER",
            "unsupported",
        ):
            with self.assertRaisesRegex(ValueError, "不支援的 chat provider"):
                create_chat_model()

    def test_unsupported_embedding_provider_is_rejected(self) -> None:
        with patch(
            "services.provider_factory.config.EMBEDDING_PROVIDER",
            "unsupported",
        ):
            with self.assertRaisesRegex(
                ValueError,
                "不支援的 embedding provider",
            ):
                create_embeddings()

    @patch("services.provider_factory.VertexAIEmbeddings")
    @patch("services.provider_factory.OpenAIEmbeddings")
    @patch("services.vertex_chat.TimeoutChatVertexAI")
    @patch("services.provider_factory.ChatOpenAI")
    def test_provider_matrix_creates_only_selected_clients(
        self,
        chat_openai,
        chat_vertex_ai,
        openai_embeddings,
        vertex_ai_embeddings,
    ) -> None:
        provider_combinations = (
            ("openai", "openai"),
            ("vertexai", "openai"),
            ("openai", "vertexai"),
            ("vertexai", "vertexai"),
        )

        for chat_provider, embedding_provider in provider_combinations:
            with self.subTest(
                chat_provider=chat_provider,
                embedding_provider=embedding_provider,
            ):
                chat_openai.reset_mock()
                chat_vertex_ai.reset_mock()
                openai_embeddings.reset_mock()
                vertex_ai_embeddings.reset_mock()

                with patch.multiple(
                    "services.provider_factory.config",
                    CHAT_PROVIDER=chat_provider,
                    EMBEDDING_PROVIDER=embedding_provider,
                    OPENAI_API_KEY="openai-key",
                    OPENAI_CHAT_MODEL="gpt-4o-mini",
                    OPENAI_EMBEDDING_MODEL="text-embedding-3-small",
                    GOOGLE_CLOUD_PROJECT="project-id",
                    GOOGLE_CLOUD_LOCATION="global",
                    VERTEX_CHAT_MODEL="gemini-2.5-flash",
                    VERTEX_EMBEDDING_MODEL="gemini-embedding-001",
                    AI_REQUEST_TIMEOUT_SECONDS=60.0,
                    AI_MAX_RETRIES=2,
                ):
                    create_chat_model()
                    create_embeddings()

                if chat_provider == "openai":
                    chat_openai.assert_called_once_with(
                        api_key="openai-key",
                        model="gpt-4o-mini",
                        timeout=60.0,
                        max_retries=2,
                    )
                    chat_vertex_ai.assert_not_called()
                else:
                    chat_vertex_ai.assert_called_once_with(
                        model="gemini-2.5-flash",
                        project="project-id",
                        location="global",
                        max_retries=3,
                        request_timeout_seconds=60.0,
                    )
                    chat_openai.assert_not_called()

                if embedding_provider == "openai":
                    openai_embeddings.assert_called_once_with(
                        api_key="openai-key",
                        model="text-embedding-3-small",
                        timeout=60.0,
                        max_retries=2,
                    )
                    vertex_ai_embeddings.assert_not_called()
                else:
                    vertex_ai_embeddings.assert_called_once_with(
                        model="gemini-embedding-001",
                        project="project-id",
                        location="global",
                        request_timeout_seconds=60.0,
                        max_retries=2,
                    )
                    openai_embeddings.assert_not_called()


if __name__ == "__main__":
    unittest.main()

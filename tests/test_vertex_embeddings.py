import unittest
from types import SimpleNamespace
from unittest.mock import patch

from google.genai.errors import ClientError, ServerError

from app.exceptions import AIProviderError, RetryableAIProviderError
from services.vertex_embeddings import VertexAIEmbeddings


class VertexAIEmbeddingsTests(unittest.TestCase):
    @patch("services.vertex_embeddings.genai.Client")
    def test_embeds_documents_in_bounded_batches(self, client_class) -> None:
        client = client_class.return_value
        client.models.embed_content.side_effect = [
            SimpleNamespace(
                embeddings=[
                    SimpleNamespace(values=[1.0, 0.0]),
                    SimpleNamespace(values=[0.0, 1.0]),
                ]
            ),
            SimpleNamespace(
                embeddings=[SimpleNamespace(values=[0.5, 0.5])]
            ),
        ]
        embeddings = VertexAIEmbeddings(
            model="gemini-embedding-001",
            project="project-id",
            location="global",
            batch_size=2,
            request_interval_seconds=0,
        )

        result = embeddings.embed_documents(["one", "two", "three"])

        self.assertEqual(
            result,
            [[1.0, 0.0], [0.0, 1.0], [0.5, 0.5]],
        )
        self.assertEqual(
            [
                item.kwargs["contents"]
                for item in client.models.embed_content.call_args_list
            ],
            [["one", "two"], ["three"]],
        )
        self.assertEqual(
            [
                item.kwargs["config"].task_type
                for item in client.models.embed_content.call_args_list
            ],
            ["RETRIEVAL_DOCUMENT", "RETRIEVAL_DOCUMENT"],
        )
        http_options = client_class.call_args.kwargs["http_options"]
        self.assertEqual(http_options.timeout, 60_000)
        self.assertEqual(http_options.retry_options.attempts, 3)

    @patch("services.vertex_embeddings.genai.Client")
    def test_embeds_query_with_retrieval_query_task(self, client_class) -> None:
        client = client_class.return_value
        client.models.embed_content.return_value = SimpleNamespace(
            embeddings=[SimpleNamespace(values=[0.25, 0.75])]
        )
        embeddings = VertexAIEmbeddings(
            model="gemini-embedding-001",
            project="project-id",
            location="global",
            request_interval_seconds=0,
        )

        result = embeddings.embed_query("question")

        self.assertEqual(result, [0.25, 0.75])
        request = client.models.embed_content.call_args
        self.assertEqual(request.kwargs["contents"], ["question"])
        self.assertEqual(request.kwargs["config"].task_type, "RETRIEVAL_QUERY")

    @patch("services.vertex_embeddings.genai.Client")
    def test_rejects_mismatched_response_count(self, client_class) -> None:
        client_class.return_value.models.embed_content.return_value = (
            SimpleNamespace(embeddings=[])
        )
        embeddings = VertexAIEmbeddings(
            model="gemini-embedding-001",
            project="project-id",
            location="global",
            request_interval_seconds=0,
        )

        with self.assertRaisesRegex(AIProviderError, "回傳數量不一致"):
            embeddings.embed_documents(["document"])

    @patch("services.vertex_embeddings.genai.Client")
    def test_rejects_empty_embedding(self, client_class) -> None:
        client_class.return_value.models.embed_content.return_value = (
            SimpleNamespace(
                embeddings=[SimpleNamespace(values=[])],
            )
        )
        embeddings = VertexAIEmbeddings(
            model="gemini-embedding-001",
            project="project-id",
            location="global",
            request_interval_seconds=0,
        )

        with self.assertRaisesRegex(AIProviderError, "回傳空白向量"):
            embeddings.embed_documents(["document"])

    @patch("services.vertex_embeddings.genai.Client")
    def test_converts_retryable_google_api_errors(self, client_class) -> None:
        embeddings = VertexAIEmbeddings(
            model="gemini-embedding-001",
            project="project-id",
            location="global",
            request_interval_seconds=0,
        )
        provider_errors = (
            ClientError(429, {"error": "quota detail"}),
            ServerError(503, {"error": "service detail"}),
        )

        for provider_error in provider_errors:
            with self.subTest(error_type=type(provider_error).__name__):
                client_class.return_value.models.embed_content.side_effect = (
                    provider_error
                )
                with self.assertRaisesRegex(
                    RetryableAIProviderError,
                    "Vertex AI embedding request failed",
                ):
                    embeddings.embed_query("question")

    @patch("services.vertex_embeddings.genai.Client")
    def test_converts_non_retryable_google_api_error(self, client_class) -> None:
        client_class.return_value.models.embed_content.side_effect = ClientError(
            400,
            {"error": "invalid request detail"},
        )
        embeddings = VertexAIEmbeddings(
            model="gemini-embedding-001",
            project="project-id",
            location="global",
            request_interval_seconds=0,
        )

        with self.assertRaises(AIProviderError) as error:
            embeddings.embed_query("question")

        self.assertNotIsInstance(error.exception, RetryableAIProviderError)

    def test_rejects_invalid_batch_size(self) -> None:
        with self.assertRaisesRegex(ValueError, "batch_size"):
            VertexAIEmbeddings(
                model="gemini-embedding-001",
                project="project-id",
                location="global",
                batch_size=0,
            )

    def test_rejects_invalid_timeout_and_retry_values(self) -> None:
        invalid_options = (
            ({"request_timeout_seconds": 0}, "request_timeout_seconds"),
            ({"max_retries": -1}, "max_retries"),
        )

        for options, expected_error in invalid_options:
            with self.subTest(options=options):
                with self.assertRaisesRegex(ValueError, expected_error):
                    VertexAIEmbeddings(
                        model="gemini-embedding-001",
                        project="project-id",
                        location="global",
                        **options,
                    )


if __name__ == "__main__":
    unittest.main()

import unittest
from unittest.mock import AsyncMock, Mock, PropertyMock, patch

from google.auth.credentials import AnonymousCredentials
from google.api_core.exceptions import ServiceUnavailable
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import BaseModel, ValidationError

from services.provider_factory import create_chat_model
from services.vertex_chat import TimeoutChatVertexAI


class RouteSchema(BaseModel):
    """Choose an answer route."""

    mode: str


class VertexChatTimeoutTests(unittest.TestCase):
    def setUp(self) -> None:
        self.model = TimeoutChatVertexAI(
            model="gemini-2.5-flash",
            project="test-project",
            location="global",
            credentials=AnonymousCredentials(),
            request_timeout_seconds=45.0,
        )

    def test_timeout_reaches_rpc_for_plain_tools_and_structured_output(self) -> None:
        result = ChatResult(generations=[ChatGeneration(message=AIMessage(
            content="",
            tool_calls=[{
                "name": "RouteSchema",
                "args": {"mode": "SQL"},
                "id": "route-call",
            }],
        ))])
        with (
            patch(
                "langchain_google_vertexai.ChatVertexAI.prediction_client",
                new_callable=PropertyMock,
                return_value=Mock(),
            ),
            patch(
                "langchain_google_vertexai.chat_models._completion_with_retry"
            ) as completion,
            patch(
                "langchain_google_vertexai.ChatVertexAI._gemini_response_to_chat_result",
                return_value=result,
            ),
        ):
            calls = (
                self.model,
                self.model.bind_tools([RouteSchema]),
                self.model.with_structured_output(RouteSchema),
                self.model.with_structured_output(RouteSchema, method="json_mode"),
            )
            for call in calls:
                with self.subTest(call_type=type(call).__name__):
                    # JSON mode parses content rather than tool calls.
                    if call is calls[-1]:
                        result.generations[0].message.content = '{"mode":"SQL"}'
                    response = call.invoke("Choose SQL")
                    self.assertEqual(completion.call_args.kwargs["timeout"], 45.0)
                    if call in calls[2:]:
                        self.assertEqual(response.mode, "SQL")
            self.assertEqual(completion.call_count, 4)

    def test_explicit_call_timeout_overrides_default(self) -> None:
        result = ChatResult(generations=[
            ChatGeneration(message=AIMessage(content="ok"))
        ])
        with patch(
            "langchain_google_vertexai.ChatVertexAI._generate_gemini",
            return_value=result,
        ) as generate:
            self.model.invoke("hello", timeout=12.0)
        self.assertEqual(generate.call_args.kwargs["timeout"], 12.0)

    def test_timeout_must_be_positive(self) -> None:
        with self.assertRaises(ValidationError):
            self.model.__class__(
                model="gemini-2.5-flash",
                project="test-project",
                credentials=AnonymousCredentials(),
                request_timeout_seconds=0,
            )

    def test_factory_retry_setting_controls_actual_attempts(self) -> None:
        for extra_retries in (0, 1, 2):
            with self.subTest(extra_retries=extra_retries):
                with (
                    patch.multiple(
                        "services.provider_factory.config",
                        CHAT_PROVIDER="vertexai",
                        GOOGLE_CLOUD_PROJECT="test-project",
                        GOOGLE_CLOUD_LOCATION="global",
                        VERTEX_CHAT_MODEL="gemini-2.5-flash",
                        AI_REQUEST_TIMEOUT_SECONDS=45.0,
                        AI_MAX_RETRIES=extra_retries,
                    ),
                    patch(
                        "services.vertex_chat.TimeoutChatVertexAI",
                        side_effect=lambda **kwargs: TimeoutChatVertexAI(
                            credentials=AnonymousCredentials(), **kwargs
                        ),
                    ),
                ):
                    model = create_chat_model()

                client = Mock()
                client.generate_content.side_effect = ServiceUnavailable("test")
                with (
                    patch(
                        "langchain_google_vertexai.ChatVertexAI.prediction_client",
                        new_callable=PropertyMock,
                        return_value=client,
                    ),
                    patch("tenacity.nap.time.sleep"),
                ):
                    with self.assertRaises(ServiceUnavailable):
                        model.invoke("hello")
                self.assertEqual(
                    client.generate_content.call_count, extra_retries + 1
                )


class VertexChatAsyncTimeoutTests(unittest.IsolatedAsyncioTestCase):
    async def test_async_invoke_uses_default_timeout(self) -> None:
        model = TimeoutChatVertexAI(
            model="gemini-2.5-flash",
            project="test-project",
            credentials=AnonymousCredentials(),
            request_timeout_seconds=30.0,
        )
        result = ChatResult(generations=[
            ChatGeneration(message=AIMessage(content="ok"))
        ])
        with patch(
            "langchain_google_vertexai.ChatVertexAI._agenerate_gemini",
            new_callable=AsyncMock,
            return_value=result,
        ) as generate:
            await model.ainvoke("hello")
        self.assertEqual(generate.call_args.kwargs["timeout"], 30.0)


if __name__ == "__main__":
    unittest.main()

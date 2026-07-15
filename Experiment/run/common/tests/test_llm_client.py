from __future__ import annotations

from email.utils import formatdate
import httpx
import json
import os
from openai import APIConnectionError, APITimeoutError
from pathlib import Path
from types import SimpleNamespace
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from Experiment.run.common import llm_client


class FakeHTTPError(RuntimeError):
    def __init__(self, status_code: int, headers=None, *, body=None, response_json=None):
        super().__init__(f"HTTP {status_code}")
        self.status_code = status_code
        self.body = body
        self.response = SimpleNamespace(
            status_code=status_code,
            headers=headers or {},
            json=lambda: response_json,
        )


class FakeCompletions:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    def create(self, **request):
        self.calls.append(request)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def response_with_content(content: str):
    message = SimpleNamespace(content=content, model_dump=lambda: {"content": content})
    choice = SimpleNamespace(message=message, finish_reason="stop")
    return SimpleNamespace(choices=[choice])


def transport_client(outcomes, *, retries=1, base_delay=0.25, max_delay=2.0):
    client = llm_client.LLMClient.__new__(llm_client.LLMClient)
    client.provider = "openai"
    client.model = "test-model"
    client.api_base = "https://example.test/v1"
    client.extra_body = {}
    client.max_tokens = 64
    client.transport_max_retries = retries
    client.retry_base_delay_seconds = base_delay
    client.retry_max_delay_seconds = max_delay
    completions = FakeCompletions(outcomes)
    client.client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    return client, completions


def json_transport_client(outcomes, *, retries=0):
    client, completions = transport_client(outcomes, retries=retries)
    client.use_json_mode = True
    client.use_cache = False
    client.cache_path = Path("unused-cache.json")
    client.cache = {}
    client._cache_lock = llm_client.RLock()
    return client, completions


class TransportRetryTests(unittest.TestCase):
    def test_cloudflare_origin_failures_are_retryable(self) -> None:
        self.assertTrue({520, 521, 522, 523, 524}.issubset(llm_client.RETRYABLE_HTTP_STATUSES))

    def test_retries_only_the_configured_http_statuses(self) -> None:
        for status_code in sorted(llm_client.RETRYABLE_HTTP_STATUSES):
            with self.subTest(status_code=status_code):
                client, completions = transport_client(
                    [FakeHTTPError(status_code), response_with_content("ok")]
                )
                with patch.object(llm_client.time, "sleep") as sleep:
                    self.assertEqual(client._call_chat("system", "user", json_mode=False), "ok")
                self.assertEqual(len(completions.calls), 2)
                sleep.assert_called_once_with(0.25)

        client, completions = transport_client(
            [FakeHTTPError(500), response_with_content("must not be reached")],
            retries=3,
        )
        with patch.object(llm_client.time, "sleep") as sleep:
            with self.assertRaises(llm_client.LLMRequestError) as raised:
                client._call_chat("system", "user", json_mode=False)
        self.assertEqual(raised.exception.status_code, 500)
        self.assertEqual(raised.exception.attempts, 1)
        self.assertEqual(len(completions.calls), 1)
        sleep.assert_not_called()

    def test_retries_structured_connection_and_timeout_errors(self) -> None:
        request = httpx.Request("POST", "https://example.test/v1/chat/completions")
        for error in (
            APIConnectionError(request=request),
            APITimeoutError(request=request),
            json.JSONDecodeError("truncated API envelope", '{"choices": [', 13),
        ):
            with self.subTest(error_type=type(error).__name__):
                client, completions = transport_client([error, response_with_content("ok")])
                with patch.object(llm_client.time, "sleep") as sleep:
                    self.assertEqual(client._call_chat("system", "user", json_mode=False), "ok")
                self.assertEqual(len(completions.calls), 2)
                sleep.assert_called_once_with(0.25)

        response_status_error = RuntimeError("structured response status")
        response_status_error.response = SimpleNamespace(status_code=503, headers={})
        client, completions = transport_client(
            [response_status_error, response_with_content("ok")]
        )
        with patch.object(llm_client.time, "sleep"):
            self.assertEqual(client._call_chat("", "user", json_mode=False), "ok")
        self.assertEqual(len(completions.calls), 2)

        message_only_client, completions = transport_client(
            [RuntimeError("HTTP 429"), response_with_content("must not be reached")],
            retries=3,
        )
        with patch.object(llm_client.time, "sleep") as sleep:
            with self.assertRaises(llm_client.LLMRequestError) as raised:
                message_only_client._call_chat("", "user", json_mode=False)
        self.assertIsNone(raised.exception.status_code)
        self.assertEqual(len(completions.calls), 1)
        sleep.assert_not_called()

    def test_retry_after_and_exponential_backoff_are_bounded(self) -> None:
        retry_after_client, _ = transport_client(
            [FakeHTTPError(429, {"Retry-After": "90"}), response_with_content("ok")],
            max_delay=2.0,
        )
        with patch.object(llm_client.time, "sleep") as sleep:
            retry_after_client._call_chat("", "user", json_mode=False)
        sleep.assert_called_once_with(2.0)

        millisecond_client, _ = transport_client(
            [FakeHTTPError(429, {"retry-after-ms": "1500"}), response_with_content("ok")],
            max_delay=2.0,
        )
        with patch.object(llm_client.time, "sleep") as sleep:
            millisecond_client._call_chat("", "user", json_mode=False)
        sleep.assert_called_once_with(1.5)

        structured_body_client, _ = transport_client(
            [
                FakeHTTPError(504, body={"error": {"retry_after": 120}}),
                response_with_content("ok"),
            ],
            max_delay=180.0,
        )
        with patch.object(llm_client.time, "sleep") as sleep:
            structured_body_client._call_chat("", "user", json_mode=False)
        sleep.assert_called_once_with(120.0)

        response_json_client, _ = transport_client(
            [
                FakeHTTPError(503, response_json={"error": {"retry_after_ms": 2500}}),
                response_with_content("ok"),
            ],
            max_delay=180.0,
        )
        with patch.object(llm_client.time, "sleep") as sleep:
            response_json_client._call_chat("", "user", json_mode=False)
        sleep.assert_called_once_with(2.5)

        backoff_client, completions = transport_client(
            [
                FakeHTTPError(503),
                FakeHTTPError(503),
                FakeHTTPError(503),
                response_with_content("ok"),
            ],
            retries=3,
            base_delay=0.5,
            max_delay=1.0,
        )
        with patch.object(llm_client.time, "sleep") as sleep:
            backoff_client._call_chat("", "user", json_mode=False)
        self.assertEqual(len(completions.calls), 4)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [0.5, 1.0, 1.0])

    def test_retry_after_http_date_is_supported(self) -> None:
        retry_at = formatdate(130, usegmt=True)
        self.assertEqual(
            llm_client._parse_retry_after_seconds(retry_at, now_epoch=100),
            30.0,
        )

    def test_exhaustion_reports_status_and_attempt_count(self) -> None:
        client, completions = transport_client(
            [FakeHTTPError(502), FakeHTTPError(502), FakeHTTPError(502)],
            retries=2,
        )
        with patch.object(llm_client.time, "sleep"):
            with self.assertRaises(llm_client.LLMRequestError) as raised:
                client._call_chat("", "user", json_mode=False)
        self.assertEqual(len(completions.calls), 3)
        self.assertEqual(raised.exception.status_code, 502)
        self.assertEqual(raised.exception.attempts, 3)
        self.assertTrue(raised.exception.retryable)

    def test_payload_split_recoverable_uses_only_approved_structured_causes(self) -> None:
        request = httpx.Request("POST", "https://example.test/v1/chat/completions")
        cases = (
            (
                json.JSONDecodeError("truncated API envelope", '{"choices": [', 13),
                True,
            ),
            (
                FakeHTTPError(
                    400,
                    body={"error": {"code": "context_length_exceeded"}},
                ),
                True,
            ),
            (
                FakeHTTPError(
                    413,
                    response_json={"error": {"type": "RequestTooLarge"}},
                ),
                True,
            ),
            (
                FakeHTTPError(
                    429,
                    body={"error": {"code": "context_length_exceeded"}},
                ),
                False,
            ),
            (FakeHTTPError(502), False),
            (FakeHTTPError(503), False),
            (FakeHTTPError(504), False),
            (APIConnectionError(request=request), False),
            (APITimeoutError(request=request), False),
        )
        for error, expected in cases:
            with self.subTest(error_type=type(error).__name__, expected=expected):
                client, completions = transport_client([error], retries=0)
                with self.assertRaises(llm_client.LLMRequestError) as raised:
                    client._call_chat("", "user", json_mode=False)
                self.assertEqual(len(completions.calls), 1)
                self.assertEqual(raised.exception.payload_split_recoverable, expected)

        guarded_error = llm_client.LLMRequestError(
            "openai",
            "test-model",
            "https://example.test/v1",
            "rate limited",
            status_code=429,
            payload_split_recoverable=True,
            json_mode_unsupported=True,
        )
        self.assertFalse(guarded_error.payload_split_recoverable)
        self.assertFalse(guarded_error.json_mode_unsupported)

    def test_constructor_disables_sdk_retries_and_reads_transport_config(self) -> None:
        environment = {
            "LLM_MAX_RETRIES": "4",
            "LLM_RETRY_BASE_DELAY_SECONDS": "0.5",
            "LLM_RETRY_MAX_DELAY_SECONDS": "7",
        }
        with patch.dict(os.environ, environment, clear=False), patch("openai.OpenAI") as openai:
            client = llm_client.LLMClient(
                "openai",
                "test-model",
                "test-key",
                "https://example.test/v1",
                Path("unused-cache.json"),
                False,
            )
        self.assertEqual(client.transport_max_retries, 4)
        self.assertEqual(client.retry_base_delay_seconds, 0.5)
        self.assertEqual(client.retry_max_delay_seconds, 7.0)
        self.assertEqual(openai.call_args.kwargs["max_retries"], 0)

        with patch.dict(os.environ, {}, clear=True), patch("openai.OpenAI"):
            default_client = llm_client.LLMClient(
                "openai",
                "test-model",
                "test-key",
                "https://example.test/v1",
                Path("unused-cache.json"),
                False,
            )
        self.assertEqual(default_client.transport_max_retries, 3)
        self.assertEqual(default_client.retry_max_delay_seconds, 120.0)
        env_example = Path(__file__).resolve().parents[4] / ".env_example"
        self.assertIn("LLM_MAX_RETRIES=3", env_example.read_text())


class ParseRetryBoundaryTests(unittest.TestCase):
    def json_client(self) -> llm_client.LLMClient:
        client = llm_client.LLMClient.__new__(llm_client.LLMClient)
        client.provider = "openai"
        client.model = "test-model"
        client.api_base = "https://example.test/v1"
        client.extra_body = {}
        client.max_tokens = 64
        client.use_cache = False
        client.cache_path = Path("unused-cache.json")
        client.cache = {}
        client._cache_lock = llm_client.RLock()
        return client

    def test_transport_failure_does_not_consume_parse_retries(self) -> None:
        client = self.json_client()
        client.use_json_mode = False
        request_error = llm_client.LLMRequestError(
            "openai",
            "test-model",
            "https://example.test/v1",
            "unavailable",
            status_code=503,
            attempts=3,
        )
        client._call_chat = Mock(side_effect=request_error)
        with patch.dict(os.environ, {"LLM_PARSE_RETRIES": "5"}), patch.object(
            llm_client.time, "sleep"
        ) as sleep:
            with self.assertRaises(llm_client.LLMRequestError):
                client.complete_json("system", "user")
        self.assertEqual(client._call_chat.call_count, 1)
        sleep.assert_not_called()

    def test_parse_failure_uses_only_parse_retry_loop(self) -> None:
        client = self.json_client()
        client.use_json_mode = True
        client._call_chat = Mock(side_effect=["not JSON", '{"ok": true}'])
        with patch.dict(os.environ, {"LLM_PARSE_RETRIES": "1"}), patch.object(
            llm_client.time, "sleep"
        ) as sleep:
            self.assertEqual(client.complete_json("system", "user"), {"ok": True})
        self.assertEqual(client._call_chat.call_count, 2)
        self.assertEqual(
            [call.kwargs["json_mode"] for call in client._call_chat.call_args_list],
            [True, True],
        )
        self.assertTrue(client.use_json_mode)
        sleep.assert_called_once_with(1)

    def test_explicit_json_mode_unsupported_falls_back_once_and_persists(self) -> None:
        for status_code in (400, 422):
            with self.subTest(status_code=status_code):
                error_payload = (
                    {
                        "error": {
                            "param": "responseFormat",
                            "code": "UnsupportedParameter",
                            "message": "response_format is not supported",
                        }
                    }
                    if status_code == 400
                    else {
                        "error": {
                            "message": "This model does not support response_format",
                        }
                    }
                )
                mode_error = (
                    FakeHTTPError(status_code, body=error_payload)
                    if status_code == 400
                    else FakeHTTPError(status_code, response_json=error_payload)
                )
                client, completions = json_transport_client(
                    [
                        mode_error,
                        response_with_content('{"first": true}'),
                        response_with_content('{"second": true}'),
                    ]
                )
                with patch.dict(os.environ, {"LLM_PARSE_RETRIES": "4"}), patch.object(
                    llm_client.time, "sleep"
                ) as sleep:
                    self.assertEqual(client.complete_json("system", "first"), {"first": True})
                    self.assertEqual(client.complete_json("system", "second"), {"second": True})
                self.assertEqual(len(completions.calls), 3)
                self.assertIn("response_format", completions.calls[0])
                self.assertNotIn("response_format", completions.calls[1])
                self.assertNotIn("response_format", completions.calls[2])
                self.assertFalse(client.use_json_mode)
                sleep.assert_not_called()

    def test_generic_or_unstructured_400_does_not_disable_json_mode(self) -> None:
        errors = (
            FakeHTTPError(
                400,
                body={"error": {"code": "invalid_request_error", "message": "bad request"}},
            ),
            FakeHTTPError(
                400,
                body={
                    "error": {
                        "message": "response_format is valid; temperature is unsupported",
                    }
                },
            ),
            FakeHTTPError(400),
        )
        errors[2].args = ("response_format is unsupported",)
        for error in errors:
            with self.subTest(body=error.body):
                client, completions = json_transport_client(
                    [error, response_with_content('{"must": "not run"}')]
                )
                with self.assertRaises(llm_client.LLMRequestError) as raised:
                    client.complete_json("system", "user")
                self.assertFalse(raised.exception.json_mode_unsupported)
                self.assertEqual(len(completions.calls), 1)
                self.assertTrue(client.use_json_mode)

    def test_retryable_transport_status_never_triggers_json_mode_fallback(self) -> None:
        client, completions = json_transport_client(
            [
                FakeHTTPError(
                    429,
                    body={
                        "error": {
                            "param": "response_format",
                            "code": "unsupported_parameter",
                        }
                    },
                ),
                response_with_content('{"must": "not run"}'),
            ],
            retries=0,
        )
        with self.assertRaises(llm_client.LLMRequestError) as raised:
            client.complete_json("system", "user")
        self.assertFalse(raised.exception.json_mode_unsupported)
        self.assertFalse(raised.exception.payload_split_recoverable)
        self.assertEqual(len(completions.calls), 1)
        self.assertTrue(client.use_json_mode)

    def test_transport_error_in_json_mode_escapes_without_fallback_or_cache_write(self) -> None:
        client = self.json_client()
        client.use_json_mode = True
        request_error = llm_client.LLMRequestError(
            "openai",
            "test-model",
            "https://example.test/v1",
            "rate limited",
            status_code=429,
            attempts=2,
        )
        client._call_chat = Mock(side_effect=request_error)
        client.use_cache = True
        with TemporaryDirectory() as temp_dir:
            client.cache_path = Path(temp_dir) / "cache.json"
            with patch.dict(os.environ, {"LLM_PARSE_RETRIES": "4"}), patch.object(
                llm_client.time, "sleep"
            ) as sleep:
                with self.assertRaises(llm_client.LLMRequestError):
                    client.complete_json("system", "user")
            self.assertFalse(client.cache_path.exists())
        self.assertEqual(client.cache, {})
        self.assertEqual(client._call_chat.call_count, 1)
        self.assertTrue(client._call_chat.call_args.kwargs["json_mode"])
        sleep.assert_not_called()


if __name__ == "__main__":
    unittest.main()

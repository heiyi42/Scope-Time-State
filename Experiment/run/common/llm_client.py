from __future__ import annotations

from copy import deepcopy
from email.utils import parsedate_to_datetime
import hashlib
import json
import math
import os
from pathlib import Path
import re
from threading import RLock
import time
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


RETRYABLE_HTTP_STATUSES = frozenset({429, 502, 503, 504, 520, 521, 522, 523, 524})


class LLMRequestError(RuntimeError):
    def __init__(
        self,
        provider: str,
        model: str,
        endpoint: str,
        message: str,
        *,
        status_code: Optional[int] = None,
        attempts: int = 1,
        retryable: Optional[bool] = None,
        payload_split_recoverable: bool = False,
        json_mode_unsupported: bool = False,
    ):
        super().__init__(message)
        self.provider = provider
        self.model = model
        self.endpoint = endpoint
        self.status_code = status_code
        self.attempts = attempts
        self.retryable = status_code in RETRYABLE_HTTP_STATUSES if retryable is None else retryable
        self.payload_split_recoverable = bool(
            payload_split_recoverable and status_code not in RETRYABLE_HTTP_STATUSES
        )
        self.json_mode_unsupported = bool(
            json_mode_unsupported and status_code in {400, 422}
        )


def _nonnegative_int_env(name: str, default: str) -> int:
    try:
        value = int(os.environ.get(name, default))
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if value < 0:
        raise ValueError(f"{name} must not be negative")
    return value


def _nonnegative_float_env(name: str, default: str) -> float:
    try:
        value = float(os.environ.get(name, default))
    except ValueError as exc:
        raise ValueError(f"{name} must be a number") from exc
    if not math.isfinite(value) or value < 0:
        raise ValueError(f"{name} must be a finite nonnegative number")
    return value


def _http_status_code(exc: Exception) -> Optional[int]:
    value = getattr(exc, "status_code", None)
    if value is None:
        value = getattr(getattr(exc, "response", None), "status_code", None)
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _is_connection_transport_error(exc: Exception) -> bool:
    try:
        from openai import APIConnectionError, APITimeoutError
    except ImportError:
        return False
    return isinstance(exc, (APIConnectionError, APITimeoutError))


def _is_retryable_transport_error(exc: Exception, status_code: Optional[int]) -> bool:
    if status_code in RETRYABLE_HTTP_STATUSES:
        return True
    if isinstance(exc, json.JSONDecodeError):
        # The SDK raises this while decoding a truncated/malformed HTTP API
        # envelope. Model message JSON is parsed later by complete_json().
        return True
    return _is_connection_transport_error(exc)


def _response_headers(exc: Exception) -> Mapping[str, object]:
    headers = getattr(getattr(exc, "response", None), "headers", None)
    return headers if isinstance(headers, Mapping) else {}


def _structured_error_payloads(exc: Exception) -> List[object]:
    payloads: List[object] = []
    body = getattr(exc, "body", None)
    if isinstance(body, (Mapping, list, tuple)):
        payloads.append(body)
    response_json = getattr(getattr(exc, "response", None), "json", None)
    if callable(response_json):
        try:
            response_json = response_json()
        except Exception:
            response_json = None
    if isinstance(response_json, (Mapping, list, tuple)) and all(
        response_json is not payload for payload in payloads
    ):
        payloads.append(response_json)
    return payloads


def _structured_mappings(payloads: Iterable[object]) -> Iterable[Mapping[str, object]]:
    queue = list(payloads)
    while queue:
        item = queue.pop(0)
        if isinstance(item, Mapping):
            yield item
            queue.extend(item.values())
        elif isinstance(item, (list, tuple)):
            queue.extend(item)


def _normalized_error_marker(value: object) -> str:
    text = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", str(value or "").strip())
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def _structured_payload_split_recoverable(
    exc: Exception,
    payloads: Optional[Sequence[object]] = None,
) -> bool:
    markers = {
        "context_length_exceeded",
        "context_length_error",
        "context_window_exceeded",
        "max_context_length_exceeded",
        "request_too_large",
        "payload_too_large",
        "request_entity_too_large",
        "content_too_large",
    }
    selected_payloads = _structured_error_payloads(exc) if payloads is None else payloads
    for item in _structured_mappings(selected_payloads):
        normalized = {
            _normalized_error_marker(key): _normalized_error_marker(value)
            for key, value in item.items()
            if not isinstance(value, (Mapping, list, tuple))
        }
        for key in ("code", "type", "reason", "error_code"):
            if normalized.get(key) in markers:
                return True
        structured_text = "_".join(
            normalized.get(key, "") for key in ("message", "detail", "description")
        )
        if any(marker in structured_text for marker in markers):
            return True
        if (
            ("context_length" in structured_text or "context_window" in structured_text)
            and any(term in structured_text for term in ("exceed", "maximum", "too_large"))
        ):
            return True
    return False


def _payload_split_recoverable(
    exc: Exception,
    status_code: Optional[int],
    payloads: Optional[Sequence[object]] = None,
) -> bool:
    if status_code in RETRYABLE_HTTP_STATUSES or _is_connection_transport_error(exc):
        return False
    if isinstance(exc, json.JSONDecodeError):
        return True
    return _structured_payload_split_recoverable(exc, payloads)


def _message_rejects_response_format(message: str) -> bool:
    return bool(
        re.search(
            r"response_format_(?:(?:parameter|field)_)?(?:is_)?(?:unsupported|not_supported)",
            message,
        )
        or re.search(
            r"(?:unsupported_(?:parameter_)?|does_not_support_(?:the_)?)response_format",
            message,
        )
    )


def _json_mode_unsupported(
    exc: Exception,
    status_code: Optional[int],
    payloads: Optional[Sequence[object]] = None,
) -> bool:
    if status_code not in {400, 422}:
        return False
    selected_payloads = _structured_error_payloads(exc) if payloads is None else payloads
    for item in _structured_mappings(selected_payloads):
        normalized = {
            _normalized_error_marker(key): _normalized_error_marker(value)
            for key, value in item.items()
            if not isinstance(value, (Mapping, list, tuple))
        }
        parameter = normalized.get("param") or normalized.get("parameter") or normalized.get("field")
        code = normalized.get("code") or normalized.get("error_code") or normalized.get("type") or ""
        message = "_".join(
            normalized.get(key, "") for key in ("message", "detail", "description")
        )
        code_is_explicit = "response_format" in code and (
            "unsupported" in code or "not_supported" in code
        )
        unsupported_marker = any(
            marker in f"_{code}_{message}_"
            for marker in ("unsupported", "not_supported", "does_not_support")
        )
        if code_is_explicit or (
            parameter == "response_format" and unsupported_marker
        ) or (
            _message_rejects_response_format(message)
        ):
            return True
    return False


def _parse_retry_after_seconds(value: object, *, now_epoch: Optional[float] = None) -> Optional[float]:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        seconds = float(text)
    except ValueError:
        try:
            retry_at = parsedate_to_datetime(text)
        except (TypeError, ValueError, OverflowError):
            return None
        if retry_at.tzinfo is None:
            return None
        seconds = retry_at.timestamp() - (time.time() if now_epoch is None else now_epoch)
    return max(0.0, seconds) if math.isfinite(seconds) else None


def _parse_retry_after_milliseconds(value: object) -> Optional[float]:
    try:
        milliseconds = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    if not math.isfinite(milliseconds):
        return None
    return max(0.0, milliseconds / 1000.0)


def _structured_retry_after_seconds(payload: object) -> Optional[float]:
    """Read retry hints only from structured response fields, never exception text."""
    queue = [payload]
    while queue:
        item = queue.pop(0)
        if isinstance(item, Mapping):
            normalized = {str(key).lower().replace("-", "_"): value for key, value in item.items()}
            for key in ("retry_after_ms", "retry_after_milliseconds"):
                if key in normalized:
                    delay = _parse_retry_after_milliseconds(normalized[key])
                    if delay is not None:
                        return delay
            for key in ("retry_after", "retry_after_seconds"):
                if key in normalized:
                    delay = _parse_retry_after_seconds(normalized[key])
                    if delay is not None:
                        return delay
            queue.extend(item.values())
        elif isinstance(item, (list, tuple)):
            queue.extend(item)
    return None


def _retry_after_seconds(exc: Exception, *, now_epoch: Optional[float] = None) -> Optional[float]:
    headers = _response_headers(exc)
    normalized_headers = {str(key).lower(): value for key, value in headers.items()}
    retry_after_ms = normalized_headers.get("retry-after-ms")
    if retry_after_ms is not None:
        delay = _parse_retry_after_milliseconds(retry_after_ms)
        if delay is not None:
            return delay
    raw_value = normalized_headers.get("retry-after")
    delay = _parse_retry_after_seconds(raw_value, now_epoch=now_epoch)
    if delay is not None:
        return delay
    for payload in _structured_error_payloads(exc):
        delay = _structured_retry_after_seconds(payload)
        if delay is not None:
            return delay
    return None


def _bounded_retry_delay(
    exc: Exception,
    retry_index: int,
    *,
    base_delay_seconds: float,
    max_delay_seconds: float,
) -> float:
    retry_after = _retry_after_seconds(exc)
    if retry_after is not None:
        return min(max_delay_seconds, retry_after)
    delay = base_delay_seconds
    for _ in range(retry_index):
        delay = min(max_delay_seconds, delay * 2.0)
    return min(max_delay_seconds, delay)


class LLMClient:
    def __init__(self, provider: str, model: str, api_key: str, api_base: str, cache_path: Path, use_cache: bool):
        from openai import OpenAI

        self.provider = provider
        self.model = model
        self.api_base = api_base
        self.extra_body = self._request_extra_body()
        timeout_seconds = float(os.environ.get("LLM_REQUEST_TIMEOUT", "120"))
        self.transport_max_retries = _nonnegative_int_env("LLM_MAX_RETRIES", "3")
        self.retry_base_delay_seconds = _nonnegative_float_env("LLM_RETRY_BASE_DELAY_SECONDS", "1")
        self.retry_max_delay_seconds = _nonnegative_float_env("LLM_RETRY_MAX_DELAY_SECONDS", "120")
        self.client = OpenAI(
            api_key=api_key,
            base_url=api_base,
            timeout=timeout_seconds,
            # Transport retries are handled below so their status boundary and
            # Retry-After behavior are identical across OpenAI-compatible providers.
            max_retries=0,
        )
        self.max_tokens = int(os.environ.get("LLM_MAX_TOKENS", "2048"))
        disabled_json_mode_providers = {
            item.strip()
            for item in os.environ.get("LLM_DISABLE_JSON_MODE_FOR_PROVIDERS", "").split(",")
            if item.strip()
        }
        self.use_json_mode = provider not in disabled_json_mode_providers
        self.cache_path = cache_path
        self.use_cache = use_cache
        self.cache: Dict[str, object] = {}
        self._cache_lock = RLock()
        if use_cache and cache_path.exists():
            self.cache = json.loads(cache_path.read_text())

    def complete_json(self, system_prompt: str, user_prompt: str) -> Dict[str, object]:
        cache_key = hashlib.sha256(
            json.dumps(
                {
                    "provider": self.provider,
                    "model": self.model,
                    "api_base": self.api_base,
                    "max_tokens": self.max_tokens,
                    "extra_body": self.extra_body,
                    "system": system_prompt,
                    "user": user_prompt,
                },
                ensure_ascii=False,
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
        if self.use_cache:
            with self._cache_lock:
                if cache_key in self.cache:
                    return deepcopy(self.cache[cache_key])

        parse_retries = _nonnegative_int_env("LLM_PARSE_RETRIES", "2")
        json_mode = bool(self.use_json_mode)
        try:
            parsed = self._complete_json_in_mode(
                system_prompt,
                user_prompt,
                json_mode=json_mode,
                parse_retries=parse_retries,
            )
        except LLMRequestError as exc:
            if (
                not json_mode
                or exc.status_code not in {400, 422}
                or not exc.json_mode_unsupported
            ):
                raise
            self.use_json_mode = False
            parsed = self._complete_json_in_mode(
                system_prompt,
                user_prompt,
                json_mode=False,
                parse_retries=parse_retries,
            )

        if self.use_cache:
            with self._cache_lock:
                next_cache = dict(self.cache)
                next_cache[cache_key] = deepcopy(parsed)
                cache_text = json.dumps(next_cache, ensure_ascii=False, indent=2)
                self.cache = next_cache
                self.cache_path.parent.mkdir(parents=True, exist_ok=True)
                self.cache_path.write_text(cache_text)
        return deepcopy(parsed)

    def _complete_json_in_mode(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        json_mode: bool,
        parse_retries: int,
    ) -> Dict[str, object]:
        last_parse_error: Optional[Exception] = None
        for retry_index in range(parse_retries + 1):
            try:
                content = self._call_chat(system_prompt, user_prompt, json_mode=json_mode)
                return json_safe_object(parse_json_object(content))
            except ValueError as exc:
                last_parse_error = exc
            if retry_index < parse_retries:
                time.sleep(1 + retry_index)
        if last_parse_error is not None:
            raise last_parse_error
        raise ValueError("model did not return parseable JSON")

    def complete_text(self, system_prompt: str, user_prompt: str) -> str:
        cache_key = hashlib.sha256(
            json.dumps(
                {
                    "provider": self.provider,
                    "model": self.model,
                    "api_base": self.api_base,
                    "max_tokens": self.max_tokens,
                    "extra_body": self.extra_body,
                    "response_mode": "text",
                    "system": system_prompt,
                    "user": user_prompt,
                },
                ensure_ascii=False,
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
        if self.use_cache:
            with self._cache_lock:
                cached = self.cache.get(cache_key)
                if isinstance(cached, dict) and isinstance(cached.get("content"), str):
                    return str(cached["content"])

        content = self._call_chat(system_prompt, user_prompt, json_mode=False)

        if self.use_cache:
            with self._cache_lock:
                next_cache = dict(self.cache)
                next_cache[cache_key] = {"content": content}
                cache_text = json.dumps(next_cache, ensure_ascii=False, indent=2)
                self.cache = next_cache
                self.cache_path.parent.mkdir(parents=True, exist_ok=True)
                self.cache_path.write_text(cache_text)
        return content

    def complete_text_messages(self, messages: Sequence[Dict[str, str]]) -> str:
        message_rows = [{"role": str(item["role"]), "content": str(item["content"])} for item in messages]
        cache_key = hashlib.sha256(
            json.dumps(
                {
                    "provider": self.provider,
                    "model": self.model,
                    "api_base": self.api_base,
                    "max_tokens": self.max_tokens,
                    "extra_body": self.extra_body,
                    "response_mode": "text_messages",
                    "messages": message_rows,
                },
                ensure_ascii=False,
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
        if self.use_cache:
            with self._cache_lock:
                cached = self.cache.get(cache_key)
                if isinstance(cached, dict) and isinstance(cached.get("content"), str):
                    return str(cached["content"])

        content = self._call_chat_messages(message_rows, json_mode=False)

        if self.use_cache:
            with self._cache_lock:
                next_cache = dict(self.cache)
                next_cache[cache_key] = {"content": content}
                cache_text = json.dumps(next_cache, ensure_ascii=False, indent=2)
                self.cache = next_cache
                self.cache_path.parent.mkdir(parents=True, exist_ok=True)
                self.cache_path.write_text(cache_text)
        return content

    def _call_chat(self, system_prompt: str, user_prompt: str, json_mode: bool) -> str:
        messages = []
        if system_prompt.strip():
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": user_prompt})
        return self._call_chat_messages(messages, json_mode=json_mode)

    def _call_chat_messages(self, messages: Sequence[Dict[str, str]], json_mode: bool) -> str:
        request: Dict[str, object] = {
            "model": self.model,
            "messages": list(messages),
            "temperature": 0,
            "max_tokens": self.max_tokens,
        }
        if json_mode:
            request["response_format"] = {"type": "json_object"}
        if self.extra_body:
            request["extra_body"] = self.extra_body
        response = None
        for retry_index in range(self.transport_max_retries + 1):
            try:
                response = self.client.chat.completions.create(**request)
                break
            except Exception as exc:
                status_code = _http_status_code(exc)
                attempts = retry_index + 1
                retryable = _is_retryable_transport_error(exc, status_code)
                if retryable and retry_index < self.transport_max_retries:
                    delay = _bounded_retry_delay(
                        exc,
                        retry_index,
                        base_delay_seconds=self.retry_base_delay_seconds,
                        max_delay_seconds=self.retry_max_delay_seconds,
                    )
                    time.sleep(delay)
                    continue
                message = (
                    f"{self.provider} API request failed; model={self.model}; base_url={self.api_base}; "
                    f"status={status_code}; attempts={attempts}; error={exc}"
                )
                structured_payloads = _structured_error_payloads(exc)
                raise LLMRequestError(
                    self.provider,
                    self.model,
                    self.api_base,
                    message,
                    status_code=status_code,
                    attempts=attempts,
                    retryable=retryable,
                    payload_split_recoverable=_payload_split_recoverable(
                        exc,
                        status_code,
                        structured_payloads,
                    ),
                    json_mode_unsupported=_json_mode_unsupported(
                        exc,
                        status_code,
                        structured_payloads,
                    ),
                ) from exc
        if response is None:
            raise RuntimeError("unreachable LLM transport retry state")
        choice = response.choices[0]
        content = choice.message.content or ""
        if not content.strip():
            message_payload = choice.message.model_dump()
            reasoning_len = len(str(message_payload.get("reasoning_content") or ""))
            raise ValueError(
                "model returned empty message.content; "
                f"finish_reason={choice.finish_reason}; reasoning_content_chars={reasoning_len}; "
                "increase LLM_MAX_TOKENS or reduce the prompt/chunk size"
            )
        return content

    def _request_extra_body(self) -> Dict[str, object]:
        if self.provider != "deepseek":
            return {}
        thinking = os.environ.get("DEEPSEEK_THINKING", "").strip().lower()
        if thinking not in {"enabled", "disabled"}:
            return {}
        return {"thinking": {"type": thinking}}


def parse_json_object(text: str) -> Dict[str, object]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`")
        if stripped.startswith("json"):
            stripped = stripped[4:].strip()
    try:
        value = json.loads(stripped)
    except json.JSONDecodeError as first_error:
        start = stripped.find("{")
        if start < 0:
            raise ValueError(f"model did not return JSON: {text[:200]}")
        decoder = json.JSONDecoder()
        try:
            value, _ = decoder.raw_decode(stripped[start:])
        except json.JSONDecodeError:
            end = stripped.rfind("}")
            if end < start:
                raise ValueError(f"model did not return JSON: {text[:200]}") from first_error
            candidate = stripped[start : end + 1]
            try:
                value = json.loads(candidate)
            except json.JSONDecodeError:
                try:
                    import json_repair
                except ImportError as repair_error:
                    raise ValueError(f"model did not return repairable JSON: {text[:200]}") from repair_error
                try:
                    value = json.loads(json_repair.repair_json(candidate))
                except Exception as repair_error:
                    raise repair_error from first_error
    if not isinstance(value, dict):
        raise ValueError("model JSON output is not an object")
    return value


def json_safe_object(value: Dict[str, object]) -> Dict[str, object]:
    try:
        return json.loads(json.dumps(value, ensure_ascii=False))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"model JSON output is not serializable: {exc}") from exc


def provider_config(provider: str) -> Tuple[str, str, str]:
    prefix = provider.upper()
    api_key = os.environ.get(f"{prefix}_API_KEY")
    model = os.environ.get(f"{prefix}_MODEL")
    api_base = os.environ.get(f"{prefix}_API_BASE") or os.environ.get(f"{prefix}_BASE_URL")
    if not api_key:
        raise RuntimeError(f"missing {prefix}_API_KEY in .env or environment")
    if not model:
        raise RuntimeError(f"missing {prefix}_MODEL in .env or environment")
    if not api_base:
        raise RuntimeError(f"missing {prefix}_API_BASE or {prefix}_BASE_URL in .env or environment")
    return api_key, model, api_base

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import time
from typing import Any, Callable, Dict, Mapping, Optional

import requests

from Experiment.run.common.llm_client import LLMRequestError, parse_json_object, json_safe_object


StatusCallback = Callable[[str, dict[str, Any]], None]


class StableRequestsJsonClient:
    """OpenAI-compatible JSON client with retries, cache, and richer parse fallback.

    This is method-local on purpose. It does not change the main project LLM
    client or the previous graph method.
    """

    def __init__(
        self,
        model: str,
        api_key: str,
        api_base: str,
        cache_path: Path,
        use_cache: bool,
        request_timeout: int = 300,
        max_tokens: int = 8192,
        status_callback: Optional[StatusCallback] = None,
    ) -> None:
        self.model = model
        self.api_key = api_key
        self.api_base = api_base.rstrip("/")
        self.cache_path = cache_path
        self.use_cache = use_cache
        self.request_timeout = request_timeout
        self.max_tokens = max_tokens
        self.status_callback = status_callback
        self.call_index = 0
        self.cache: Dict[str, Dict[str, Any]] = {}
        if use_cache and cache_path.exists():
            try:
                self.cache = json.loads(cache_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                self.cache = {}

    def _emit(self, stage: str, **payload: Any) -> None:
        if self.status_callback is not None:
            self.status_callback(stage, payload)

    def _save_cache(self) -> None:
        if not self.use_cache:
            return
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.cache_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.cache, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.cache_path)

    def complete_json(self, system_prompt: str, user_prompt: str) -> Dict[str, Any]:
        self.call_index += 1
        cache_key = hashlib.sha256(
            json.dumps(
                {"model": self.model, "system": system_prompt, "user": user_prompt},
                ensure_ascii=False,
                sort_keys=True,
            ).encode()
        ).hexdigest()
        if self.use_cache and cache_key in self.cache:
            self._emit("llm_cache_hit", llm_call_index=self.call_index)
            return dict(self.cache[cache_key])

        url = f"{self.api_base}/chat/completions"
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.1,
            "max_tokens": self.max_tokens,
        }
        parse_retries = int(os.environ.get("LLM_PARSE_RETRIES", "4"))
        retry_sleep = float(os.environ.get("LLM_RETRY_SLEEP_SECONDS", "2"))
        last_error: Optional[Exception] = None

        for attempt in range(parse_retries + 1):
            self._emit("llm_request", llm_call_index=self.call_index, attempt=attempt + 1)
            for json_mode in (True, False):
                try:
                    req_payload = dict(payload)
                    if json_mode:
                        req_payload["response_format"] = {"type": "json_object"}
                    resp = requests.post(url, headers=headers, json=req_payload, timeout=self.request_timeout)
                    if resp.status_code != 200:
                        msg = f"API error {resp.status_code}: {resp.text[:500]}"
                        raise LLMRequestError("requests", self.model, self.api_base, msg)
                    data = resp.json()
                    content = self._message_text(data)
                    if not content.strip():
                        raise ValueError("model returned empty content")
                    parsed = json_safe_object(parse_json_object(content))
                    if self.use_cache:
                        self.cache[cache_key] = dict(parsed)
                        self._save_cache()
                    self._emit("llm_response_parsed", llm_call_index=self.call_index, attempt=attempt + 1)
                    return dict(parsed)
                except (ValueError, KeyError, json.JSONDecodeError, requests.Timeout, requests.ConnectionError) as exc:
                    last_error = exc
                    self._emit(
                        "llm_retryable_error",
                        llm_call_index=self.call_index,
                        attempt=attempt + 1,
                        error=repr(exc),
                    )
                    continue
                except LLMRequestError as exc:
                    if json_mode:
                        last_error = exc
                        self._emit(
                            "llm_retryable_error",
                            llm_call_index=self.call_index,
                            attempt=attempt + 1,
                            error=repr(exc),
                        )
                        continue
                    raise
            if attempt < parse_retries:
                time.sleep(retry_sleep * (attempt + 1))

        if last_error is not None:
            raise last_error
        raise ValueError("model did not return parseable JSON")

    def _message_text(self, data: Mapping[str, Any]) -> str:
        try:
            message = data["choices"][0]["message"]
        except (KeyError, IndexError, TypeError) as exc:
            sample = json.dumps(data, ensure_ascii=False)[:500]
            raise ValueError(f"unexpected API response structure: {sample}") from exc
        content = message.get("content") or ""
        if content:
            return str(content)
        reasoning_content = message.get("reasoning_content") or message.get("reasoning") or ""
        if reasoning_content:
            return str(reasoning_content)
        return ""


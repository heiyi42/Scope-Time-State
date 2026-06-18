from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import time
from typing import Dict


class LLMRequestError(RuntimeError):
    def __init__(self, provider: str, model: str, endpoint: str, message: str):
        super().__init__(message)
        self.provider = provider
        self.model = model
        self.endpoint = endpoint


class LLMClient:
    def __init__(self, provider: str, model: str, api_key: str, api_base: str, cache_path: Path, use_cache: bool):
        from openai import OpenAI

        self.provider = provider
        self.model = model
        self.api_base = api_base
        timeout_seconds = float(os.environ.get("LLM_REQUEST_TIMEOUT", "120"))
        max_retries = int(os.environ.get("LLM_MAX_RETRIES", "1"))
        self.client = OpenAI(
            api_key=api_key,
            base_url=api_base,
            timeout=timeout_seconds,
            max_retries=max_retries,
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
        self.cache: Dict[str, Dict[str, object]] = {}
        if use_cache and cache_path.exists():
            self.cache = json.loads(cache_path.read_text())

    def complete_json(self, system_prompt: str, user_prompt: str) -> Dict[str, object]:
        cache_key = hashlib.sha256(
            json.dumps(
                {
                    "provider": self.provider,
                    "model": self.model,
                    "api_base": self.api_base,
                    "system": system_prompt,
                    "user": user_prompt,
                },
                ensure_ascii=False,
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
        if self.use_cache and cache_key in self.cache:
            return deepcopy(self.cache[cache_key])

        parse_retries = int(os.environ.get("LLM_PARSE_RETRIES", "2"))
        last_parse_error: Optional[Exception] = None
        for retry_index in range(parse_retries + 1):
            json_modes = [True, False] if self.use_json_mode else [False]
            for json_mode in json_modes:
                try:
                    content = self._call_chat(system_prompt, user_prompt, json_mode=json_mode)
                    parsed = json_safe_object(parse_json_object(content))
                    break
                except ValueError as exc:
                    last_parse_error = exc
                    continue
                except Exception as json_mode_exc:
                    if json_mode or not self.use_json_mode:
                        last_parse_error = json_mode_exc
                        continue
                    raise
            else:
                if retry_index < parse_retries:
                    time.sleep(1 + retry_index)
                    continue
                if last_parse_error is not None:
                    raise last_parse_error
                raise ValueError("model did not return parseable JSON")
            break

        if self.use_cache:
            next_cache = dict(self.cache)
            next_cache[cache_key] = deepcopy(parsed)
            cache_text = json.dumps(next_cache, ensure_ascii=False, indent=2)
            self.cache = next_cache
            self.cache_path.parent.mkdir(exist_ok=True)
            self.cache_path.write_text(cache_text)
        return deepcopy(parsed)

    def _call_chat(self, system_prompt: str, user_prompt: str, json_mode: bool) -> str:
        request: Dict[str, object] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0,
            "max_tokens": self.max_tokens,
        }
        if json_mode:
            request["response_format"] = {"type": "json_object"}
        try:
            response = self.client.chat.completions.create(**request)
        except Exception as exc:
            message = f"{self.provider} API request failed; model={self.model}; base_url={self.api_base}; error={exc}"
            raise LLMRequestError(self.provider, self.model, self.api_base, message) from exc
        return response.choices[0].message.content or ""


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

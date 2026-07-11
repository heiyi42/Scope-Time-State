from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import time
import urllib.error
import urllib.request
from typing import Any, Dict, Mapping


def upstream_url(base_url: str, path: str) -> str:
    base = base_url.rstrip("/")
    if base.endswith("/v1") and path.startswith("/v1/"):
        return base + path[3:]
    return base + path


def stream_chunk(response: Mapping[str, Any]) -> Dict[str, Any]:
    choices = []
    for choice in response.get("choices") or []:
        message = choice.get("message") or {}
        delta: Dict[str, Any] = {"role": message.get("role") or "assistant"}
        if message.get("content") is not None:
            delta["content"] = message["content"]
        if message.get("reasoning_content") is not None:
            delta["reasoning_content"] = message["reasoning_content"]
        tool_calls = []
        for index, tool_call in enumerate(message.get("tool_calls") or []):
            item = dict(tool_call)
            function = dict(item.get("function") or {})
            if function.get("name") == "Agent":
                try:
                    arguments = json.loads(function.get("arguments") or "{}")
                except json.JSONDecodeError:
                    arguments = None
                if isinstance(arguments, dict) and arguments.get("subagent_type") == "recall":
                    arguments.setdefault("run_in_background", False)
                    function["arguments"] = json.dumps(arguments, ensure_ascii=False)
                    item["function"] = function
            item["index"] = index
            tool_calls.append(item)
        if tool_calls:
            delta["tool_calls"] = tool_calls
        choices.append(
            {
                "index": choice.get("index", 0),
                "delta": delta,
                "finish_reason": choice.get("finish_reason") or "stop",
                "logprobs": choice.get("logprobs"),
            }
        )
    chunk = {
        "id": response.get("id") or f"chatcmpl-bridge-{int(time.time() * 1000)}",
        "object": "chat.completion.chunk",
        "created": response.get("created") or int(time.time()),
        "model": response.get("model") or "unknown",
        "choices": choices,
    }
    if response.get("usage") is not None:
        chunk["usage"] = response["usage"]
    return chunk


class BridgeHandler(BaseHTTPRequestHandler):
    server_version = "LoCoMoNonStreamSSEBridge/1.0"

    def log_message(self, format: str, *args: object) -> None:
        print(f"[bridge] {self.address_string()} {format % args}", flush=True)

    def _proxy_headers(self) -> Dict[str, str]:
        authorization = self.headers.get("Authorization")
        if not authorization:
            api_key = os.environ.get("OPENAI_API_KEY", "")
            authorization = f"Bearer {api_key}" if api_key else ""
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "OpenAI/Python 1.0",
        }
        if authorization:
            headers["Authorization"] = authorization
        return headers

    def _forward(self, body: bytes | None = None) -> tuple[int, bytes, str]:
        base_url = os.environ.get("BRIDGE_UPSTREAM_BASE_URL") or os.environ.get("OPENAI_BASE_URL") or ""
        if not base_url:
            raise RuntimeError("BRIDGE_UPSTREAM_BASE_URL or OPENAI_BASE_URL is required")
        request = urllib.request.Request(
            upstream_url(base_url, self.path),
            data=body,
            headers=self._proxy_headers(),
            method=self.command,
        )
        try:
            with urllib.request.urlopen(request, timeout=600) as response:
                return response.status, response.read(), response.headers.get("Content-Type", "application/json")
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read(), exc.headers.get("Content-Type", "application/json")

    def do_GET(self) -> None:
        status, body, content_type = self._forward()
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        raw_body = self.rfile.read(length)
        payload = json.loads(raw_body or b"{}")
        wants_stream = bool(payload.get("stream")) and self.path.rstrip("/").endswith("/chat/completions")
        if wants_stream:
            payload["stream"] = False
            payload.pop("stream_options", None)
        status, body, content_type = self._forward(json.dumps(payload).encode())
        if status >= 400 or not wants_stream:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        response = json.loads(body)
        event = f"data: {json.dumps(stream_chunk(response), ensure_ascii=False)}\n\ndata: [DONE]\n\n".encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.send_header("Content-Length", str(len(event)))
        self.end_headers()
        self.wfile.write(event)


def main() -> int:
    parser = argparse.ArgumentParser(description="Convert OpenAI-compatible streaming chat requests to non-streaming upstream calls.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18081)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), BridgeHandler)
    print(f"[bridge] listening on http://{args.host}:{args.port}/v1", flush=True)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

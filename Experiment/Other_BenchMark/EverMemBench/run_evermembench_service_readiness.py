#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import socket
from dataclasses import dataclass
from typing import Iterable, List, Optional
from urllib.parse import urlparse
from urllib.request import ProxyHandler, Request, build_opener


NO_PROXY_OPENER = build_opener(ProxyHandler({}))


def load_dotenv_file(path: str) -> None:
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[len("export ") :].strip()
            if "=" not in line:
                continue
            name, value = line.split("=", 1)
            name = name.strip()
            value = value.strip().strip("'\"")
            if not name or name in os.environ:
                continue
            os.environ[name] = os.path.expandvars(value)


def load_project_dotenv() -> None:
    candidates = []
    here = os.path.abspath(os.path.dirname(__file__))
    for start in [os.getcwd(), here]:
        current = os.path.abspath(start)
        while True:
            candidates.append(os.path.join(current, ".env"))
            parent = os.path.dirname(current)
            if parent == current:
                break
            current = parent
    seen = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        load_dotenv_file(candidate)


@dataclass
class Check:
    name: str
    ok: bool
    detail: str


def env_value(name: str) -> str:
    return os.environ.get(name, "").strip()


def require_env(names: Iterable[str], *, any_of: bool = False) -> Check:
    names = list(names)
    present = [name for name in names if env_value(name)]
    if any_of:
        ok = bool(present)
        detail = "set: " + ",".join(present) if present else "missing one of: " + ",".join(names)
        return Check("env " + "|".join(names), ok, detail)
    missing = [name for name in names if not env_value(name)]
    ok = not missing
    detail = "ok" if ok else "missing: " + ",".join(missing)
    return Check("env " + ",".join(names), ok, detail)


def check_embedding_dim() -> Check:
    dim = env_value("OPENAI_EMBEDDING_DIM") or env_value("GRAPHITI_EMBEDDING_DIM") or env_value("EMBEDDING_DIM")
    ok = dim == "1536"
    return Check("embedding dim", ok, f"value={dim or '<unset>'}; expected=1536")


def parse_host_port(url_or_uri: str, default_port: Optional[int] = None) -> tuple[str, int]:
    parsed = urlparse(url_or_uri)
    if parsed.scheme in {"http", "https", "bolt"}:
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or (443 if parsed.scheme == "https" else default_port)
        if port is None:
            raise ValueError(f"missing port in {url_or_uri}")
        return host, int(port)
    if ":" in url_or_uri:
        host, port_text = url_or_uri.rsplit(":", 1)
        return host or "127.0.0.1", int(port_text)
    if default_port is None:
        raise ValueError(f"missing port in {url_or_uri}")
    return url_or_uri or "127.0.0.1", default_port


def socket_check(name: str, url_or_uri: str, default_port: Optional[int] = None, timeout: float = 2.0) -> Check:
    if not url_or_uri:
        return Check(name, False, "missing URL/URI")
    try:
        host, port = parse_host_port(url_or_uri, default_port=default_port)
    except Exception as exc:
        return Check(name, False, f"invalid endpoint: {exc}")
    sock = socket.socket()
    sock.settimeout(timeout)
    try:
        sock.connect((host, port))
    except Exception as exc:
        return Check(name, False, f"{host}:{port} not reachable: {exc}")
    finally:
        sock.close()
    return Check(name, True, f"{host}:{port} reachable")


def http_check(name: str, base_url: str, path: str = "/", timeout: float = 5.0) -> Check:
    if not base_url:
        return Check(name, False, "missing base URL")
    url = base_url.rstrip("/") + path
    try:
        req = Request(url, headers={"User-Agent": "evermembench-readiness/1.0"})
        with NO_PROXY_OPENER.open(req, timeout=timeout) as response:
            return Check(name, True, f"HTTP {response.status} {url}")
    except Exception as exc:
        # A 401/404 still proves the service is reachable, but urllib raises for it.
        status = getattr(exc, "code", None)
        if status in {401, 403, 404, 405}:
            return Check(name, True, f"HTTP {status} {url}")
        return Check(name, False, f"{url} failed: {exc}")


def http_check_candidates(name: str, base_urls: List[str], *, env_name: str = "", path: str = "/", timeout: float = 5.0) -> Check:
    failures: List[str] = []
    for base_url in base_urls:
        check = http_check(name, base_url, path=path, timeout=timeout)
        if check.ok:
            suffix = f"; set {env_name}={base_url.rstrip('/')}" if env_name else ""
            return Check(name, True, check.detail + suffix)
        failures.append(check.detail)
    return Check(name, False, " | ".join(failures))


def llm_chat_check() -> Check:
    base_url = env_value("LOCAL_API_BASE") or env_value("LLM_BASE_URL")
    model = env_value("LOCAL_MODEL") or env_value("LLM_ANSWER_MODEL") or env_value("LLM_MODEL")
    api_key = env_value("LOCAL_API_KEY") or env_value("LLM_API_KEY") or "local"
    if not base_url or not model:
        return Check("local llm chat", False, "missing LOCAL_API_BASE/LOCAL_MODEL or LLM_BASE_URL/LLM_MODEL")
    url = base_url.rstrip("/") + "/chat/completions"
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "Reply with OK."}],
        "temperature": 0,
        "max_tokens": 8,
    }
    try:
        req = Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
            method="POST",
        )
        with NO_PROXY_OPENER.open(req, timeout=30) as response:
            data = json.loads(response.read().decode("utf-8"))
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        return Check("local llm chat", bool(content.strip()), f"model={model}; response={content[:40]!r}")
    except Exception as exc:
        return Check("local llm chat", False, f"{url} failed: {exc}")


def main() -> int:
    load_project_dotenv()

    parser = argparse.ArgumentParser(description="Check EverMemBench local/self-host baseline service readiness.")
    parser.add_argument("--check-llm", action="store_true", help="Call the local OpenAI-compatible chat endpoint.")
    args = parser.parse_args()

    memos_base_url = env_value("MEMOS_LOCAL_BASE_URL")
    memos_candidates = [memos_base_url] if memos_base_url else ["http://localhost:8001", "http://localhost:8000"]

    checks: List[Check] = [
        require_env(["LOCAL_API_BASE", "LOCAL_API_KEY", "LOCAL_MODEL"]),
        require_env(["LLM_BASE_URL", "LLM_API_KEY", "LLM_ANSWER_MODEL", "LLM_JUDGE_MODEL"]),
        require_env(["OPENAI_EMBEDDING_API_KEY", "OPENAI_API_KEY"], any_of=True),
        require_env(["OPENAI_EMBEDDING_MODEL"]),
        check_embedding_dim(),
        http_check("mem0_local REST", env_value("MEM0_LOCAL_BASE_URL") or "http://localhost:8888"),
        http_check_candidates("memos_local REST", memos_candidates, env_name="MEMOS_LOCAL_BASE_URL"),
        socket_check("memobase service", env_value("MEMOBASE_BASE_URL") or "http://localhost:8019", default_port=8019),
        require_env(["MEMOBASE_API_TOKEN"]),
        socket_check("neo4j bolt", env_value("NEO4J_URI") or "bolt://localhost:7687", default_port=7687),
        require_env(["NEO4J_USER", "NEO4J_PASSWORD"]),
        require_env(["GRAPHITI_LLM_API_KEY", "GRAPHITI_LLM_BASE_URL", "GRAPHITI_LLM_MODEL"]),
        require_env(["GRAPHITI_EMBEDDING_API_KEY", "GRAPHITI_EMBEDDING_BASE_URL", "GRAPHITI_EMBEDDING_MODEL", "GRAPHITI_EMBEDDING_DIM"]),
    ]
    if args.check_llm:
        checks.append(llm_chat_check())

    width = max(len(check.name) for check in checks)
    for check in checks:
        marker = "PASS" if check.ok else "FAIL"
        print(f"{marker} {check.name:<{width}} {check.detail}")

    return 0 if all(check.ok for check in checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())

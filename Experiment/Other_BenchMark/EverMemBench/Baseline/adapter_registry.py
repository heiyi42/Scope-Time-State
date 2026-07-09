from __future__ import annotations

from importlib import import_module
import os
from pathlib import Path
import sys
from typing import Any, Dict, Optional, Tuple, Type


BASELINE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = Path(__file__).resolve().parents[4]
for import_path in (PROJECT_DIR, BASELINE_DIR):
    if str(import_path) not in sys.path:
        sys.path.insert(0, str(import_path))

from common.official_eval.imports import BaseAdapter, load_yaml  # noqa: E402


ADAPTERS: Dict[str, Tuple[str, str, Optional[Path]]] = {
    "memos_local": ("memos_local.adapter", "MemosLocalAdapter", BASELINE_DIR / "memos_local/config.yaml"),
    "mem0_local": ("mem0_local.adapter", "Mem0LocalAdapter", BASELINE_DIR / "mem0_local/config.yaml"),
    "memobase": ("memobase.adapter", "MemobaseAdapter", BASELINE_DIR / "memobase/config.yaml"),
    "graphiti_local": ("graphiti_local.adapter", "GraphitiLocalAdapter", BASELINE_DIR / "graphiti_local/config.yaml"),
    "llm": ("full_context_llm.adapter", "LLMAdapter", BASELINE_DIR / "full_context_llm/config.yaml"),
}


def supported_adapters() -> Tuple[str, ...]:
    return tuple(ADAPTERS)


def load_adapter_config(system_name: str, *, base_url: str = "") -> Dict[str, Any]:
    module_name, class_name, config_path = _adapter_spec(system_name)
    if config_path is None:
        config: Dict[str, Any] = {"name": system_name}
    else:
        config = load_yaml(str(config_path))
    if base_url:
        config["base_url"] = base_url
        if system_name in {"memos_local", "mem0_local"}:
            config["api_url"] = base_url
        elif system_name == "memobase":
            config["project_url"] = base_url
    return config


def get_adapter_class(system_name: str) -> Type[BaseAdapter]:
    module_name, class_name, _config_path = _adapter_spec(system_name)
    module = import_module(module_name)
    adapter_class = getattr(module, class_name)
    if not issubclass(adapter_class, BaseAdapter):
        raise TypeError(f"{system_name} adapter does not subclass BaseAdapter")
    return adapter_class


def create_adapter(
    system_name: str,
    *,
    output_dir: Optional[Path] = None,
    base_url: str = "",
    config_overrides: Optional[Dict[str, Any]] = None,
) -> BaseAdapter:
    if base_url:
        if system_name == "memobase":
            os.environ["MEMOBASE_BASE_URL"] = base_url
        elif system_name == "memos_local":
            os.environ["MEMOS_LOCAL_BASE_URL"] = base_url
        elif system_name == "mem0_local":
            os.environ["MEM0_LOCAL_BASE_URL"] = base_url
    config = load_adapter_config(system_name, base_url=base_url)
    if config_overrides:
        config.update(config_overrides)
    return get_adapter_class(system_name)(config, output_dir)


def _adapter_spec(system_name: str) -> Tuple[str, str, Optional[Path]]:
    try:
        return ADAPTERS[system_name]
    except KeyError as exc:
        supported = ", ".join(sorted(ADAPTERS))
        raise ValueError(f"unknown EverMemBench baseline adapter {system_name!r}; supported: {supported}") from exc

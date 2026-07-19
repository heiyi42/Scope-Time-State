from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import tempfile
import unittest

import yaml


BENCHMARK_DIR = Path(__file__).resolve().parents[1]
MODULE_PATH = BENCHMARK_DIR / "Baseline" / "graph_rag" / "run.py"
SPEC = importlib.util.spec_from_file_location("locomo_graph_rag", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
graph_rag = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(graph_rag)


class GraphRAGProfileTests(unittest.TestCase):
    def parse(self, profile: str):
        return graph_rag.resolve_args(
            graph_rag.parse_args(["--stage", "init", "--llm-profile", profile, "--sample-id", "conv-26"])
        )

    def test_qwen_uses_school_server_and_openai_embedding(self) -> None:
        with EnvironmentOverride(
            LOCAL_API_BASE="https://school.example.edu/v1",
            LOCAL_API_KEY="school-key",
            LOCAL_MODEL="Qwen2.5-7B-Instruct",
            OPENAI_EMBEDDING_API_KEY="embedding-key",
            OPENAI_EMBEDDING_BASE_URL="https://api.openai.com/v1",
        ):
            args = self.parse("qwen7b")
        self.assertEqual(args.model, "Qwen2.5-7B-Instruct")
        self.assertEqual(args.chat_api_base, "https://school.example.edu/v1")
        self.assertEqual(args.chat_api_key, "school-key")
        self.assertEqual(args.embedding_model, "text-embedding-3-small")
        self.assertEqual(args.embedding_api_base, "https://api.openai.com/v1")
        self.assertEqual(args.embedding_api_key, "embedding-key")

    def test_qwen_rejects_incomplete_school_endpoint(self) -> None:
        with EnvironmentOverride(
            LOCAL_API_BASE="",
            LOCAL_API_KEY="",
            LOCAL_MODEL="Qwen2.5-7B-Instruct",
        ):
            with self.assertRaisesRegex(ValueError, "LOCAL_API_BASE, LOCAL_API_KEY"):
                self.parse("qwen7b")

    def test_profiles_have_isolated_workspaces_and_outputs(self) -> None:
        with EnvironmentOverride(LOCAL_API_BASE="", LOCAL_API_KEY="", LOCAL_MODEL=""):
            qwen = self.parse("qwen7b")
            gpt = self.parse("gpt4omini")
        self.assertNotEqual(qwen.workspace, gpt.workspace)
        self.assertNotEqual(qwen.output, gpt.output)

    def test_current_graphrag_settings_get_separate_model_endpoints(self) -> None:
        with EnvironmentOverride(
            LOCAL_API_BASE="https://school.example.edu/v1",
            LOCAL_API_KEY="school-key",
            LOCAL_MODEL="Qwen2.5-7B-Instruct",
            OPENAI_EMBEDDING_API_KEY="embedding-key",
            OPENAI_EMBEDDING_BASE_URL="https://api.openai.com/v1",
        ):
            args = self.parse("qwen7b")
        settings = {
            "completion_models": {"default_completion_model": {"model": "old-chat"}},
            "embedding_models": {"default_embedding_model": {"model": "old-embedding"}},
        }
        graph_rag.configure_model_maps(settings, args)
        chat = settings["completion_models"]["default_completion_model"]
        embedding = settings["embedding_models"]["default_embedding_model"]
        self.assertEqual(chat["model"], "Qwen2.5-7B-Instruct")
        self.assertEqual(chat["api_base"], "https://school.example.edu/v1")
        self.assertEqual(chat["api_key"], "${GRAPHRAG_CHAT_API_KEY}")
        self.assertEqual(chat["call_args"]["max_tokens"], 1024)
        self.assertEqual(embedding["model"], "text-embedding-3-small")
        self.assertEqual(embedding["api_base"], "https://api.openai.com/v1")
        self.assertEqual(embedding["api_key"], "${GRAPHRAG_EMBEDDING_API_KEY}")
        self.assertNotIn("call_args", embedding)

    def test_workspace_configuration_writes_two_keys_without_crossing_them(self) -> None:
        with EnvironmentOverride(
            LOCAL_API_BASE="https://school.example.edu/v1",
            LOCAL_API_KEY="school-key",
            LOCAL_MODEL="Qwen2.5-7B-Instruct",
            OPENAI_EMBEDDING_API_KEY="embedding-key",
            OPENAI_EMBEDDING_BASE_URL="https://api.openai.com/v1",
        ):
            args = self.parse("qwen7b")
        with tempfile.TemporaryDirectory() as temporary_dir:
            args.workspace = Path(temporary_dir)
            (args.workspace / "settings.yaml").write_text(
                yaml.safe_dump(
                    {
                        "completion_models": {"default_completion_model": {"model": "old-chat"}},
                        "embedding_models": {"default_embedding_model": {"model": "old-embedding"}},
                    },
                    sort_keys=False,
                ),
                encoding="utf-8",
            )
            graph_rag.write_graphrag_configuration(args)
            env_text = (args.workspace / ".env").read_text(encoding="utf-8")
            settings = yaml.safe_load((args.workspace / "settings.yaml").read_text(encoding="utf-8"))
        self.assertIn("GRAPHRAG_CHAT_API_KEY=school-key", env_text)
        self.assertIn("GRAPHRAG_EMBEDDING_API_KEY=embedding-key", env_text)
        self.assertEqual(
            settings["completion_models"]["default_completion_model"]["api_base"],
            "https://school.example.edu/v1",
        )
        self.assertEqual(
            settings["embedding_models"]["default_embedding_model"]["api_base"],
            "https://api.openai.com/v1",
        )


class EnvironmentOverride:
    def __init__(self, **values: str) -> None:
        self.values = values
        self.original: dict[str, str | None] = {}

    def __enter__(self):
        for key, value in self.values.items():
            self.original[key] = os.environ.get(key)
            if value:
                os.environ[key] = value
            else:
                os.environ.pop(key, None)
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        for key, value in self.original.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


if __name__ == "__main__":
    unittest.main()

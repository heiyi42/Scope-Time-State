from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import unittest


BENCHMARK_DIR = Path(__file__).resolve().parents[1]
MODULE_PATH = BENCHMARK_DIR / "Baseline" / "ours_scope_time_state" / "run_sts.py"
SPEC = importlib.util.spec_from_file_location("locomo_sts_profiles", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
sts = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(sts)


class STSProfileTests(unittest.TestCase):
    def parse(self, profile: str, command: str = "run"):
        raw = sts.make_parser().parse_args(
            [command, "--llm-profile", profile, "--sample-id", "conv-26"]
        )
        return sts.resolve_args(raw)

    def value(self, values: list[str], option: str) -> str:
        return values[values.index(option) + 1]

    def test_profiles_are_pinned_to_shared_state_merge_schema(self) -> None:
        sts.validate_active_schema()
        self.assertEqual(sts.graph_builder.GRAPH_SCHEMA_V2, sts.STATE_MERGE_SCHEMA)
        self.assertEqual(sts.graph_query_runner.ACTIVE_GRAPH_SCHEMA_V2, sts.STATE_MERGE_SCHEMA)

    def test_qwen_build_profile_uses_local_7b_budget(self) -> None:
        with self.local_endpoint_env(model=""):
            args = self.parse("qwen7b", "build")
        values = sts.build_graph_args(args)
        self.assertEqual(args.model, "qwen2.5:7b")
        self.assertEqual(args.llm_base_url, "http://127.0.0.1:11434/v1")
        self.assertEqual(self.value(values, "--graph-schema"), "v2")
        self.assertEqual(self.value(values, "--message-chunk-size"), "4")
        self.assertEqual(self.value(values, "--claim-workers"), "1")
        self.assertEqual(self.value(values, "--resolver-workers"), "1")
        self.assertEqual(self.value(values, "--max-tokens"), "1024")

    def test_qwen_profile_uses_school_server_local_env_as_one_endpoint(self) -> None:
        with self.local_endpoint_env(
            base_url="https://school.example.edu/v1",
            api_key="school-secret",
            model="Qwen2.5-7B-Instruct",
        ):
            args = self.parse("qwen7b", "build")
        self.assertEqual(args.model, "Qwen2.5-7B-Instruct")
        self.assertEqual(args.llm_base_url, "https://school.example.edu/v1")
        self.assertEqual(args.llm_api_key, "school-secret")

    def test_qwen_school_server_config_rejects_incomplete_endpoint(self) -> None:
        with self.local_endpoint_env(base_url="", api_key="", model="Qwen2.5-7B-Instruct"):
            with self.assertRaisesRegex(ValueError, "LOCAL_API_BASE, LOCAL_API_KEY"):
                self.parse("qwen7b", "build")

    def test_gpt4omini_build_profile_uses_standard_budget(self) -> None:
        args = self.parse("gpt4omini", "build")
        values = sts.build_graph_args(args)
        self.assertEqual(args.model, "gpt-4o-mini")
        self.assertEqual(self.value(values, "--claim-workers"), "4")
        self.assertEqual(self.value(values, "--resolver-workers"), "4")
        self.assertEqual(self.value(values, "--max-tokens"), "4096")

    def test_both_query_profiles_use_text_embedding_3_small_and_full_chain(self) -> None:
        for profile in sts.PROFILES:
            with self.subTest(profile=profile):
                args = self.parse(profile, "query")
                values = sts.query_graph_args(args)
                self.assertEqual(self.value(values, "--embedding-model"), "text-embedding-3-small")
                self.assertEqual(self.value(values, "--variants"), "graph_embedding_scope_event")
                self.assertEqual(self.value(values, "--time-role-selector"), "llm")
                self.assertEqual(self.value(values, "--event-time-routing"), "rerank")
                self.assertEqual(self.value(values, "--graph-expansion"), "relation-aware")
                self.assertEqual(self.value(values, "--evidence-selector"), "llm-ledger")

    def test_profile_artifacts_and_caches_do_not_collide(self) -> None:
        qwen = self.parse("qwen7b")
        gpt = self.parse("gpt4omini")
        self.assertNotEqual(qwen.graph_root, gpt.graph_root)
        self.assertNotEqual(qwen.build_cache, gpt.build_cache)
        self.assertNotEqual(qwen.query_cache, gpt.query_cache)
        self.assertNotEqual(sts.result_path(qwen), sts.result_path(gpt))

    def test_qwen_llm_endpoint_does_not_override_embedding_endpoint(self) -> None:
        with self.local_endpoint_env(model=""):
            args = self.parse("qwen7b")
        old_values = {
            key: os.environ.get(key)
            for key in ("OPENAI_MODEL", "OPENAI_API_BASE", "OPENAI_API_KEY")
        }
        try:
            sts.configure_llm_environment(args)
            self.assertEqual(os.environ["OPENAI_MODEL"], "qwen2.5:7b")
            self.assertEqual(os.environ["OPENAI_API_BASE"], "http://127.0.0.1:11434/v1")
            values = sts.query_graph_args(args)
            self.assertEqual(
                self.value(values, "--embedding-base-url"),
                "https://api.openai.com/v1",
            )
        finally:
            for key, value in old_values.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

    def local_endpoint_env(self, *, base_url: str = "", api_key: str = "", model: str = ""):
        return EnvironmentOverride(
            LOCAL_API_BASE=base_url,
            LOCAL_API_KEY=api_key,
            LOCAL_MODEL=model,
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

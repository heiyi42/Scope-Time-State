from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch


MODULE_PATH = Path(__file__).resolve().parent / "run_locomo_scope_time_state.py"
SPEC = importlib.util.spec_from_file_location("locomo_scope_time_state_ablation", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
ablation = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ablation)


class LoCoMoScopeTimeStateAblationTests(unittest.TestCase):
    def parse(self, policy: str = "all"):
        return ablation.make_parser().parse_args(
            [policy, "--sample-id", "conv-26", "--limit-cases", "5"]
        )

    @staticmethod
    def value(values: list[str], option: str) -> str:
        return values[values.index(option) + 1]

    def test_all_policies_are_exposed(self) -> None:
        self.assertEqual(
            ablation.POLICIES,
            ("event-rag", "scope-event", "scope-event-time", "sts"),
        )

    def test_every_policy_uses_the_same_fixed_budget(self) -> None:
        args = self.parse()
        for policy in ablation.POLICIES:
            with self.subTest(policy=policy):
                values = ablation.query_args(args, policy)
                self.assertEqual(self.value(values, "--retrieval-policy"), policy)
                self.assertEqual(self.value(values, "--candidate-k"), "80")
                self.assertEqual(self.value(values, "--embedding-candidate-k"), "80")
                self.assertEqual(self.value(values, "--max-context-events"), "24")
                self.assertEqual(self.value(values, "--evidence-selector"), "direct")
                self.assertEqual(self.value(values, "--variants"), "graph_embedding_scope_event")

    def test_policy_artifacts_do_not_collide(self) -> None:
        args = self.parse()
        outputs = {ablation.result_path(args, policy) for policy in ablation.POLICIES}
        caches = {ablation.cache_path(args, policy) for policy in ablation.POLICIES}
        self.assertEqual(len(outputs), len(ablation.POLICIES))
        self.assertEqual(len(caches), len(ablation.POLICIES))
        self.assertEqual(
            ablation.result_path(args, "sts"),
            args.result_dir / "sts" / "conv-26" / "sts.json",
        )

    def test_default_graph_root_is_the_canonical_state_merge_directory(self) -> None:
        args = self.parse("sts")
        self.assertEqual(
            ablation.CURRENT_GRAPH_ROOT.name,
            "locomo_qa_sample_graph_v2_state_merge",
        )
        self.assertEqual(
            ablation.graph_dir(args),
            ablation.CURRENT_GRAPH_ROOT / "conv-26",
        )

    def test_all_samples_runs_four_policies_for_ten_conversations(self) -> None:
        with patch.object(ablation.graph_query_runner, "main", return_value=0) as runner:
            status = ablation.main(["all", "--all-samples", "--limit-cases", "1"])

        self.assertEqual(status, 0)
        self.assertEqual(runner.call_count, 40)
        forwarded = [call.args[0] for call in runner.call_args_list]
        sample_ids = [self.value(values, "--sample-id") for values in forwarded]
        policies = [self.value(values, "--retrieval-policy") for values in forwarded]
        self.assertEqual(set(sample_ids), set(ablation.DEFAULT_SAMPLE_IDS))
        self.assertEqual(set(policies), set(ablation.POLICIES))

    def test_all_samples_rejects_one_sample_graph_dir(self) -> None:
        with self.assertRaisesRegex(ValueError, "identifies one sample"):
            ablation.main(["all", "--all-samples", "--graph-dir", "/tmp/one-graph"])


if __name__ == "__main__":
    unittest.main()

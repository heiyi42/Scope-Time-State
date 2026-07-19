from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch


MODULE_PATH = Path(__file__).resolve().parent / "run_locomo_claim_scope_time_state.py"
SPEC = importlib.util.spec_from_file_location("locomo_claim_scope_time_state_ablation", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
ablation = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ablation)


class LoCoMoClaimScopeTimeStateAblationTests(unittest.TestCase):
    @staticmethod
    def value(values: list[str], option: str) -> str:
        return values[values.index(option) + 1]

    def parse(self, policy: str = "all"):
        return ablation.make_parser().parse_args([policy, "--sample-id", "conv-26"])

    def test_claim_policies_are_additive(self) -> None:
        self.assertEqual(
            ablation.POLICIES,
            ("claim", "scope-claim", "scope-claim-time", "scope-claim-time-state"),
        )
        self.assertTrue(
            set(ablation.POLICIES).isdisjoint(ablation.graph_query_runner.EVENT_RETRIEVAL_POLICIES)
        )

    def test_fixed_claim_budget_and_time_selector(self) -> None:
        args = self.parse()
        for policy in ablation.POLICIES:
            values = ablation.query_args(args, policy)
            self.assertEqual(self.value(values, "--variants"), "graph_embedding_scope_claim")
            self.assertEqual(self.value(values, "--top-k"), "16")
            self.assertEqual(self.value(values, "--max-claim-lines"), "24")
            self.assertEqual(self.value(values, "--max-context-events"), "24")
            self.assertEqual(self.value(values, "--max-state-lines"), "0")
            self.assertEqual(self.value(values, "--scope-backoff-k"), "8")
            self.assertEqual(self.value(values, "--candidate-k"), "80")
            self.assertEqual(self.value(values, "--embedding-candidate-k"), "80")
            self.assertEqual(self.value(values, "--time-role-selector"), "llm-top2")

    def test_results_do_not_overlap_event_ablation(self) -> None:
        args = self.parse()
        self.assertEqual(
            ablation.result_path(args, "scope-claim-time-state"),
            args.result_dir
            / "scope-claim-time-state"
            / "conv-26"
            / "scope-claim-time-state.json",
        )
        self.assertEqual(args.result_dir.name, "claim_scope_time_state_ablation")

    def test_all_samples_runs_all_claim_policies(self) -> None:
        with patch.object(ablation.graph_query_runner, "main", return_value=0) as runner:
            status = ablation.main(["all", "--all-samples", "--limit-cases", "1"])
        self.assertEqual(status, 0)
        self.assertEqual(runner.call_count, 40)


if __name__ == "__main__":
    unittest.main()

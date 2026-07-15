# EPBench Long Book adapter for official ARTEM

The files under `Baseline/ARTEM/` are the official upstream implementation and
must remain unchanged. This adapter supplies only repository-specific paths,
EPBench parquet conversion, checkpointed extraction, and a runnable CLI.

Fixed run contract:

- corpus: Claude 3.5 Sonnet Long Book, 196 validated chapters, 102,870 tokens;
- event extraction, answer generation, and judge model: `gpt-4o-mini`;
- time/space/entity/content retrieval vigilance: `[1.0, 0.99, 0.99, 0.98]`.

The SentenceTransformer `all-MiniLM-L6-v2` remains the official ARTEM semantic
channel encoder; it is not an answer/extraction/judge LLM. The adapter runs all
686 source QA rows and does not reproduce the paper's hardware, DeepSeek model,
600/548-row reporting subsets, or output-length exclusions.

Evaluation stays in the official modules:

- `LLM_as_a_Judge.py`: official memory-augmented answer prompt and gpt-4o-mini judge;
- `STEM_evaluation.py`: retrieval-only metrics;
- `ARTEM_evaluation.py`: integrated ARTEM metrics.

The adapter invokes their full-dataset functions and deliberately does not call
the separate `filter_for_paper_version` functions.

The official answer path selects index `0` for `latest` even though its time
list is ascending. The adapter overrides only that selection and uses the last
item from `all_vigilant_events_time_sorted`, matching the paper contract and
the official `STEM_evaluation.py` behavior. Upstream files remain unchanged.

The official retrieval serializer also omits `post_entities`. The adapter
restores it from the formatted source event before answer generation so the
official prompt can answer the `Other entities` trace without changing upstream.

```bash
ADAPTER=Experiment/Other_BenchMark/Episodic-Memory/adapters/artem_epbench

conda run -n py311 python "$ADAPTER/run.py" \
  --stage extract \
  --output-root "$ADAPTER/output/smoke" \
  --limit-chapters 2

conda run -n py311 python "$ADAPTER/run.py" \
  --stage retrieve \
  --output-root "$ADAPTER/output/smoke" \
  --question-offset 240 \
  --limit-questions 2 \
  --max-retrievals 2

conda run -n py311 python "$ADAPTER/run.py" \
  --stage answer \
  --output-root "$ADAPTER/output/smoke" \
  --question-offset 240 \
  --limit-questions 2

conda run -n py311 python "$ADAPTER/run.py" \
  --stage stem-eval \
  --output-root "$ADAPTER/output/smoke"

conda run -n py311 python "$ADAPTER/run.py" \
  --stage artem-eval \
  --output-root "$ADAPTER/output/smoke"
```

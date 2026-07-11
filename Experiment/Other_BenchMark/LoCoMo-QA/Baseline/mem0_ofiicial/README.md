# Mem0 official LoCoMo implementation

This directory is an isolated implementation of the public
[`mem0ai/memory-benchmarks`](https://github.com/mem0ai/memory-benchmarks) Mem0 ingest/retrieval protocol,
with QA scored by the original [`snap-research/locomo`](https://github.com/snap-research/locomo)
`task_eval/evaluation.py` semantics.
It does not replace `Baseline/mem0_local`.

Pinned upstream reference:

```text
commit 4b61c5d31b9c668a12b4f5e78064248a02c82d2b
LoCoMo scorer commit 3eb6f2c585f5e1699204e3c3bdf7adc5c28cb376
```

The run uses the official protocol boundaries:

- every non-empty conversation turn is one ingest chunk;
- roles are assigned from the two LoCoMo speakers;
- the session timestamp is sent as the Mem0 `timestamp` field;
- OSS Mem0 calls use `POST /memories` and `POST /search` with the official payload shape;
- retrieval and QA use only the top 20 memories;
- categories 2/3/4 use LoCoMo's normalized, stemmed token-F1;
- category 1 uses LoCoMo's comma-split multi-answer F1;
- categories 1–4 are scored by default; category 5 is excluded.

The requested model configuration is fixed by default:

```text
Mem0 ingest / fact extraction: gpt-4o-mini
QA answerer:                   gpt-4o-mini
Scorer:                        LoCoMo official deterministic F1 (no judge LLM)
```

`mem0-config.yaml` configures the Mem0 OSS server's ingest LLM. It must be mounted into the
server before ingest; changing it after memories have already been written does not rebuild those
memories.

## Run

Configure the QA OpenAI-compatible endpoint in the environment:

```bash
export OPENAI_API_KEY=...
export OPENAI_BASE_URL=https://api.openai.com/v1
```

Start the Mem0 OSS server with [`mem0-config.yaml`](mem0-config.yaml), then run one conversation:

```bash
conda run -n py311 env PYTHONDONTWRITEBYTECODE=1 \
  python Experiment/Other_BenchMark/LoCoMo-QA/Baseline/mem0_ofiicial/runner.py \
  --project-name locomo_mem0_official_gpt4omini \
  --sample-id conv-26 \
  --answerer-model gpt-4o-mini \
  --provider openai \
  --mem0-host http://localhost:8888
```

For retrieval-only checkpoints followed by a separate QA/scoring pass:

```bash
conda run -n py311 python Experiment/Other_BenchMark/LoCoMo-QA/Baseline/mem0_ofiicial/runner.py \
  --project-name locomo_mem0_official_gpt4omini \
  --sample-id conv-26 \
  --predict-only

conda run -n py311 python Experiment/Other_BenchMark/LoCoMo-QA/Baseline/mem0_ofiicial/runner.py \
  --project-name locomo_mem0_official_gpt4omini \
  --sample-id conv-26 \
  --evaluate-only \
  --answerer-model gpt-4o-mini
```

Gold answers are read only by the deterministic scorer after answer generation. Gold answers,
evidence IDs, and question categories are not passed to the QA model.

Outputs are written under:

```text
Graph/output/results/locomo_qa/mem0_ofiicial/predicted_<project-name>/
```

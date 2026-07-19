# LoCoMo STS — Qwen 2.5 7B and GPT-4o-mini

This is the Qwen 7B and GPT-4o-mini entrypoint for the repository's active Scope-Time-State method. It does not fork or copy the graph implementation: both graph construction and QA call the single maintained implementation in `Baseline/ours_scope_time_state`. The entrypoint hard-checks the shared `scope-time-state-graph-v2-state-merge` schema and refuses to run against the retired `locomo-qa-sample-sts-graph-v2-time-role` format.

Both profiles use the same graph and retrieval semantics. Only model-capacity settings differ:

- Qwen 7B construction: four turns per extraction chunk, one Claim worker, one resolver worker, two Claims per turn, 1024 output tokens.
- GPT-4o-mini construction: four turns per extraction chunk, four Claim workers, four resolver workers, two Claims per turn, 4096 output tokens.
- Retrieval: Scope BM25+dense union, scoped Event BM25+dense union, question-only Time-role selection, Time rerank, relation-aware `Event -> Claim -> StateFacet` expansion.
- Qwen answer path: 16 context Events, 12 StateFacet lines, 512 output tokens, one worker.
- GPT-4o-mini answer path: 24 context Events, 8 StateFacet lines, 2048 output tokens, four workers.
- Dense retrieval remains limited to Scope and Event and is fixed to `text-embedding-3-small` for both profiles.

Start Ollama and make sure the model exists:

```bash
ollama pull qwen2.5:7b
ollama serve
```

For Qwen on a school OpenAI-compatible server, set the endpoint as one complete
triple in the repository `.env`:

```env
LOCAL_API_BASE=https://your-school-server.example/v1
LOCAL_API_KEY=your-school-server-key
LOCAL_MODEL=Qwen2.5-7B-Instruct
```

`--llm-profile qwen7b` uses this triple when `LOCAL_MODEL` is filled. If
`LOCAL_MODEL` is absent or still a placeholder, it falls back to local Ollama.
The server LLM settings are mapped to the shared OpenAI-compatible client; they
do not replace the separate `OPENAI_EMBEDDING_*` settings below.

Configure embeddings separately. For OpenAI embeddings:

```bash
export OPENAI_EMBEDDING_API_KEY=...
export OPENAI_EMBEDDING_BASE_URL=https://api.openai.com/v1
export OPENAI_EMBEDDING_MODEL=text-embedding-3-small
```

Build and run all questions for one conversation:

```bash
python Experiment/Other_BenchMark/LoCoMo-QA/Baseline/ours_scope_time_state/run_sts.py run \
  --llm-profile qwen7b \
  --sample-id conv-26
```

Use the same method with GPT-4o-mini:

```bash
python Experiment/Other_BenchMark/LoCoMo-QA/Baseline/ours_scope_time_state/run_sts.py run \
  --llm-profile gpt4omini \
  --sample-id conv-26
```

The two stages can be resumed independently with `build` and `query`. A bounded end-to-end smoke run is:

```bash
python Experiment/Other_BenchMark/LoCoMo-QA/Baseline/ours_scope_time_state/run_sts.py run \
  --llm-profile qwen7b \
  --sample-id conv-26 \
  --event-limit 2 \
  --limit-cases 1
```

Outputs are isolated by model under `Graph/locomo_qa/ours_scope_time_state/` and are ignored by Git. Override `--graph-root`, `--result-dir`, or cache paths when running multiple experimental profiles.

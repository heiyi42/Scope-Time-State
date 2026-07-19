# LoCoMo-QA GraphRAG Baseline

This folder is a thin LoCoMo data adapter for the existing Microsoft GraphRAG
Python package. It does not implement a custom graph builder, graph retriever,
or GraphRAG algorithm.

The adapter does three things:

1. Convert `data/locomo10.json` conversations into GraphRAG workspace input.
2. Orchestrate the installed `graphrag` CLI for init, index, and query.
3. Evaluate generated answers with the same LoCoMo answer-F1 helpers used by
   the other baselines in this directory.

The query stage adds the same kind of LoCoMo answer-format instruction used by
the other local baselines: return a short gold-style answer, cite dialog ids, and
abstain with a fixed unavailable phrase when the premise is unsupported. It also
passes GraphRAG's native `--response-type` option as a compact JSON hint instead
of the package default `Multiple Paragraphs`.

GraphRAG CLI query output does not expose LoCoMo dialog ids, so evidence/context
recall columns cannot be recovered from old CLI-only answer files. For new local
search runs, `run.py` calls the official GraphRAG Python API to capture context
text units, maps `[D#:turn]` markers back to LoCoMo dialog ids, and reports
`cand_r`, `cand_p`, `ev_r`, `ev_p`, and `ev_f1` in the same table shape as the
other local baselines.

## Files

- `prepare_input.py`: converts LoCoMo conversations into GraphRAG input text.
- `run.py`: runs `prepare`, `init`, `index`, `answer`, and `evaluate` stages.

## Install

The package is not vendored in this repository. Install it in the Python
environment used for the experiment:

```powershell
& "C:\Anaconda\envs\py311\python.exe" -m pip install graphrag
```

## Environment

The wrapper supports two isolated LLM profiles: `qwen7b` and `gpt4omini`.
For Qwen on the school OpenAI-compatible server, configure the repository
`.env` with one complete chat endpoint:

```env
LOCAL_API_BASE=https://your-school-server.example/v1
LOCAL_API_KEY=your-school-server-key
LOCAL_MODEL=Qwen2.5-7B-Instruct
```

Embedding always uses OpenAI `text-embedding-3-small`, never the school Qwen
endpoint:

```env
OPENAI_EMBEDDING_API_KEY=your-openai-key
OPENAI_EMBEDDING_BASE_URL=https://api.openai.com/v1
```

After `graphrag init`, the wrapper rewrites the generated model maps so chat and
embedding use separate API keys and `api_base` values. Workspaces and result
files are also isolated by profile.

## Run

Use an absolute workspace path to keep GraphRAG outputs in the intended folder:

```powershell
Set-Location -LiteralPath "C:\学习\项目组\AAAI\Scope-Time-State"
$ws = "C:\学习\项目组\AAAI\Scope-Time-State\Graph\output\baseline_store\locomo_qa\graph_rag\qwen25_7b\conv-26"
```

Prepare GraphRAG input:

```powershell
& "C:\Anaconda\envs\py311\python.exe" -u `
  ".\Experiment\Other_BenchMark\LoCoMo-QA\Baseline\graph_rag\run.py" `
  --stage prepare `
  --llm-profile qwen7b `
  --sample-id conv-26 `
  --workspace $ws
```

Initialize the GraphRAG workspace:

```powershell
& "C:\Anaconda\envs\py311\python.exe" -u `
  ".\Experiment\Other_BenchMark\LoCoMo-QA\Baseline\graph_rag\run.py" `
  --stage init `
  --llm-profile qwen7b `
  --workspace $ws `
  --force-init
```

Index:

```powershell
& "C:\Anaconda\envs\py311\python.exe" -u `
  ".\Experiment\Other_BenchMark\LoCoMo-QA\Baseline\graph_rag\run.py" `
  --stage index `
  --llm-profile qwen7b `
  --workspace $ws
```

Answer a small smoke subset:

```powershell
& "C:\Anaconda\envs\py311\python.exe" -u `
  ".\Experiment\Other_BenchMark\LoCoMo-QA\Baseline\graph_rag\run.py" `
  --stage answer `
  --llm-profile qwen7b `
  --sample-id conv-26 `
  --workspace $ws `
  --question-types multi-hop open-domain `
  --limit-per-type 1 `
  --method local `
  --output ".\Graph\output\results\results_locomo_qa_graph_rag_conv26_smoke.jsonl"
```

Evaluate an answer file:

```powershell
& "C:\Anaconda\envs\py311\python.exe" -u `
  ".\Experiment\Other_BenchMark\LoCoMo-QA\Baseline\graph_rag\run.py" `
  --stage evaluate `
  --sample-id conv-26 `
  --workspace $ws `
  --predictions ".\Graph\output\results\results_locomo_qa_graph_rag_conv26_smoke.jsonl" `
  --eval-output ".\Graph\output\results\results_locomo_qa_graph_rag_conv26_smoke_eval.json"
```

Use `--stage all` to run prepare, init, index, answer, and evaluate in sequence
after the package and credentials are ready.

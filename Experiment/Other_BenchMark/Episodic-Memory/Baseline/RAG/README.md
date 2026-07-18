# EPBench Paragraph RAG Baseline

`run.py` implements the paper-style RAG baseline:

1. Load the canonical EPBench book and QA file.
2. Split the book into labeled paragraph chunks.
3. Embed chunks and questions with `text-embedding-3-small`.
4. Retrieve top-68 chunks by cosine similarity.
5. Put the retrieved chunks before the question.
6. Answer with `gpt-4o-mini`.

The answer stage does not use gold answers or judge output. Gold fields are
kept only in the prediction JSONL so the post-hoc judge can score the answers.

Default output:

```text
artifacts\baselines\rag_canonical_book_paragraph_top68_gpt4omini_paper_prompt
```

Run from the `Episodic-Memory` project root:

```powershell
$ragOut = ".\artifacts\baselines\rag_canonical_book_paragraph_top68_gpt4omini_paper_prompt"

& "C:\Anaconda\envs\py311\python.exe" -u ".\Baseline\RAG\run.py" `
  --limit -1 `
  --reset `
  --out_dir $ragOut
```

Then score with:

```powershell
& "C:\Anaconda\envs\py311\python.exe" -u ".\Baseline\official_epbench_llm_judge_eval_strict.py" `
  --predictions_path "$ragOut\rag_paragraph_embedding_predictions.jsonl" `
  --out_dir "$ragOut\llm_judge_eval_strict" `
  --judge_model "gpt-4o-mini" `
  --resume
```

# EPBench Unified STS v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an EPBench-native STS v2 graph, hybrid retrieval, QA, and judge pipeline for the fixed 196-chapter Long Book corpus.

**Architecture:** Add an isolated `Baseline/STS` adapter that owns EPBench parsing, extraction, graph materialization, retrieval, QA, and CLI behavior while reusing the benchmark-neutral v2 schema, state fold, embedding client, and temporal utilities. Preserve one chapter per `Episode/Event`, use compact event cards plus fine-grained Claims for retrieval, aggregate all evidence back to chapter IDs, and keep ARTEM completely untouched.

**Tech Stack:** Python 3.11, `unittest`, pandas/pyarrow, OpenAI-compatible `LLMClient`, `gpt-4o-mini`, `text-embedding-3-small`, shared STS v2 JSONL artifacts.

## Global Constraints

- All Python commands run through `conda run --no-capture-output -n py311`.
- Supported corpus is exactly `Experiment/Other_BenchMark/Episodic-Memory/data/Udefault_Sdefault_seed0/books/model_claude-3-5-sonnet-20240620_itermax_10_Idefault_nbchapters_196_nbtokens_102870`.
- Graph build reads `book.json` only; it must not open `df_qa.parquet`, `df_book_groundtruth.parquet`, or derived gold artifacts.
- Build, QA, and judge model defaults are exactly `gpt-4o-mini`; embedding default is exactly `text-embedding-3-small`.
- Graph schema remains exactly `scope-time-state-graph-v2-state-merge`; do not add EPBench-only node or edge types.
- `COMPATIBLE` is represented by shared StateFacet support; `DIFFERENT_TARGET` remains separate; only `SUPERSEDES`, `CORRECTS`, and `CONFLICTS_WITH` become Claim-Claim edges.
- One chapter is one `Episode/Event`; extraction chunks are prompt windows only.
- Do not import or modify `Baseline/ARTEM` or `adapters/artem_epbench` runtime code.
- New logic replaces obsolete code in the files it owns; do not leave alternate legacy branches or dead entrypoints.
- Default artifacts live below `Graph/output/{graph,cache,results}/epbench_long_book_sts_v2`.

## File Map

- Create `Experiment/Other_BenchMark/Episodic-Memory/Baseline/STS/__init__.py`: public package marker.
- Create `Experiment/Other_BenchMark/Episodic-Memory/Baseline/STS/config.py`: frozen paths, models, budgets, and score weights.
- Create `Experiment/Other_BenchMark/Episodic-Memory/Baseline/STS/loader.py`: chapter and QA dataclasses/loaders with stage separation.
- Create `Experiment/Other_BenchMark/Episodic-Memory/Baseline/STS/graph_builder.py`: extraction, normalization, v2 materialization, validation, atomic publication.
- Create `Experiment/Other_BenchMark/Episodic-Memory/Baseline/STS/staged.py`: BM25/dense indexes, question framing, chapter aggregation, Time ordering, graph expansion.
- Create `Experiment/Other_BenchMark/Episodic-Memory/Baseline/STS/qa_runner.py`: answer and judge stages with per-row checkpoints.
- Create `Experiment/Other_BenchMark/Episodic-Memory/Baseline/STS/run.py`: single stage-oriented CLI.
- Create `Experiment/Other_BenchMark/Episodic-Memory/Baseline/STS/README.md`: supported commands and leakage boundary.
- Create `Experiment/Other_BenchMark/Episodic-Memory/Baseline/STS/tests/`: unit and smoke tests.

---

### Task 1: Frozen EPBench configuration and stage-separated loaders

**Files:**
- Create: `Experiment/Other_BenchMark/Episodic-Memory/Baseline/STS/__init__.py`
- Create: `Experiment/Other_BenchMark/Episodic-Memory/Baseline/STS/config.py`
- Create: `Experiment/Other_BenchMark/Episodic-Memory/Baseline/STS/loader.py`
- Create: `Experiment/Other_BenchMark/Episodic-Memory/Baseline/STS/tests/__init__.py`
- Create: `Experiment/Other_BenchMark/Episodic-Memory/Baseline/STS/tests/test_loader.py`

**Interfaces:**
- Produces: `Chapter(chapter_id: int, text: str)`, `QAItem(row_index: int, q_idx: int, question: str, correct_answer: list[str], correct_answer_chapters: list[int])`.
- Produces: `load_chapters(book_path: Path = BOOK_PATH) -> list[Chapter]` and `load_qa(qa_path: Path = QA_PATH) -> list[QAItem]`.
- Produces config constants `CORPUS_DIR`, `BOOK_PATH`, `QA_PATH`, `GRAPH_DIR`, `CACHE_DIR`, `RESULT_DIR`, model defaults, retrieval budgets, and score weights.

- [ ] **Step 1: Write failing loader tests**

```python
class LoaderTests(unittest.TestCase):
    def test_fixed_book_has_196_ordered_chapters(self):
        chapters = load_chapters()
        self.assertEqual(196, len(chapters))
        self.assertEqual(list(range(1, 197)), [row.chapter_id for row in chapters])
        self.assertTrue(all(row.text.strip() for row in chapters))

    def test_qa_loader_is_a_separate_explicit_call(self):
        rows = load_qa()
        self.assertEqual(686, len(rows))
        self.assertEqual(list(range(686)), [row.row_index for row in rows])
```

- [ ] **Step 2: Run tests and verify the package is missing**

Run:

```bash
conda run --no-capture-output -n py311 python -m unittest \
  Experiment/Other_BenchMark/Episodic-Memory/Baseline/STS/tests/test_loader.py -v
```

Expected: import failure for `STS.loader`.

- [ ] **Step 3: Implement frozen config and chapter-only loader**

```python
@dataclass(frozen=True)
class Chapter:
    chapter_id: int
    text: str

def load_chapters(book_path: Path = BOOK_PATH) -> list[Chapter]:
    payload = json.loads(book_path.read_text(encoding="utf-8"))
    if not isinstance(payload, str):
        raise TypeError("EPBench book.json must contain one JSON string")
    matches = CHAPTER_RE.finditer(payload)
    chapters = [Chapter(int(match.group(1)), match.group(2).strip()) for match in matches]
    if len(chapters) != 196 or [row.chapter_id for row in chapters] != list(range(1, 197)):
        raise ValueError("fixed EPBench corpus must contain ordered chapters 1..196")
    return chapters
```

Implement `load_qa()` with pandas only in `loader.py`; do not call it from graph-building code. Normalize numpy arrays to Python lists and preserve parquet row order independently of duplicated `q_idx` values.

- [ ] **Step 4: Run loader tests**

Expected: 2 tests pass.

- [ ] **Step 5: Commit Task 1**

```bash
git add Experiment/Other_BenchMark/Episodic-Memory/Baseline/STS
git commit -m "feat: add frozen EPBench STS loaders"
```

---

### Task 2: Chapter extraction contract and base v2 graph

**Files:**
- Create: `Experiment/Other_BenchMark/Episodic-Memory/Baseline/STS/graph_builder.py`
- Create: `Experiment/Other_BenchMark/Episodic-Memory/Baseline/STS/tests/test_graph_builder.py`

**Interfaces:**
- Consumes: `Chapter`, frozen config, `LLMClient.complete_json(system_prompt: str, user_prompt: str)`.
- Produces: `extract_chapter_records(chapters, client, message_chunk_size=4, max_claims_per_chapter=8, workers=1) -> tuple[list[dict], list[dict]]`.
- Produces: `build_graph(chapters, extraction_records, merge_client=None, resolver_candidate_limit=24) -> dict[str, Any]`.
- Every extraction record is chapter-bound and contains `concise_summary`, `dates`, `locations`, `entities`, `event_types`, and `claims`.

- [ ] **Step 1: Write failing extraction and evidence tests**

```python
def test_extraction_rejects_scope_without_exact_source_evidence(self):
    chapter = Chapter(1, "Julian attended a Tech Hackathon at High Line.")
    raw = {
        "chapter_id": 1,
        "concise_summary": "Julian attended a hackathon.",
        "dates": [],
        "locations": [{"value": "Central Park", "evidence_span": "Central Park"}],
        "entities": [],
        "event_types": [],
        "claims": [],
    }
    with self.assertRaisesRegex(ValueError, "evidence_span"):
        normalize_extraction(chapter, raw)

def test_base_graph_uses_one_event_per_chapter(self):
    graph = build_graph(CHAPTERS, VALID_RECORDS, merge_client=None)
    events = [n for n in graph["nodes"] if n["node_type"] == "Episode/Event"]
    self.assertEqual([1, 2], [n["chapter_id"] for n in events])
```

- [ ] **Step 2: Run the tests and observe missing functions**

Expected: import or attribute failure for `normalize_extraction`/`build_graph`.

- [ ] **Step 3: Implement strict extraction normalization**

Use this code-owned extraction vocabulary:

```python
ALLOWED_CLAIM_PREDICATES = {
    "episodic_action", "lives_in", "works_at", "member_of", "has_status", "prefers"
}

def require_span(chapter: Chapter, span: object) -> str:
    evidence = " ".join(str(span or "").split())
    if not evidence or evidence.casefold() not in " ".join(chapter.text.split()).casefold():
        raise ValueError(f"chapter {chapter.chapter_id}: evidence_span not found")
    return evidence
```

The prompt instructs `gpt-4o-mini` to emit exactly one record per visible chapter ID and to use the fixed predicate vocabulary. Reject duplicate, missing, or cross-chapter IDs. One constrained repair call is allowed; a second invalid response raises.

- [ ] **Step 4: Materialize base nodes and edges**

For every chapter create:

```python
event = {
    "node_type": "Episode/Event",
    "event_id": f"epbench::chapter::{chapter.chapter_id}",
    "chapter_id": chapter.chapter_id,
    "raw_text": chapter.text,
    "graph_text": compact_event_card(record),
    "event_summary": record["concise_summary"],
}
```

Create stable `book`, `entity`, `location`, and `event_type` Scope IDs; first-class Time nodes; normalized Claim IDs; and only the shared edges `IN_SCOPE`, `MENTIONS`, `OCCURRED_AT`, `ASSERTS`, and `HAS_TIME` at this stage. Preserve edge role metadata for primary/participant/organization entities.

- [ ] **Step 5: Run graph-builder tests**

Expected: exact evidence rejection and one-Event-per-chapter tests pass.

- [ ] **Step 6: Commit Task 2**

```bash
git add Experiment/Other_BenchMark/Episodic-Memory/Baseline/STS/graph_builder.py \
        Experiment/Other_BenchMark/Episodic-Memory/Baseline/STS/tests/test_graph_builder.py
git commit -m "feat: build EPBench chapter events and claims"
```

---

### Task 3: Shared state fold, graph validation, and atomic publication

**Files:**
- Modify: `Experiment/Other_BenchMark/Episodic-Memory/Baseline/STS/graph_builder.py`
- Modify: `Experiment/Other_BenchMark/Episodic-Memory/Baseline/STS/tests/test_graph_builder.py`

**Interfaces:**
- Consumes: shared `StateMergeAdapter`, `fold_state_claims`, `SCHEMA_VERSION`, `NODE_TYPES`, and `EDGE_ENDPOINT_TYPES`.
- Produces: `eligible_state_identity(claim: Mapping[str, Any]) -> dict[str, str] | None`, `materialize_state_facets(nodes: dict[str, dict], edges: list[dict], claims: Sequence[dict], clusters: Sequence[dict]) -> list[dict]`, `validate_graph(nodes: Mapping[str, Mapping[str, Any]], edges: Sequence[Mapping[str, Any]]) -> list[str]`, and `write_graph(output_dir: Path, graph: Mapping[str, Any]) -> Path`.

- [ ] **Step 1: Write failing shared-v2 relation tests**

```python
def test_compatible_claims_share_statefacet_without_claim_edge(self):
    graph = build_graph(CHAPTERS, COMPATIBLE_STATE_RECORDS, merge_client=CompatibleClient())
    facets = [n for n in graph["nodes"] if n["node_type"] == "StateFacet"]
    self.assertEqual(1, len(facets))
    self.assertEqual(2, len(facets[0]["support_claim_ids"]))
    self.assertFalse(any(e["type"] == "COMPATIBLE_WITH" for e in graph["edges"]))

def test_only_shared_claim_relations_are_materialized(self):
    relation_types = {e["type"] for e in graph["edges"] if e["from"].startswith("claim::") and e["to"].startswith("claim::")}
    self.assertLessEqual(relation_types, {"SUPERSEDES", "CORRECTS", "CONFLICTS_WITH"})
```

- [ ] **Step 2: Run tests and verify StateFacet behavior is absent**

Expected: StateFacet assertions fail.

- [ ] **Step 3: Implement high-precision persistent-state eligibility**

```python
SINGLE_STATE_DIMENSIONS = {
    "lives_in": ("location", "residence"),
    "works_at": ("employment", "primary"),
    "has_status": ("status", "primary"),
}

def eligible_state_identity(claim):
    predicate = claim["predicate"]
    if predicate == "episodic_action":
        return None
    if predicate in SINGLE_STATE_DIMENSIONS:
        domain, target = SINGLE_STATE_DIMENSIONS[predicate]
    elif predicate in {"member_of", "prefers"}:
        domain, target = predicate, normalized_component(claim["value"])
    else:
        return None
    return {"state_domain": domain, "state_target": target, "state_dimension": f"{domain}:{target}"}
```

Adapt eligible Claims to the shared chronological fold. The merge client receives only the two endpoint Claims and must return one of the existing five decisions with endpoint event evidence.

- [ ] **Step 4: Materialize StateFacets and current v2 relations**

Create `SUPPORTS`, `CURRENT_AFTER`, and `CURRENT_STATE_OF` edges. Materialize only `SUPERSEDES`, `CORRECTS`, and `CONFLICTS_WITH` Claim-Claim relations. Preserve `primary_claim_id`, all support Claim/Event IDs, stable dimension identity, and `current|historical|ambiguous` status.

- [ ] **Step 5: Add validation and atomic output tests**

```python
def test_manifest_records_dialogue_only_build_inputs(self):
    self.assertEqual(["book.json"], graph["manifest"]["leakage_policy"]["graph_build_inputs"])
    self.assertFalse(graph["manifest"]["leakage_policy"]["qa_loaded"])

def test_incompatible_existing_manifest_is_not_overwritten(self):
    (target / "manifest.json").write_text('{"schema_version":"old"}')
    with self.assertRaisesRegex(ValueError, "incompatible"):
        write_graph(root, graph)
```

- [ ] **Step 6: Run Task 3 tests**

Expected: all graph-builder tests pass with zero warnings.

- [ ] **Step 7: Commit Task 3**

```bash
git add Experiment/Other_BenchMark/Episodic-Memory/Baseline/STS
git commit -m "feat: fold and publish EPBench STS v2 states"
```

---

### Task 4: Scope, Event, and Claim hybrid retrieval with chapter aggregation

**Files:**
- Create: `Experiment/Other_BenchMark/Episodic-Memory/Baseline/STS/staged.py`
- Create: `Experiment/Other_BenchMark/Episodic-Memory/Baseline/STS/tests/test_staged.py`

**Interfaces:**
- Produces: local `BM25Index.search(query, top_k, allowed_doc_ids=None)`.
- Produces: `hybrid_rank(query, bm25, dense, top_k, allowed_doc_ids=None) -> list[RankedHit]` preserving the union of independent lexical and dense candidates.
- Produces: `QuestionFrame(ordering: str, time_values: list[str], entity_queries: list[str], location_queries: list[str], event_type_queries: list[str])`.
- Produces: `STSGraphIndex.load(graph_dir)`, `retrieve(question, frame_client, scope_top_k=32, event_candidate_k=64, claim_candidate_k=64, final_chapter_k=20) -> RetrievalResult`.

- [ ] **Step 1: Write failing hybrid-union and coverage tests**

```python
def test_embedding_only_candidate_survives_union(self):
    hits = hybrid_rank("query", BM25Stub(["lexical"]), DenseStub(["dense"]), top_k=2)
    self.assertEqual({"lexical", "dense"}, {hit.doc_id for hit in hits})

def test_distinct_scope_type_coverage_beats_one_coarse_scope(self):
    result = index.retrieve("Julian Ross Tech Hackathon at High Line", FrameClient())
    self.assertEqual(20, result.ranked_chapters[0].chapter_id)
    self.assertEqual({"entity", "location", "event_type"}, set(result.ranked_chapters[0].matched_scope_types))
```

- [ ] **Step 2: Run tests and observe missing retrieval module**

Expected: import failure for `STS.staged`.

- [ ] **Step 3: Implement independent lexical/dense union**

Use the existing `OpenAIEmbeddingIndex`. Each hit records lexical score/rank, embedding score/rank, retrieval source, and a deterministic combined score:

```python
combined = lexical_score + EMBEDDING_SCORE_WEIGHT * max(embedding_score, 0.0)
```

Do not restrict dense search to lexical hits.

- [ ] **Step 4: Implement question-only frame extraction**

`build_question_frame(question: str, client)` sends only the question. It rejects extra evaluator fields and normalizes ordering to `none|latest|chronological`. Deterministic question wording overrides invalid model ordering when `latest`, `most recent`, `chronological`, or `in order` is explicit.

- [ ] **Step 5: Build graph indexes and chapter aggregation**

Index semantic Scope documents excluding `book`, compact Event `graph_text`, and Claim graph text. Aggregate all Event/Claim hits to `chapter_id`. Add `SCOPE_TYPE_COVERAGE_WEIGHT` once per distinct matched semantic Scope type; add Event and Claim hybrid scores; add time compatibility. Store each contribution in the retrieval trace.

- [ ] **Step 6: Add Time ordering and graph expansion tests**

```python
def test_latest_returns_newest_graph_time(self):
    result = index.retrieve("What was the latest Tech Hackathon?", FrameClient(ordering="latest"))
    self.assertEqual([42], [row.chapter_id for row in result.ranked_chapters[:1]])

def test_chronological_orders_selected_chapters_oldest_first(self):
    result = index.retrieve("List the events chronologically", FrameClient(ordering="chronological"))
    dates = [row.occurred_at for row in result.ranked_chapters]
    self.assertEqual(sorted(dates), dates)
```

- [ ] **Step 7: Run retrieval tests**

Expected: independent unions, multi-Scope coverage, latest, chronological, and evidence-span expansion pass.

- [ ] **Step 8: Commit Task 4**

```bash
git add Experiment/Other_BenchMark/Episodic-Memory/Baseline/STS/staged.py \
        Experiment/Other_BenchMark/Episodic-Memory/Baseline/STS/tests/test_staged.py
git commit -m "feat: add EPBench STS hybrid retrieval"
```

---

### Task 5: STS-native QA and judge checkpoints

**Files:**
- Create: `Experiment/Other_BenchMark/Episodic-Memory/Baseline/STS/qa_runner.py`
- Create: `Experiment/Other_BenchMark/Episodic-Memory/Baseline/STS/tests/test_qa_runner.py`

**Interfaces:**
- Consumes: `load_qa()`, `STSGraphIndex.retrieve()`, separate answer/judge `LLMClient` instances.
- Produces: `run_qa(graph_dir, output_path, answer_client, frame_client, embedding_config, offset=0, limit=686, resume=True) -> dict`.
- Produces: `run_judge(qa_result_path, output_path, judge_client, resume=True) -> dict`.

- [ ] **Step 1: Write failing leakage and checkpoint tests**

```python
def test_answer_prompt_does_not_receive_gold(self):
    qa_path = self.root / "qa.json"
    run_qa(
        graph_dir=self.graph_dir,
        output_path=qa_path,
        answer_client=self.answer_client,
        frame_client=self.frame_client,
        embedding_config=self.embedding_config,
        offset=0,
        limit=1,
        resume=False,
    )
    prompt = self.answer_client.user_prompts[0]
    self.assertNotIn("correct_answer", prompt)
    self.assertNotIn("correct_answer_chapters", prompt)

def test_judge_preserves_raw_answer_and_trace(self):
    judged_path = self.root / "judged.json"
    judged = run_judge(
        qa_result_path=self.qa_path,
        output_path=judged_path,
        judge_client=self.judge_client,
        resume=False,
    )
    qa_row = json.loads(self.qa_path.read_text())["rows"][0]
    judged_row = judged["rows"][0]
    self.assertEqual(qa_row["answer"], judged_row["answer"])
    self.assertEqual(qa_row["retrieval_trace"], judged_row["retrieval_trace"])
```

- [ ] **Step 2: Run tests and observe missing QA runner**

Expected: import failure for `STS.qa_runner`.

- [ ] **Step 3: Implement per-row resumable QA**

Build answer context from ranked chapter IDs, selected Claims, exact evidence spans, temporal lines, and bounded raw excerpts. The `gpt-4o-mini` answer prompt receives the question and retrieved context only. Persist each completed row atomically with retrieval trace, selected chapter IDs, context, raw answer, model, and cache metadata.

- [ ] **Step 4: Implement separate judge stage**

The judge reads stored QA rows plus `correct_answer` from the explicit QA loader, sends question/reference/prediction to `gpt-4o-mini`, and requires:

```json
{"score": 0, "correct": false, "reason": "short grounded reason"}
```

Normalize score to `0..10`, preserve raw QA fields byte-for-byte, checkpoint each judged row, and calculate overall plus `all|latest|chronological` summaries from stored rows.

- [ ] **Step 5: Run QA/judge tests**

Expected: gold exclusion, resume behavior, judge preservation, and summaries pass.

- [ ] **Step 6: Commit Task 5**

```bash
git add Experiment/Other_BenchMark/Episodic-Memory/Baseline/STS/qa_runner.py \
        Experiment/Other_BenchMark/Episodic-Memory/Baseline/STS/tests/test_qa_runner.py
git commit -m "feat: add EPBench STS QA and judge stages"
```

---

### Task 6: One CLI and bounded end-to-end smoke

**Files:**
- Create: `Experiment/Other_BenchMark/Episodic-Memory/Baseline/STS/run.py`
- Create: `Experiment/Other_BenchMark/Episodic-Memory/Baseline/STS/tests/test_pipeline_smoke.py`

**Interfaces:**
- Produces stages `build|retrieve|qa|judge|all` from one CLI.
- Produces injectable `main(argv: Sequence[str] | None = None, clients: ClientBundle | None = None) -> int` for offline smoke tests.

- [ ] **Step 1: Write failing fake-client smoke**

```python
def test_all_stage_builds_retrieves_answers_and_judges(self):
    code = main(
        ["--stage", "all", "--chapter-limit", "2", "--question-limit", "2", "--output-root", str(tmp_path)],
        clients=FAKE_CLIENTS,
    )
    self.assertEqual(0, code)
    self.assertTrue((tmp_path / "graph" / "book1" / "manifest.json").is_file())
    self.assertEqual(2, len(json.loads((tmp_path / "results" / "qa.json").read_text())["rows"]))
```

- [ ] **Step 2: Run smoke and observe missing CLI**

Expected: import failure for `STS.run`.

- [ ] **Step 3: Implement CLI defaults and stage dependency checks**

Expose explicit parameters for corpus path, output roots, model names, extraction batch size, workers, state candidate limit, embedding targets/model/cache, Scope/Event/Claim budgets, final chapter budget, offset/limit, and resume/cache toggles. `retrieve|qa|judge` must reject a missing or incompatible graph manifest rather than silently rebuilding.

- [ ] **Step 4: Run fake-client end-to-end smoke**

Expected: two chapter Events, valid v2 artifacts, two retrieval rows, two answers, two judge rows, and zero warnings.

- [ ] **Step 5: Run all STS unit tests**

```bash
conda run --no-capture-output -n py311 python -m unittest discover \
  -s Experiment/Other_BenchMark/Episodic-Memory/Baseline/STS/tests -v
```

Expected: all tests pass.

- [ ] **Step 6: Commit Task 6**

```bash
git add Experiment/Other_BenchMark/Episodic-Memory/Baseline/STS
git commit -m "feat: expose EPBench STS end-to-end CLI"
```

---

### Task 7: Documentation, static boundaries, and real smoke/full validation

**Files:**
- Create: `Experiment/Other_BenchMark/Episodic-Memory/Baseline/STS/README.md`
- Modify: `Experiment/Other_BenchMark/Episodic-Memory/Baseline/STS/tests/test_pipeline_smoke.py`

**Interfaces:**
- Documents one reproducible `conda py311` build/QA/judge sequence and artifact paths.
- Verifies the active STS package does not import ARTEM and the builder does not reference gold file names outside its leakage manifest text.

- [ ] **Step 1: Add static boundary assertions**

```python
def test_sts_runtime_has_no_artem_imports(self):
    source = "\n".join(path.read_text() for path in STS_DIR.glob("*.py"))
    self.assertNotIn("Baseline.ARTEM", source)
    self.assertNotIn("artem_epbench", source)
```

- [ ] **Step 2: Write README commands**

Document the frozen corpus, leakage boundary, model defaults, schema, output files, and exact commands for:

```bash
conda run --no-capture-output -n py311 python \
  Experiment/Other_BenchMark/Episodic-Memory/Baseline/STS/run.py \
  --stage build --model gpt-4o-mini --message-chunk-size 4

conda run --no-capture-output -n py311 python \
  Experiment/Other_BenchMark/Episodic-Memory/Baseline/STS/run.py \
  --stage qa --answer-model gpt-4o-mini --embedding-model text-embedding-3-small

conda run --no-capture-output -n py311 python \
  Experiment/Other_BenchMark/Episodic-Memory/Baseline/STS/run.py \
  --stage judge --judge-model gpt-4o-mini
```

- [ ] **Step 3: Run compile and full unit regression**

```bash
conda run --no-capture-output -n py311 python -m compileall -q \
  Experiment/Other_BenchMark/Episodic-Memory/Baseline/STS pipeline/external/sts_v2
conda run --no-capture-output -n py311 python -m unittest discover \
  -s Experiment/Other_BenchMark/Episodic-Memory/Baseline/STS/tests -v
conda run --no-capture-output -n py311 python -m unittest \
  Experiment/Other_BenchMark/LoCoMo-QA/tests/test_graph_v2.py -q
conda run --no-capture-output -n py311 python -m unittest discover \
  -s Experiment/Other_BenchMark/EverMemBench/tests -q
```

Expected: EPBench tests pass, LoCoMo 69-test regression passes, and EverMemBench 8-test regression passes.

- [ ] **Step 4: Run bounded real `gpt-4o-mini` smoke when credentials are available**

```bash
conda run --no-capture-output -n py311 python \
  Experiment/Other_BenchMark/Episodic-Memory/Baseline/STS/run.py \
  --stage all --chapter-limit 2 --question-limit 2 --model gpt-4o-mini \
  --answer-model gpt-4o-mini --judge-model gpt-4o-mini
```

Expected: rerunning the same command reuses chapter and row checkpoints.

- [ ] **Step 5: Build and validate the full graph**

```bash
conda run --no-capture-output -n py311 python \
  Experiment/Other_BenchMark/Episodic-Memory/Baseline/STS/run.py \
  --stage build --model gpt-4o-mini --message-chunk-size 4
```

Verify `manifest.summary.node_counts["Episode/Event"] == 196`, `warnings == []`, and no forbidden graph edge is present.

- [ ] **Step 6: Commit Task 7**

```bash
git add Experiment/Other_BenchMark/Episodic-Memory/Baseline/STS
git commit -m "docs: document and verify EPBench STS v2"
```

## Final Verification Gate

Before reporting completion, run the commands in Task 7 Step 3 again from the final checkout and inspect their exit codes. Then inspect `git diff --check`, the graph manifest, graph summary, and a bounded QA/judge result. Do not claim the full graph or real-model smoke passed unless those exact commands completed successfully in the current turn.

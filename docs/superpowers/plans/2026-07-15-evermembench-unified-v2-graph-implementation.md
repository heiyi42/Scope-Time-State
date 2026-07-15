# EverMemBench Unified STS v2 Graph Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace EverMemBench's v6 endpoint-lifecycle graph with the same shared STS v2 state-merge construction contract used by LoCoMo, then remove the superseded v6 code and artifacts.

**Architecture:** A benchmark-neutral `pipeline.external.sts_v2` package owns normalized Event inputs, graph schema constants, graph primitives, StateFacet folding/materialization, validation, manifests, and atomic writes. LoCoMo and EverMemBench retain only source adapters and benchmark evaluation layers; both adapters feed the same core and emit `scope-time-state-graph-v2-state-merge`.

**Tech Stack:** Python 3.11, dataclasses, JSON/JSONL, unittest, existing `Experiment.run.common.llm_client`, existing `pipeline.external.state_merge`, conda environment `py311`.

## Global Constraints

- Every Python command must run as `conda run --no-capture-output -n py311 ...`.
- Graph construction may use visible dialogue only; no QA, answer, option, task-label, or gold-evidence input.
- Delete v6 endpoint-lifecycle, task-object, and `RESPONSIBLE_FOR` logic instead of retaining compatibility branches.
- Preserve benchmark-specific answer parsing, judging, and metrics outside the shared graph core.
- Do not stage or modify unrelated dirty-worktree files.
- Replace old logic when the unified path is working; do not leave dead duplicate implementations.

---

### Task 1: Freeze the shared STS v2 schema contract

**Files:**
- Create: `pipeline/external/sts_v2/__init__.py`
- Create: `pipeline/external/sts_v2/schema.py`
- Create: `pipeline/external/sts_v2/models.py`
- Create: `pipeline/external/sts_v2/tests/__init__.py`
- Create: `pipeline/external/sts_v2/tests/test_schema.py`

**Interfaces:**
- Produces: `SCHEMA_VERSION`, `NODE_TYPES`, `EDGE_TYPES`, `EDGE_ENDPOINT_TYPES`, `NormalizedEvent`, `NormalizedCorpus`, `GraphBuildResult`.
- Consumes: no benchmark-local imports.

- [ ] **Step 1: Write the failing schema tests**

```python
from pipeline.external.sts_v2.models import NormalizedCorpus, NormalizedEvent
from pipeline.external.sts_v2.schema import EDGE_TYPES, SCHEMA_VERSION


def test_common_schema_has_no_v6_edges() -> None:
    assert SCHEMA_VERSION == "scope-time-state-graph-v2-state-merge"
    assert "RESPONSIBLE_FOR" not in EDGE_TYPES


def test_normalized_corpus_rejects_duplicate_event_ids() -> None:
    event = NormalizedEvent(
        corpus_id="01", event_id="e1", source_order=(1,), speaker="A",
        text="visible", occurred_at="2026-01-01", scope_values=(("group", "g"),),
        source_metadata={},
    )
    try:
        NormalizedCorpus(dataset="test", corpus_id="01", events=(event, event), source_manifest={})
    except ValueError as exc:
        assert "duplicate normalized event id" in str(exc)
    else:
        raise AssertionError("duplicate event ids must fail")
```

- [ ] **Step 2: Run the tests and verify the import failure**

Run:

```bash
conda run --no-capture-output -n py311 \
  python -m unittest pipeline.external.sts_v2.tests.test_schema -v
```

Expected: FAIL because `pipeline.external.sts_v2` does not exist.

- [ ] **Step 3: Implement the shared schema and normalized input types**

```python
SCHEMA_VERSION = "scope-time-state-graph-v2-state-merge"
NODE_TYPES = ("Episode/Event", "Claim", "StateFacet", "Entity/Scope", "Time")
EDGE_ENDPOINT_TYPES = {
    "MENTIONS": ("Episode/Event", "Entity/Scope"),
    "IN_SCOPE": ("Episode/Event", "Entity/Scope"),
    "ASSERTS": ("Episode/Event", "Claim"),
    "OCCURRED_AT": ("Episode/Event", "Time"),
    "HAS_TIME": ("Claim", "Time"),
    "CORRECTS": ("Claim", "Claim"),
    "SUPERSEDES": ("Claim", "Claim"),
    "CONFLICTS_WITH": ("Claim", "Claim"),
    "SUPPORTS": ("Claim", "StateFacet"),
    "CURRENT_AFTER": ("StateFacet", "Time"),
    "CURRENT_STATE_OF": ("StateFacet", "Entity/Scope"),
}
EDGE_TYPES = tuple(EDGE_ENDPOINT_TYPES)
```

`NormalizedCorpus.__post_init__` must reject empty corpus IDs, duplicate Event IDs, Event corpus mismatches, empty visible text, and non-monotonic duplicate source-order tuples.

- [ ] **Step 4: Run the schema tests**

Expected: all tests PASS.

- [ ] **Step 5: Commit the shared schema contract**

```bash
git add pipeline/external/sts_v2
git commit -m "feat: define shared STS v2 graph contract"
```

---

### Task 2: Move shared graph primitives, StateFacet materialization, validation, and writes into the core

**Files:**
- Create: `pipeline/external/sts_v2/graph.py`
- Create: `pipeline/external/sts_v2/state.py`
- Create: `pipeline/external/sts_v2/storage.py`
- Create: `pipeline/external/sts_v2/tests/test_graph.py`
- Modify: `pipeline/external/state_merge.py`

**Interfaces:**
- Consumes: `NormalizedCorpus`, `SCHEMA_VERSION`, `StateMergeAdapter`, `fold_state_claims`.
- Produces: `add_node`, `add_edge`, `dedupe_edges`, `materialize_state_facets`, `validate_graph`, `graph_summary`, `write_graph_atomic`.

- [ ] **Step 1: Write failing tests for StateFacet proof ownership and forbidden edges**

```python
def test_materialized_facet_has_one_primary_and_all_supports() -> None:
    result = materialize_state_facets(
        corpus_id="c1",
        claims_by_id={"c-old": OLD, "c-new": NEW},
        clusters=[{
            "owner_key": "alice", "domain_key": "occupation",
            "dimension_key": "primary", "primary_claim_id": "c-new",
            "support_claim_ids": ["c-old", "c-new"], "status": "current",
        }],
    )
    facet = result.nodes[0]
    assert facet["primary_claim_id"] == "c-new"
    assert facet["support_claim_ids"] == ["c-old", "c-new"]
    assert {edge["from"] for edge in result.edges if edge["type"] == "SUPPORTS"} == {"c-old", "c-new"}


def test_validator_rejects_responsible_for() -> None:
    warnings = validate_graph(nodes={}, edges=[{"type": "RESPONSIBLE_FOR", "from": "a", "to": "b"}])
    assert any("unsupported_edge_type" in item for item in warnings)
```

- [ ] **Step 2: Run the tests and verify failures**

Run the new test module through conda `py311`; expect missing-function failures.

- [ ] **Step 3: Implement common graph primitives and StateFacet materialization**

Move the active LoCoMo v2 semantics without its loader types:

- stable facet ID from `(corpus_id, owner_key, domain_key, dimension_key)`;
- `SUPPORTS` from every support Claim;
- `CURRENT_AFTER` from the primary Claim report Time;
- `CURRENT_STATE_OF` to deterministic owner Scopes;
- Claim relation edges copied from the fold result;
- no task-object or responsibility edge support.

`validate_graph` must fail on unknown node/edge types, missing endpoints, endpoint type mismatches, duplicate IDs, invalid StateFacet support, multiple primary Claims, or forbidden gold fields.

- [ ] **Step 4: Implement validated atomic writes**

```python
def write_graph_atomic(output_root: Path, corpus_id: str, result: GraphBuildResult) -> Path:
    # Verify schema/corpus compatibility, write all four files into a sibling
    # temporary directory, then atomically replace only the same corpus/schema.
```

The files are `manifest.json`, `graph_summary.json`, `nodes.jsonl`, and `edges.jsonl`.

- [ ] **Step 5: Run shared-core tests**

Expected: all `pipeline.external.sts_v2.tests` PASS.

- [ ] **Step 6: Commit the common graph core**

```bash
git add pipeline/external/sts_v2 pipeline/external/state_merge.py
git commit -m "feat: add shared STS v2 graph materialization"
```

---

### Task 3: Extract the active LoCoMo v2 Claim and Time pipeline into the shared builder

**Files:**
- Create: `pipeline/external/sts_v2/builder.py`
- Create: `pipeline/external/sts_v2/prompts.py`
- Create: `pipeline/external/sts_v2/tests/test_builder.py`
- Modify: `Experiment/Other_BenchMark/LoCoMo-QA/Baseline/ours_scope_time_state/graph_builder.py`
- Modify: `Experiment/Other_BenchMark/LoCoMo-QA/tests/test_graph_v2.py`

**Interfaces:**
- Consumes: `NormalizedCorpus`, optional `LLMClient`, shared graph/state/storage modules.
- Produces: `BuildConfig`, `build_graph(corpus, config, client, runtime) -> GraphBuildResult`.

- [ ] **Step 1: Add failing builder contract tests**

Tests must construct a two-Event synthetic corpus with an occupation update and assert:

```python
assert result.manifest["schema_version"] == SCHEMA_VERSION
assert result.manifest["leakage_policy"]["gold_fields_used"] == []
assert result.summary["warnings"] == []
assert result.summary["state_facet_count"] == 1
assert any(edge["type"] == "SUPERSEDES" for edge in result.edges)
```

Inject deterministic Claim extraction and merge callbacks so the unit test makes no network call.

- [ ] **Step 2: Run and confirm failure before extraction**

Expected: `build_graph` missing.

- [ ] **Step 3: Move the active LoCoMo v2 behavior into the shared builder**

The shared builder owns:

- Claim prompt/normalization fields `subject`, `canonical_subject`, `subject_key`, `facet_key`, `state_domain`, `slot_type`, `state_target`, `state_dimension`, `value`, `time_role`, and `time_value`;
- persistent-state eligibility;
- deterministic and LLM-assisted dimension resolution;
- ordered folding with `COMPATIBLE`, `DIFFERENT_TARGET`, `SUPERSEDES`, `CORRECTS`, and `CONFLICTS_WITH`;
- Event, Claim, Time, and StateFacet materialization;
- the common manifest and graph summary.

Do not move LoCoMo file loading or CLI argument parsing into the core.

- [ ] **Step 4: Convert LoCoMo builder to a thin adapter**

Add:

```python
def normalize_locomo_sample(data_path: Path, sample_id: str, event_limit: int = 0) -> NormalizedCorpus:
    sample = load_sample(data_path, sample_id)
    events = tuple(normalize_locomo_turn(sample.sample_id, turn) for turn in selected_turns)
    return NormalizedCorpus(
        dataset="locomo_qa", corpus_id=sample.sample_id, events=events,
        source_manifest={"graph_build_inputs": ["locomo10.json:sample.conversation"]},
    )
```

Keep the existing CLI surface but route v2 exclusively through `pipeline.external.sts_v2.builder.build_graph`. Remove duplicated v2 Claim/state/materialization/validation code from the benchmark-local file; retain only explicitly requested v1 legacy code.

- [ ] **Step 5: Run LoCoMo v2 regression tests through py311**

```bash
conda run --no-capture-output -n py311 \
  python -m unittest discover -s Experiment/Other_BenchMark/LoCoMo-QA/tests -p 'test_graph_v2.py' -v
```

Expected: PASS with no network access.

- [ ] **Step 6: Commit the shared builder and LoCoMo adapter**

```bash
git add pipeline/external/sts_v2 Experiment/Other_BenchMark/LoCoMo-QA/Baseline/ours_scope_time_state/graph_builder.py Experiment/Other_BenchMark/LoCoMo-QA/tests/test_graph_v2.py
git commit -m "refactor: route LoCoMo through shared STS v2 builder"
```

---

### Task 4: Replace the EverMemBench v6 builder with a thin shared-v2 adapter

**Files:**
- Modify: `Experiment/Other_BenchMark/EverMemBench/Baseline/ours_scope_time_state/loader.py`
- Replace: `Experiment/Other_BenchMark/EverMemBench/Baseline/ours_scope_time_state/graph_builder.py`
- Delete: `Experiment/Other_BenchMark/EverMemBench/Baseline/ours_scope_time_state/enrich_topic_graph.py`
- Delete: `Experiment/Other_BenchMark/EverMemBench/run_evermembench_enrich_topic_graph.py`
- Create: `Experiment/Other_BenchMark/EverMemBench/tests/test_unified_graph_builder.py`

**Interfaces:**
- Consumes: `load_topic_events`, `NormalizedCorpus`, `BuildConfig`, `build_graph`, `write_graph_atomic`.
- Produces: `normalize_evermembench_topic(topic_id, data_root, event_limit) -> NormalizedCorpus` and the existing graph-builder CLI.

- [ ] **Step 1: Write failing EverMemBench adapter tests**

Use a temporary dataset containing `01/dialogue.json` and a sentinel `01/qa_1.json` that raises if opened. Assert:

```python
corpus = normalize_evermembench_topic("01", root)
assert corpus.dataset == "evermembench"
assert corpus.corpus_id == "01"
assert corpus.source_manifest["graph_build_inputs"] == ["dialogue.json"]
assert [kind for event in corpus.events for kind, _ in event.scope_values] == ["topic", "group", "person"]
```

Also scan the built graph and assert that no node has `scope_type == "task_object"` and no edge is `RESPONSIBLE_FOR`.

- [ ] **Step 2: Run and confirm the tests fail against v6**

Expected: shared adapter missing and v6-specific assertions fail.

- [ ] **Step 3: Implement the EverMemBench normalized adapter**

Map each `EverMemEvent` to `NormalizedEvent`:

```python
NormalizedEvent(
    corpus_id=topic_id,
    event_id=event.event_id,
    source_order=event.sort_key,
    speaker=event.speaker,
    text=event.text,
    occurred_at=event.occurred_at,
    scope_values=(("topic", topic_id), ("group", event.group), ("person", event.speaker)),
    source_metadata={"date": event.date, "time": event.time, "message_index": event.message_index},
)
```

- [ ] **Step 4: Replace the EverMemBench graph builder**

Keep CLI options for topic, data root, LLM provider/model, Claim workers, resolver workers, cache, event limit, and output root. Remove heuristic Claim mode, lifecycle augmentation, task-object extraction, responsibility edges, v6 resolver, v6 summary fields, and v6 schema strings.

Default output:

```text
Graph/output/graph/evermembench_topic_graph_v2_state_merge/<topic_id>/
```

- [ ] **Step 5: Delete v6 enrichment entrypoints and imports**

Remove files and references because enrichment exists only to add v6 time-source/task-object/responsibility fields.

- [ ] **Step 6: Run EverMemBench builder tests**

Expected: PASS, with dialogue-only leakage manifest and no v6 vocabulary.

- [ ] **Step 7: Commit the EverMemBench builder migration**

```bash
git add -A Experiment/Other_BenchMark/EverMemBench/Baseline/ours_scope_time_state Experiment/Other_BenchMark/EverMemBench/run_evermembench_enrich_topic_graph.py Experiment/Other_BenchMark/EverMemBench/tests
git commit -m "refactor: build EverMemBench with shared STS v2"
```

---

### Task 5: Remove v6 retrieval assumptions from EverMemBench QA

**Files:**
- Modify: `Experiment/Other_BenchMark/EverMemBench/Baseline/ours_scope_time_state/staged.py`
- Modify: `Experiment/Other_BenchMark/EverMemBench/Baseline/ours_scope_time_state/qa_eval_runner.py`
- Modify: `Experiment/Other_BenchMark/EverMemBench/Baseline/ours_scope_time_state/qa_probe.py`
- Create: `Experiment/Other_BenchMark/EverMemBench/tests/test_unified_graph_retrieval.py`

**Interfaces:**
- Consumes: common v2 graph files.
- Produces: one question-only `Scope -> Event -> Claim -> StateFacet` path for every EverMemBench row.

- [ ] **Step 1: Add failing retrieval contract tests**

Build a small fixture graph with topic/group/person Scopes and assert:

```python
trace = evidence.expand(question="What is Alice's current role?", scope_top_k=4, event_top_k=4)
assert trace["mode"] == "sts"
assert trace["graph_schema_version"] == "scope-time-state-graph-v2-state-merge"
assert "task_object" not in json.dumps(trace)
assert "RESPONSIBLE_FOR" not in json.dumps(trace)
assert set(trace["selected_state_ids"]).issubset(reachable_state_ids)
```

- [ ] **Step 2: Run tests and verify v6 references fail the contract**

Expected: FAIL due to task-object/v6 assumptions.

- [ ] **Step 3: Delete v6-only indexing and traversal**

Remove:

- task-object scope documents and score bonuses;
- task-object candidate reservation/demotion;
- Claim `task_object_scope_ids` handling;
- `RESPONSIBLE_FOR` indexes and traversal;
- endpoint-lifecycle-specific trace labels;
- acceptance of the v6 schema string.

Keep topic/group/person Scope routing, Event lexical/dense retrieval, Time rerank, relation-aware Claim closure, StateFacet proof closure, answer generation, MC parsing, judge, and official metrics.

- [ ] **Step 4: Require the common schema at graph load**

Graph loading must reject any manifest whose schema is not exactly `scope-time-state-graph-v2-state-merge`; do not add an old-schema branch.

- [ ] **Step 5: Run retrieval and temporal-grounding tests through py311**

```bash
conda run --no-capture-output -n py311 \
  python -m unittest discover -s Experiment/Other_BenchMark/EverMemBench/tests -p 'test_*.py' -v
```

Expected: all tests PASS.

- [ ] **Step 6: Commit the unified retrieval path**

```bash
git add Experiment/Other_BenchMark/EverMemBench/Baseline/ours_scope_time_state Experiment/Other_BenchMark/EverMemBench/tests
git commit -m "refactor: align EverMemBench retrieval with STS v2"
```

---

### Task 6: Update entrypoints and documentation, then delete v6 artifacts

**Files:**
- Modify: `Experiment/Other_BenchMark/EverMemBench/README.md`
- Modify: `Experiment/Other_BenchMark/EverMemBench/run_evermembench_graph_builder.py` only if its import target changes.
- Modify: `Experiment/Other_BenchMark/EverMemBench/run_evermembench_qa_eval.py` only if its import target changes.
- Delete: `Graph/output/graph/evermembench_topic_graph_llm_v6_endpoint_lifecycle/`
- Delete: files whose manifest/result `graph_dir` resolves inside that v6 root.
- Delete: `Graph/output/cache/llm_cache.evermembench_graph_builder.v6_endpoint_lifecycle*`.

**Interfaces:**
- Produces: one documented build/QA command using the common v2 graph.

- [ ] **Step 1: Inventory exact deletion targets**

Use a read-only script to list graph, result, and cache paths. A result is deletable only if its JSON records a `graph_dir` under the v6 root or lives inside that graph root. Save the printed inventory in the task log before deletion.

- [ ] **Step 2: Update README commands**

The documented graph path becomes:

```text
Graph/output/graph/evermembench_topic_graph_v2_state_merge/01
```

Remove descriptions of lifecycle fallback, task-object, responsibility, v6 enrichment, and v6 schema.

- [ ] **Step 3: Delete authorized v6 artifacts**

Use `apply_patch` for tracked code/document deletions. Use direct filesystem removal only for ignored generated graph/result/cache artifacts after the inventory check. Do not remove unrelated local Ollama smoke or official-baseline results unless they record the deleted v6 graph path.

- [ ] **Step 4: Assert no v6 references remain**

Run:

```bash
rg -n "evermembench-sts-topic-graph-v6-endpoint-lifecycle|evermembench_topic_graph_llm_v6_endpoint_lifecycle|RESPONSIBLE_FOR|task_object|event_endpoint_.*fallback" \
  Experiment/Other_BenchMark/EverMemBench pipeline/external/sts_v2
```

Expected: no matches in active code or docs.

- [ ] **Step 5: Commit docs and tracked cleanup**

```bash
git add -A Experiment/Other_BenchMark/EverMemBench
git commit -m "docs: remove EverMemBench v6 graph path"
```

Generated ignored artifacts are verified separately and are not forced into git.

---

### Task 7: Run complete py311 verification and bounded topic-01 smoke

**Files:**
- Modify only files implicated by a reproducible verification failure; delete replaced faulty logic in the same fix.

**Interfaces:**
- Verifies all previous tasks.

- [ ] **Step 1: Compile changed Python modules**

```bash
conda run --no-capture-output -n py311 \
  python -m compileall -q \
  pipeline/external/sts_v2 \
  Experiment/Other_BenchMark/LoCoMo-QA/Baseline/ours_scope_time_state \
  Experiment/Other_BenchMark/EverMemBench/Baseline/ours_scope_time_state
```

Expected: exit code 0.

- [ ] **Step 2: Run shared, LoCoMo, and EverMemBench test suites**

Run all three unittest commands from Tasks 1, 3, and 5. Expected: all PASS.

- [ ] **Step 3: Run an offline bounded EverMemBench adapter/build smoke**

Use a temporary two-Event topic fixture and injected deterministic Claim/merge callbacks. Expected: complete four-file graph, common schema, zero warnings, no gold fields, and no v6 vocabulary.

- [ ] **Step 4: Run the real topic-01 bounded build through py311**

```bash
conda run --no-capture-output -n py311 \
  python Experiment/Other_BenchMark/EverMemBench/run_evermembench_graph_builder.py \
  --topic 01 \
  --claim-mode llm \
  --resolver-mode llm \
  --event-limit 8 \
  --output-dir Graph/output/graph/evermembench_topic_graph_v2_state_merge_smoke
```

Use the configured provider/model from the environment rather than silently substituting another model. If credentials or the endpoint are unavailable, record the exact external blocker; offline contract verification must still pass.

- [ ] **Step 5: Run bounded topic-01 QA when the real smoke graph exists**

Run one MC and one open-ended item through `run_evermembench_qa_eval.py` with that graph. Expected: both rows report the common schema and `graph_trace.mode=sts`, with no v6/task-object trace fields.

- [ ] **Step 6: Verify artifact deletion**

Assert the old graph root, v6 result references, and v6 cache roots do not exist.

- [ ] **Step 7: Review the final diff and commit verification fixes**

Stage only migration files. Confirm unrelated dirty-worktree entries remain unstaged. Commit only if verification required tracked fixes.

---

### Task 8: Final acceptance audit

**Files:**
- Read-only audit of all migration files and outputs.

**Interfaces:**
- Produces: final evidence-backed handoff.

- [ ] **Step 1: Check spec coverage**

Confirm shared core use by both adapters, dialogue-only manifests, common schema, no v6 reader, no dead task-object/lifecycle code, and benchmark-specific evaluation preservation.

- [ ] **Step 2: Check git scope**

Use `git status --short` and `git diff --stat` to distinguish migration changes from pre-existing user changes. Do not claim unrelated changes.

- [ ] **Step 3: Report verification evidence**

Report exact conda `py311` commands, pass counts, smoke output path, schema version, warning count, and any external endpoint blocker. Do not claim the full 01-05 rebuild unless it was actually run.

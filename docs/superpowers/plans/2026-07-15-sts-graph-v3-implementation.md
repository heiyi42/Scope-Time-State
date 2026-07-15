# STS Graph v3 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement a new, isolated STS Graph v3 whose `gpt-4o-mini` construction contract stays small, whose graph and retrieval semantics remain benchmark-neutral, and whose LoCoMo path improves multi-hop and adversarial behavior without regressing single-hop or temporal tasks.

**Architecture:** LoCoMo is a thin adapter over a shared `pipeline/sts_v3` core. The adapter emits only visible-memory records and source-provided Memory/Session Scope. The core owns deterministic graph IDs, six stored node roles, typed edges, incremental state folding, Scope-routed Event-first retrieval, on-demand Claim completion, Time/State validity, bounded typed joins, three-valued verification, and operation-aware readout. v3 has dedicated code and artifact roots and imports no v2 runtime module.

**Tech Stack:** Python 3.11, stdlib `dataclasses`/`unittest`, `tiktoken` for extraction budgets, `dateparser` for conservative time normalization, existing `LLMClient` for temperature-zero JSON calls, optional existing `OpenAIEmbeddingIndex` behind a v3 wrapper, JSON/JSONL artifacts.

## Global Constraints

- Execute this plan in an isolated worktree created with `superpowers:using-git-worktrees`, on branch `codex/sts-graph-v3`. The current checkout is dirty and contains user-owned v2 changes.
- Before the first implementation edit, snapshot the current bytes of all protected v2 code/artifact roots. Compare against that exact snapshot after the final smoke; do not compare against `HEAD`.
- Never modify, import runtime code from, stage, or overwrite:
  - `Experiment/Other_BenchMark/LoCoMo-QA/Baseline/ours_scope_time_state/`
  - `Experiment/Other_BenchMark/LoCoMo-QA/tests/test_graph_v2.py`
  - `Experiment/Other_BenchMark/LoCoMo-QA/run_locomo_graph_builder.py`
  - `Graph/output/results/locomo_qa/ours_scope_time_state/`
  - pre-existing `Graph/output/graph/locomo_qa_sample_graph_*` roots
  - pre-existing LoCoMo cache roots under `Graph/output/cache/`
- v2 is a live frozen A/B baseline, not dead code. The user's delete-replaced-code rule applies inside the new v3 surfaces: when a v3 implementation is replaced, remove the replaced implementation, flags, imports, tests, and branches in the same task.
- Do not import the untracked `pipeline/external/state_merge.py`, the untracked `pipeline/external/temporal_grounding.py`, or `pipeline/external/time_role_selection.py`.
- Do not add Pydantic, NetworkX, `rank_bm25`, PPR, community detection, generic BFS, a predicate ontology, a task-type retrieval switch, or a third online semantic LLM stage.
- Core APIs never receive benchmark name, qtype/category, gold answer, gold evidence IDs, answer-session IDs, options, or repair hints. LoCoMo category is available only after retrieval for official scoring/reporting.
- LoCoMo graph Scope is exactly one hard Memory Scope per `sample_id` plus one child Session Scope per source session. Speaker is an Entity and session date is Time. Do not materialize Speaker Scope or Topic Scope.
- Unit and integration tests are offline and use fake completion/dense clients. Networked extraction and QA smokes are explicit, separately gated commands.
- Use stdlib `unittest`; do not introduce pytest configuration.
- Stage paths explicitly. Never run `git add -A` or a command that stages the dirty parent checkout.

### Bug-fix and complexity change control

- The schema surface is frozen during implementation: ten model-emitted Claim fields, six node roles, the 14 edge types in the design, the compact query-frame fields, and the fixed retrieval-budget names. A bug is not permission to add another field/type/mode.
- Every discovered bug first gets a minimal failing regression test and is classified into adapter, extraction validation, deterministic materialization, indexing, retrieval, verification, or readout. Fix it in that existing layer using existing schema semantics.
- Prefer stricter validation, a corrected deterministic rule, a better index/posting, or a verifier/readout fix. Do not add catch-all `metadata`/`extras` blobs, duplicated derived fields, benchmark repair hints, fallback variants, or a compatibility switch.
- When replacing a v3 rule or helper, delete its old branch, imports, flags, and obsolete tests in the same commit. Keep one source of truth in `pipeline/sts_v3`; never patch the same semantic rule again in the LoCoMo wrapper.
- If a reproducible case truly cannot be represented by the frozen schema, stop implementation. Present the failing case, why every existing field/edge is insufficient, the smallest proposed schema delta, and its cross-benchmark effect. Do not make that schema change without explicit user approval.
- Refactoring internal helpers is allowed when it reduces duplication or control-flow complexity without changing public/schema contracts. It must preserve tests and remove the replaced implementation; do not accumulate `v2`, `new`, `fixed`, or `fallback` copies inside v3.

---

## Locked File Map

### Create: shared core

| File | Responsibility |
|---|---|
| `pipeline/sts_v3/__init__.py` | Export only stable v3 public types/constants; no v2 aliases. |
| `pipeline/sts_v3/adapter.py` | Benchmark-neutral visible-memory contract, record validation/hash, write-path guard, protected-tree digest. |
| `pipeline/sts_v3/schema.py` | Six node roles, typed edges, deterministic IDs, graph serialization/loading, graph invariants. |
| `pipeline/sts_v3/build.py` | Ten-field extraction, chunking, span validation, Entity/Time materialization, Claim identity/dedup, incremental state fold, graph build. |
| `pipeline/sts_v3/retrieve.py` | Query frame, BM25, standard RRF, graph index, Scope/Event/Claim retrieval, Time/State routing, typed joins, exact posting scan, trace. |
| `pipeline/sts_v3/verify.py` | Exact binding unification, SUPPORT/REFUTE/UNKNOWN, proof closure, operation readout, final-answer whitelist. |
| `pipeline/sts_v3/tests/__init__.py` | Test package marker. |
| `pipeline/sts_v3/tests/test_contract.py` | Synthetic schema/build/retrieval/verifier/generalization/isolation contracts. |

### Create: LoCoMo thin layer

| File | Responsibility |
|---|---|
| `Experiment/Other_BenchMark/LoCoMo-QA/Baseline/ours_scope_time_state_v3/__init__.py` | v3 LoCoMo package marker. |
| `Experiment/Other_BenchMark/LoCoMo-QA/Baseline/ours_scope_time_state_v3/adapter.py` | Convert `LoCoMoSample` to visible-memory records and a question string to a core query request. |
| `Experiment/Other_BenchMark/LoCoMo-QA/Baseline/ours_scope_time_state_v3/graph_builder.py` | Dedicated build/extraction-smoke CLI, LLM wiring, protected snapshot verification, isolated artifact paths. |
| `Experiment/Other_BenchMark/LoCoMo-QA/Baseline/ours_scope_time_state_v3/graph_query_runner.py` | Dedicated QA CLI, graph/index loading, at-most-two online semantic stages, result/trace writing, official F1 reporting. |
| `Experiment/Other_BenchMark/LoCoMo-QA/Baseline/ours_scope_time_state_v3/README.md` | Exact v3 commands, artifact contract, promotion gates; avoids the dirty benchmark README. |
| `Experiment/Other_BenchMark/LoCoMo-QA/tests/test_sts_v3.py` | LoCoMo adapter, CLI, leakage, output-isolation, and fake-client end-to-end tests. |

### Modify

| File | Change |
|---|---|
| `requirements.txt` | Add `tiktoken>=0.12`; add no other dependency. |

### Read-only reuse

- `Experiment/Other_BenchMark/LoCoMo-QA/Baseline/common/loader.py`: `load_sample`, `load_sample_qa`, `DialogTurn`, `LoCoMoSample`.
- `Experiment/run/common/io.py`: `.env` loading in the two CLIs only.
- `Experiment/run/common/llm_client.py`: `LLMClient.complete_json(system_prompt, user_prompt)`; do not modify this dirty file.
- `pipeline/external/embedding_retrieval.py`: optional `OpenAIEmbeddingIndex`; core tests inject a fake dense index.
- `Experiment/Other_BenchMark/LoCoMo-QA/Baseline/mem0_ofiicial/evaluation.py`: `official_qa_f1` in the reporting layer only.

## Locked Core Interfaces

These signatures are the implementation contract. If a task exposes a need to change one, update this plan and the design spec first, then make the code/test change in the same commit.

```text
# pipeline/sts_v3/adapter.py
@dataclass(frozen=True)
class ScopeInput:
    scope_kind: str
    scope_key: str
    label: str
    aliases: tuple[str, ...] = ()
    parent_scope_key: str | None = None
    is_hard_boundary: bool = False

@dataclass(frozen=True)
class VisibleMemoryRecord:
    memory_id: str
    source_record_id: str
    sequence_index: int
    text: str
    speaker_or_author: str
    source_time: str
    structural_scopes: tuple[ScopeInput, ...]
    source_type: str
    language: str | None = None

@dataclass(frozen=True)
class QueryRequest:
    memory_id: str
    question: str
    actor: str | None = None
    date_anchor: str | None = None

validate_records(records: Sequence[VisibleMemoryRecord]) -> tuple[VisibleMemoryRecord, ...]
visible_memory_hash(records: Sequence[VisibleMemoryRecord]) -> str
assert_safe_write_path(path: Path, *, allowed_root: Path, protected_roots: Sequence[Path]) -> Path
checksum_roots(roots: Sequence[Path]) -> dict[str, dict[str, object]]
```

```text
# pipeline/sts_v3/schema.py
NodeType = Literal["Scope", "Event", "Entity", "Claim", "Time", "StateFacet"]

@dataclass(frozen=True)
class GraphNode:
    node_id: str
    node_type: NodeType
    graph_id: str
    memory_id: str
    construction_method: str
    properties: Mapping[str, object]

@dataclass(frozen=True)
class GraphEdge:
    edge_id: str
    edge_type: str
    source_id: str
    target_id: str
    construction_method: str
    properties: Mapping[str, object]

@dataclass(frozen=True)
class STSGraph:
    graph_id: str
    memory_id: str
    manifest: Mapping[str, object]
    nodes: tuple[GraphNode, ...]
    edges: tuple[GraphEdge, ...]

stable_id(prefix: str, *parts: object) -> str
lexical_normalize(value: str) -> str
validate_graph(graph: STSGraph) -> None
write_graph(graph: STSGraph, output_dir: Path) -> None
load_graph(graph_dir: Path) -> STSGraph
```

`write_graph` writes flattened, stable-key records to `manifest.json`, `nodes.jsonl`, and `edges.jsonl` through a same-parent temporary directory and atomic rename. `properties` is an in-memory implementation detail; serialized node/edge fields match the design spec exactly.

The manifest has exactly these stable fields; it contains no wall-clock timestamp, filesystem path, QA metadata, or benchmark task label:

```python
MANIFEST_FIELDS = {
    "graph_schema", "builder_version", "graph_id", "memory_id", "build_hash",
    "visible_memory_hash", "prompt_hash", "construction_model", "build_config",
    "source_record_count", "node_counts", "edge_counts",
}
```

```text
# pipeline/sts_v3/build.py
class JsonCompleter(Protocol):
    complete_json: Callable[[str, str], Mapping[str, object]]

@dataclass(frozen=True)
class BuildConfig:
    graph_schema: str = "sts-graph-v3"
    builder_version: str = "3.0.0"
    construction_model: str = "gpt-4o-mini"
    target_events_per_call: int = 4
    context_events_each_side: int = 2
    max_input_tokens: int = 8000
    soft_claim_limit: int = 4
    hard_claim_limit: int = 6

@dataclass(frozen=True)
class ExtractedClaim:
    event_handle: str
    subject: str
    predicate: str
    object_value: str
    object_kind: Literal["entity", "literal"]
    polarity: Literal["positive", "negative"]
    assertion_status: Literal["asserted", "uncertain", "non_asserted"]
    temporal_kind: Literal["event", "state", "unknown"]
    time_text: str | None
    evidence_span: str
    evidence_start: int
    evidence_end: int
    time_start: int | None
    time_end: int | None

@dataclass(frozen=True)
class BuildResult:
    graph: STSGraph
    diagnostics: Mapping[str, object]

parse_claim_payload(payload: Mapping[str, object], event_text_by_handle: Mapping[str, str]) -> tuple[ExtractedClaim, ...]
build_graph(records: Sequence[VisibleMemoryRecord], *, extraction_client: JsonCompleter, state_client: JsonCompleter, config: BuildConfig = BuildConfig()) -> BuildResult
```

```text
# pipeline/sts_v3/retrieve.py
@dataclass(frozen=True)
class QueryBinding:
    binding_id: str
    subject: str
    predicate: str
    object_value: str
    time_text: str | None
    polarity: Literal["positive", "negative", "any"]
    assertion: Literal["asserted", "uncertain", "non_asserted", "any"]

@dataclass(frozen=True)
class QueryFrame:
    bindings: tuple[QueryBinding, ...]
    answer: str
    operation: Literal["lookup", "list", "count", "boolean"]
    answer_mode: Literal["extract", "compose"]
    state_mode: Literal["none", "current", "history", "at_time"]
    count_unit: Literal["occurrence", "event", "entity", "value", "stated_number"] | None

@dataclass(frozen=True)
class RetrievalBudget:
    atomic_queries: int = 4
    scope_top_k: int = 14
    anchor_scope_reserve: int = 4
    event_seed_top_k: int = 18
    binding_event_reserve: int = 2
    claim_completion_top_k: int = 8
    exact_posting_scan_cap: int = 256
    state_top_k: int = 4
    frontier_entities: int = 4
    claims_per_frontier: int = 3
    max_claim_joins: int = 2
    global_backoff_events: int = 8
    scalar_context_events: int = 8
    set_context_events: int = 16

@dataclass(frozen=True)
class CandidateBatch(Generic[T]):
    rows: tuple[T, ...]
    total: int
    exhausted: bool

@dataclass(frozen=True)
class CandidatePath:
    path_id: str
    covered_binding_ids: tuple[str, ...]
    claim_ids: tuple[str, ...]
    event_ids: tuple[str, ...]
    substitutions: Mapping[str, str]
    semantic_joins: int
    time_status: Literal["compatible", "unknown", "incompatible"]
    state_status: Literal["valid", "not_used", "invalid", "ambiguous"]
    retrieval_rank: int

@dataclass(frozen=True)
class RetrievalResult:
    paths: tuple[CandidatePath, ...]
    selected_event_ids: tuple[str, ...]
    trace: Mapping[str, object]

parse_query_frame(payload: Mapping[str, object]) -> QueryFrame | None
compile_atomic_queries(question: str, frame: QueryFrame) -> tuple[str, ...]
rrf_fuse(rankings: Sequence[Sequence[str]], *, k: int = 60) -> tuple[tuple[str, float], ...]

class BM25Index:
    search(query: str, *, top_k: int, allowed_doc_ids: Collection[str] | None = None) -> CandidateBatch[str]

class DenseRanker(Protocol):
    search(query: str, *, top_k: int, allowed_doc_ids: Collection[str] | None = None) -> Sequence[str]

class STSIndex:
    from_graph(graph: STSGraph) -> "STSIndex"

class STSRetriever:
    __init__(index: STSIndex, *, budget: RetrievalBudget = RetrievalBudget(), dense_rankers: Mapping[str, DenseRanker] | None = None)
    retrieve(request: QueryRequest, frame: QueryFrame | None) -> RetrievalResult
```

```text
# pipeline/sts_v3/verify.py
class Verdict(str, Enum):
    SUPPORT = "SUPPORT"
    REFUTE = "REFUTE"
    UNKNOWN = "UNKNOWN"

@dataclass(frozen=True)
class BindingVerdict:
    binding_id: str
    verdict: Verdict
    proof_path_ids: tuple[str, ...]
    reason: str

@dataclass(frozen=True)
class ProofBundle:
    binding_verdicts: tuple[BindingVerdict, ...]
    selected_path_ids: tuple[str, ...]
    selected_claim_ids: tuple[str, ...]
    selected_event_ids: tuple[str, ...]
    substitution_rows: tuple[Mapping[str, str], ...]
    coverage_truncated: bool

@dataclass(frozen=True)
class AnswerPlan:
    status: Literal["ready", "unavailable", "incomplete"]
    deterministic_answer: str | int | bool | tuple[str, ...] | None
    answer_mode: Literal["deterministic", "llm_extract", "llm_composition", "none"]
    allowed_values: tuple[str, ...]
    allowed_event_ids: tuple[str, ...]
    reason: str

verify_paths(index: STSIndex, frame: QueryFrame, result: RetrievalResult) -> ProofBundle
readout(index: STSIndex, request: QueryRequest, frame: QueryFrame, bundle: ProofBundle, *, budget: RetrievalBudget = RetrievalBudget()) -> AnswerPlan
validate_answer_payload(plan: AnswerPlan, payload: Mapping[str, object]) -> Mapping[str, object]
```

---

## Task 0: Create an isolated execution baseline

**Files:** No repository files changed in this task.

- [ ] Invoke `superpowers:using-git-worktrees`, create a clean worktree from the commit that contains this plan, and create/switch to `codex/sts-graph-v3`.
- [ ] Record the exact implementation base and clean status:

```bash
git rev-parse HEAD | tee /tmp/sts-v3-implementation-base.txt
git status --short
```

Expected: the implementation worktree already contains the approved spec and this plan and is otherwise clean; do not reset or clean the user's parent checkout.

- [ ] Snapshot the original dirty workspace—not `HEAD` and not an empty worktree artifact directory—with this exact command. It includes the protected v2 source directory, v2 test, v2 wrapper, v2 result root, each existing `locomo_qa_sample_graph_*` directory, and each pre-existing cache directory whose name contains `locomo` case-insensitively except the dedicated v3 cache root.

```bash
PROTECTED_PROJECT_ROOT=/Users/mac/Desktop/EpisodicMemory \
SNAPSHOT_OUT=/tmp/sts-v3-protected-before.json \
python - <<'PY'
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

project = Path(os.environ["PROTECTED_PROJECT_ROOT"]).resolve()
output = Path(os.environ["SNAPSHOT_OUT"])
fixed = [
    project / "Experiment/Other_BenchMark/LoCoMo-QA/Baseline/ours_scope_time_state",
    project / "Experiment/Other_BenchMark/LoCoMo-QA/tests/test_graph_v2.py",
    project / "Experiment/Other_BenchMark/LoCoMo-QA/run_locomo_graph_builder.py",
    project / "Graph/output/results/locomo_qa/ours_scope_time_state",
]
graph_root = project / "Graph/output/graph"
cache_root = project / "Graph/output/cache"
roots = fixed + sorted(graph_root.glob("locomo_qa_sample_graph_*"))
if cache_root.exists():
    roots += sorted(
        path
        for path in cache_root.iterdir()
        if "locomo" in path.name.lower() and path.name != "locomo_qa_sts_v3"
    )

def ignored(path: Path) -> bool:
    return (
        "__pycache__" in path.parts
        or path.name == ".DS_Store"
        or path.suffix in {".pyc", ".tmp"}
    )

def digest_root(root: Path) -> dict[str, object]:
    resolved = root.resolve(strict=False)
    aggregate = hashlib.sha256()
    file_count = 0
    link_count = 0
    total_bytes = 0
    if root.is_file() and not root.is_symlink():
        rows = [root]
    elif root.exists() and not root.is_symlink():
        rows = sorted(path for path in root.rglob("*") if not ignored(path))
    else:
        rows = [root] if root.is_symlink() else []
    for path in rows:
        relative = "." if path == root else path.relative_to(root).as_posix()
        if path.is_symlink():
            link_count += 1
            aggregate.update(f"L\0{relative}\0{os.readlink(path)}\n".encode("utf-8"))
        elif path.is_file():
            content = path.read_bytes()
            file_count += 1
            total_bytes += len(content)
            aggregate.update(
                f"F\0{relative}\0{hashlib.sha256(content).hexdigest()}\n".encode("utf-8")
            )
    return {
        "path": str(root.absolute()),
        "resolved_path": str(resolved),
        "exists": root.exists() or root.is_symlink(),
        "file_count": file_count,
        "link_count": link_count,
        "total_bytes": total_bytes,
        "sha256": aggregate.hexdigest(),
    }

payload = {"roots": [digest_root(root) for root in roots]}
output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(output)
print(sum(int(row["file_count"]) for row in payload["roots"]), "files")
PY
```

- [ ] Inspect `/tmp/sts-v3-protected-before.json`; retain it until Task 12. For each root it records resolved path, existence, recursive regular-file count, symlink count, total bytes, and SHA-256 over sorted relative-path/content hashes. Do not run this full-tree hash in unit tests; the current protected artifacts are large.
- [ ] Run the user's current dirty v2 regression read-only in the original workspace, where its uncommitted dependencies exist; do not copy those files into the clean v3 worktree:

```bash
(
  cd /Users/mac/Desktop/EpisodicMemory
  PYTHONDONTWRITEBYTECODE=1 conda run --no-capture-output -n py311 \
    python Experiment/Other_BenchMark/LoCoMo-QA/tests/test_graph_v2.py -v
) 2>&1 | tee /tmp/sts-v3-v2-before.log
rg -n "Ran 68 tests|^OK$" /tmp/sts-v3-v2-before.log
```

Expected: both lines match. This is the before regression for the actual dirty v2 baseline; the clean v3 worktree does not pretend its older committed test file is equivalent.
- [ ] Inspect the snapshot and retain it until Task 12. Do not run this full-tree hash in unit tests; the current protected artifacts are large.

**Commit:** none.

## Task 1: Establish adapter, schema, serialization, and isolation contracts

**Files:**

- Create: `pipeline/sts_v3/__init__.py`
- Create: `pipeline/sts_v3/adapter.py`
- Create: `pipeline/sts_v3/schema.py`
- Create: `pipeline/sts_v3/tests/__init__.py`
- Create: `pipeline/sts_v3/tests/test_contract.py`
- Modify: `requirements.txt`

- [ ] Add failing `AdapterContractTests`, `SchemaSerializationTests`, and `PathIsolationTests`. Cover empty/duplicate IDs, more than one `memory_id`, non-increasing `sequence_index`, missing Scope parents, stable visible-memory hash, stable IDs, exact manifest fields, JSONL round trip, nested protected path rejection, symlink escape rejection, and temporary-root checksum equality.

Use this fixture shape so later tasks share one neutral corpus rather than a LoCoMo-shaped fixture:

```python
def record(
    source_id: str,
    sequence: int,
    text: str,
    *,
    speaker: str = "Ari",
    source_time: str = "2026-01-01",
    session: str = "session-1",
) -> VisibleMemoryRecord:
    return VisibleMemoryRecord(
        memory_id="memory-1",
        source_record_id=source_id,
        sequence_index=sequence,
        text=text,
        speaker_or_author=speaker,
        source_time=source_time,
        structural_scopes=(
            ScopeInput("memory", "memory-1", "memory-1", is_hard_boundary=True),
            ScopeInput("session", session, session, parent_scope_key="memory-1"),
        ),
        source_type="message",
    )
```

- [ ] Run the focused tests and confirm they fail because `pipeline.sts_v3` does not exist:

```bash
PYTHONDONTWRITEBYTECODE=1 python -m unittest \
  pipeline.sts_v3.tests.test_contract.AdapterContractTests \
  pipeline.sts_v3.tests.test_contract.SchemaSerializationTests \
  pipeline.sts_v3.tests.test_contract.PathIsolationTests -v
```

- [ ] Add `tiktoken>=0.12` to `requirements.txt`; implement the locked adapter/schema interfaces. Canonical hashes use UTF-8 JSON with `ensure_ascii=False`, `sort_keys=True`, and compact separators. `stable_id(prefix, *parts)` returns `f"{prefix}_{sha256(canonical_parts).hexdigest()[:24]}"`.
- [ ] Implement `assert_safe_write_path` with both conditions: resolved target must be inside `allowed_root`, and neither the resolved target nor any existing path component/symlink target may equal or descend from a protected root.
- [ ] Implement graph serialization with sorted nodes/edges, flattened properties, newline-terminated JSONL, same-parent temporary directory, validation before write, and atomic directory rename. Core `write_graph` rejects every pre-existing target. The CLI may read/guard/remove an existing same-memory v3 target only under explicit `--replace`; no silent overwrite path exists.
- [ ] Run the focused tests and confirm they pass:

```bash
PYTHONDONTWRITEBYTECODE=1 python -m unittest \
  pipeline.sts_v3.tests.test_contract.AdapterContractTests \
  pipeline.sts_v3.tests.test_contract.SchemaSerializationTests \
  pipeline.sts_v3.tests.test_contract.PathIsolationTests -v
```

- [ ] Remove any temporary schema aliases or duplicate serializers introduced during the task; `pipeline/sts_v3/__init__.py` exports only the locked public types/functions.
- [ ] Commit only this task's files:

```bash
git add requirements.txt pipeline/sts_v3/__init__.py pipeline/sts_v3/adapter.py \
  pipeline/sts_v3/schema.py pipeline/sts_v3/tests/__init__.py \
  pipeline/sts_v3/tests/test_contract.py
git commit -m "feat: establish STS Graph v3 contracts"
```

## Task 2: Add the LoCoMo visible-memory adapter

**Files:**

- Create: `Experiment/Other_BenchMark/LoCoMo-QA/Baseline/ours_scope_time_state_v3/__init__.py`
- Create: `Experiment/Other_BenchMark/LoCoMo-QA/Baseline/ours_scope_time_state_v3/adapter.py`
- Create: `Experiment/Other_BenchMark/LoCoMo-QA/tests/test_sts_v3.py`

- [ ] Add failing `LoCoMoV3AdapterTests` that load `conv-26` and assert: 419 records, 19 distinct Session Scopes, one Memory Scope, Memory is the only hard boundary, every Session parent is `conv-26`, no `speaker`/`topic` Scope, speaker remains `speaker_or_author`, session date remains `source_time`, and source records are ordered by session/dialog order.
- [ ] Add an in-memory synthetic adapter test that mutates qtype, gold answer, gold evidence, and options outside the `LoCoMoSample`; assert the adapted records and `visible_memory_hash` do not change. The construction adapter must call `load_sample`, never `load_sample_qa`.
- [ ] Run and confirm import/adapter failures:

```bash
PYTHONDONTWRITEBYTECODE=1 python \
  Experiment/Other_BenchMark/LoCoMo-QA/tests/test_sts_v3.py \
  LoCoMoV3AdapterTests -v
```

- [ ] Implement only these adapter functions:

```text
adapt_sample(sample: LoCoMoSample, *, record_limit: int = 0) -> tuple[VisibleMemoryRecord, ...]

load_records(data_path: Path, sample_id: str, *, record_limit: int = 0) -> tuple[VisibleMemoryRecord, ...]

def adapt_query(sample_id: str, question: str) -> QueryRequest:
    return QueryRequest(memory_id=sample_id, question=question)

locomo_protected_roots(project_root: Path) -> tuple[Path, ...]
```

`adapt_sample` maps `sample_id` to Memory Scope, `session.session_id` to Session Scope, `dia_id` to `source_record_id`, and a global zero-based order to `sequence_index`. Use raw `turn.text`; append a non-empty image caption/query in deterministic tagged lines so visible multimodal text is not discarded. Do not add graph IDs, Entity types, topic labels, question metadata, or gold metadata.

`locomo_protected_roots` returns the exact v2 source directory, v2 test, existing v2 top-level wrapper, v2 result root, existing `locomo_qa_sample_graph_*` roots, and existing LoCoMo cache roots. It must explicitly exclude the dedicated `Graph/output/cache/locomo_qa_sts_v3` root even after that root exists. Add a regression that builder then query can reuse the v3 cache without treating it as frozen v2 state.

- [ ] Run the focused adapter tests and confirm they pass:

```bash
PYTHONDONTWRITEBYTECODE=1 python \
  Experiment/Other_BenchMark/LoCoMo-QA/tests/test_sts_v3.py \
  LoCoMoV3AdapterTests -v
```

- [ ] Commit the isolated adapter:

```bash
git add \
  Experiment/Other_BenchMark/LoCoMo-QA/Baseline/ours_scope_time_state_v3/__init__.py \
  Experiment/Other_BenchMark/LoCoMo-QA/Baseline/ours_scope_time_state_v3/adapter.py \
  Experiment/Other_BenchMark/LoCoMo-QA/tests/test_sts_v3.py
git commit -m "feat: adapt LoCoMo to STS Graph v3 records"
```

## Task 3: Implement the ten-field extraction contract

**Files:**

- Create: `pipeline/sts_v3/build.py`
- Modify: `pipeline/sts_v3/tests/test_contract.py`

- [ ] Add failing `ExtractionContractTests` for: exactly ten model fields; rejected graph-owned extra fields; whitelisted short handles; unique exact evidence spans; `time_text` uniquely inside the evidence span; valid enums; empty subject/predicate/object rejection; no hard-Scope-crossing batch; token cap; oversized single-Event rejection without truncation; one-Event overflow retry; repeated overflow raising `ClaimOverflowError` without keeping a prefix.
- [ ] Use a queued fake client that records prompts and returns one payload per call:

```python
class SequenceJsonClient:
    def __init__(self, payloads: Sequence[Mapping[str, object]]):
        self.payloads = list(payloads)
        self.prompts: list[tuple[str, str]] = []

    def complete_json(self, system_prompt: str, user_prompt: str) -> Mapping[str, object]:
        self.prompts.append((system_prompt, user_prompt))
        return self.payloads.pop(0)
```

- [ ] Run and confirm failures because extraction functions are absent:

```bash
PYTHONDONTWRITEBYTECODE=1 python -m unittest \
  pipeline.sts_v3.tests.test_contract.ExtractionContractTests -v
```

- [ ] Implement `BuildConfig`, `ExtractedClaim`, `ExtractionBatch`, `ClaimOverflowError`, `plan_extraction_batches`, `parse_claim_payload`, and `extract_claims`.
- [ ] Lock the construction prompt to the ten scalar fields and four small enums. Target short handles are `E1..En`; neighboring context is separately marked non-target and cannot be named in output. The prompt contains an explicit target-handle whitelist and raw source IDs never appear as writable model output fields.
- [ ] Count prompt tokens with `tiktoken.encoding_for_model(config.construction_model)`, falling back to `cl100k_base` only when the model name is unknown. A batch target is four Events, context is at most two Events on either side inside the same hard boundary, and the full prompt must stay at or below 8,000 tokens.
- [ ] If one source Event plus the fixed prompt exceeds 8,000 tokens, raise `OversizeEventError` and record the source ID; do not truncate or silently split raw evidence. A future document adapter must expose stable source chunks as records rather than changing this schema contract.
- [ ] Locate spans with exact `str.find` plus a second-occurrence check. Unicode/whitespace normalization may identify candidates but may not alter accepted offsets. Accept only when `event_text[start:end] == evidence_span`; accept `time_text` only when its unique raw interval is contained by `[evidence_start, evidence_end)`.
- [ ] If one Event exceeds four accepted Claims, retry that Event alone. If the retry still exceeds six, raise `ClaimOverflowError`; never slice the Claim list.
- [ ] Run the extraction tests and confirm they pass:

```bash
PYTHONDONTWRITEBYTECODE=1 python -m unittest \
  pipeline.sts_v3.tests.test_contract.ExtractionContractTests -v
```

- [ ] Delete any lenient parser or silent repair branch used while iterating; invalid Claims are diagnostics plus discard, not graph content.
- [ ] Commit:

```bash
git add pipeline/sts_v3/build.py pipeline/sts_v3/tests/test_contract.py
git commit -m "feat: add minimal STS v3 claim extraction"
```

## Task 4: Materialize the deterministic graph and Claim identity

**Files:**

- Modify: `pipeline/sts_v3/build.py`
- Modify: `pipeline/sts_v3/schema.py`
- Modify: `pipeline/sts_v3/tests/test_contract.py`

- [ ] Add failing `BuildMaterializationTests`, `ClaimIdentityTests`, and `GraphInvariantTests` covering all six node roles and every allowed edge; exact speaker Entity resolution; conjunction non-merge; literal/object edges; Event source Time; Claim inherited/explicit Time; same-Event proposition dedup; cross-Event proposition provenance retention; opposite polarity and different temporal keys not colliding; deterministic build hash; all 13 graph invariants from the design spec.
- [ ] Use a fixture where `"Ari and Bo"` appears as an object and assert it never canonicalizes to Ari or Bo. Use two Events with the same Claim and assert two Claim nodes, two `ASSERTS` edges, and one shared proposition key.
- [ ] Run and confirm materialization/invariant failures:

```bash
PYTHONDONTWRITEBYTECODE=1 python -m unittest \
  pipeline.sts_v3.tests.test_contract.BuildMaterializationTests \
  pipeline.sts_v3.tests.test_contract.ClaimIdentityTests \
  pipeline.sts_v3.tests.test_contract.GraphInvariantTests -v
```

- [ ] Implement deterministic Scope/Event/Entity/Time materialization first. Source or speaker exact names may resolve; exact verified aliases are memory-local; fuzzy/dense similarity may never persist an Entity merge.
- [ ] Do not guess Entity type from a name. In the first LoCoMo adapter, persist `entity_type=null` and `entity_type_source="not_provided"`; use `resolution_method` only from `source_identity`, `exact_name`, `exact_verified_alias`, or `unresolved_surface`. A later adapter may supply a descriptive open-vocabulary type without changing retrieval identity rules.
- [ ] Materialize source-owned edges deterministically: each structural child gets `PARENT_SCOPE(hierarchy_role="source_parent")`; each Event links only to its leaf structural Scope(s) with `IN_SCOPE(scope_role="source_container")`, reaching ancestors through `PARENT_SCOPE`; speaker uses `MENTIONS(mention_role="speaker", surface=<exact source speaker>)`; other exact extracted mentions use `mention_role="claim_argument"`; source Time uses `OCCURRED_AT(source_field="source_time")`.
- [ ] Derive literal datatype in code, not in model output: exact booleans -> `boolean`, base-10 integers -> `integer`, finite decimals -> `decimal`, unambiguous ISO-normalizable dates -> `date`, otherwise -> `text`. Preserve `object_literal` as extracted text and use the datatype-aware normalized value only in identity/unification keys. The stored datatype field remains open for later adapters; no ontology branch depends on it.
- [ ] Implement conservative Time normalization in `build.py`: parse `source_time` first; parse Claim `time_text` relative to that anchor with `dateparser`; store exact/range/relative-resolved values only when unambiguous, otherwise preserve raw text with `normalization_status="unresolved"`. Do not normalize a copied/whitespace-collapsed span.
- [ ] Assign Claim Time roles without another model call: `temporal_kind=event -> occurred_at`; `temporal_kind=state` with an explicit `since/from` boundary -> `valid_from`, with `until/through` -> `valid_until`, otherwise -> `valid_at`; `temporal_kind=unknown -> mentioned_at`. If `time_text` is null, create no `HAS_TIME`; state ordering falls back to the source Event's `OCCURRED_AT` Time. Every emitted `HAS_TIME` carries the exact source span and every source Event Time carries `anchor_event_id`.
- [ ] Implement keys exactly as:

```python
predicate_key = lexical_normalize(predicate)
object_key = (
    f"entity:{object_entity_id}"
    if object_kind == "entity"
    else f"literal:{literal_datatype}:{lexical_normalize(object_literal)}"
)
temporal_key = canonical_time_roles_and_intervals_or_raw_text_or_none
proposition_key = sha256_json([
    subject_entity_id, predicate_key, object_key, polarity,
    assertion_status, temporal_extent, temporal_key,
])
dimension_key = sha256_json([subject_entity_id, predicate_key])
```

- [ ] Store only `proposition_key` on Claim and only `dimension_key` on StateFacet. `predicate_key`, `object_key`, and `temporal_key` are deterministic build/index values, not extra persisted Claim fields.
- [ ] Use these exact stable-ID inputs:

```text
graph_id        = stable_id("graph", graph_schema, builder_version, build_hash)
Scope.node_id   = stable_id("scope", memory_id, scope_kind, scope_key)
Event.node_id   = stable_id("event", memory_id, source_record_id)
resolved Entity = stable_id("entity", memory_id, canonical_key)
unresolved Entity = stable_id("entity", memory_id, source_event_id, surface, mention_ordinal)
Claim.node_id   = stable_id("claim", source_event_id, proposition_key)
source Time     = stable_id("time", source_event_id, "source_time", normalized_or_raw_key)
Claim Time      = stable_id("time", claim_id, time_role, source_start, source_end, normalized_or_raw_key)
StateFacet      = stable_id("state", memory_id, dimension_key)
edge_id         = stable_id("edge", edge_type, source_id, target_id, canonical_required_edge_fields)
```

`build_hash = sha256(graph_schema, builder_version, construction_model, semantic BuildConfig, visible_memory_hash, prompt_hash)`. Exclude path, time of day, QA metadata, cache state, execution order, and operational CLI flags.

- [ ] Physically deduplicate only `(source_event_id, proposition_key)`. Preserve Claims across different Events. Generate all node/edge IDs from stable semantic parts, never wall-clock time, filesystem path, QA row, worker order, or model response order.
- [ ] Complete `validate_graph` for exact per-node/per-edge required field sets with no unknown properties, allowed endpoint types, dangling endpoints, Claim cardinalities, span provenance, Time provenance, key recomputation, StateFacet shape, lifecycle dimensions/basis Events, high-precision Entity resolution, deterministic manifest hash, and safe graph schema/version.
- [ ] Run the focused tests and confirm they pass:

```bash
PYTHONDONTWRITEBYTECODE=1 python -m unittest \
  pipeline.sts_v3.tests.test_contract.BuildMaterializationTests \
  pipeline.sts_v3.tests.test_contract.ClaimIdentityTests \
  pipeline.sts_v3.tests.test_contract.GraphInvariantTests -v
```

- [ ] Remove any temporary generic `RELATED_TO`, duplicated Event speaker/time fields, or graph-owned LLM field; the stored schema must match the design table exactly.
- [ ] Commit:

```bash
git add pipeline/sts_v3/build.py pipeline/sts_v3/schema.py \
  pipeline/sts_v3/tests/test_contract.py
git commit -m "feat: materialize deterministic STS v3 graphs"
```

## Task 5: Add the incremental current-state fold

**Files:**

- Modify: `pipeline/sts_v3/build.py`
- Modify: `pipeline/sts_v3/schema.py`
- Modify: `pipeline/sts_v3/tests/test_contract.py`

- [ ] Add failing `StateFoldTests` for eligibility, deterministic order, same-value compatible evidence, explicit replacement, explicit correction, unresolved conflict, invalid resolver output, independent values, lifecycle proof closure, contradictory Time direction, and linear resolver calls.
- [ ] Include a 100-Claim synthetic dimension and assert resolver calls are at most 99, never all-pairs. Include Claims with another subject/predicate and assert zero cross-dimension comparisons.
- [ ] Run and confirm state tests fail:

```bash
PYTHONDONTWRITEBYTECODE=1 python -m unittest \
  pipeline.sts_v3.tests.test_contract.StateFoldTests -v
```

- [ ] Implement the state types inside `build.py` rather than adding another public schema module:

```text
StateDecision = Literal[
    "same", "new_replaces_old", "new_corrects_old", "conflict", "separate"
]

@dataclass(frozen=True)
class StateCandidate:
    claim_id: str
    source_event_id: str
    subject_entity_id: str
    subject_surface: str
    predicate: str
    predicate_key: str
    dimension_key: str
    object_key: str
    object_surface: str
    polarity: str
    sequence_index: int
    source_record_id: str
    effective_time_id: str | None
    effective_time_start: str | None
    effective_time_end: str | None
    evidence_span: str
    raw_event_text: str

@dataclass(frozen=True)
class FoldedState:
    dimension_key: str
    predicate: str
    subject_entity_id: str
    status: Literal["current", "ambiguous"]
    resolution_method: Literal["deterministic", "pairwise_llm", "mixed"]
    selected_claim_id: str | None
    compatible_claim_ids: tuple[str, ...]
    candidate_claim_ids: tuple[str, ...]
    current_after_time_id: str | None
    current_after_basis_claim_id: str | None

@dataclass(frozen=True)
class LifecycleRelation:
    relation: Literal["SUPERSEDES", "CORRECTS", "CONFLICTS_WITH"]
    source_claim_id: str
    target_claim_id: str
    decision_method: Literal["deterministic", "pairwise_llm"]
    basis_event_ids: tuple[str, ...]

@dataclass(frozen=True)
class StateFoldResult:
    states: tuple[FoldedState, ...]
    lifecycle_relations: tuple[LifecycleRelation, ...]

fold_state_claims(
    candidates: Sequence[StateCandidate], *, resolver_client: JsonCompleter
) -> StateFoldResult
```

- [ ] Filter to asserted, ongoing Claims with a resolved subject. Group by `(subject_entity_id, predicate_key)` and process incoming Claims in `(sequence_index, source_record_id)` order. For each compared pair: when both effective Times resolve, chronological order governs allowed lifecycle direction; equal Times break by source order; when neither resolves, source order applies; when only one resolves, source order supplies deterministic processing but cannot itself justify replacement. Resolver labels always identify source-earlier/source-later explicitly, and code rejects a replacement whose resolved Time direction contradicts it unless the evidence explicitly states a correction/retrospective replacement.
- [ ] Apply these deterministic decisions before the resolver:
  1. same `object_key` and same polarity -> `same`;
  2. a later raw Event with an explicit correction cue (`actually`, `correction`, `I meant`, `to correct`, or an explicit `not X but Y`) and non-contradictory Time -> `new_corrects_old`;
  3. a later raw Event that explicitly excludes the prior value (`no longer X`, `Y instead of X`, `switched/changed/moved from X to Y`, `stopped X and started Y`, or `now Y rather than X`), mentions both old and new surfaces, and has non-contradictory Time -> `new_replaces_old`;
  4. otherwise call the pairwise resolver once on the current representative and incoming Claim.
- [ ] The resolver prompt contains only the two structured Claims and their two raw Events and accepts exactly `{"decision":"same|new_replaces_old|new_corrects_old|conflict|separate"}`. Reject extra fields or an invalid value as `conflict`; never run a repair call.
- [ ] Process a group incrementally. The current representative is the selected Claim, or the latest candidate when the group is already ambiguous. Once a group is ambiguous, later comparisons may add evidence/lifecycle edges but may not restore a selected facet unless every retained candidate is deterministically resolved into one surviving Claim. Once a decision is `separate`, remove the provisional facet for that dimension and keep all Claims directly retrievable.
- [ ] For `same`, make the later incoming Claim the selected representative and move earlier same-value evidence to `compatible`; for replacement/correction, make the incoming Claim selected and keep the old Claim only on the lifecycle edge; for conflict, remove selected support and retain all unresolved representatives as candidates. These are fold semantics, not predicate-cardinality rules.
- [ ] Keep `fold_state_claims` pure: it returns `FoldedState`/`LifecycleRelation`, not graph nodes or edges. `build_graph` supplies graph provenance and materializes `current` only with exactly one `SUPPORTS(support_role=selected)`; same-value repetitions use `support_role=compatible`; unresolved contradiction uses one `ambiguous` facet with at least two `support_role=candidate` edges. Every facet has one `STATE_OF` owner edge; a facet with resolved selected-Claim effective Time has one `CURRENT_AFTER(basis_claim_id=...)`. Add `SUPERSEDES`, `CORRECTS`, or symmetric `CONFLICTS_WITH` with exact source Event IDs. Never materialize a historical facet.
- [ ] Run state and graph-invariant tests and confirm they pass:

```bash
PYTHONDONTWRITEBYTECODE=1 python -m unittest \
  pipeline.sts_v3.tests.test_contract.StateFoldTests \
  pipeline.sts_v3.tests.test_contract.GraphInvariantTests -v
```

- [ ] Delete any cluster ontology, winner/reason model schema, historical facet path, or all-pairs helper created during iteration.
- [ ] Commit:

```bash
git add pipeline/sts_v3/build.py pipeline/sts_v3/schema.py \
  pipeline/sts_v3/tests/test_contract.py
git commit -m "feat: fold current state incrementally"
```

## Task 6: Add the isolated LoCoMo graph-builder CLI

**Files:**

- Create: `Experiment/Other_BenchMark/LoCoMo-QA/Baseline/ours_scope_time_state_v3/graph_builder.py`
- Modify: `Experiment/Other_BenchMark/LoCoMo-QA/tests/test_sts_v3.py`

- [ ] Add failing `LoCoMoV3BuilderCliTests` for defaults, `--dry-run`, fake-client build, explicit v3-only replacement, output/cache path escape, symlink escape, manifest fields, and absence of v2 module imports.
- [ ] Patch the CLI client factory in tests; assert no network request and no write outside `TemporaryDirectory`. Assert CLI arguments do not include `--graph-schema`, `--claim-mode`, `--resolver-mode`, `legacy`, `auto`, variants, Ledger, or time-selector controls.
- [ ] Run and confirm the builder tests fail:

```bash
PYTHONDONTWRITEBYTECODE=1 python \
  Experiment/Other_BenchMark/LoCoMo-QA/tests/test_sts_v3.py \
  LoCoMoV3BuilderCliTests -v
```

- [ ] Implement a direct-script import bootstrap for the project and `Baseline` roots, then wire the clean LoCoMo adapter, `locomo_protected_roots`, `LLMClient`, `BuildConfig`, path guard, `build_graph`, and `write_graph`.
- [ ] Expose two operational subcommands, not algorithm variants:

```text
graph_builder.py build
  --data PATH
  --sample-id conv-26
  --provider openai
  --model gpt-4o-mini
  --graph-root Graph/output/graph/locomo_qa_sts_v3
  --cache-root Graph/output/cache/locomo_qa_sts_v3
  --event-limit 0
  --no-cache
  --replace
  --dry-run

graph_builder.py extraction-smoke
  the same data/provider/model/cache arguments
  --events 100
  --repeats 2
  --result-root Graph/output/results/locomo_qa/ours_scope_time_state_v3
```

- [ ] Default graph target is `<graph-root>/<sample_id>/`; graph writes `manifest.json`, `nodes.jsonl`, `edges.jsonl`, and `build_report.json`. Cache keys include graph schema, prompt hash, model, visible-memory hash, and source handles.
- [ ] Resolve and guard graph target, LLM cache, smoke result, temporary directory, and replacement target before opening any file. `--replace` is accepted only when the existing target manifest says `graph_schema="sts-graph-v3"` and the same `memory_id`. Build and validate the new graph in a guarded sibling temporary directory, rename the old v3 target to a guarded sibling backup, rename the new directory into place, restore the backup on installation failure, then delete the backup. Do not delete the working v3 graph before a validated replacement exists.
- [ ] `extraction-smoke` runs the same extraction contract twice without response-cache reuse and with `LLM_PARSE_RETRIES=0`. “First-pass parse” means the first public `complete_json` invocation returns one JSON object without a semantic parse retry; transport retries remain transport accounting. Write this rate, strict ten-field schema rate, handle validity, span validity, proposition-set F1, overflow count, model, prompt hash, and visible-memory hash. It does not write a second graph schema or bypass validation.
- [ ] Run the offline fake-client tests and confirm they pass:

```bash
PYTHONDONTWRITEBYTECODE=1 python \
  Experiment/Other_BenchMark/LoCoMo-QA/tests/test_sts_v3.py \
  LoCoMoV3BuilderCliTests -v
```

- [ ] Search the new CLI for prohibited imports/switches and expect no matches:

```bash
rg -n "ours_scope_time_state(?!_v3)|state_merge|temporal_grounding|time_role_selection|legacy|relation-aware|ledger" \
  Experiment/Other_BenchMark/LoCoMo-QA/Baseline/ours_scope_time_state_v3 \
  --pcre2
```

- [ ] Commit:

```bash
git add \
  Experiment/Other_BenchMark/LoCoMo-QA/Baseline/ours_scope_time_state_v3/graph_builder.py \
  Experiment/Other_BenchMark/LoCoMo-QA/tests/test_sts_v3.py
git commit -m "feat: add isolated LoCoMo STS v3 builder"
```

## Task 7: Build the query frame, BM25 indexes, and standard RRF

**Files:**

- Create: `pipeline/sts_v3/retrieve.py`
- Modify: `pipeline/sts_v3/tests/test_contract.py`

- [ ] Add failing `QueryFrameTests`, `BM25Tests`, `RRFTests`, and `STSIndexTests`. Cover valid/invalid frame enums, invalid frame returning `None`, four-binding query compilation, no frame repair call, BM25 allowed subset/exhaustion, standard RRF sums, BM25-only fallback, injected `scope`/`event`/`claim` dense rankers, deterministic tie break, Scope documents, exact Entity alias lookup, and inverted postings.
- [ ] Pin the RRF expectation explicitly:

```python
ranked = rrf_fuse((("a", "b"), ("b", "c")), k=60)
self.assertAlmostEqual(dict(ranked)["a"], 1 / 61)
self.assertAlmostEqual(dict(ranked)["b"], 1 / 62 + 1 / 61)
self.assertAlmostEqual(dict(ranked)["c"], 1 / 62)
```

- [ ] Run and confirm failures because retrieval does not exist:

```bash
PYTHONDONTWRITEBYTECODE=1 python -m unittest \
  pipeline.sts_v3.tests.test_contract.QueryFrameTests \
  pipeline.sts_v3.tests.test_contract.BM25Tests \
  pipeline.sts_v3.tests.test_contract.RRFTests \
  pipeline.sts_v3.tests.test_contract.STSIndexTests -v
```

- [ ] Implement strict query-frame parsing with at most four bindings and three intermediate variables. Require unique binding IDs and non-empty s/p/o. For lookup/list extraction, `answer` must name a variable present in a binding subject, object, or Time field; a “When” question represents its answer with existing `t="?answer"`. Boolean/count may use synthetic `?answer`, while count still needs an enumerable binding variable unless `count_unit=stated_number`. Require `count_unit` to be non-null only for count and `state_mode=at_time` to have at least one non-variable binding Time. Predicate uses the same open lower-snake-case formatting contract as construction; it is not selected from an enum vocabulary. A failed frame produces `frame=None`; retrieval may return diagnostic Events from the original question/entity anchors, but verification/readout returns unavailable.
- [ ] Implement atomic queries: original question plus up to three binding texts. With four bindings, combine b3/b4 only in the fourth retrieval string; keep all four separate in `QueryFrame`.
- [ ] Implement BM25 with NFKC/lowercase word tokens, `k1=1.5`, `b=0.75`, and:

```text
idf(term) = ln(1 + (N - df(term) + 0.5) / (df(term) + 0.5))
score = sum(idf * tf*(k1+1) / (tf + k1*(1-b+b*doc_len/avg_doc_len)))
```

`CandidateBatch.total` is the count before `top_k`; `exhausted` is `total <= top_k`.

- [ ] `STSRetriever` receives one immutable `STSIndex`, one fixed `RetrievalBudget`, and an optional copied mapping whose only allowed keys are `scope`, `event`, and `claim`. An absent key is BM25-only for that index; reject unknown keys rather than introducing backend modes.

- [ ] Implement standard `rrf_fuse` as the sum over every supplied ranking. Each `(atomic query, BM25)` and `(atomic query, optional dense)` list is a separate ranking. Do not mix raw scores, take cross-query maxima, or add overlap bonuses.
- [ ] Build `STSIndex` maps for nodes/edges, Event-to-Scope/Claim/Entity/Time, Claim arguments/Time/Event, facet owner/support, lifecycle, exact aliases, Scope documents, Event documents, Claim documents, and exact Claim postings.
- [ ] Build each Scope document in code from its label/aliases plus linked raw Event text, Entity aliases, Claim predicates/objects, and normalized Times. Long documents are deterministically chunked for optional dense indexing; BM25 retains the full document.
- [ ] Run focused tests and confirm they pass:

```bash
PYTHONDONTWRITEBYTECODE=1 python -m unittest \
  pipeline.sts_v3.tests.test_contract.QueryFrameTests \
  pipeline.sts_v3.tests.test_contract.BM25Tests \
  pipeline.sts_v3.tests.test_contract.RRFTests \
  pipeline.sts_v3.tests.test_contract.STSIndexTests -v
```

- [ ] Delete any copied v2 fusion function or task-shaped operation alias; only the locked four operations and standard RRF remain.
- [ ] Commit:

```bash
git add pipeline/sts_v3/retrieve.py pipeline/sts_v3/tests/test_contract.py
git commit -m "feat: index STS v3 graphs with standard RRF"
```

## Task 8: Implement Scope routing, Event-first retrieval, Claim completion, Time, and State

**Files:**

- Modify: `pipeline/sts_v3/retrieve.py`
- Modify: `pipeline/sts_v3/tests/test_contract.py`

- [ ] Add failing `ScopeRoutingTests`, `EventFirstTests`, `ClaimCompletionTests`, `TimeRoutingTests`, and `StateRoutingTests`. Cover exact Entity anchor reserve, Session preference over Memory, generic leaf-Scope routing, Scope BM25+dense RRF, per-binding Event reserve, 18-Event cap, attached asserted Claims, single-hop early stop, scoped completion only for unresolved bindings, Claim-to-Event closure, query-Time anchor precedence, relative-Time normalization, Time-answer variable binding, Time three-bucket ordering, current-only StateFacet lookup, and global backoff only for incomplete proof.
- [ ] Explicitly assert an Entity anchor finds Session Scope through both provenance paths: `Entity <- MENTIONS <- Event -> IN_SCOPE -> Session` and `Entity <- HAS_SUBJECT/HAS_OBJECT <- Claim <- ASSERTS <- Event -> IN_SCOPE -> Session`. Speaker never becomes a Scope.
- [ ] Run and confirm failures:

```bash
PYTHONDONTWRITEBYTECODE=1 python -m unittest \
  pipeline.sts_v3.tests.test_contract.ScopeRoutingTests \
  pipeline.sts_v3.tests.test_contract.EventFirstTests \
  pipeline.sts_v3.tests.test_contract.ClaimCompletionTests \
  pipeline.sts_v3.tests.test_contract.TimeRoutingTests \
  pipeline.sts_v3.tests.test_contract.StateRoutingTests -v
```

- [ ] Implement Scope routing in this order: exact Entity provenance reserves at most four deepest non-hard source-provided leaf Scopes without checking `scope_kind` text; BM25 and optional dense rankings fill to 14 with standard RRF; the containing hard Memory Scope constrains the search but does not displace a more specific child in the reserve. LoCoMo's selected leaves happen to be Session Scopes; generic tests use thread/channel/document-section labels unchanged.
- [ ] Implement Event-first seed: each binding gets up to two reserved Events, remaining positions use fused rank, and the union stops at 18. Attach asserted Claims via `ASSERTS`. A raw Event is candidate evidence but cannot satisfy a binding without a matching Claim.
- [ ] Determine binding coverage with the exact fields already available. If attached Claims cover every binding and form a complete single-hop proof, skip Claim completion and joins. Otherwise query the Claim index only inside selected Scopes for unresolved bindings, reserve two per unresolved binding, cap the union at eight, and require unique `ASSERTS` closure.
- [ ] Normalize a non-variable binding Time in code with `dateparser`. Anchor precedence is `QueryRequest.date_anchor`, then the latest resolved source Event Time inside the exact hard boundary, then unresolved. Record the chosen anchor/source in stage diagnostics. Do not use an answer, qtype, or candidate-specific future fact as the query anchor.
- [ ] Implement Time classification as `compatible > unknown > incompatible`: interval overlap/containment is compatible, two resolved non-overlapping intervals are incompatible, and any unresolved side is unknown. Explicit conflict is rejected; unknown is retained at lower rank and cannot alone satisfy an explicit Time constraint. When `binding.time_text` is a variable, bind it to the exact selected Claim Time, or to its Event occurrence Time only when the Claim has no explicit Time and event-time inheritance is valid.
- [ ] Consult StateFacet only for `state_mode="current"`, using resolved owner Entity plus exact `predicate_key`, with at most four facets. Attach selected/candidate Claim and raw Event closure; `history`/`at_time` never use current facet.
- [ ] If the scoped proof is still incomplete, add at most four memory-wide Events per unresolved binding and eight total. Never cross a hard boundary; return each Event to its real Scope and reapply Claim, Time, State, and binding checks.
- [ ] Represent every Scope/Event/Claim/facet/frontier/backoff generator as `CandidateBatch(rows,total,exhausted)` and OR every non-exhausted generator still used by the selected proof into `coverage_truncated`. Scalar readout may still return a fully supported answer; list/count completeness may not.
- [ ] Populate these trace keys on every return, including empty/failure returns:

```python
TRACE_KEYS = (
    "query_frame", "atomic_queries", "selected_scope_ids", "seed_event_ids",
    "attached_claim_ids", "claim_completion_ids", "posting_scan_totals",
    "posting_scan_exhausted", "state_facet_ids", "semantic_paths",
    "binding_verdicts", "selected_proof_ids", "answer_event_ids",
    "answer_derivation", "global_backoff_used", "coverage_truncated",
)
```

- [ ] Run focused tests and confirm they pass:

```bash
PYTHONDONTWRITEBYTECODE=1 python -m unittest \
  pipeline.sts_v3.tests.test_contract.ScopeRoutingTests \
  pipeline.sts_v3.tests.test_contract.EventFirstTests \
  pipeline.sts_v3.tests.test_contract.ClaimCompletionTests \
  pipeline.sts_v3.tests.test_contract.TimeRoutingTests \
  pipeline.sts_v3.tests.test_contract.StateRoutingTests -v
```

- [ ] Remove any independent Claim/State primary lane, recency boost, Scope type switch, or fallback that bypasses the verifier.
- [ ] Commit:

```bash
git add pipeline/sts_v3/retrieve.py pipeline/sts_v3/tests/test_contract.py
git commit -m "feat: retrieve STS v3 evidence event first"
```

## Task 9: Add bounded typed joins and exhaustive list/count postings

**Files:**

- Modify: `pipeline/sts_v3/retrieve.py`
- Modify: `pipeline/sts_v3/tests/test_contract.py`

- [ ] Add failing `TypedJoinTests`, `PostingScanTests`, and `CoverageAccountingTests`. Cover legal `b1.o=?x -> b2.s=?x`, illegal role combinations, exact Entity/literal variable unification, two-join maximum, four-frontier/three-Claim caps, degree-32 hub guard, no MENTIONS/Scope expansion, global backoff ordering, posting totals, 256 cap, semantic-predicate incompleteness, unresolved hard boundary, and posting exhaustion superseding earlier top-k uncertainty.
- [ ] Include an adversarial fixture where the same name appears in two unresolved Entities; assert text equality cannot unify them. Include a hub mentioned by 100 Events; assert MENTIONS degree cannot cause semantic expansion.
- [ ] Run and confirm failures:

```bash
PYTHONDONTWRITEBYTECODE=1 python -m unittest \
  pipeline.sts_v3.tests.test_contract.TypedJoinTests \
  pipeline.sts_v3.tests.test_contract.PostingScanTests \
  pipeline.sts_v3.tests.test_contract.CoverageAccountingTests -v
```

- [ ] Implement a frontier only from a Claim argument bound to an intermediate variable. Expand through exact `HAS_SUBJECT`/`HAS_OBJECT` role agreement into another Claim argument; never expand from `MENTIONS`, `IN_SCOPE`, `PARENT_SCOPE`, Event, Time, or StateFacet.
- [ ] Enforce `max_claim_joins=2`, at most four frontier Entities, at most three new Claims per frontier, and no expansion of a non-question Entity whose Claim-argument degree exceeds 32. Rank paths lexicographically by complete binding coverage, covered count, exact subject/object agreement, valid Time/State, retrieval rank, fewer joins, then fewer raw Events.
- [ ] Build exact postings keyed by:

```python
PostingKey = tuple[
    str | None,  # subject_entity_id
    str,         # predicate_key
    str | None,  # object_key
    str,         # polarity or "any"
    str,         # assertion or "any"
    str | None,  # exact compatible temporal key
]
```

For `list`/`count`, scan the whole request `memory_id` after exact subject/predicate keys are known. Process at most 256 matching Claims or exact intermediate join rows and always return pre-cap `total` plus `exhausted`.

- [ ] Set `coverage_truncated=True` when a required predicate is only semantically retrieved, a hard boundary is not exactly selected, a posting/join total exceeds 256, or any generator still used by the final proof is not exhausted. An exhausted exact posting scan may clear earlier seed-cap uncertainty only for the exact domain it scanned.
- [ ] Keep the answer-context budget separate from scanning. Posting may inspect 256 Claims, while only proof Events may enter the final eight/sixteen Event context.
- [ ] Run and confirm focused tests pass:

```bash
PYTHONDONTWRITEBYTECODE=1 python -m unittest \
  pipeline.sts_v3.tests.test_contract.TypedJoinTests \
  pipeline.sts_v3.tests.test_contract.PostingScanTests \
  pipeline.sts_v3.tests.test_contract.CoverageAccountingTests -v
```

- [ ] Delete any unrestricted BFS, generic neighbor function, hub score formula, or exact-count path that ignores `exhausted`.
- [ ] Commit:

```bash
git add pipeline/sts_v3/retrieve.py pipeline/sts_v3/tests/test_contract.py
git commit -m "feat: add bounded STS joins and exact scans"
```

## Task 10: Implement three-valued verification and operation readout

**Files:**

- Create: `pipeline/sts_v3/verify.py`
- Modify: `pipeline/sts_v3/tests/test_contract.py`

- [ ] Add failing `BindingVerificationTests`, `LifecycleVerificationTests`, `ReadoutTests`, and `AnswerWhitelistTests`. Cover exact subject/object/predicate/polarity/assertion/Time checks, repeated-variable unification, correlated multi-variable substitution rows, raw Event closure, opposite polarity REFUTE, UNKNOWN-not-REFUTE, historical supersession semantics, current correction semantics, boolean, lookup, Time answer projection, relative/interval duration projection, list, count units, shared-answer intersection, comparison composition, context overflow, and model output/citation whitelist.
- [ ] Pin the adversarial behavior with tests such as:

```python
self.assertEqual(verdict_for(missing_claim), Verdict.UNKNOWN)
self.assertEqual(verdict_for(opposite_exact_claim), Verdict.REFUTE)
self.assertNotEqual(Verdict.UNKNOWN, Verdict.REFUTE)
```

- [ ] Run and confirm failures because verification is absent:

```bash
PYTHONDONTWRITEBYTECODE=1 python -m unittest \
  pipeline.sts_v3.tests.test_contract.BindingVerificationTests \
  pipeline.sts_v3.tests.test_contract.LifecycleVerificationTests \
  pipeline.sts_v3.tests.test_contract.ReadoutTests \
  pipeline.sts_v3.tests.test_contract.AnswerWhitelistTests -v
```

- [ ] Implement exact binding unification. Store substitutions as identity keys (`entity:<node_id>`, datatype-aware `literal:<type>:<normalized>`, or `time:<node_id>`); `readout` resolves display labels through `STSIndex`. Preserve joint substitution rows by natural-joining compatible selected-path mappings—never flatten each variable into an independent value set. BM25/dense rank only proposes paths; SUPPORT requires exact normalized predicate, exact resolved Entity/literal arguments, exact requested polarity/assertion, compatible explicit Time, consistent variables, and unique raw Event provenance.
- [ ] Return REFUTE only for an otherwise exact proposition with opposite requested polarity. A `CORRECTS` edge refutes only the exact corrected proposition. A `SUPERSEDES` edge refutes an old value only for `state_mode="current"` after the transition; for `history`/`at_time`, evaluate the old Claim against its own interval. Every other miss is UNKNOWN.
- [ ] Implement readout exactly:
  - lookup: all premise bindings SUPPORT before reading `?answer`;
  - boolean: SUPPORT -> yes, REFUTE -> no, UNKNOWN -> unavailable;
  - list: one provenance-closed proof per distinct value;
  - count: distinct occurrence/Event/Entity/value, or an explicit stated-number Claim according to `count_unit`;
  - shared answer: the same substitution independently SUPPORTs each binding;
  - composition/comparison: every operand/premise SUPPORTs before the answer model is allowed.
- [ ] For a Time answer variable, project allowed values from its bound Time node using existing fields only: exact/range normalized start/end, the exact raw phrase, and a code-computed duration when both bounds are resolved. Use the original `QueryRequest.question` to choose deterministic “when” versus “how long” projection; if multiple projections remain valid, pass only those whitelisted values to the existing final extract/composition stage. Do not add an answer-slot field, Time node field, or temporal retrieval mode.
- [ ] Return incomplete/unavailable, not a truncated answer, when a selected proof needs more than eight scalar or sixteen set-like Events. Never emit exact count while `coverage_truncated=True`.
- [ ] Implement `validate_answer_payload`: output `answer`, `values`, and `evidence_event_ids` must be subsets of `AnswerPlan.allowed_values`/`allowed_event_ids`; composition may derive a new answer string only when every premise SUPPORTs, but citations remain whitelisted. Invalid output becomes unavailable and never triggers repair or graph mutation.
- [ ] Run and confirm focused tests pass:

```bash
PYTHONDONTWRITEBYTECODE=1 python -m unittest \
  pipeline.sts_v3.tests.test_contract.BindingVerificationTests \
  pipeline.sts_v3.tests.test_contract.LifecycleVerificationTests \
  pipeline.sts_v3.tests.test_contract.ReadoutTests \
  pipeline.sts_v3.tests.test_contract.AnswerWhitelistTests -v
```

- [ ] Delete any weighted verifier threshold, similarity-derived SUPPORT, `UNKNOWN=False` coercion, or answer repair call.
- [ ] Commit:

```bash
git add pipeline/sts_v3/verify.py pipeline/sts_v3/tests/test_contract.py
git commit -m "feat: verify and read out STS v3 proofs"
```

## Task 11: Add the LoCoMo QA runner

**Files:**

- Create: `Experiment/Other_BenchMark/LoCoMo-QA/Baseline/ours_scope_time_state_v3/graph_query_runner.py`
- Modify: `Experiment/Other_BenchMark/LoCoMo-QA/tests/test_sts_v3.py`

- [ ] Add failing `LoCoMoV3QueryCliTests` and `LoCoMoV3EndToEndTests`. Cover CLI defaults, graph schema mismatch, BM25-only mode, optional fake dense mode, frame failure, deterministic boolean/count, final-answer whitelist, at-most-two semantic completion calls, complete trace, result isolation, official scoring, and absence of qtype/gold/evidence in core prompts.
- [ ] Use a spying fake client. A normal extract/compose question must call exactly twice—frame then answer. Deterministic boolean/count calls exactly once. Frame failure calls exactly once and returns unavailable. Transport/parse retries inside `LLMClient` do not create a third semantic stage; trace `online_semantic_calls` counts wrapper `complete_json` stage invocations.
- [ ] Run and confirm failures:

```bash
PYTHONDONTWRITEBYTECODE=1 python \
  Experiment/Other_BenchMark/LoCoMo-QA/tests/test_sts_v3.py \
  LoCoMoV3QueryCliTests LoCoMoV3EndToEndTests -v
```

- [ ] Implement CLI arguments with fixed algorithm budgets, not task-specific knobs:

```text
--data PATH
--sample-id conv-26
--graph-dir Graph/output/graph/locomo_qa_sts_v3/conv-26
--provider openai
--model gpt-4o-mini
--embedding-model text-embedding-3-small
--disable-dense
--cache-root Graph/output/cache/locomo_qa_sts_v3
--result-root Graph/output/results/locomo_qa/ours_scope_time_state_v3
--output PATH
--limit-cases 0
--qa-index INT
--no-cache
```

- [ ] Load the graph and build `STSIndex` once. When dense is enabled, wrap `OpenAIEmbeddingIndex` separately for Scope/Event/Claim documents, enforce allowed IDs, record returned/allowed totals, and fuse only ranks. Split documents deterministically before the reused index's 6,000-character truncation; map chunk hits back to their parent ID by the best chunk rank, deduplicate the parent ranking, then feed that ranking to standard RRF. If embedding credentials are absent or `--disable-dense` is set, run BM25-only with no semantic change.
- [ ] Before opening query/embedding caches, output JSON, JSONL trace, or temporary files, resolve them under the dedicated v3 cache/result allow-roots and reject `locomo_protected_roots`. The explicit v3-cache exclusion must let a graph build followed by QA share `locomo_qa_sts_v3` safely.
- [ ] Load QA rows only in the wrapper. Pass core only `adapt_query(row.sample_id, row.question)`. Do not put category, question type, answer, evidence IDs, or question ID in frame/answer prompts. After answer generation, add those fields back for official scoring/reporting.
- [ ] For each row: frame call -> retrieve -> verify -> readout -> optional final answer call. Deterministic ready answers skip the final call. Any unavailable plan yields `"No information available."` with only selected proof citations, which supports abstention without exposing the LoCoMo adversarial category.
- [ ] Build the final answer prompt only from the original question, validated frame, binding verdicts, operation rule, allowed substitutions, and selected raw Events in source order. Include each selected Event's exact text plus its covering Claim/Time/lifecycle fields; exclude retrieval scores, unselected candidates, Scope documents, qtype, gold, and evaluator labels. Require JSON `answer`, `values`, and `evidence_event_ids`, then pass it through `validate_answer_payload`.
- [ ] Write guarded output shaped as:

```json
{
  "benchmark": "LoCoMo QA",
  "method": "ours_scope_time_state_v3",
  "sample_id": "conv-26",
  "graph_schema": "sts-graph-v3",
  "provider": "openai",
  "model": "gpt-4o-mini",
  "results": [
    {
      "variant": "sts_v3",
      "summary": {},
      "rows": []
    }
  ]
}
```

Each row includes question metadata for reporting, hypothesis, official F1, selected Event IDs, binding verdicts, `online_semantic_calls`, and the complete `retrieval_trace`. It never writes derived answers back into the graph.

- [ ] Use `official_qa_f1` unchanged. Also report per-task answer F1, multi-hop selected-proof dialog recall, unsupported non-abstaining adversarial rate, max joins, max semantic calls, and citation-whitelist violations. These metrics inspect outputs after retrieval; they do not influence candidates.
- [ ] Run and confirm offline query/integration tests pass:

```bash
PYTHONDONTWRITEBYTECODE=1 python \
  Experiment/Other_BenchMark/LoCoMo-QA/tests/test_sts_v3.py \
  LoCoMoV3QueryCliTests LoCoMoV3EndToEndTests -v
```

- [ ] Confirm the new package never imports v2 runtime code:

```bash
rg -n "from .*ours_scope_time_state(?:\.| import)|import .*ours_scope_time_state(?:\s|$)" \
  pipeline/sts_v3 \
  Experiment/Other_BenchMark/LoCoMo-QA/Baseline/ours_scope_time_state_v3 \
  --pcre2
```

Expected: no matches.

- [ ] Commit:

```bash
git add \
  Experiment/Other_BenchMark/LoCoMo-QA/Baseline/ours_scope_time_state_v3/graph_query_runner.py \
  Experiment/Other_BenchMark/LoCoMo-QA/tests/test_sts_v3.py
git commit -m "feat: answer LoCoMo with the STS v3 chain"
```

## Task 12: Generalization, regression, smoke, and handoff gates

**Files:**

- Create: `Experiment/Other_BenchMark/LoCoMo-QA/Baseline/ours_scope_time_state_v3/README.md`
- Modify: `pipeline/sts_v3/tests/test_contract.py`
- Modify: `Experiment/Other_BenchMark/LoCoMo-QA/tests/test_sts_v3.py`

- [ ] Add `GeneralizationContractTests` with non-chat sources (`document`, `email`, `group_message`), open `source_type`/`scope_kind`/`entity_type`/predicate values, alternate hard-boundary layouts, missing source Time, unresolved entities, and qtype/gold/options metamorphic mutations. Assert graph hash and retrieved node IDs depend only on visible memory and question text.
- [ ] Add `VersionIsolationTests` that create tiny temporary v2 roots, caches, symlink escapes, and v3 outputs; snapshot before/after fake build+QA and assert byte-identical protected digests. Assert imported module names contain no v2 `ours_scope_time_state` package.
- [ ] Run the complete offline test suite:

```bash
PYTHONDONTWRITEBYTECODE=1 python -m unittest discover \
  -s pipeline/sts_v3/tests -p 'test_*.py' -v

PYTHONDONTWRITEBYTECODE=1 python \
  Experiment/Other_BenchMark/LoCoMo-QA/tests/test_sts_v3.py -v

PYTHONDONTWRITEBYTECODE=1 python -m compileall -q \
  pipeline/sts_v3 \
  Experiment/Other_BenchMark/LoCoMo-QA/Baseline/ours_scope_time_state_v3
```

Expected: all v3 tests pass and compilation succeeds without creating tracked bytecode. The actual dirty v2 regression is rerun separately in its original workspace below.

- [ ] Run the real 100-Event extraction smoke with the exact construction model:

```bash
python Experiment/Other_BenchMark/LoCoMo-QA/Baseline/ours_scope_time_state_v3/graph_builder.py \
  extraction-smoke \
  --data Experiment/Other_BenchMark/LoCoMo-QA/data/locomo10.json \
  --sample-id conv-26 \
  --provider openai \
  --model gpt-4o-mini \
  --events 100 \
  --repeats 2 \
  --no-cache \
  --result-root Graph/output/results/locomo_qa/ours_scope_time_state_v3
```

Required: first-pass JSON parse >= 99%, handle validity = 100%, exact evidence-span validity >= 98%, repeat-run proposition-set F1 >= 95%, and zero silent overflow.

- [ ] Build the full `conv-26` v3 graph into the isolated root:

```bash
python Experiment/Other_BenchMark/LoCoMo-QA/Baseline/ours_scope_time_state_v3/graph_builder.py \
  build \
  --data Experiment/Other_BenchMark/LoCoMo-QA/data/locomo10.json \
  --sample-id conv-26 \
  --provider openai \
  --model gpt-4o-mini \
  --graph-root Graph/output/graph/locomo_qa_sts_v3 \
  --cache-root Graph/output/cache/locomo_qa_sts_v3 \
  --replace
```

Required: validator passes, graph has exactly one hard Memory Scope and 19 Session children, no Topic/Speaker Scope, all accepted Claims close to exact raw Event spans, and all outputs remain under the v3 root.

- [ ] Run one real QA trace smoke:

```bash
python Experiment/Other_BenchMark/LoCoMo-QA/Baseline/ours_scope_time_state_v3/graph_query_runner.py \
  --data Experiment/Other_BenchMark/LoCoMo-QA/data/locomo10.json \
  --sample-id conv-26 \
  --graph-dir Graph/output/graph/locomo_qa_sts_v3/conv-26 \
  --provider openai \
  --model gpt-4o-mini \
  --cache-root Graph/output/cache/locomo_qa_sts_v3 \
  --result-root Graph/output/results/locomo_qa/ours_scope_time_state_v3 \
  --limit-cases 1
```

Required: all 16 trace keys exist, selected proof closes to raw Events, joins <= 2, semantic completion stages <= 2, citations are whitelisted, and no v2 module is imported.

- [ ] Recompute the real protected snapshot as `/tmp/sts-v3-protected-after.json` with the same Task 0 algorithm and assert it exactly equals `/tmp/sts-v3-protected-before.json`.
- [ ] Rerun the actual dirty v2 regression read-only in the original workspace and compare its test count/result with the before log:

```bash
(
  cd /Users/mac/Desktop/EpisodicMemory
  PYTHONDONTWRITEBYTECODE=1 conda run --no-capture-output -n py311 \
    python Experiment/Other_BenchMark/LoCoMo-QA/tests/test_graph_v2.py -v
) 2>&1 | tee /tmp/sts-v3-v2-after.log

rg -n "Ran 68 tests|^OK$" /tmp/sts-v3-v2-before.log
rg -n "Ran 68 tests|^OK$" /tmp/sts-v3-v2-after.log
```

Expected: both logs contain `Ran 68 tests` and `OK`; do not compare elapsed-time text byte-for-byte.
- [ ] Write the v3-local README with the preceding build/smoke commands and this full 199-question A/B command, but do not launch the expensive A/B as part of implementation unless separately authorized:

```bash
python Experiment/Other_BenchMark/LoCoMo-QA/Baseline/ours_scope_time_state_v3/graph_query_runner.py \
  --data Experiment/Other_BenchMark/LoCoMo-QA/data/locomo10.json \
  --sample-id conv-26 \
  --graph-dir Graph/output/graph/locomo_qa_sts_v3/conv-26 \
  --provider openai \
  --model gpt-4o-mini \
  --cache-root Graph/output/cache/locomo_qa_sts_v3 \
  --result-root Graph/output/results/locomo_qa/ours_scope_time_state_v3 \
  --output Graph/output/results/locomo_qa/ours_scope_time_state_v3/conv26_gpt4omini_all199.json
```

- [ ] Freeze the comparison source in the README:

```text
v2 result:
Graph/output/results/locomo_qa/ours_scope_time_state/results_locomo_qa_graph_conv26_gpt4omini_v2_unified_ledger_v6_all199_merged.json
SHA-256:
14beaf6615a8d318c84d39b4aa1f5635a67812ad52774f540e14bc7cd3569737
```

Promotion gates are: single-hop Answer F1 >= 0.5303, temporal >= 0.7211, open-domain >= 0.2597, multi-hop selected-proof dialog recall > 0.4870, unsupported non-abstaining adversarial answers <= 10%, joins <= 2, semantic stages <= 2, and zero citation-whitelist violations. `0.4870` is the v2 selected-evidence (`ledger_dialog_recall`) baseline, not final-citation recall.

- [ ] Run static scope and whitespace checks:

```bash
git diff --check
rg -n 'TO''DO|TB''D|Not''Implemented|pass\s*(#.*)?$' \
  pipeline/sts_v3 \
  Experiment/Other_BenchMark/LoCoMo-QA/Baseline/ours_scope_time_state_v3 \
  Experiment/Other_BenchMark/LoCoMo-QA/tests/test_sts_v3.py \
  --pcre2

rg -n "legacy|relation-aware|scope-coverage|ledger|time_role_selector" \
  pipeline/sts_v3 \
  Experiment/Other_BenchMark/LoCoMo-QA/Baseline/ours_scope_time_state_v3 \
  -g '*.py'
```

Expected: no incomplete implementation or forbidden v2-mode match. Tests may name prohibited strings to assert rejection, so the second scan intentionally checks runtime Python only.

- [ ] Verify the implementation diff contains only allowed paths:

```bash
BASE_COMMIT=$(cat /tmp/sts-v3-implementation-base.txt)
git diff --name-only "$BASE_COMMIT"..HEAD
git diff --name-only "$BASE_COMMIT"..HEAD | \
  rg "Experiment/Other_BenchMark/LoCoMo-QA/Baseline/ours_scope_time_state/|test_graph_v2.py|Graph/output/" \
  && exit 1 || true
```

- [ ] Invoke `superpowers:verification-before-completion`, then `superpowers:requesting-code-review`; address only verified v3 findings, deleting replaced v3 logic in the same change.
- [ ] Commit the final contracts and local README:

```bash
git add \
  pipeline/sts_v3/tests/test_contract.py \
  Experiment/Other_BenchMark/LoCoMo-QA/tests/test_sts_v3.py \
  Experiment/Other_BenchMark/LoCoMo-QA/Baseline/ours_scope_time_state_v3/README.md
git commit -m "test: gate STS Graph v3 promotion"
```

- [ ] Confirm the worktree is clean and report smoke artifact paths, test counts, extraction gates, graph counts, checksum equality, and the unexecuted full A/B command. Do not claim v3 beats v2 until the full 199-question report passes every promotion gate.

---

## Completion Checklist

- [ ] Shared v3 core and LoCoMo thin layer exist only at the locked paths.
- [ ] Model-facing construction remains exactly ten scalar Claim fields; the query frame remains compact.
- [ ] LoCoMo Scope is Memory + Session only; speaker is Entity; date is Time.
- [ ] State folding is incremental and linear per dimension; no closed cardinality ontology exists.
- [ ] Retrieval is one STS chain: Scope -> Event-first -> Claim completion -> Time/State -> typed joins -> verifier.
- [ ] Single-hop can stop after Event-attached Claim proof; multi-hop uses at most two semantic joins.
- [ ] List/count claims completeness only after an exhausted exact posting scan.
- [ ] UNKNOWN never becomes REFUTE; unsupported adversarial questions abstain.
- [ ] qtype/gold/options cannot change graph hashes or retrieved node IDs.
- [ ] v2 code/artifact checksums match the pre-implementation snapshot.
- [ ] Replaced v3 code/flags are deleted; no dead compatibility branch remains.
- [ ] Every implementation bug was fixed inside the frozen schema, or execution paused for explicit approval before a schema delta.
- [ ] Unit, integration, v2 regression, 100-Event extraction, full graph build, and one-row QA trace gates pass.
- [ ] Full 199-question A/B remains a documented, explicit follow-up run.

# V3: Neo4j Backend For Prebuilt LLM KG Graphs

## Purpose

This version keeps the v2 graph construction and JSON retrieval behavior, and
adds Neo4j as a graph storage backend.

Neo4j is not used as a new reasoning algorithm in this first version. It stores
the same case-level local graphs that already exist as JSON artifacts.

```text
JSON backend:
  graph JSON -> NetworkX MultiDiGraph -> StatePacketGraphRetriever -> State_packet

Neo4j backend:
  question_id-scoped Neo4j subgraph -> NetworkX MultiDiGraph -> StatePacketGraphRetriever -> State_packet
```

If import and reconstruction are lossless, both backends should produce the
same State_packet.

## Supported Functions

### 1. Build JSON Graphs

This wraps the v2 stability-first builder.

```bash
python -m longmemeval_s_graph_retrieval.prebuilt_llm_kg_graph_v3_neo4j_backend.build_json_graphs \
  --limit-per-type 10 \
  --construction-provider deepseek \
  --construction-model deepseek-v4-flash
```

Default JSON graph layout:

```text
prebuilt_llm_kg_graph_v2_stability_first/artifacts/graphs/<question_type>/<question_id>.graph.json
```

### 2. Import JSON Graphs Into Neo4j

Import all selected JSON graphs into one Neo4j database. Each node and
relationship is isolated by `question_id`.

```bash
python -m longmemeval_s_graph_retrieval.prebuilt_llm_kg_graph_v3_neo4j_backend.import_to_neo4j \
  --graph-dir longmemeval_s_graph_retrieval/prebuilt_llm_kg_graph_v2_stability_first/artifacts/graphs \
  --create-constraints \
  --clear-existing-question
```

Use `--clear-method-data` only when you want to delete all existing Neo4j data
for this method before re-importing.

Dry-run without connecting to Neo4j:

```bash
python -m longmemeval_s_graph_retrieval.prebuilt_llm_kg_graph_v3_neo4j_backend.import_to_neo4j \
  --graph-dir longmemeval_s_graph_retrieval/prebuilt_llm_kg_graph_v2_stability_first/artifacts/graphs \
  --dry-run
```

### 3. Run Pipeline From JSON Graphs

This is the v2 JSON backend.

```bash
python -m longmemeval_s_graph_retrieval.prebuilt_llm_kg_graph_v3_neo4j_backend.run_from_json \
  --limit-per-type 10 \
  --graph-dir longmemeval_s_graph_retrieval/prebuilt_llm_kg_graph_v2_stability_first/artifacts/graphs \
  --answer-provider openai \
  --answer-model gpt-4o-mini
```

### 4. Run Pipeline From Neo4j

This loads the `question_id`-scoped subgraph from Neo4j, converts it back to a
NetworkX graph, then reuses the same State_packet retriever as the JSON backend.

```bash
python -m longmemeval_s_graph_retrieval.prebuilt_llm_kg_graph_v3_neo4j_backend.run_from_neo4j \
  --limit-per-type 10 \
  --answer-provider openai \
  --answer-model gpt-4o-mini
```

Dry-run after import:

```bash
python -m longmemeval_s_graph_retrieval.prebuilt_llm_kg_graph_v3_neo4j_backend.run_from_neo4j \
  --limit-per-type 10 \
  --dry-run
```

## Neo4j Configuration

Copy `.env.example` into the repository `.env`, or add these variables to an
existing `.env`:

```text
NEO4J_URI=bolt://localhost:7687
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=password
```

Neo4j Aura uses the same code path:

```text
NEO4J_URI=neo4j+s://xxxx.databases.neo4j.io
```

Install the driver before running Neo4j commands:

```bash
pip install neo4j
```

JSON graph building and JSON graph retrieval do not require Neo4j.

## Validation

Compare JSON graph reconstruction with Neo4j graph reconstruction:

```bash
python -m longmemeval_s_graph_retrieval.prebuilt_llm_kg_graph_v3_neo4j_backend.validate_neo4j \
  --graph-dir longmemeval_s_graph_retrieval/prebuilt_llm_kg_graph_v2_stability_first/artifacts/graphs \
  --compare-state-packet
```

Validation checks:

- JSON node count vs Neo4j-loaded node count.
- JSON edge count vs Neo4j-loaded edge count.
- Optional State_packet equality after canonicalization.

## Design Boundary

This version deliberately uses simple `question_id` matching in Neo4j:

```cypher
MATCH (n:GraphNode {method: $method, question_id: $question_id})-[r]->
      (m:GraphNode {method: $method, question_id: $question_id})
RETURN n, r, m
```

It does not translate the whole State_packet algorithm into Cypher yet. Neo4j is
used as graph persistence, visualization, and retrieval storage.


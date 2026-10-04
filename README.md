# Scope-Time-State

This repository contains the anonymous implementation of Scope-Time-State
(STS), a long-term memory method that resolves evidence by its conversational
scope, temporal position, and evolving state.

STS builds one shared graph with five domain objects:

- **Event**: a source conversation segment or benchmark chapter.
- **Claim**: an atomic factual statement extracted from an Event.
- **Scope**: a coherent situation that groups related Events.
- **State**: an ordered Claim thread describing one evolving subject.
- **TimeGroup**: Claims whose relative order is not supported by the evidence.

The graph uses explicit `ScopeEventRelation`, `EventClaimRelation`,
`StateMembership`, and temporal-order records. Retrieval starts from Claims,
then activates Scope, State, and Time metadata to organize evidence without
discarding the direct Claim anchors.

## Repository layout

```text
src/sts/
├── graph/          # schema, construction, and STS relations
├── extraction/     # Event, Claim, and Scope extraction
├── state/          # State threading and temporal ordering
├── retrieval/      # BM25/vector indexes and RRF retrieval
├── generation/     # context formatting and answer generation
├── evaluation/     # judge and metrics
├── providers/      # LLM and embedding clients
└── adapters/       # dataset-specific internal adapters

benchmarks/
├── locomo/
└── epbench/
```

Generated datasets, indexes, checkpoints, logs, and answers are excluded from
version control.

## Installation

Python 3.11 or newer is required.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
cp .env.example .env
```

Fill in the OpenAI-compatible LLM and embedding endpoint settings in `.env`.

## LoCoMo

Place `locomo10.json` at `data/locomo/locomo10.json`, or pass `--data`.

Build the graph and indexes:

```bash
python benchmarks/locomo/build.py --sample-id conv-26
```

Run retrieval and answer generation:

```bash
python benchmarks/locomo/run.py query --sample-id conv-26
```

Evaluate completed answers:

```bash
python benchmarks/locomo/run.py evaluate --sample-id conv-26
```

Use `python benchmarks/locomo/run.py run` for construction, retrieval, and
answer generation in one command. Evaluation remains a separate command so a
judge rerun cannot silently regenerate answers.

## EPBench

Place `book.json` and `df_qa.parquet` in `data/epbench/`, or pass
`--data-folder`.

```bash
python benchmarks/epbench/build.py
python benchmarks/epbench/answer.py
python benchmarks/epbench/evaluate.py
```

EPBench construction and answer generation never read evaluator-only answer,
chapter-label, cue, or retrieval-type fields.

## Source check

```bash
python -m compileall -q src benchmarks
```

All serialized output uses the STS schema. No compatibility loader for older
artifact formats is included; rebuild artifacts after schema or prompt changes.

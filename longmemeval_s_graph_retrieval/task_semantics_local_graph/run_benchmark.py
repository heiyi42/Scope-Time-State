"""
Task-Semantics Local Graph Runner for LongMemEval-S.

Replaces the LLM-based evidence extraction with a rule-based local graph.
BM25 → graph build → state_packet → LLM answer (gpt-4o-mini) → gpt-4o judge.

Usage (single type):
    python -m longmemeval_s_graph_retrieval.task_semantics_local_graph.run_benchmark \
        --question-types knowledge-update --limit-per-type 2

Usage (all types, parallel — run 6 processes externally):
    for t in knowledge-update multi-session ...; do
        python -m ... --question-types $t --limit-per-type 10 &
    done
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

PROJECT_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_DIR))

from pipeline.external.longmemeval_s.runner import (
    LMERow, load_rows, select_rows, session_text, tokenized,
    bm25_top_session_ids, retrieval_query, compact_session_text_for_question,
    answer_check_prompt,
)
from Experiment.run.common.io import load_dotenv
from Experiment.run.common.llm_client import provider_config

# ── Graph method ──
from longmemeval_s_graph_retrieval.task_semantics_local_graph.pipeline import (
    build_state_packet_from_sessions,
    validate_state_packet,
)

DATA_PATH = PROJECT_DIR / "Experiment/Other_BenchMark/LongMemEval-S/LongMemEval-S_data/data/longmemeval_s_cleaned.json"
OUTPUT_DIR = PROJECT_DIR / "longmemeval_s_graph_retrieval/task_semantics_local_graph/outputs"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Task-Semantics Local Graph benchmark runner")
    p.add_argument("--data", default=str(DATA_PATH))
    p.add_argument("--provider", default="openai")
    p.add_argument("--question-types", nargs="+", default=[])
    p.add_argument("--limit-per-type", type=int, default=10)
    p.add_argument("--top-k", type=int, default=20, help="BM25 candidate session count")
    p.add_argument("--max-session-chars", type=int, default=6000,
                   help="Per-session character cap for graph input")
    p.add_argument("--judge", action="store_true", default=True)
    p.add_argument("--judge-provider", default="openai")
    p.add_argument("--judge-model", default="gpt-4o-2024-08-06")
    p.add_argument("--output", default=str(OUTPUT_DIR / "results_graph_rule.json"))
    p.add_argument("--cache", default=str(OUTPUT_DIR / "llm_cache_graph_rule.json"))
    p.add_argument("--judge-cache", default=str(OUTPUT_DIR / "judge_cache_graph_rule.json"))
    return p.parse_args()


def sessions_for_graph(row: LMERow, selected_ids: Sequence[str], max_chars: int) -> List[Dict[str, Any]]:
    """Convert LMERow sessions to graph-compatible format."""
    selected = set(selected_ids)
    sessions: List[Dict[str, Any]] = []
    for sid, date, session in zip(row.haystack_session_ids, row.haystack_dates, row.haystack_sessions):
        if sid not in selected:
            continue
        full = session_text(session)
        if len(full) > max_chars:
            full = compact_session_text_for_question(session, row.question, max_chars)
        sessions.append({
            "session_id": sid,
            "date": date,
            "turns": [{"role": str(t.get("role", "unknown")), "content": str(t.get("content", ""))}
                      for t in session],
            "full_text": full,
        })
    return sessions


def truncate_state_packet(packet: Dict[str, Any], max_facets: int = 6, max_snippets: int = 15, max_rejected: int = 6, max_value_chars: int = 500) -> Dict[str, Any]:
    """Truncate state_packet to fit within LLM context window."""
    import copy
    p = copy.deepcopy(packet)
    p["state_facets"] = p["state_facets"][:max_facets]
    for f in p["state_facets"]:
        if len(str(f.get("value", ""))) > max_value_chars:
            f["value"] = str(f["value"])[:max_value_chars] + "..."
    p["evidence_snippets"] = p.get("evidence_snippets", [])[:max_snippets]
    p["rejected_claims"] = p["rejected_claims"][:max_rejected]
    for c in p["rejected_claims"]:
        if len(str(c.get("claim", ""))) > max_value_chars:
            c["claim"] = str(c["claim"])[:max_value_chars] + "..."
    return p


def answer_system_prompt() -> str:
    return (
        "You answer LongMemEval-S questions using only the extracted evidence from a state packet. "
        "The state packet contains evidence snippets, state facets, and rejected claims. "
        "Use only this information. If the evidence does not contain enough to answer, say \"I don't know\". "
        "Return strict JSON with key answer."
    )


def answer_user_prompt(row: LMERow, state_packet: Dict[str, Any]) -> str:
    packet_json = json.dumps(state_packet, ensure_ascii=False, indent=2)
    return (
        f"Benchmark: LongMemEval-S\n"
        f"Question date: {row.question_date}\n"
        f"Question type: {row.question_type}\n\n"
        f"Question: {row.question}\n\n"
        f"State packet (extracted evidence):\n{packet_json}\n\n"
        "Respond as JSON only:\n"
        '{"answer": "..."}'
    )


def normalize_answer(value: str) -> str:
    lowered = value.lower()
    lowered = lowered.translate(str.maketrans("", "", "!\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~"))
    lowered = re.sub(r"\b(a|an|the)\b", " ", lowered)
    return " ".join(lowered.split())


def local_answer_match(gold: str, hypothesis: str) -> bool:
    g = normalize_answer(gold)
    h = normalize_answer(hypothesis)
    if not g or not h:
        return False
    return g == h or g in h or h in g


def judge_call(client: Any, row: Dict[str, Any]) -> Dict[str, Any]:
    prompt = answer_check_prompt(
        LMERow(
            question_id=row["question_id"],
            question_type=row["question_type"],
            question=row["question"],
            answer=row["gold_answer"],
            question_date=row.get("question_date", ""),
            haystack_session_ids=(),
            haystack_dates=(),
            haystack_sessions=(),
            answer_session_ids=(),
        ),
        row["hypothesis"],
    )
    completion = client.chat.completions.create(
        model=client.model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
        max_tokens=10,
    )
    response = (completion.choices[0].message.content or "").strip()
    return {"model": client.model, "label": "yes" in response.lower(), "response": response}


def main() -> int:
    args = parse_args()
    load_dotenv()

    api_key, model, api_base = provider_config(args.provider)

    from openai import OpenAI
    llm_client = OpenAI(api_key=api_key, base_url=api_base, timeout=120, max_retries=2)

    if args.judge:
        judge_key, judge_model_name, judge_base = provider_config(args.judge_provider)
        if args.judge_model:
            judge_model_name = args.judge_model
        judge = OpenAI(api_key=judge_key, base_url=judge_base, timeout=120, max_retries=2)
        judge.model = judge_model_name  # hack for judge_call
    else:
        judge = None

    rows = load_rows(Path(args.data))
    rows = select_rows(rows, args.question_types, 0, args.limit_per_type)

    print(f"Running {len(rows)} cases: {dict(Counter(r.question_type for r in rows))}")
    print(f"Model: {model}, Judge: {getattr(judge, 'model', 'none')}")
    print()

    results: List[Dict[str, Any]] = []
    for i, row in enumerate(rows, 1):
        # 1. BM25
        selected_ids = bm25_top_session_ids(row, args.top_k, retrieval_query(row, expand=True))

        # 2. Build graph → state_packet (rule-based, no LLM)
        sessions = sessions_for_graph(row, selected_ids, args.max_session_chars)
        state_packet = build_state_packet_from_sessions(
            sessions=sessions,
            question=row.question,
            question_type=row.question_type,
            question_date=row.question_date,
        )
        validate_state_packet(state_packet)
        state_packet = truncate_state_packet(state_packet)  # clip to fit context window

        # 3. LLM answer
        completion = llm_client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": answer_system_prompt()},
                {"role": "user", "content": answer_user_prompt(row, state_packet)},
            ],
            temperature=0,
            max_tokens=512,
        )
        raw = (completion.choices[0].message.content or "").strip()
        try:
            answer = json.loads(raw).get("answer", raw)
        except json.JSONDecodeError:
            answer = raw

        # 4. Judge
        result_row = {
            "question_id": row.question_id,
            "question_type": row.question_type,
            "question": row.question,
            "gold_answer": row.answer,
            "hypothesis": str(answer),
            "question_date": row.question_date,
            "answer_session_ids": list(row.answer_session_ids),
            "evidence_session_ids": state_packet.get("relevant_session_ids", []),
            "state_facets": state_packet.get("state_facets", []),
            "rejected_claims": state_packet.get("rejected_claims", []),
            "enough_evidence": state_packet.get("enough_evidence", False),
        }

        if judge:
            j = judge_call(judge, result_row)
            result_row["autoeval_label"] = j
        else:
            result_row["autoeval_label"] = None

        result_row["local_answer_match"] = local_answer_match(row.answer, str(answer))
        results.append(result_row)

        label = result_row["autoeval_label"]["label"] if result_row["autoeval_label"] else "?"
        print(f"[{i}/{len(rows)}] {row.question_id} {row.question_type} → "
              f"{'YES' if label else 'no ' if label is not None else '?'} | local={result_row['local_answer_match']}")

    # Summary
    by_type: Dict[str, List[Dict]] = {}
    for r in results:
        by_type.setdefault(r["question_type"], []).append(r)

    print(f"\n{'='*70}")
    print(f"Task-Semantics Local Graph (rule-based) — {model} + gpt-4o judge")
    print(f"{'='*70}")
    print(f"\n{'type':<28} {'n':>3} {'ans_j':>8}")
    print(f"{'-'*43}")

    type_accs = {}
    for qt, items in sorted(by_type.items()):
        n = len(items)
        acc = sum(1 for r in items if r["autoeval_label"] and r["autoeval_label"]["label"]) / n if n else 0
        type_accs[qt] = acc
        print(f"  {qt:<28} {n:>3} {acc:>8.3f}")

    macro = sum(type_accs.values()) / len(type_accs) if type_accs else 0
    micro = sum(1 for r in results if r["autoeval_label"] and r["autoeval_label"]["label"]) / len(results) if results else 0
    print(f"{'-'*43}")
    print(f"  {'MACRO (task-averaged)':<28}     {macro:>8.3f}")
    print(f"  {'MICRO (overall)':<28}     {micro:>8.3f}")

    # Save
    output = {
        "method": "task_semantics_local_graph",
        "model": model,
        "judge_model": getattr(judge, 'model', 'none'),
        "n_cases": len(results),
        "macro_acc": macro,
        "micro_acc": micro,
        "by_type": {qt: {"n": len(items), "acc": type_accs[qt]} for qt, items in sorted(by_type.items())},
        "rows": results,
    }

    out_path = Path(args.output)
    out_path.parent.mkdir(exist_ok=True)
    json.dump(output, open(out_path, "w"), ensure_ascii=False, indent=2)
    print(f"\nWrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

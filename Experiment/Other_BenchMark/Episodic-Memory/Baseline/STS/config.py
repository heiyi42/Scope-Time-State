"""Frozen EPBench Long Book paths and STS v2 defaults."""

from __future__ import annotations

from pathlib import Path

STS_DIR = Path(__file__).resolve().parent
EPBENCH_ROOT = STS_DIR.parents[1]
REPO_ROOT = STS_DIR.parents[4]
CORPUS_DIR = (
    EPBENCH_ROOT
    / "data"
    / "Udefault_Sdefault_seed0"
    / "books"
    / "model_claude-3-5-sonnet-20240620_itermax_10_"
    "Idefault_nbchapters_196_nbtokens_102870"
)
BOOK_PATH = CORPUS_DIR / "book.json"
QA_PATH = CORPUS_DIR / "df_qa.parquet"

ARTIFACT_NAME = "epbench_long_book_sts_v2"
GRAPH_DIR = REPO_ROOT / "Graph" / "graph" / ARTIFACT_NAME
CACHE_DIR = REPO_ROOT / "Graph" / "cache" / ARTIFACT_NAME
RESULT_DIR = REPO_ROOT / "Graph" / "results" / ARTIFACT_NAME

BUILD_MODEL = "gpt-4o-mini"
ANSWER_MODEL = "gpt-4o-mini"
JUDGE_MODEL = "gpt-4o-mini"
EMBEDDING_MODEL = "text-embedding-3-small"

MESSAGE_CHUNK_SIZE = 1
MAX_CLAIMS_PER_CHAPTER = 8
RESOLVER_CANDIDATE_LIMIT = 24
SCOPE_TOP_K = 14
CLAIM_CANDIDATE_K = 80
SCOPE_BACKOFF_K = 8
STATE_ANCHOR_CLAIM_K = 16
FINAL_CLAIM_K = 24
FINAL_CHAPTER_K = 24

EMBEDDING_SCORE_WEIGHT = 1.0
SCOPE_TYPE_COVERAGE_WEIGHT = 0.35
TIME_COMPATIBILITY_WEIGHT = 0.25

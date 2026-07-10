#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_DIR="$ROOT/source/EverMemBench"
DATA_DIR="$ROOT/dataset"

CONDA_ENV="${CONDA_ENV:-py311}"
SYSTEMS="${EVERMEMBENCH_SYSTEMS:-embedding_rag mem0_local memobase memos_local graphiti_local}"
TOPICS="${EVERMEMBENCH_TOPICS:-01 02 03 04 05}"
STAGES="${EVERMEMBENCH_STAGES:-add search answer evaluate}"
OUTPUT_DIR="${EVERMEMBENCH_OUTPUT_DIR:-$SOURCE_DIR/eval/results}"
TOP_K="${EVERMEMBENCH_TOP_K:-10}"
RUN_ID="${EVERMEMBENCH_RUN_ID:-$(date +%Y%m%d_%H%M%S)}"
LOG_DIR="${EVERMEMBENCH_LOG_DIR:-$ROOT/log}"

mkdir -p "$LOG_DIR"

DOTENV="$ROOT/../../../.env"
if [[ -f "$DOTENV" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$DOTENV"
  set +a
fi

export NO_PROXY="${NO_PROXY:-localhost,127.0.0.1,::1}"
export no_proxy="${no_proxy:-$NO_PROXY}"

read -r -a SYSTEM_ARGS <<< "$SYSTEMS"
read -r -a TOPIC_ARGS <<< "$TOPICS"
read -r -a STAGE_ARGS <<< "$STAGES"

EXTRA_ARGS=()
if [[ "${EVERMEMBENCH_SMOKE:-0}" == "1" ]]; then
  EXTRA_ARGS+=(--smoke --smoke-days "${EVERMEMBENCH_SMOKE_DAYS:-1}")
  if [[ -n "${EVERMEMBENCH_QA_LIMIT:-}" ]]; then
    EXTRA_ARGS+=(--qa-limit "$EVERMEMBENCH_QA_LIMIT")
  else
    EXTRA_ARGS+=(--qa-limit 5)
  fi
elif [[ -n "${EVERMEMBENCH_QA_LIMIT:-}" ]]; then
  EXTRA_ARGS+=(--qa-limit "$EVERMEMBENCH_QA_LIMIT")
fi

cd "$SOURCE_DIR"

for system in "${SYSTEM_ARGS[@]}"; do
  for topic in "${TOPIC_ARGS[@]}"; do
    dataset="$DATA_DIR/$topic/dialogue.json"
    qa="$DATA_DIR/$topic/qa_${topic}.json"
    user_id="topic${topic}_${system}_${RUN_ID}"
    log_file="$LOG_DIR/official_${system}_topic${topic}_${RUN_ID}.log"
    set +e
    {
      echo "== EverMemBench official baseline: system=$system topic=$topic user_id=$user_id =="
      echo "== stages=${STAGES} output_dir=$OUTPUT_DIR log_file=$log_file =="
      PYTHONUNBUFFERED=1 conda run -n "$CONDA_ENV" python -m eval.cli \
        --dataset "$dataset" \
        --qa "$qa" \
        --system "$system" \
        --user-id "$user_id" \
        --stages "${STAGE_ARGS[@]}" \
        --top-k "$TOP_K" \
        --output-dir "$OUTPUT_DIR" \
        "${EXTRA_ARGS[@]}"
    } 2>&1 | tee -a "$log_file"
    status=${PIPESTATUS[0]}
    set -e
    if [[ "$status" -ne 0 ]]; then
      echo "EverMemBench official baseline failed: system=$system topic=$topic log=$log_file" >&2
      exit "$status"
    fi
  done
done

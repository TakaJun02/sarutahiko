#!/usr/bin/env bash

# Run the single OpenAI-compatible vLLM endpoint inside the ibera Ray head.

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=cluster-common.sh
source "${SCRIPT_DIR}/cluster-common.sh"

load_project_env
require_command docker

# Read Inference_sever even though serve runs on ibera; this catches a copied or
# incomplete .env before vLLM starts and keeps every cluster script on one source.
WORKER_IP="$(worker_node_ip)"
CONTAINER_NAME="${PP2_HEAD_CONTAINER:-pp2-ray-head-ibera}"

if ! docker ps --format '{{.Names}}' | grep -Fxq "${CONTAINER_NAME}"; then
  echo "ERROR: running Ray head container not found: ${CONTAINER_NAME}" >&2
  exit 1
fi

MODEL_NAME="${PP2_MODEL:-google/gemma-4-31B-it-qat-w4a16-ct}"
PIPELINE_PARALLEL_SIZE="${PIPELINE_PARALLEL_SIZE:-2}"
TENSOR_PARALLEL_SIZE="${TENSOR_PARALLEL_SIZE:-1}"
MAX_MODEL_LEN="${MAX_MODEL_LEN:-16384}"
MAX_NUM_SEQS="${MAX_NUM_SEQS:-4}"
GPU_MEMORY_UTILIZATION="${GPU_MEMORY_UTILIZATION:-0.92}"
LIMIT_MM_PER_PROMPT="${LIMIT_MM_PER_PROMPT:-}"
if [[ -z "${LIMIT_MM_PER_PROMPT}" ]]; then
  LIMIT_MM_PER_PROMPT='{"image": 0}'
fi
VLLM_HOST_VALUE="${VLLM_HOST:-127.0.0.1}"
VLLM_PORT_VALUE="${VLLM_PORT:-8000}"
ENABLE_PREFIX_CACHING="${ENABLE_PREFIX_CACHING:-1}"
ENABLE_NATIVE_TOOL_CALLING="${ENABLE_NATIVE_TOOL_CALLING:-0}"

echo "Checking Ray resources for PP=${PIPELINE_PARALLEL_SIZE} (nubia=${WORKER_IP})."
docker exec --interactive "${CONTAINER_NAME}" python3 - "${PIPELINE_PARALLEL_SIZE}" <<'PY'
import sys

import ray

required_gpus = int(sys.argv[1])
ray.init(address="auto", ignore_reinit_error=True)
resources = ray.cluster_resources()
available_gpus = int(resources.get("GPU", 0))
print(f"Ray cluster resources: {resources}")
if available_gpus < required_gpus:
    raise SystemExit(
        f"ERROR: Ray reports {available_gpus} GPU(s); {required_gpus} required."
    )
PY

SERVE_ARGS=(
  "${MODEL_NAME}"
  --host "${VLLM_HOST_VALUE}"
  --port "${VLLM_PORT_VALUE}"
  --distributed-executor-backend ray
  --pipeline-parallel-size "${PIPELINE_PARALLEL_SIZE}"
  --tensor-parallel-size "${TENSOR_PARALLEL_SIZE}"
  --max-model-len "${MAX_MODEL_LEN}"
  --max-num-seqs "${MAX_NUM_SEQS}"
  --gpu-memory-utilization "${GPU_MEMORY_UTILIZATION}"
  --limit-mm-per-prompt "${LIMIT_MM_PER_PROMPT}"
)

if [[ "${ENABLE_PREFIX_CACHING}" == "1" ]]; then
  SERVE_ARGS+=(--enable-prefix-caching)
fi

if [[ "${ENABLE_NATIVE_TOOL_CALLING}" == "1" ]]; then
  SERVE_ARGS+=(--enable-auto-tool-choice --tool-call-parser gemma4)
  if [[ -n "${VLLM_CHAT_TEMPLATE:-}" ]]; then
    SERVE_ARGS+=(--chat-template "${VLLM_CHAT_TEMPLATE}")
  fi
fi

EXEC_ENV=()
if [[ -n "${VLLM_PP_LAYER_PARTITION:-}" ]]; then
  EXEC_ENV+=(--env "VLLM_PP_LAYER_PARTITION=${VLLM_PP_LAYER_PARTITION}")
fi

DOCKER_TTY=()
if [[ -t 0 && -t 1 ]]; then
  DOCKER_TTY=(-it)
fi

echo "Starting ${MODEL_NAME} with PP=${PIPELINE_PARALLEL_SIZE}, TP=${TENSOR_PARALLEL_SIZE}, max_model_len=${MAX_MODEL_LEN}."
echo "This command stays in the foreground; stop the PoC with start-head.sh stop."
exec docker exec "${DOCKER_TTY[@]}" "${EXEC_ENV[@]}" \
  "${CONTAINER_NAME}" vllm serve "${SERVE_ARGS[@]}"

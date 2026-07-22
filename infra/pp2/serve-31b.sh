#!/usr/bin/env bash

# Run the single OpenAI-compatible vLLM endpoint inside the ibera Ray head.
#
# FR-35: `start` (default) launches vLLM DETACHED inside the head container so
# the endpoint survives the launching shell/session. Logs go to
# /root/pp2-serve.log inside the container (`$0 logs`). Set PP2_FOREGROUND=1
# to keep the pre-FR-35 foreground behavior for debugging.

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=cluster-common.sh
source "${SCRIPT_DIR}/cluster-common.sh"

load_project_env
require_command docker

CONTAINER_NAME="${PP2_HEAD_CONTAINER:-pp2-ray-head-ibera}"
SERVE_LOG="/root/pp2-serve.log"
API_URL="http://127.0.0.1:${VLLM_PORT:-8000}/v1/models"

require_running_container() {
  if ! docker ps --format '{{.Names}}' | grep -Fxq "${CONTAINER_NAME}"; then
    echo "ERROR: running Ray head container not found: ${CONTAINER_NAME}" >&2
    exit 1
  fi
}

ACTION="${1:-start}"
case "${ACTION}" in
  stop)
    require_running_container
    if docker exec "${CONTAINER_NAME}" pkill -f "vllm serve" 2>/dev/null; then
      echo "Sent SIGTERM to vllm serve in ${CONTAINER_NAME}."
    else
      echo "No vllm serve process found in ${CONTAINER_NAME}."
    fi
    exit 0
    ;;
  status)
    require_running_container
    if curl -fs -m 5 "${API_URL}" >/dev/null 2>&1; then
      echo "API READY: ${API_URL}"
      curl -fs -m 5 "${API_URL}"
      echo
    else
      echo "API not responding on ${API_URL}."
      docker exec "${CONTAINER_NAME}" bash -c "tail -n 5 ${SERVE_LOG} 2>/dev/null" || true
    fi
    exit 0
    ;;
  logs)
    require_running_container
    exec docker exec "${CONTAINER_NAME}" tail -n 100 -f "${SERVE_LOG}"
    ;;
  start)
    ;;
  *)
    echo "Usage: $0 [start|status|logs|stop]" >&2
    exit 2
    ;;
esac

require_running_container

# Read Inference_sever even though serve runs on ibera; this catches a copied or
# incomplete .env before vLLM starts and keeps every cluster script on one source.
WORKER_IP="$(worker_node_ip)"

MODEL_NAME="${PP2_MODEL:-google/gemma-4-31B-it-qat-w4a16-ct}"
PIPELINE_PARALLEL_SIZE="${PIPELINE_PARALLEL_SIZE:-2}"
TENSOR_PARALLEL_SIZE="${TENSOR_PARALLEL_SIZE:-1}"
MAX_MODEL_LEN="${MAX_MODEL_LEN:-16384}"
# 8 matches the open-campus concurrency target (ARCHITECTURE.md section 5).
# The PoC measured c1/c4; vLLM degrades gracefully via preemption beyond that.
MAX_NUM_SEQS="${MAX_NUM_SEQS:-8}"
GPU_MEMORY_UTILIZATION="${GPU_MEMORY_UTILIZATION:-0.92}"
LIMIT_MM_PER_PROMPT="${LIMIT_MM_PER_PROMPT:-}"
if [[ -z "${LIMIT_MM_PER_PROMPT}" ]]; then
  LIMIT_MM_PER_PROMPT='{"image": 0}'
fi
VLLM_HOST_VALUE="${VLLM_HOST:-127.0.0.1}"
VLLM_PORT_VALUE="${VLLM_PORT:-8000}"
ENABLE_PREFIX_CACHING="${ENABLE_PREFIX_CACHING:-1}"
ENABLE_NATIVE_TOOL_CALLING="${ENABLE_NATIVE_TOOL_CALLING:-0}"
READY_TIMEOUT_SECONDS="${PP2_READY_TIMEOUT:-600}"

if curl -fs -m 3 "${API_URL}" >/dev/null 2>&1; then
  echo "ERROR: something already serves ${API_URL} (12B compose vllm still up, or serve already running)." >&2
  echo "Stop it first (docker compose stop vllm / $0 stop)." >&2
  exit 1
fi

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
# Pin the torch-distributed (c10d) rendezvous to a deterministic high port.
# Belt-and-braces only: the real fix is the per-host firewall allow
# (README / PP2_MULTINODE_GUIDE), because NCCL/Gloo use dynamic ports anyway.
EXEC_ENV+=(--env "VLLM_PORT=${PP2_VLLM_INTERNAL_PORT:-29500}")

echo "Starting ${MODEL_NAME} with PP=${PIPELINE_PARALLEL_SIZE}, TP=${TENSOR_PARALLEL_SIZE}, max_model_len=${MAX_MODEL_LEN}, max_num_seqs=${MAX_NUM_SEQS}."

if [[ "${PP2_FOREGROUND:-0}" == "1" ]]; then
  DOCKER_TTY=()
  if [[ -t 0 && -t 1 ]]; then
    DOCKER_TTY=(-it)
  fi
  echo "Foreground mode; stop with Ctrl-C (or start-head.sh stop)."
  exec docker exec "${DOCKER_TTY[@]}" "${EXEC_ENV[@]}" \
    "${CONTAINER_NAME}" vllm serve "${SERVE_ARGS[@]}"
fi

SERVE_COMMAND="$(printf '%q ' vllm serve "${SERVE_ARGS[@]}")"
docker exec --detach "${EXEC_ENV[@]}" "${CONTAINER_NAME}" \
  bash -c "exec ${SERVE_COMMAND} >> ${SERVE_LOG} 2>&1"
echo "Detached serve launched; logs: $0 logs"

echo "Waiting up to ${READY_TIMEOUT_SECONDS}s for ${API_URL} ..."
waited=0
until curl -fs -m 3 "${API_URL}" >/dev/null 2>&1; do
  if ! docker exec "${CONTAINER_NAME}" pgrep -f "vllm serve" >/dev/null 2>&1; then
    echo "ERROR: vllm serve process exited during startup. Last log lines:" >&2
    docker exec "${CONTAINER_NAME}" bash -c "tail -n 30 ${SERVE_LOG}" >&2 || true
    exit 1
  fi
  if (( waited >= READY_TIMEOUT_SECONDS )); then
    echo "ERROR: API did not become ready within ${READY_TIMEOUT_SECONDS}s. See: $0 logs" >&2
    exit 1
  fi
  sleep 5
  waited=$((waited + 5))
done
echo "API READY after ~${waited}s: ${API_URL}"

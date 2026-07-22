#!/usr/bin/env bash

# Start the nubia Ray worker container. The container retries until the ibera
# head is available, which permits the required worker -> head launch order.

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=cluster-common.sh
source "${SCRIPT_DIR}/cluster-common.sh"

load_project_env
require_command docker
require_command ip

ACTION="${1:-start}"
CONTAINER_NAME="${PP2_WORKER_CONTAINER:-pp2-ray-worker-nubia}"

case "${ACTION}" in
  stop)
    stop_container "${CONTAINER_NAME}"
    exit 0
    ;;
  status)
    show_container_status "${CONTAINER_NAME}"
    if docker ps --format '{{.Names}}' | grep -Fxq "${CONTAINER_NAME}"; then
      docker logs --tail 20 "${CONTAINER_NAME}"
    fi
    exit 0
    ;;
  logs)
    docker logs --follow "${CONTAINER_NAME}"
    exit 0
    ;;
  start)
    ;;
  *)
    echo "Usage: $0 [start|status|logs|stop]" >&2
    exit 2
    ;;
esac

if [[ -z "${HEAD_NODE_IP:-}" ]]; then
  echo "ERROR: export HEAD_NODE_IP=<ibera LAN IP> before starting nubia." >&2
  exit 1
fi

require_image
ensure_container_absent "${CONTAINER_NAME}"

WORKER_IP="$(worker_node_ip)"
NIC="${PP2_NIC:-$(route_interface "${HEAD_NODE_IP}")}"
if [[ -z "${NIC}" ]]; then
  echo "ERROR: could not determine the nubia NIC toward ${HEAD_NODE_IP}. Set PP2_NIC." >&2
  exit 1
fi

NCCL_IFNAME="${NCCL_SOCKET_IFNAME:-${NIC}}"
GLOO_IFNAME="${GLOO_SOCKET_IFNAME:-${NIC}}"
RAY_PORT_VALUE="${RAY_PORT:-6379}"
NODE_MANAGER_PORT="${RAY_NODE_MANAGER_PORT:-10002}"
OBJECT_MANAGER_PORT="${RAY_OBJECT_MANAGER_PORT:-10003}"
MIN_WORKER_PORT="${RAY_MIN_WORKER_PORT:-11000}"
MAX_WORKER_PORT="${RAY_MAX_WORKER_PORT:-11999}"
JOIN_RETRY_SECONDS="${RAY_JOIN_RETRY_SECONDS:-5}"
SHM_SIZE="${PP2_SHM_SIZE:-16g}"
HF_CACHE_DIR="${HF_CACHE_DIR:-${HF_HOME:-${HOME}/.cache/huggingface}}"
PARTITION_ENV=()
if [[ -n "${VLLM_PP_LAYER_PARTITION:-}" ]]; then
  PARTITION_ENV+=(--env "VLLM_PP_LAYER_PARTITION=${VLLM_PP_LAYER_PARTITION}")
fi

if [[ ! -d "${HF_CACHE_DIR}" ]]; then
  echo "ERROR: HF cache directory does not exist: ${HF_CACHE_DIR}" >&2
  exit 1
fi

echo "Starting nubia worker ${WORKER_IP} via ${NIC}; waiting for Ray head ${HEAD_NODE_IP}:${RAY_PORT_VALUE}."

docker run --detach \
  --name "${CONTAINER_NAME}" \
  --network host \
  --gpus all \
  --shm-size "${SHM_SIZE}" \
  --volume "${HF_CACHE_DIR}:/root/.cache/huggingface" \
  --env "HEAD_NODE_IP=${HEAD_NODE_IP}" \
  --env "WORKER_NODE_IP=${WORKER_IP}" \
  --env "RAY_PORT=${RAY_PORT_VALUE}" \
  --env "RAY_NODE_MANAGER_PORT=${NODE_MANAGER_PORT}" \
  --env "RAY_OBJECT_MANAGER_PORT=${OBJECT_MANAGER_PORT}" \
  --env "RAY_MIN_WORKER_PORT=${MIN_WORKER_PORT}" \
  --env "RAY_MAX_WORKER_PORT=${MAX_WORKER_PORT}" \
  --env "RAY_JOIN_RETRY_SECONDS=${JOIN_RETRY_SECONDS}" \
  --env "VLLM_HOST_IP=${WORKER_IP}" \
  --env "NCCL_SOCKET_IFNAME=${NCCL_IFNAME}" \
  --env "GLOO_SOCKET_IFNAME=${GLOO_IFNAME}" \
  --env "NCCL_IB_DISABLE=${NCCL_IB_DISABLE:-1}" \
  --env "HF_HUB_OFFLINE=${HF_HUB_OFFLINE:-1}" \
  "${PARTITION_ENV[@]}" \
  --entrypoint /bin/bash \
  "${PP2_IMAGE}" -lc '
    while true; do
      ray stop --force >/dev/null 2>&1 || true
      echo "Trying Ray head ${HEAD_NODE_IP}:${RAY_PORT}..."
      ray start \
        --address="${HEAD_NODE_IP}:${RAY_PORT}" \
        --node-ip-address="${WORKER_NODE_IP}" \
        --num-gpus=1 \
        --node-manager-port="${RAY_NODE_MANAGER_PORT}" \
        --object-manager-port="${RAY_OBJECT_MANAGER_PORT}" \
        --min-worker-port="${RAY_MIN_WORKER_PORT}" \
        --max-worker-port="${RAY_MAX_WORKER_PORT}" \
        --block && exit 0
      echo "Ray head is not ready; retrying in ${RAY_JOIN_RETRY_SECONDS}s."
      sleep "${RAY_JOIN_RETRY_SECONDS}"
    done
  ' >/dev/null

echo "Worker container started. Follow its join loop with: $0 logs"

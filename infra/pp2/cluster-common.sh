#!/usr/bin/env bash

# Shared helpers for the FR-34 PP=2 PoC launch scripts.

set -euo pipefail

PP2_SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PP2_REPO_ROOT="$(cd -- "${PP2_SCRIPT_DIR}/../.." && pwd)"
# The official v0.25.0 image does not bundle ray (multi-node extras were moved
# out of the base image); both hosts build this derived tag from README §1-3.
PP2_IMAGE="${PP2_IMAGE:-pp2-vllm:v0.25.0-ray}"

load_project_env() {
  local env_file="${ENV_FILE:-${PP2_REPO_ROOT}/.env}"
  if [[ ! -f "${env_file}" ]]; then
    echo "ERROR: .env not found: ${env_file}" >&2
    echo "Set ENV_FILE to the copied project .env path." >&2
    exit 1
  fi

  set -a
  # shellcheck disable=SC1090
  source "${env_file}"
  set +a

  if [[ -z "${Inference_sever:-}" ]]; then
    echo "ERROR: Inference_sever is not set in ${env_file}." >&2
    exit 1
  fi
}

worker_node_ip() {
  local value="${WORKER_NODE_IP:-${Inference_sever}}"
  value="${value#http://}"
  value="${value#https://}"
  value="${value%%/*}"
  value="${value%%:*}"
  if [[ -z "${value}" ]]; then
    echo "ERROR: Inference_sever did not contain a worker host/IP." >&2
    exit 1
  fi
  printf '%s\n' "${value}"
}

route_source_ip() {
  local peer_ip="$1"
  ip route get "${peer_ip}" | awk '{for (i = 1; i <= NF; i++) if ($i == "src") {print $(i + 1); exit}}'
}

route_interface() {
  local peer_ip="$1"
  ip route get "${peer_ip}" | awk '{for (i = 1; i <= NF; i++) if ($i == "dev") {print $(i + 1); exit}}'
}

require_command() {
  local command_name="$1"
  if ! command -v "${command_name}" >/dev/null 2>&1; then
    echo "ERROR: required command not found: ${command_name}" >&2
    exit 1
  fi
}

require_image() {
  if ! docker image inspect "${PP2_IMAGE}" >/dev/null 2>&1; then
    echo "ERROR: ${PP2_IMAGE} is not present locally." >&2
    echo "Build it with the docker build command in infra/pp2/README.md §1-3" >&2
    echo "(or pull/pin as described there for the base image)." >&2
    exit 1
  fi
}

ensure_container_absent() {
  local container_name="$1"
  if docker container inspect "${container_name}" >/dev/null 2>&1; then
    echo "ERROR: container ${container_name} already exists." >&2
    echo "Inspect it with '$0 status' or remove the PoC container with '$0 stop'." >&2
    exit 1
  fi
}

stop_container() {
  local container_name="$1"
  if docker container inspect "${container_name}" >/dev/null 2>&1; then
    docker rm --force "${container_name}" >/dev/null
    echo "Removed ephemeral container ${container_name}; the mounted HF cache was not removed."
  else
    echo "Container ${container_name} does not exist."
  fi
}

show_container_status() {
  local container_name="$1"
  if docker container inspect "${container_name}" >/dev/null 2>&1; then
    docker ps --all --filter "name=^/${container_name}$" \
      --format 'table {{.Names}}\t{{.Status}}\t{{.Image}}'
  else
    echo "Container ${container_name} does not exist."
  fi
}


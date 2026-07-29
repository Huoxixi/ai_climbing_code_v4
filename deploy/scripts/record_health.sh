#!/usr/bin/env bash
set -Eeuo pipefail

OPS_DIR="${OPS_DIR:-/var/lib/ai-climbing/ops}"
HEALTH_LOG="${OPS_DIR}/health.csv"
LOCK_FILE="/run/lock/ai-climbing-health.lock"

mkdir -p "${OPS_DIR}" "$(dirname "${LOCK_FILE}")"
touch "${HEALTH_LOG}"
exec 9>"${LOCK_FILE}"
flock -n 9 || exit 0

timestamp="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
if response="$(curl --fail --silent --show-error --max-time 10 http://127.0.0.1:8000/api/health)" &&
  grep -Eq '"status"[[:space:]]*:[[:space:]]*"success"' <<<"${response}"; then
  printf '%s,1\n' "${timestamp}" >> "${HEALTH_LOG}"
else
  printf '%s,0\n' "${timestamp}" >> "${HEALTH_LOG}"
  exit 1
fi

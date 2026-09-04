#!/usr/bin/env bash
set -Eeuo pipefail

ORIGIN_URL="${QUICK_TUNNEL_ORIGIN:-http://127.0.0.1:8080}"
STATE_DIR="${QUICK_TUNNEL_STATE_DIR:-/run/ai-climbing-tunnel}"
URL_FILE="${STATE_DIR}/url"

umask 027
install -d -m 0750 "${STATE_DIR}"
rm -f "${URL_FILE}"

if [[ "${ORIGIN_URL}" != "http://127.0.0.1:8080" ]]; then
  echo "Refusing to expose an unexpected origin: ${ORIGIN_URL}" >&2
  exit 1
fi
if ! command -v cloudflared >/dev/null 2>&1; then
  echo "cloudflared is not installed." >&2
  exit 1
fi

cloudflared tunnel \
  --no-autoupdate \
  --url "${ORIGIN_URL}" \
  --loglevel info 2>&1 |
while IFS= read -r line; do
  printf '%s\n' "${line}"
  if [[ "${line}" =~ https://[-a-z0-9]+\.trycloudflare\.com ]]; then
    printf '%s\n' "${BASH_REMATCH[0]}" > "${URL_FILE}.tmp"
    mv -f "${URL_FILE}.tmp" "${URL_FILE}"
  fi
done

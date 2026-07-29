#!/usr/bin/env bash
set -Eeuo pipefail

failed=0

require_command() {
  if command -v "$1" >/dev/null; then
    printf '[PASS] %s\n' "$1"
  else
    printf '[FAIL] missing command: %s\n' "$1"
    failed=1
  fi
}

if [[ ! -r /etc/os-release ]]; then
  echo "[FAIL] /etc/os-release is unavailable."
  exit 1
fi
. /etc/os-release
if [[ "${ID:-}" == "ubuntu" && "${VERSION_ID:-}" == "24.04" ]]; then
  echo "[PASS] Ubuntu 24.04 LTS"
else
  echo "[FAIL] Required OS is Ubuntu 24.04 LTS; found ${PRETTY_NAME:-unknown}."
  failed=1
fi

if [[ "$(ps -p 1 -o comm=)" == "systemd" ]]; then
  echo "[PASS] systemd is PID 1"
else
  echo "[FAIL] systemd is not PID 1"
  failed=1
fi

for command_name in git rsync nginx python3.12 node npm tailscale rclone curl tar sha256sum flock; do
  require_command "${command_name}"
done

if command -v nginx >/dev/null; then
  public_nginx_listeners="$(
    nginx -T 2>&1 |
      sed -nE 's/^[[:space:]]*(listen[[:space:]]+[^;]+;).*$/\1/p' |
      grep -Ev '^listen[[:space:]]+127\.0\.0\.1:8080([[:space:]]|;)' || true
  )"
  if [[ -n "${public_nginx_listeners}" ]]; then
    echo "[FAIL] Nginx has listeners other than 127.0.0.1:8080:"
    printf '%s\n' "${public_nginx_listeners}"
    failed=1
  else
    echo "[PASS] Nginx is limited to 127.0.0.1:8080"
  fi
fi

echo
uname -a
free -h
df -h /
timedatectl status
systemctl --no-pager --type=service --state=running

exit "${failed}"

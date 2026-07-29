#!/usr/bin/env bash
set -Eeuo pipefail

RELEASE_ROOT="/opt/ai-climbing/releases"
CURRENT_LINK="/opt/ai-climbing/current"
SERVICE_NAME="${SERVICE_NAME:-ai-climbing.service}"
RELEASE_NAME="${1:-}"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Rollback must run as root." >&2
  exit 1
fi
if [[ ! "${RELEASE_NAME}" =~ ^[A-Za-z0-9._-]+$ ]]; then
  echo "Usage: rollback_release.sh <existing-release-name>" >&2
  exit 1
fi

target="${RELEASE_ROOT}/${RELEASE_NAME}"
if [[ ! -d "${target}" || ! -x "${target}/backend/.venv/bin/python" ]]; then
  echo "Release is missing or incomplete: ${target}" >&2
  exit 1
fi

previous="$(readlink -f "${CURRENT_LINK}" || true)"
temporary_link="/opt/ai-climbing/.current.rollback.$$"
ln -s "${target}" "${temporary_link}"
mv -Tf "${temporary_link}" "${CURRENT_LINK}"

release_sha="$(cat "${target}/RELEASE_SHA")"
printf 'RELEASE_SHA=%s\n' "${release_sha}" > /etc/ai-climbing/release.env
chmod 0644 /etc/ai-climbing/release.env

if systemctl restart "${SERVICE_NAME}" &&
  curl --fail --silent --show-error --max-time 15 http://127.0.0.1:8000/api/health |
    grep -q "${release_sha:0:12}"; then
  nginx -t
  systemctl reload nginx
  echo "Rolled back code to ${RELEASE_NAME}; runtime data was not changed."
  exit 0
fi

if [[ -n "${previous}" && -d "${previous}" ]]; then
  ln -s "${previous}" "${temporary_link}"
  mv -Tf "${temporary_link}" "${CURRENT_LINK}"
  printf 'RELEASE_SHA=%s\n' "$(cat "${previous}/RELEASE_SHA")" > /etc/ai-climbing/release.env
  systemctl restart "${SERVICE_NAME}" || true
fi
echo "Rollback target failed health verification; previous code was restored." >&2
exit 1

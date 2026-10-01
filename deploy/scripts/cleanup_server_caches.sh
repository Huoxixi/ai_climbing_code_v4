#!/usr/bin/env bash
# Run audit first. This never deletes releases, backups, models, data or configuration.
set -Eeuo pipefail
mode="${1:-audit}"
[[ "${EUID}" -eq 0 ]] || { echo 'Run in the production root terminal.' >&2; exit 77; }
[[ "${mode}" == audit || "${mode}" == clean ]] || { echo 'Usage: cleanup_server_caches.sh [audit|clean]' >&2; exit 64; }
readonly release_root=/opt/ai-climbing/releases
readonly current_link=/opt/ai-climbing/current
readonly caches=(/root/.cache/pip /root/.npm/_cacache /var/cache/apt/archives)
current="$(readlink -f -- "${current_link}")"
case "${current}" in "${release_root}"/*) ;; *) echo 'Unexpected current release path; stopped.' >&2; exit 1 ;; esac
[[ -d "${current}" && -f "${current}/RELEASE_SHA" ]] || { echo 'Incomplete current release; stopped.' >&2; exit 1; }
before_sha="$(cat "${current}/RELEASE_SHA")"
[[ "${before_sha}" =~ ^[0-9a-f]{40}$ ]] || { echo 'Invalid release identifier; stopped.' >&2; exit 1; }
echo "MODE=${mode}"
echo "CURRENT=${current}"
echo "RELEASE_SHA=${before_sha}"
echo 'SPACE_BEFORE'
df -h /
echo 'RELEASE_SIZES (all releases are preserved)'
du -xhd1 "${release_root}" 2>/dev/null | sort -h
echo 'CACHE_SIZES (only these exact paths are eligible)'
for cache in "${caches[@]}"; do
  if [[ -e "${cache}" ]]; then
    [[ ! -L "${cache}" && "$(realpath -e -- "${cache}")" == "${cache}" ]] || { echo "Cache is redirected; stopped: ${cache}" >&2; exit 1; }
    du -xsh "${cache}"
  fi
done
echo 'OTHER_SIZE_TOTALS (read-only; no content is printed)'
for directory in /opt/ai-climbing/resource-tests /var/backups/ai-climbing /var/lib/ai-climbing /var/log; do
  [[ ! -d "${directory}" ]] || du -xsh "${directory}"
done
if [[ "${mode}" == audit ]]; then
  echo 'AUDIT_ONLY=1; nothing was deleted. Review the totals, then run with clean to remove download caches only.'
  exit 0
fi
if pgrep -f '[d]eploy_release.sh|[p]ip (install|wheel|download)|[n]pm (ci|install)|[a]pt(-get)? (install|upgrade|update)' >/dev/null; then
  echo 'A deployment or package installation is running; stopped.' >&2
  exit 1
fi
systemctl is-active --quiet ai-climbing.service || { echo 'Backend is not active; stopped.' >&2; exit 1; }
curl -fsS --max-time 5 http://127.0.0.1:8000/api/health >/dev/null
[[ "$(readlink -f -- "${current_link}")" == "${current}" ]] || { echo 'Release changed during audit; stopped.' >&2; exit 1; }
install -d -m 0700 /run/ai-climbing-cleanup
record="/run/ai-climbing-cleanup/$(date -u +%Y%m%dT%H%M%SZ).log"
printf 'CURRENT=%s\nRELEASE_SHA=%s\n' "${current}" "${before_sha}" > "${record}"
df -B1 / >> "${record}"
for cache in "${caches[@]}"; do
  [[ -d "${cache}" ]] || continue
  [[ ! -L "${cache}" && "$(realpath -e -- "${cache}")" == "${cache}" ]] || exit 1
  printf 'CACHE=%s\n' "${cache}" >> "${record}"
  if [[ "${cache}" == /var/cache/apt/archives ]]; then
    # Preserve apt locks and state; delete downloaded package archives only.
    find "${cache}" -xdev -maxdepth 1 -type f -name '*.deb' -print -delete >> "${record}"
  else
    # Cached distributions and content-addressed npm downloads are rebuildable.
    find "${cache}" -xdev -mindepth 1 -maxdepth 1 -exec rm -rf -- {} +
  fi
done
[[ "$(readlink -f -- "${current_link}")" == "${current}" && "$(cat "${current}/RELEASE_SHA")" == "${before_sha}" ]] || { echo 'Unexpected release change; investigate.' >&2; exit 1; }
systemctl is-active ai-climbing nginx
curl -fsS --max-time 5 http://127.0.0.1:8000/api/health
echo
echo 'SPACE_AFTER'
df -h /
df -B1 / >> "${record}"
echo "AUDIT_RECORD=${record}"
available="$(df -B1 --output=avail / | tail -n 1 | tr -d ' ')"
if (( available < 8 * 1024 * 1024 * 1024 )); then
  echo 'REVIEW_REQUIRED=less than 8 GiB available. Do not deploy yet; review historical release sizes and retention separately.'
else
  echo 'CACHE_CLEANUP=complete. Space is available; GitHub gates and normal deployment checks are still required.'
fi

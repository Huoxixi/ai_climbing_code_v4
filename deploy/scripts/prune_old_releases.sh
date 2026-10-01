#!/usr/bin/env bash
# Explicitly authorized retention policy: newest three complete releases.
# The current release must be among them; no business data or config is deleted.
set -Eeuo pipefail
mode="${1:-audit}"
[[ "${EUID}" -eq 0 ]] || { echo 'Run in the production root terminal.' >&2; exit 77; }
[[ "${mode}" == audit || "${mode}" == prune ]] || { echo 'Usage: prune_old_releases.sh [audit|prune]' >&2; exit 64; }
readonly releases=/opt/ai-climbing/releases
readonly current_link=/opt/ai-climbing/current
[[ ! -L "${releases}" && "$(realpath -e "${releases}")" == "${releases}" ]] || exit 1
current="$(readlink -f -- "${current_link}")"
case "${current}" in "${releases}"/*) ;; *) echo 'Unexpected current release; stopped.' >&2; exit 1 ;; esac
current_tag="$(basename "${current}")"
[[ -f "${current}/RELEASE_SHA" ]] || exit 1
current_sha="$(cat "${current}/RELEASE_SHA")"
mapfile -t tags < <(find "${releases}" -mindepth 1 -maxdepth 1 -type d -printf '%f\n' | grep -E '^pilot-v[0-9]{4}\.[0-9]{2}\.[0-9]{2}-rc[0-9]+$' | sort -Vr)
(( ${#tags[@]} >= 3 )) || { echo 'Fewer than three releases; nothing to remove.'; exit 0; }
keep=("${tags[@]:0:3}")
printf 'KEEP=%s\n' "${keep[*]}"
retained=false
for tag in "${keep[@]}"; do
  [[ -f "${releases}/${tag}/RELEASE_SHA" && -x "${releases}/${tag}/backend/.venv/bin/python" && -d "${releases}/${tag}/frontend/dist" ]] || { echo "Retained release is incomplete: ${tag}; stopped." >&2; exit 1; }
  [[ "${tag}" != "${current_tag}" ]] || retained=true
done
[[ "${retained}" == true ]] || { echo 'Current is outside newest three; stopped.' >&2; exit 1; }
df -h /
for tag in "${tags[@]:3}"; do
  release="${releases}/${tag}"
  [[ ! -L "${release}" && "$(realpath -e "${release}")" == "${release}" && -f "${release}/RELEASE_SHA" ]] || { echo "Invalid release: ${tag}; stopped." >&2; exit 1; }
  [[ -L "${release}/backend/data" && "$(readlink -f "${release}/backend/data")" == /var/lib/ai-climbing/data ]] || { echo "Data boundary cannot be verified: ${tag}; stopped." >&2; exit 1; }
  if find "${release}" -xdev \( -type d \( -name .git -o -name .local -o -name .private \) -o -type f \( -name .env -o -name '*.sqlite*' -o -name '*.db' -o -name '*.pem' -o -name '*.key' \) \) -print -quit | grep -q .; then
    echo "Protected material inside ${tag}; stopped." >&2; exit 1
  fi
  printf 'REMOVE_CANDIDATE=%s SHA=%s\n' "${tag}" "$(cat "${release}/RELEASE_SHA")"
  du -xsh "${release}"
done
[[ "${mode}" == prune ]] || { echo 'AUDIT_ONLY=1; nothing changed.'; exit 0; }
if pgrep -f '[d]eploy_release.sh|[r]ollback_release.sh' >/dev/null; then
  echo 'Deployment or rollback is running; stopped.' >&2; exit 1
fi
exec 9>/run/ai-climbing-release-prune.lock
flock -n 9 || { echo 'Another retention cleanup is running; stopped.' >&2; exit 1; }
systemctl is-active --quiet ai-climbing.service || exit 1
curl -fsS --max-time 5 http://127.0.0.1:8000/api/health >/dev/null
install -d -m 0700 /run/ai-climbing-cleanup
record="/run/ai-climbing-cleanup/releases-$(date -u +%Y%m%dT%H%M%SZ).log"
printf 'CURRENT=%s\nRELEASE_SHA=%s\nKEEP=%s\n' "${current}" "${current_sha}" "${keep[*]}" > "${record}"
for tag in "${tags[@]:3}"; do
  release="${releases}/${tag}"
  [[ "$(readlink -f "${current_link}")" == "${current}" && "$(cat "${current}/RELEASE_SHA")" == "${current_sha}" ]] || { echo 'Current release changed; stopped.' >&2; exit 1; }
  [[ ! -L "${release}" && "$(realpath -e "${release}")" == "${releases}/${tag}" && "${release}" != "${current}" ]] || exit 1
  [[ -L "${release}/backend/data" && "$(readlink -f "${release}/backend/data")" == /var/lib/ai-climbing/data ]] || exit 1
  printf 'REMOVED=%s SHA=%s\n' "${tag}" "$(cat "${release}/RELEASE_SHA")" | tee -a "${record}"
  # GNU rm removes the backend/data link itself and never traverses its target.
  rm -rf --one-file-system -- "${release}"
done
[[ "$(readlink -f "${current_link}")" == "${current}" && "$(cat "${current}/RELEASE_SHA")" == "${current_sha}" ]] || exit 1
echo 'RELEASES_AFTER'
find "${releases}" -mindepth 1 -maxdepth 1 -type d -printf '%f\n' | sort -V
systemctl is-active ai-climbing nginx
curl -fsS --max-time 5 http://127.0.0.1:8000/api/health
echo
df -h /
echo "AUDIT_RECORD=${record}"

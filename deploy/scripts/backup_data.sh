#!/usr/bin/env bash
set -Eeuo pipefail

BACKUP_ENV_FILE="${BACKUP_ENV_FILE:-/etc/ai-climbing/backup.env}"
if [[ -r "${BACKUP_ENV_FILE}" ]]; then
  # The production file is root-owned and mode 0600.
  set -a
  # shellcheck disable=SC1090
  source "${BACKUP_ENV_FILE}"
  set +a
fi

DATA_DIR="${DATA_DIR:-/var/lib/ai-climbing/data}"
BACKUP_ROOT="${BACKUP_ROOT:-/var/backups/ai-climbing}"
SERVICE_NAME="${SERVICE_NAME:-ai-climbing.service}"
RCLONE_REMOTE="${RCLONE_REMOTE:-}"
RCLONE_CONFIG="${RCLONE_CONFIG:-/etc/ai-climbing/rclone.conf}"
BACKUP_KIND="${1:-daily}"
STATUS_DIR="/var/lib/ai-climbing/ops"
LOCK_FILE="/run/lock/ai-climbing-backup.lock"

if [[ "${EUID}" -ne 0 ]]; then
  echo "This backup must run as root." >&2
  exit 1
fi
if [[ ! "${BACKUP_KIND}" =~ ^(daily|pre-deploy|manual)$ ]]; then
  echo "Backup kind must be daily, pre-deploy, or manual." >&2
  exit 1
fi
if [[ "${BACKUP_KIND}" != "manual" && -z "${RCLONE_REMOTE}" ]]; then
  echo "RCLONE_REMOTE is required for daily and pre-deploy backups." >&2
  exit 1
fi

resolved_data="$(realpath -m "${DATA_DIR}")"
if [[ "${resolved_data}" != /var/lib/ai-climbing/* || ! -d "${resolved_data}" ]]; then
  echo "Refusing to back up an unexpected data directory: ${resolved_data}" >&2
  exit 1
fi

mkdir -p "${BACKUP_ROOT}/${BACKUP_KIND}" "${STATUS_DIR}" "$(dirname "${LOCK_FILE}")"
exec 9>"${LOCK_FILE}"
flock -n 9 || {
  echo "Another backup is already running." >&2
  exit 1
}

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
archive_name="ai-climbing-${BACKUP_KIND}-${timestamp}.tar.gz"
archive_path="${BACKUP_ROOT}/${BACKUP_KIND}/${archive_name}"
checksum_path="${archive_path}.sha256"
temporary_archive="${archive_path}.partial"
service_was_active=false
service_stopped=false
completed=false

write_status() {
  local result="$1"
  local status_tmp="${STATUS_DIR}/last-backup.env.tmp"
  {
    printf 'RESULT=%s\n' "${result}"
    printf 'KIND=%s\n' "${BACKUP_KIND}"
    printf 'ARCHIVE=%s\n' "${archive_name}"
    printf 'FINISHED_AT=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    printf 'REMOTE_VERIFIED=%s\n' "$([[ -n "${RCLONE_REMOTE}" && "${result}" == "success" ]] && echo true || echo false)"
  } > "${status_tmp}"
  chmod 0640 "${status_tmp}"
  chown ai-climbing:ai-climbing "${status_tmp}"
  mv -f "${status_tmp}" "${STATUS_DIR}/last-backup.env"
}

finish() {
  local exit_code=$?
  rm -f "${temporary_archive}"
  if [[ "${service_stopped}" == true && "${service_was_active}" == true ]]; then
    systemctl start "${SERVICE_NAME}" || true
  fi
  if [[ "${completed}" != true ]]; then
    write_status failed || true
  fi
  exit "${exit_code}"
}
trap finish EXIT

if systemctl is-active --quiet "${SERVICE_NAME}"; then
  service_was_active=true
  systemctl stop "${SERVICE_NAME}"
  service_stopped=true
fi

data_parent="$(dirname "${resolved_data}")"
data_name="$(basename "${resolved_data}")"
tar -C "${data_parent}" -czf "${temporary_archive}" "${data_name}"
mv -f "${temporary_archive}" "${archive_path}"
(
  cd "$(dirname "${archive_path}")"
  sha256sum "${archive_name}" > "$(basename "${checksum_path}")"
)

if [[ "${service_was_active}" == true ]]; then
  systemctl start "${SERVICE_NAME}"
  service_stopped=false
  curl --fail --silent --show-error --max-time 15 http://127.0.0.1:8000/api/health >/dev/null
fi

if [[ -n "${RCLONE_REMOTE}" ]]; then
  command -v rclone >/dev/null
  remote_prefix="${RCLONE_REMOTE%/}/${BACKUP_KIND}/$(date -u +%Y/%m)"
  rclone --config "${RCLONE_CONFIG}" copyto "${archive_path}" "${remote_prefix}/${archive_name}"
  rclone --config "${RCLONE_CONFIG}" copyto "${checksum_path}" "${remote_prefix}/${archive_name}.sha256"

  verify_dir="$(mktemp -d "${BACKUP_ROOT}/verify.XXXXXX")"
  rclone --config "${RCLONE_CONFIG}" copyto "${remote_prefix}/${archive_name}" "${verify_dir}/${archive_name}"
  rclone --config "${RCLONE_CONFIG}" copyto "${remote_prefix}/${archive_name}.sha256" "${verify_dir}/${archive_name}.sha256"
  (
    cd "${verify_dir}"
    sha256sum -c "${archive_name}.sha256"
  )
  rm -rf -- "${verify_dir}"

  if [[ "${BACKUP_KIND}" == "daily" && "$(TZ=Asia/Shanghai date +%d)" == "01" ]]; then
    monthly_prefix="${RCLONE_REMOTE%/}/monthly/$(TZ=Asia/Shanghai date +%Y/%m)"
    rclone --config "${RCLONE_CONFIG}" copyto "${archive_path}" "${monthly_prefix}/${archive_name}"
    rclone --config "${RCLONE_CONFIG}" copyto "${checksum_path}" "${monthly_prefix}/${archive_name}.sha256"
  fi
fi

completed=true
write_status success
echo "Backup completed and verified: ${archive_path}"

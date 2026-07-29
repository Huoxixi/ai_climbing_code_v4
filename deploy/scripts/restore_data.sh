#!/usr/bin/env bash
set -Eeuo pipefail

DATA_DIR="${DATA_DIR:-/var/lib/ai-climbing/data}"
SERVICE_NAME="${SERVICE_NAME:-ai-climbing.service}"
ARCHIVE_PATH="${1:-}"

if [[ "${EUID}" -ne 0 ]]; then
  echo "This restore must run as root." >&2
  exit 1
fi
if [[ -z "${ARCHIVE_PATH}" || ! -f "${ARCHIVE_PATH}" || ! -f "${ARCHIVE_PATH}.sha256" ]]; then
  echo "Usage: restore_data.sh /absolute/path/backup.tar.gz" >&2
  echo "The matching .sha256 file must be beside the archive." >&2
  exit 1
fi

resolved_data="$(realpath -m "${DATA_DIR}")"
if [[ "${resolved_data}" != /var/lib/ai-climbing/* ]]; then
  echo "Refusing to restore an unexpected target: ${resolved_data}" >&2
  exit 1
fi

cat <<EOF
【高风险操作确认】
目标对象：${resolved_data}
将执行的 SQL 或操作：停止服务，校验并恢复备份 ${ARCHIVE_PATH}
影响范围：当前全部本地岩板、岩点、图片、活动和操作记录
是否会造成数据丢失：备份时间之后的操作不会出现在恢复结果中
是否可以回滚：可以；当前数据会移入隔离目录，不立即删除
建议备份方式：恢复前保留当前目录，并确认对象存储中的备份校验通过
请用户回复“确认执行”后再继续。
EOF

read -r confirmation
if [[ "${confirmation}" != "确认执行" ]]; then
  echo "未收到准确确认，恢复已取消。"
  exit 2
fi

(
  cd "$(dirname "${ARCHIVE_PATH}")"
  sha256sum -c "$(basename "${ARCHIVE_PATH}.sha256")"
)

restore_parent="$(dirname "${resolved_data}")"
restore_work="$(mktemp -d "${restore_parent}/restore-work.XXXXXX")"
timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
quarantine="${restore_parent}/data.pre-restore.${timestamp}"
failed_restore="${restore_parent}/data.failed-restore.${timestamp}"
service_stopped=false
current_moved=false
restore_succeeded=false

cleanup() {
  if [[ "${restore_succeeded}" != true && "${current_moved}" == true ]]; then
    systemctl stop "${SERVICE_NAME}" || true
    if [[ -d "${resolved_data}" && ! -e "${failed_restore}" ]]; then
      mv -- "${resolved_data}" "${failed_restore}" || true
    fi
    if [[ -d "${quarantine}" && ! -e "${resolved_data}" ]]; then
      mv -- "${quarantine}" "${resolved_data}" || true
    fi
  fi
  if [[ "${service_stopped}" == true ]]; then
    systemctl start "${SERVICE_NAME}" || true
  fi
  rm -rf -- "${restore_work}"
}
trap cleanup EXIT

tar -xzf "${ARCHIVE_PATH}" -C "${restore_work}"
if [[ ! -d "${restore_work}/data" || ! -f "${restore_work}/data/saved_boards.json" ]]; then
  echo "Archive does not contain the expected data directory." >&2
  exit 1
fi

systemctl stop "${SERVICE_NAME}"
service_stopped=true
mv -- "${resolved_data}" "${quarantine}"
current_moved=true
mv -- "${restore_work}/data" "${resolved_data}"
chown -R ai-climbing:ai-climbing "${resolved_data}"
chmod -R u+rwX,g+rX,o-rwx "${resolved_data}"

if systemctl start "${SERVICE_NAME}" &&
  curl --fail --silent --show-error --max-time 15 http://127.0.0.1:8000/api/health >/dev/null; then
  service_stopped=false
  restore_succeeded=true
  echo "Restore completed. Previous data remains recoverable at: ${quarantine}"
  exit 0
fi

systemctl stop "${SERVICE_NAME}" || true
mv -- "${resolved_data}" "${failed_restore}"
mv -- "${quarantine}" "${resolved_data}"
systemctl start "${SERVICE_NAME}" || true
service_stopped=false
current_moved=false
echo "Restored data failed health verification; the previous data was put back." >&2
echo "Failed restore retained at: ${failed_restore}" >&2
exit 1

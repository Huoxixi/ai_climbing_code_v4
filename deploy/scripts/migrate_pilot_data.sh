#!/usr/bin/env bash
set -Eeuo pipefail

SOURCE_DATA="${1:-}"
TARGET_DATA="/var/lib/ai-climbing/data"
MIGRATION_ROOT="/var/lib/ai-climbing/migrations"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Initial data migration must run as root." >&2
  exit 1
fi
if [[ -z "${SOURCE_DATA}" || ! -d "${SOURCE_DATA}" ]]; then
  echo "Usage: migrate_pilot_data.sh /absolute/path/to/approved/backend/data" >&2
  exit 1
fi
if find "${TARGET_DATA}" -mindepth 1 -print -quit 2>/dev/null | grep -q .; then
  echo "Target data directory is not empty. Refusing to overwrite it." >&2
  exit 1
fi

resolved_source="$(realpath "${SOURCE_DATA}")"
case "${resolved_source}" in
  /root/ai_climbing_code/backend/data|/root/ai_climbing_code_review/*/backend/data)
    ;;
  *)
    echo "Source must be the audited project data directory or an audited review copy." >&2
    exit 1
    ;;
esac

for required_file in saved_boards.json holds_mapping.json holds_vectors.json standard_board_review_queue.json; do
  [[ -f "${resolved_source}/${required_file}" ]] || {
    echo "Approved source is missing ${required_file}." >&2
    exit 1
  }
done

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
staging="$(mktemp -d /var/lib/ai-climbing/data-migration.XXXXXX)"
record_dir="${MIGRATION_ROOT}/${timestamp}"
trap 'rm -rf -- "${staging}"' EXIT

rsync -a "${resolved_source}/" "${staging}/"
mkdir -p "${record_dir}"
(
  cd "${staging}"
  find . -type f -print0 | sort -z | xargs -0 sha256sum > "${record_dir}/manifest.sha256"
)
{
  printf 'SOURCE=%s\n' "${resolved_source}"
  printf 'MIGRATED_AT=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  printf 'FILE_COUNT=%s\n' "$(find "${staging}" -type f | wc -l)"
  printf 'TOTAL_BYTES=%s\n' "$(du -sb "${staging}" | awk '{print $1}')"
} > "${record_dir}/migration.env"

rmdir "${TARGET_DATA}"
mv "${staging}" "${TARGET_DATA}"
trap - EXIT
chown -R ai-climbing:ai-climbing "${TARGET_DATA}"
chmod -R u+rwX,g+rX,o-rwx "${TARGET_DATA}"
chmod -R o-rwx "${record_dir}"
echo "Approved pilot data migrated. Audit record: ${record_dir}"

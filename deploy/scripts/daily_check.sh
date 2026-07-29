#!/usr/bin/env bash
set -Eeuo pipefail

STATUS_FILE="/var/lib/ai-climbing/ops/last-backup.env"
HEALTH_LOG="/var/lib/ai-climbing/ops/health.csv"
failed=0

check() {
  local label="$1"
  shift
  if "$@"; then
    printf '[PASS] %s\n' "${label}"
  else
    printf '[FAIL] %s\n' "${label}"
    failed=1
  fi
}

health_ok() {
  curl --fail --silent --max-time 10 http://127.0.0.1:8000/api/health |
    grep -Eq '"status"[[:space:]]*:[[:space:]]*"success"'
}

backup_recent() {
  [[ -f "${STATUS_FILE}" ]] || return 1
  grep -q '^RESULT=success$' "${STATUS_FILE}" || return 1
  local age_seconds
  age_seconds="$(( $(date +%s) - $(stat -c %Y "${STATUS_FILE}") ))"
  (( age_seconds < 108000 ))
}

disk_below_threshold() {
  local used
  used="$(df -P /var/lib/ai-climbing | awk 'NR==2 {gsub("%","",$5); print $5}')"
  (( used < 80 ))
}

health_availability() {
  [[ -s "${HEALTH_LOG}" ]] || return 1
  awk -F, '
    { total += 1; ok += $2 }
    END { exit !(total > 0 && (ok / total) >= 0.98) }
  ' "${HEALTH_LOG}"
}

check "后端服务正在运行" systemctl is-active --quiet ai-climbing.service
check "本地健康接口正常" health_ok
check "最近30小时存在成功备份" backup_recent
check "磁盘使用率低于80%" disk_below_threshold
check "Tailscale在线" tailscale status
check "累计健康记录可用率不低于98%" health_availability

echo "人工补充检查：对象存储控制台版本/保留策略、AI余额、参与人员名单、未解决问题。"
exit "${failed}"

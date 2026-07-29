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

teacher_gateway_ok() {
  local status
  if [[ -e /etc/ai-climbing/public-https-enabled ]]; then
    status="$(
      curl --insecure --silent --show-error \
        --output /dev/null \
        --write-out '%{http_code}' \
        --resolve climb.panyandingxian.cn:443:127.0.0.1 \
        https://climb.panyandingxian.cn/
    )"
  else
    ss -lnt |
      grep -Eq '[[:space:]]127[.]0[.]0[.]1:8443[[:space:]]' ||
      return 1
    status="$(
      curl --insecure --silent --show-error \
        --output /dev/null \
        --write-out '%{http_code}' \
        --header 'Host: climb.panyandingxian.cn' \
        https://127.0.0.1:8443/
    )"
  fi
  [[ "${status}" == "401" ]]
}

teacher_certificate_ok() {
  if [[ ! -e /etc/ai-climbing/public-https-enabled ]]; then
    return 0
  fi
  openssl x509 \
    -checkend 1209600 \
    -noout \
    -in /etc/letsencrypt/live/climb.panyandingxian.cn/fullchain.pem
}

check "后端服务正在运行" systemctl is-active --quiet ai-climbing.service
check "本地健康接口正常" health_ok
check "最近30小时存在成功备份" backup_recent
check "磁盘使用率低于80%" disk_below_threshold
check "SSH隧道策略配置有效" sshd -t
check "操作入口仅监听本机8080端口" bash -c \
  "ss -lnt | grep -Eq '[[:space:]]127[.]0[.]0[.]1:8080[[:space:]]'"
check "只读入口仅监听本机8081端口" bash -c \
  "ss -lnt | grep -Eq '[[:space:]]127[.]0[.]0[.]1:8081[[:space:]]'"
check "累计健康记录可用率不低于98%" health_availability
check "教师HTTPS入口要求身份认证" teacher_gateway_ok
check "教师HTTPS证书至少还有14天有效期" teacher_certificate_ok

echo "人工补充检查：公网网页端口、安全组、对象存储版本/保留策略、AI余额、参与人员名单、未解决问题。"
exit "${failed}"

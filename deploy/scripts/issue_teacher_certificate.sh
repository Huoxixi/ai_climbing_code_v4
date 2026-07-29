#!/usr/bin/env bash
set -Eeuo pipefail

DOMAIN="climb.panyandingxian.cn"
PUBLIC_IP="106.14.216.81"
PROJECT_ROOT="${PROJECT_ROOT:-/root/ai_climbing_code}"
ICP_FILE="/etc/ai-climbing/icp-number"
NGINX_AVAILABLE="/etc/nginx/sites-available/ai-climbing-teacher-gateway.conf"
NGINX_ENABLED="/etc/nginx/sites-enabled/ai-climbing-teacher-gateway.conf"
ACME_ROOT="/var/www/ai-climbing-certbot"
restore_internal=true

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run this script as root." >&2
  exit 1
fi
if [[ ! -s "${ICP_FILE}" ]]; then
  echo "Missing ${ICP_FILE}; public activation requires an approved ICP number." >&2
  exit 1
fi
if ! getent ahostsv4 "${DOMAIN}" |
  awk '{print $1}' |
  grep -Fxq "${PUBLIC_IP}"; then
  echo "${DOMAIN} does not resolve to ${PUBLIC_IP}." >&2
  exit 1
fi

restore_gateway() {
  if [[ "${restore_internal}" == true ]]; then
    PROJECT_ROOT="${PROJECT_ROOT}" \
      bash "${PROJECT_ROOT}/deploy/scripts/provision_teacher_gateway.sh" internal ||
      true
  fi
}
trap restore_gateway EXIT

if ! command -v certbot >/dev/null; then
  apt-get update
  DEBIAN_FRONTEND=noninteractive apt-get install -y certbot
fi

mkdir -p "${ACME_ROOT}"
install -o root -g root -m 0644 \
  "${PROJECT_ROOT}/deploy/nginx/ai_climbing_teacher_acme.conf" \
  "${NGINX_AVAILABLE}"
ln -sfn "${NGINX_AVAILABLE}" "${NGINX_ENABLED}"
nginx -t
systemctl reload nginx

certbot certonly \
  --webroot \
  --webroot-path "${ACME_ROOT}" \
  --domain "${DOMAIN}" \
  --non-interactive \
  --agree-tos \
  --register-unsafely-without-email \
  --keep-until-expiring

PROJECT_ROOT="${PROJECT_ROOT}" \
  bash "${PROJECT_ROOT}/deploy/scripts/provision_teacher_gateway.sh" public
restore_internal=false

certbot certificates --domain "${DOMAIN}"
echo "Certificate issued and the public teacher gateway is active."

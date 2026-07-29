#!/usr/bin/env bash
set -Eeuo pipefail

MODE="${1:-internal}"
DOMAIN="climb.panyandingxian.cn"
PROJECT_ROOT="${PROJECT_ROOT:-/root/ai_climbing_code}"
NGINX_AVAILABLE="/etc/nginx/sites-available/ai-climbing-teacher-gateway.conf"
NGINX_ENABLED="/etc/nginx/sites-enabled/ai-climbing-teacher-gateway.conf"
LIMITS_TARGET="/etc/nginx/conf.d/ai-climbing-teacher-limits.conf"
TLS_DIR="/etc/ai-climbing/tls"
PUBLIC_HTTPS_FLAG="/etc/ai-climbing/public-https-enabled"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run this script as root." >&2
  exit 1
fi

case "${MODE}" in
  internal)
    SOURCE_CONFIG="${PROJECT_ROOT}/deploy/nginx/ai_climbing_teacher_internal.conf"
    mkdir -p "${TLS_DIR}"
    chmod 700 "${TLS_DIR}"
    if [[ ! -s "${TLS_DIR}/teacher-internal.crt" ||
          ! -s "${TLS_DIR}/teacher-internal.key" ]]; then
      openssl req \
        -x509 \
        -nodes \
        -newkey rsa:2048 \
        -days 30 \
        -subj "/CN=${DOMAIN}" \
        -addext "subjectAltName=DNS:${DOMAIN}" \
        -keyout "${TLS_DIR}/teacher-internal.key" \
        -out "${TLS_DIR}/teacher-internal.crt"
      chmod 600 "${TLS_DIR}/teacher-internal.key"
      chmod 644 "${TLS_DIR}/teacher-internal.crt"
    fi
    ;;
  public)
    SOURCE_CONFIG="${PROJECT_ROOT}/deploy/nginx/ai_climbing_teacher_public.conf"
    CERT_DIR="/etc/letsencrypt/live/${DOMAIN}"
    if [[ ! -s "${CERT_DIR}/fullchain.pem" ||
          ! -s "${CERT_DIR}/privkey.pem" ]]; then
      echo "A valid Let's Encrypt certificate for ${DOMAIN} is required." >&2
      exit 1
    fi
    mkdir -p /var/www/ai-climbing-certbot
    ;;
  *)
    echo "Usage: $0 [internal|public]" >&2
    exit 2
    ;;
esac

if [[ ! -r /etc/nginx/ai-climbing-teacher-users.htpasswd ]]; then
  echo "Teacher accounts have not been created." >&2
  exit 1
fi
if [[ ! -r "${SOURCE_CONFIG}" ]]; then
  echo "Missing Nginx source config: ${SOURCE_CONFIG}" >&2
  exit 1
fi

install -o root -g root -m 0644 \
  "${PROJECT_ROOT}/deploy/nginx/ai_climbing_teacher_limits.conf" \
  "${LIMITS_TARGET}"

previous_config=""
if [[ -e "${NGINX_AVAILABLE}" ]]; then
  previous_config="$(mktemp)"
  cp --preserve=mode,ownership,timestamps "${NGINX_AVAILABLE}" "${previous_config}"
fi
install -o root -g root -m 0644 "${SOURCE_CONFIG}" "${NGINX_AVAILABLE}"
ln -sfn "${NGINX_AVAILABLE}" "${NGINX_ENABLED}"

restore_previous_config() {
  if [[ -n "${previous_config}" ]]; then
    cp --preserve=mode,ownership,timestamps "${previous_config}" "${NGINX_AVAILABLE}"
    ln -sfn "${NGINX_AVAILABLE}" "${NGINX_ENABLED}"
  else
    rm -f "${NGINX_ENABLED}" "${NGINX_AVAILABLE}"
  fi
  nginx -t
  systemctl reload nginx
}

if ! nginx -t || ! systemctl reload nginx; then
  echo "Teacher gateway activation failed; restoring the previous Nginx config." >&2
  restore_previous_config
  if [[ -n "${previous_config}" ]]; then
    rm -f "${previous_config}"
  fi
  exit 1
fi
if [[ -n "${previous_config}" ]]; then
  rm -f "${previous_config}"
fi

if [[ "${MODE}" == "public" ]]; then
  install -o root -g root -m 0644 /dev/null "${PUBLIC_HTTPS_FLAG}"
else
  rm -f "${PUBLIC_HTTPS_FLAG}"
fi

echo "Teacher gateway enabled in ${MODE} mode."

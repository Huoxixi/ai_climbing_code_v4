#!/usr/bin/env bash
set -Eeuo pipefail

ROLE="${1:-}"
USERNAME="${2:-}"
PUBLIC_KEY_FILE="${3:-}"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Tunnel user creation must run as root." >&2
  exit 1
fi
if [[ "${ROLE}" != "operator" && "${ROLE}" != "viewer" ]]; then
  echo "Usage: create_tunnel_user.sh operator|viewer pilot-username /absolute/path/to/public-key.pub" >&2
  exit 1
fi
if [[ ! "${USERNAME}" =~ ^pilot-[a-z0-9][a-z0-9-]{1,30}$ ]]; then
  echo "Username must start with pilot- and contain only lowercase letters, numbers, and hyphens." >&2
  exit 1
fi
if [[ "${PUBLIC_KEY_FILE}" != /* || ! -f "${PUBLIC_KEY_FILE}" ]]; then
  echo "A readable absolute public-key file path is required." >&2
  exit 1
fi
if [[ "$(wc -l < "${PUBLIC_KEY_FILE}")" -ne 1 ]] ||
  ! grep -Eq '^(ssh-ed25519|sk-ssh-ed25519@openssh.com|ecdsa-sha2-nistp256) ' "${PUBLIC_KEY_FILE}"; then
  echo "The public-key file must contain exactly one supported SSH public key." >&2
  exit 1
fi

GROUP="ai-climbing-viewers"
TARGET_PORT="8081"
if [[ "${ROLE}" == "operator" ]]; then
  GROUP="ai-climbing-operators"
  TARGET_PORT="8080"
fi

getent group "${GROUP}" >/dev/null || groupadd --system "${GROUP}"
if id "${USERNAME}" >/dev/null 2>&1; then
  echo "Refusing to modify existing user: ${USERNAME}" >&2
  exit 1
fi

useradd --create-home --shell /usr/sbin/nologin --gid "${GROUP}" "${USERNAME}"
home_dir="$(getent passwd "${USERNAME}" | cut -d: -f6)"
install -d -o "${USERNAME}" -g "${GROUP}" -m 0700 "${home_dir}/.ssh"
install -o "${USERNAME}" -g "${GROUP}" -m 0600 "${PUBLIC_KEY_FILE}" "${home_dir}/.ssh/authorized_keys"
passwd -l "${USERNAME}" >/dev/null

sshd -t
systemctl reload ssh
echo "Created ${ROLE} tunnel user ${USERNAME}; permitted destination: 127.0.0.1:${TARGET_PORT}"

#!/usr/bin/env bash
set -Eeuo pipefail

SOURCE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Server asset installation must run as root." >&2
  exit 1
fi

"${SOURCE_ROOT}/deploy/scripts/server_preflight.sh"

if ! id ai-climbing >/dev/null 2>&1; then
  useradd --system --home /var/lib/ai-climbing --shell /usr/sbin/nologin ai-climbing
fi
getent group ai-climbing-operators >/dev/null || groupadd --system ai-climbing-operators
getent group ai-climbing-viewers >/dev/null || groupadd --system ai-climbing-viewers

install -d -o root -g ai-climbing -m 0750 /etc/ai-climbing
install -d -o root -g root -m 0755 /opt/ai-climbing/releases
install -d -o ai-climbing -g ai-climbing -m 0750 /var/lib/ai-climbing/data
install -d -o ai-climbing -g ai-climbing -m 0750 /var/lib/ai-climbing/ops
install -d -o root -g ai-climbing -m 0750 /var/backups/ai-climbing
install -d -o root -g root -m 0755 /usr/local/lib/ai-climbing

if [[ ! -f /etc/ai-climbing/backend.env ]]; then
  install -o root -g ai-climbing -m 0640 "${SOURCE_ROOT}/deploy/env/backend.env.example" /etc/ai-climbing/backend.env
fi
if [[ ! -f /etc/ai-climbing/backup.env ]]; then
  install -o root -g root -m 0600 "${SOURCE_ROOT}/deploy/env/backup.env.example" /etc/ai-climbing/backup.env
fi

install -o root -g root -m 0755 "${SOURCE_ROOT}"/deploy/scripts/*.sh /usr/local/lib/ai-climbing/
install -o root -g root -m 0644 "${SOURCE_ROOT}"/deploy/systemd/* /etc/systemd/system/
install -d -o root -g root -m 0755 /etc/ssh/sshd_config.d
install -o root -g root -m 0644 "${SOURCE_ROOT}/deploy/ssh/60-ai-climbing-pilot.conf" /etc/ssh/sshd_config.d/60-ai-climbing-pilot.conf
install -d -o root -g root -m 0755 /etc/systemd/journald.conf.d
install -o root -g root -m 0644 "${SOURCE_ROOT}/deploy/journald/ai-climbing.conf" /etc/systemd/journald.conf.d/ai-climbing.conf
install -o root -g root -m 0644 "${SOURCE_ROOT}/deploy/nginx/ai_climbing.conf" /etc/nginx/sites-available/ai_climbing.conf
if [[ -L /etc/nginx/sites-enabled/ai_climbing ]]; then
  unlink /etc/nginx/sites-enabled/ai_climbing
fi
ln -sfn /etc/nginx/sites-available/ai_climbing.conf /etc/nginx/sites-enabled/ai_climbing.conf

systemctl daemon-reload
systemctl restart systemd-journald
systemctl enable ai-climbing-backup.timer ai-climbing-health.timer
sshd -t
systemctl reload ssh
nginx -t

cat <<'EOF'
Server assets installed, but the application is not public or started yet.
Next gates:
1. Migrate the approved data into /var/lib/ai-climbing/data.
2. Configure /etc/ai-climbing/backend.env and backup.env.
3. Configure a private rclone remote and bucket lifecycle.
4. Create individual SSH tunnel users for operator and viewer access.
5. Keep public web ports closed before the first release.
EOF

#!/usr/bin/env bash
set -Eeuo pipefail

REPOSITORY="git@github.com:Huoxixi/ai_climbing_code_v4.git"
SOURCE_ROOT="/root/ai_climbing_code"
RELEASE_ROOT="/opt/ai-climbing/releases"
CURRENT_LINK="/opt/ai-climbing/current"
RELEASE_TAG="${1:-}"
CLIMBING_MODEL_CHECKPOINT="/var/lib/ai-climbing/models/climbing/verified-model_final.pth"
CLIMBING_MODEL_SHA256="995960a74819e21bd66d7be56ae6e1c8124ec0a06fece4fae13812887d86ebea"
DETECTRON2_WHEEL_CACHE="/var/cache/ai-climbing/detectron2"
DETECTRON2_WHEEL="${DETECTRON2_WHEEL_CACHE}/detectron2-py312-torch2.8-cpu.whl"
DETECTRON2_WHEEL_SHA256="${DETECTRON2_WHEEL}.sha256"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Release deployment must run as root." >&2
  exit 1
fi
if [[ ! "${RELEASE_TAG}" =~ ^pilot-v[0-9A-Za-z._-]+$ ]]; then
  echo "Usage: deploy_release.sh pilot-v<version>" >&2
  exit 1
fi

for required in git rsync python3.12 npm curl nginx; do
  command -v "${required}" >/dev/null || {
    echo "Missing required command: ${required}" >&2
    exit 1
  }
done
[[ -f /etc/ai-climbing/backend.env ]] || {
  echo "/etc/ai-climbing/backend.env is missing." >&2
  exit 1
}
[[ -f /var/lib/ai-climbing/data/saved_boards.json ]] || {
  echo "Approved pilot data has not been migrated into /var/lib/ai-climbing/data." >&2
  exit 1
}
grep -q '^APP_ENV=production$' /etc/ai-climbing/backend.env
grep -q '^LOCAL_ONLY=true$' /etc/ai-climbing/backend.env
grep -q '^DISABLE_SUPABASE=true$' /etc/ai-climbing/backend.env
grep -q '^ENABLE_SIMULATION=false$' /etc/ai-climbing/backend.env
grep -q '^ENABLE_CLIMB_REPLAY=true$' /etc/ai-climbing/backend.env
grep -q '^PILOT_AUTH_ENABLED=true$' /etc/ai-climbing/backend.env
grep -q '^PILOT_COOKIE_SECURE=true$' /etc/ai-climbing/backend.env
[[ -r /etc/ai-climbing/pilot-users.json ]] || {
  echo "/etc/ai-climbing/pilot-users.json is missing or unreadable."
  exit 1
}
[[ -r "${CLIMBING_MODEL_CHECKPOINT}" ]] || {
  echo "Climbing model checkpoint is missing: ${CLIMBING_MODEL_CHECKPOINT}" >&2
  exit 1
}
printf '%s  %s\n' "${CLIMBING_MODEL_SHA256}" "${CLIMBING_MODEL_CHECKPOINT}" |
  sha256sum --check --status || {
    echo "Climbing model checkpoint hash verification failed." >&2
    exit 1
  }

temporary_root="$(mktemp -d /tmp/ai_climbing_code_v4.XXXXXX)"
building_release="${RELEASE_ROOT}/.${RELEASE_TAG}.building"
final_release="${RELEASE_ROOT}/${RELEASE_TAG}"
smoke_pid=""
detectron2_wheel_build=""

cleanup() {
  if [[ -n "${smoke_pid}" ]]; then
    kill "${smoke_pid}" >/dev/null 2>&1 || true
    wait "${smoke_pid}" >/dev/null 2>&1 || true
  fi
  rm -rf -- "${temporary_root}"
  if [[ -d "${building_release}" ]]; then
    rm -rf -- "${building_release}"
  fi
  if [[ -n "${detectron2_wheel_build}" && -d "${detectron2_wheel_build}" ]]; then
    rm -rf -- "${detectron2_wheel_build}"
  fi
}
trap cleanup EXIT

git clone "${REPOSITORY}" "${temporary_root}/ai_climbing_code_v4"
git -C "${temporary_root}/ai_climbing_code_v4" checkout --detach "refs/tags/${RELEASE_TAG}"
release_sha="$(git -C "${temporary_root}/ai_climbing_code_v4" rev-parse HEAD)"

mkdir -p "${SOURCE_ROOT}"
rsync -av \
  --exclude='backend/.env' \
  --exclude='backend/.venv' \
  --exclude='node_modules' \
  --exclude='frontend/node_modules' \
  "${temporary_root}/ai_climbing_code_v4/" "${SOURCE_ROOT}/"

if [[ -e "${final_release}" ]]; then
  echo "Immutable release already exists: ${final_release}" >&2
  exit 1
fi

cd "${SOURCE_ROOT}/frontend"
npm ci
npm audit --audit-level=high
VITE_ENABLE_SIMULATION=false npm run test
VITE_ENABLE_SIMULATION=false npm run build

mkdir -p "${building_release}"
rsync -a \
  --exclude='.git' \
  --exclude='backend/.env' \
  --exclude='backend/.venv' \
  --exclude='backend/data' \
  --exclude='frontend/dist' \
  --exclude='frontend/node_modules' \
  "${temporary_root}/ai_climbing_code_v4/" "${building_release}/"
rsync -a "${SOURCE_ROOT}/frontend/dist/" "${building_release}/frontend/dist/"

python3.12 -m venv "${building_release}/backend/.venv"
mkdir -p "${DETECTRON2_WHEEL_CACHE}"
requirements_without_detectron2="${temporary_root}/requirements-production.without-detectron2.lock"
grep -vE '/detectron2-[^/]+\.tar\.gz$' \
  "${building_release}/backend/requirements-production.lock" \
  > "${requirements_without_detectron2}"
"${building_release}/backend/.venv/bin/python" -m pip install --disable-pip-version-check -r "${requirements_without_detectron2}"
if [[ -f "${DETECTRON2_WHEEL}" && -f "${DETECTRON2_WHEEL_SHA256}" ]] &&
  sha256sum --check --status "${DETECTRON2_WHEEL_SHA256}"; then
  echo "Using cached detectron2 wheel: ${DETECTRON2_WHEEL}"
else
  rm -f -- "${DETECTRON2_WHEEL}" "${DETECTRON2_WHEEL_SHA256}"
  detectron2_wheel_build="$(mktemp -d /tmp/ai-climbing-detectron2-wheel.XXXXXX)"
  "${building_release}/backend/.venv/bin/python" -m pip wheel \
    --disable-pip-version-check \
    --no-deps \
    --no-build-isolation \
    --wheel-dir "${detectron2_wheel_build}" \
    "${building_release}/backend/vendor/detectron2-a2f4a877.tar.gz"
  detectron2_wheel_candidate="$(find "${detectron2_wheel_build}" -maxdepth 1 -type f -name 'detectron2-*.whl' -print -quit)"
  [[ -n "${detectron2_wheel_candidate}" && -f "${detectron2_wheel_candidate}" ]] || {
    echo "detectron2 wheel build produced no wheel." >&2
    exit 1
  }
  install -m 0644 "${detectron2_wheel_candidate}" "${DETECTRON2_WHEEL}"
  printf '%s  %s\n' "$(sha256sum "${DETECTRON2_WHEEL}" | awk '{print $1}')" "${DETECTRON2_WHEEL}" > "${DETECTRON2_WHEEL_SHA256}"
  rm -rf -- "${detectron2_wheel_build}"
  detectron2_wheel_build=""
fi
"${building_release}/backend/.venv/bin/python" -m pip install \
  --disable-pip-version-check \
  --no-deps \
  "${DETECTRON2_WHEEL}"
"${building_release}/backend/.venv/bin/python" -c \
  'import torch, torchvision, detectron2; print(torch.__version__, torchvision.__version__, detectron2.__version__)'
mkdir -p "${temporary_root}/test-data"
rsync -a "${temporary_root}/ai_climbing_code_v4/backend/data/" "${temporary_root}/test-data/"
ln -s "${temporary_root}/test-data" "${building_release}/backend/data"
printf '%s\n' "${release_sha}" > "${building_release}/RELEASE_SHA"
chown -R root:ai-climbing "${building_release}"
chmod -R o-rwx,g+rX "${building_release}"
chmod o+x "${building_release}" "${building_release}/frontend"
find "${building_release}/frontend/dist" -type d -exec chmod 0755 {} +
find "${building_release}/frontend/dist" -type f -exec chmod 0644 {} +

cd "${building_release}/backend"
LOCAL_ONLY=true DISABLE_SUPABASE=true ENABLE_SIMULATION=false \
  "${building_release}/backend/.venv/bin/python" -m unittest \
  test_ai_lab_experiments \
  test_hold_image_processing \
  test_local_only_mode \
  test_photo_route_benchmark \
  test_photo_route_drafts \
  test_photo_route_processing \
  test_photo_route_v2 \
  test_photo_route_evaluation \
  test_photo_route_experiments \
  test_photo_route_instance_masks \
  test_hole_grid_topology \
  test_climb_replay \
  test_media_normalization \
  test_photo_wall_processing \
  test_pilot_access \
  test_member_accounts \
  test_release_hardening \
  test_release_readiness \
  test_standard_board \
  test_standard_board_activity \
  test_standard_board_difficulty \
  test_standard_board_local_first \
  test_standard_board_tags

APP_ENV=production LOCAL_ONLY=true DISABLE_SUPABASE=true ENABLE_SIMULATION=false ENABLE_CLIMB_REPLAY=true RELEASE_SHA="${release_sha}" \
  "${building_release}/backend/.venv/bin/python" -m uvicorn main:app --host 127.0.0.1 --port 8001 --workers 1 \
  >"${temporary_root}/smoke.log" 2>&1 &
smoke_pid=$!
for _ in {1..20}; do
  if curl --fail --silent --max-time 3 http://127.0.0.1:8001/api/health |
    grep -q "${release_sha:0:12}"; then
    break
  fi
  sleep 1
done
curl --fail --silent --show-error --max-time 5 http://127.0.0.1:8001/api/health |
  grep -q "${release_sha:0:12}"
if curl --fail --silent --max-time 3 http://127.0.0.1:8001/docs >/dev/null; then
  echo "Production debug docs are unexpectedly available." >&2
  exit 1
fi
kill "${smoke_pid}"
wait "${smoke_pid}" || true
smoke_pid=""

rm "${building_release}/backend/data"
ln -s /var/lib/ai-climbing/data "${building_release}/backend/data"

if systemctl is-active --quiet ai-climbing.service; then
  /usr/local/lib/ai-climbing/backup_data.sh pre-deploy
fi

previous=""
if [[ -L "${CURRENT_LINK}" ]]; then
  previous="$(readlink -f -- "${CURRENT_LINK}")" || {
    echo "Current release link is invalid; refusing to switch versions." >&2
    exit 1
  }
  case "${previous}" in
    "${RELEASE_ROOT}"/*)
      [[ -d "${previous}" && -f "${previous}/RELEASE_SHA" ]] || {
        echo "Current release is incomplete: ${previous}" >&2
        exit 1
      }
      ;;
    *)
      echo "Current release points outside ${RELEASE_ROOT}: ${previous}" >&2
      exit 1
      ;;
  esac
elif [[ -e "${CURRENT_LINK}" ]]; then
  echo "Current release path exists but is not a symbolic link." >&2
  exit 1
fi

nginx -t
mv "${building_release}" "${final_release}"
temporary_link="/opt/ai-climbing/.current.release.$$"
ln -s "${final_release}" "${temporary_link}"
mv -Tf "${temporary_link}" "${CURRENT_LINK}"
printf 'RELEASE_SHA=%s\n' "${release_sha}" > /etc/ai-climbing/release.env
chmod 0644 /etc/ai-climbing/release.env

activation_ok=false
if systemctl restart ai-climbing.service; then
  for _ in {1..45}; do
    if curl --fail --silent --max-time 3 http://127.0.0.1:8000/api/health |
      grep -q "${release_sha:0:12}"; then
      activation_ok=true
      break
    fi
    sleep 1
  done
fi

if [[ "${activation_ok}" == true ]]; then
  if nginx -t && systemctl reload nginx; then
    operator_status="$(
      curl --silent --output /dev/null --write-out '%{http_code}' --max-time 5 \
        http://127.0.0.1:8080/ || true
    )"
    viewer_status="$(
      curl --silent --output /dev/null --write-out '%{http_code}' --max-time 5 \
        http://127.0.0.1:8081/ || true
    )"
    viewer_write_status="$(
      curl --silent --output /dev/null --write-out '%{http_code}' --max-time 5 \
        --request POST http://127.0.0.1:8081/api/save-board || true
    )"
  else
    activation_ok=false
  fi
  if [[ "${operator_status:-}" != 200 || "${viewer_status:-}" != 200 || "${viewer_write_status:-}" != 403 ]]; then
    activation_ok=false
  fi
fi

if [[ "${activation_ok}" != true ]]; then
  if [[ -n "${previous}" && -d "${previous}" ]]; then
    ln -s "${previous}" "${temporary_link}"
    mv -Tf "${temporary_link}" "${CURRENT_LINK}"
    printf 'RELEASE_SHA=%s\n' "$(cat "${previous}/RELEASE_SHA")" > /etc/ai-climbing/release.env
    systemctl restart ai-climbing.service || true
    systemctl reload nginx || true
  else
    systemctl stop ai-climbing.service || true
    rm -f -- "${CURRENT_LINK}" /etc/ai-climbing/release.env
  fi
  rm -rf -- "${final_release}"
  echo "New release failed health verification and code was rolled back." >&2
  exit 1
fi

systemctl enable --now ai-climbing.service ai-climbing-backup.timer ai-climbing-health.timer
echo "Release ${RELEASE_TAG} (${release_sha}) is active. Begin the 30-minute observation window."

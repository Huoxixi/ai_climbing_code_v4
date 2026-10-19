#!/usr/bin/env bash
# Called only by deploy_release.sh with a reviewed tag checkout.
set -Eeuo pipefail
[[ ${EUID} -eq 0 ]] || { echo 'Deployment requires root.' >&2; exit 1; }
source_dir="$(realpath "${1:?Source checkout required}")"
tag="${2:-}"
[[ "$source_dir" == /tmp/ai-climbing-release.*/source && "$tag" =~ ^pilot-v[0-9A-Za-z._-]+$ ]] || exit 1
sha="$(git -C "$source_dir" rev-parse HEAD)"
[[ "$sha" == "$(git -C "$source_dir" rev-parse "refs/tags/$tag^{commit}")" ]] || exit 1
release_mode="$(python3.12 -I "$source_dir/deploy/maintenance/bootstrap_mode.py" "$tag")"
if [[ "$release_mode" == ssh-maintenance ]]; then
  # The stable dispatcher already owns the shared deployment lock on fd 8.
  # This reviewed tag updates tools only; never build/switch/restart the site.
  python3.12 -I "$source_dir/deploy/maintenance/install.py" "$tag"
  echo "Fixed SSH maintenance tools installed from $tag ($sha); website unchanged."
  exit 0
fi
[[ "$release_mode" == browser ]] || exit 1
release_root=/opt/ai-climbing/releases
current=/opt/ai-climbing/current
building="$release_root/.$tag.building"
final="$release_root/$tag"
temporary_link="/opt/ai-climbing/.current.browser.$$"
previous="$(readlink -f "$current")"
[[ "$previous" == "$release_root/"* && -f "$previous/RELEASE_SHA" && -x "$previous/backend/.venv/bin/python" ]] || {
  echo 'A complete previous release is required for rollback.' >&2; exit 1;
}
[[ ! -e "$building" && ! -e "$final" && ! -L "$building" && ! -L "$final" ]] || {
  echo 'Immutable release already exists; use a new tag.' >&2; exit 1;
}
for command in npm curl nginx python3.12 sha256sum; do command -v "$command" >/dev/null; done
[[ -f /etc/ai-climbing/backend.env && -d /var/lib/ai-climbing/data ]] || exit 1
available="$(df -Pk "$release_root" | awk 'NR==2 {print $4}')"
(( available >= 8*1024*1024 )) || { echo 'Less than the required 8 GiB free space.' >&2; exit 1; }
smoke_pid=''
switched=false
complete=false
cleanup() {
  local status=$?
  trap - EXIT INT TERM HUP
  if [[ -n "$smoke_pid" ]]; then kill "$smoke_pid" 2>/dev/null || true; wait "$smoke_pid" 2>/dev/null || true; fi
  if [[ "$switched" == true && "$complete" != true ]]; then
    echo 'Activation failed; restoring the previous code release.' >&2
    rm -f -- "$temporary_link"
    ln -s "$previous" "$temporary_link"
    mv -Tf "$temporary_link" "$current"
    printf 'RELEASE_SHA=%s\n' "$(cat "$previous/RELEASE_SHA")" > /etc/ai-climbing/release.env
    chmod 0644 /etc/ai-climbing/release.env
    systemctl restart ai-climbing.service || true
    systemctl reload nginx || true
    echo "Rollback target: $previous" >&2
  fi
  rm -f -- "$temporary_link"
  if [[ -d "$building" ]]; then rm -rf -- "$building"; fi
  exit "$status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM HUP

cd "$source_dir"
python3.12 backend/scripts/install_replay_rtmw.py --cache "$source_dir/.tmp/model-downloads"
python3.12 deploy/browser/download_installer.py
cd frontend
npm ci
npm audit --audit-level=high
npm run test:browser-unit
npm run build:browser
cd "$source_dir"
python3.12 deploy/browser/prepare_release.py "$building"
python3.12 -m venv "$building/backend/.venv"
"$building/backend/.venv/bin/python" -m pip install --disable-pip-version-check -r "$building/backend/requirements-browser.lock"
"$building/backend/.venv/bin/python" -m pip check
(cd "$building/backend" && "$building/backend/.venv/bin/python" -m unittest test_browser_web_app -v)
printf '%s\n' "$sha" > "$building/RELEASE_SHA"
chown -R root:ai-climbing "$building"
chmod -R o-rwx,g+rX "$building"
chmod o+x "$building" "$building/frontend"
find "$building/frontend/dist" -type d -exec chmod 0755 {} +
find "$building/frontend/dist" -type f -exec chmod 0644 {} +

health() {
  curl -fsS --max-time 5 "http://127.0.0.1:$1/api/health" |
    python3.12 -c 'import json,sys; x=json.load(sys.stdin); assert x["status"]=="success" and x["compute"]=="browser-only" and x["release_sha"]==sys.argv[1] and x["accounts"] is False and x["media_uploads"] is False' "$sha"
}
cd "$building/backend"
RELEASE_SHA="$sha" "$building/backend/.venv/bin/python" -m uvicorn main:app --host 127.0.0.1 --port 8001 --workers 1 >"$source_dir/.tmp/browser-smoke.log" 2>&1 &
smoke_pid=$!
for _ in {1..20}; do if health 8001 2>/dev/null; then break; fi; sleep 1; done
health 8001
[[ "$(curl -s --output /dev/null -w '%{http_code}' -X POST http://127.0.0.1:8001/api/member/login)" == 404 ]]
[[ "$(curl -s --output /dev/null -w '%{http_code}' -X POST http://127.0.0.1:8001/api/save-board)" == 404 ]]
kill "$smoke_pid"; wait "$smoke_pid" || true; smoke_pid=''

/usr/local/lib/ai-climbing/backup_data.sh pre-deploy
grep -q '^RESULT=success$' /var/lib/ai-climbing/ops/last-backup.env
grep -q '^REMOTE_VERIFIED=true$' /var/lib/ai-climbing/ops/last-backup.env
nginx -t
mv "$building" "$final"
ln -s "$final" "$temporary_link"
switched=true
mv -Tf "$temporary_link" "$current"
printf 'RELEASE_SHA=%s\n' "$sha" > /etc/ai-climbing/release.env
chmod 0644 /etc/ai-climbing/release.env
systemctl restart ai-climbing.service
for _ in {1..45}; do if health 8000 2>/dev/null; then break; fi; sleep 1; done
health 8000
nginx -t
systemctl reload nginx
for port in 8080 8081; do
  curl -fsS --max-time 10 "http://127.0.0.1:$port/" | grep -q '/assets/'
done
[[ "$(curl -s --max-time 10 --output /dev/null -w '%{http_code}' -X POST http://127.0.0.1:8081/api/save-board)" == 403 ]]
curl -fsS --max-time 15 https://www.panyandingxian.cn/api/health |
  python3.12 -c 'import json,sys; x=json.load(sys.stdin); assert x["release_sha"]==sys.argv[1] and x["compute"]=="browser-only"' "$sha"
curl -fsS --max-time 15 https://www.panyandingxian.cn/ | grep -q '浏览器本地复盘'
complete=true
echo "Browser release $tag ($sha) active. Previous release retained: $previous"
echo 'Old accounts, photos and media remain backed up; no legacy API is served.'

#!/usr/bin/env bash
# Stable entry point: select the deployment profile from the immutable tag.
set -Eeuo pipefail
[[ ${EUID} -eq 0 ]] || { echo 'Deployment requires root.' >&2; exit 1; }
tag="${1:-}"
[[ "$tag" =~ ^pilot-v[0-9A-Za-z._-]+$ ]] || { echo 'Expected an immutable pilot-v tag.' >&2; exit 1; }
for command in git flock python3.12; do command -v "$command" >/dev/null; done
exec 8>/run/lock/ai-climbing-deploy.lock
flock -n 8 || { echo 'Another deployment is running.' >&2; exit 1; }
checkout="$(mktemp -d /tmp/ai-climbing-release.XXXXXX)"
trap 'rm -rf -- "$checkout"' EXIT
git clone --filter=blob:none --no-checkout git@github.com:Huoxixi/ai_climbing_code_v4.git "$checkout/source"
git -C "$checkout/source" checkout --detach "refs/tags/$tag"
git -C "$checkout/source" merge-base --is-ancestor HEAD origin/main || {
  echo 'Tag is not part of the reviewed main branch.' >&2; exit 1;
}
if [[ -f "$checkout/source/deploy/browser/profile.json" ]]; then
  python3.12 -c 'import json,sys; assert json.load(open(sys.argv[1]))["mode"] == "browser-only"' "$checkout/source/deploy/browser/profile.json"
  bash "$checkout/source/deploy/scripts/deploy_browser_release.sh" "$checkout/source" "$tag"
else
  bash /usr/local/lib/ai-climbing/deploy_legacy_release.sh "$tag"
fi

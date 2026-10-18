#!/usr/bin/env bash
# One-time upgrade of the existing deployment tool; no application/configuration switch.
set -Eeuo pipefail
[[ ${EUID} -eq 0 ]] || { echo 'Root is required.' >&2; exit 1; }
tag="${1:-}"
[[ "$tag" =~ ^pilot-v[0-9A-Za-z._-]+$ ]] || exit 1
source_dir="$(git rev-parse --show-toplevel)"
sha="$(git -C "$source_dir" rev-parse HEAD)"
[[ "$sha" == "$(git -C "$source_dir" rev-parse "refs/tags/$tag^{commit}")" ]] || exit 1
git -C "$source_dir" merge-base --is-ancestor HEAD origin/main
target=/usr/local/lib/ai-climbing/deploy_release.sh
legacy=/usr/local/lib/ai-climbing/deploy_legacy_release.sh
[[ -f "$target" && ! -L "$target" && -x "$target" && "$(stat -c %u "$target")" == 0 ]] || exit 1
incoming="$source_dir/deploy/scripts/deploy_release.sh"
bash -n "$incoming"
bash -n "$source_dir/deploy/scripts/deploy_browser_release.sh"
if cmp -s "$target" "$incoming"; then
  [[ -x "$legacy" ]] || exit 1
  echo 'Deployment dispatcher already installed.'
  exit 0
fi
backup="/var/backups/ai-climbing/deployment-tools/$(date -u +%Y%m%dT%H%M%SZ)"
install -d -m 0700 "$backup"
cp -p "$target" "$backup/deploy_release.sh"
sha256sum "$backup/deploy_release.sh" > "$backup/SHA256SUMS"
printf 'SOURCE_TAG=%s\nSOURCE_SHA=%s\n' "$tag" "$sha" > "$backup/source.env"
if grep -q 'Stable entry point: select the deployment profile' "$target"; then
  [[ -x "$legacy" ]] || exit 1
else
  # Keep the exact installed legacy deployer, including any prior server fixes.
  [[ ! -e "$legacy" && ! -L "$legacy" ]] || { echo 'Review existing legacy deployer first.' >&2; exit 1; }
  install -m 0750 "$target" "$legacy"
fi
staging="/usr/local/lib/ai-climbing/.deploy_release.new.$$"
trap 'rm -f -- "$staging"' EXIT
install -m 0750 "$incoming" "$staging"
mv -Tf "$staging" "$target"
echo "Deployment tool updated from reviewed tag $tag; previous tool retained at $backup."
echo 'The running website, systemd unit, Nginx, credentials and user data were not changed.'

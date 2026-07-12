#!/usr/bin/env bash
set -euo pipefail

container="${MOVIEPILOT_CONTAINER:-moviepilot}"
base_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
asset_sites="$base_dir/assets/sites.py"

if [ ! -f "$asset_sites" ]; then
  echo "ERROR: missing asset: $asset_sites" >&2
  exit 1
fi

if ! docker inspect "$container" >/dev/null 2>&1; then
  echo "ERROR: container not found: $container" >&2
  exit 1
fi

echo "Ensuring MoviePilot helper backend is preserved as _sites_backend.so..."
if docker exec "$container" test -f /app/app/helper/sites_backend.so; then
  if ! docker exec "$container" test -f /app/app/helper/_sites_backend.so; then
    docker exec "$container" mv /app/app/helper/sites_backend.so /app/app/helper/_sites_backend.so
    echo "Renamed sites_backend.so -> _sites_backend.so"
  else
    disabled="/app/app/helper/sites_backend.so.disabled.$(date +%Y%m%d%H%M%S)"
    docker exec "$container" mv /app/app/helper/sites_backend.so "$disabled"
    echo "Moved extra sites_backend.so -> $disabled"
  fi
else
  echo "No active sites_backend.so found."
fi

echo "Deploying patched sites.py..."
docker cp "$asset_sites" "$container:/app/app/helper/sites.py"

echo "Checking Python import..."
docker exec "$container" python3 - <<'PY'
from app.helper.sites import SitesHelper
helper = SitesHelper()
indexers = helper.get_indexers()
domains = [i.get("domain") or i.get("site_domain") for i in indexers]
assert helper.auth_level == 2
assert any("dmhy" in (d or "") or "share.dmhy.org" in (d or "") for d in domains), domains
assert any("nyaa" in (d or "") for d in domains), domains
print("ok: sites helper patched")
PY

echo "Patch applied. Restart MoviePilot manually only if the running process has already imported the old module."

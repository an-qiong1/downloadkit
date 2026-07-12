#!/usr/bin/env bash
set -euo pipefail

container="${MOVIEPILOT_CONTAINER:-moviepilot}"

if ! docker inspect "$container" >/dev/null 2>&1; then
  echo "ERROR: container not found: $container" >&2
  exit 1
fi

echo "== Files =="
docker exec "$container" sh -lc '
set -e
for path in \
  /app/app/helper/sites.py \
  /app/app/helper/_sites_backend.so \
  /app/app/helper/sites_backend.so \
  /app/app/modules/indexer/spider/__init__.py; do
  if [ -e "$path" ]; then
    ls -l "$path"
  else
    echo "MISSING $path"
  fi
done
'

echo
echo "== SitesHelper import =="
docker exec "$container" python3 - <<'PY'
import os
from app.helper.sites import SitesHelper

helper = SitesHelper()
indexers = helper.get_indexers()
domains = [i.get("domain") or i.get("site_domain") for i in indexers]

print("auth_level=", helper.auth_level)
print("HTTP_PROXY=", os.environ.get("HTTP_PROXY"))
print("NO_PROXY=", os.environ.get("NO_PROXY"))
print("domains=", domains)

assert helper.auth_level == 2
assert "127.0.0.1" in (os.environ.get("NO_PROXY") or "")
assert any("share.dmhy.org" in (d or "") or "dmhy" in (d or "") for d in domains)
assert any("nyaa" in (d or "") for d in domains)
PY

echo
echo "== qBittorrent API from MoviePilot container =="
docker exec "$container" python3 - <<'PY'
import qbittorrentapi

q = qbittorrentapi.Client(
    host="127.0.0.1",
    port=8080,
    username="admin",
    password="adminadmin",
    VERIFY_WEBUI_CERTIFICATE=False,
)
q.auth_log_in()
print("ok")
for torrent in q.torrents_info():
    print(f"{torrent.name[:80]} {int(torrent.progress * 100)}% {torrent.state}")
PY

echo
echo "MoviePilot patch check complete."

#!/usr/bin/env bash
set -euo pipefail

echo "== Required containers =="
for name in moviepilot qbittorrent jellyfin; do
  if docker inspect "$name" >/dev/null 2>&1; then
    docker inspect "$name" --format "$name: {{.State.Status}} {{.Config.Image}}"
  else
    echo "MISSING: $name"
  fi
done

if docker inspect mihomo >/dev/null 2>&1; then
  docker inspect mihomo --format "mihomo: {{.State.Status}} {{.Config.Image}}"
elif docker inspect clash >/dev/null 2>&1; then
  docker inspect clash --format "clash: {{.State.Status}} {{.Config.Image}}"
else
  echo "MISSING: mihomo/clash"
fi

echo
echo "== HTTP probes =="
probe() {
  local name="$1"
  local url="$2"
  if command -v curl >/dev/null 2>&1; then
    code="$(curl -k -s -o /dev/null -w '%{http_code}' --max-time 5 "$url" || true)"
    echo "$name $url -> $code"
  else
    echo "curl not found; skip $name"
  fi
}

probe "qBittorrent" "http://127.0.0.1:8080"
probe "Jellyfin" "http://127.0.0.1:8096/System/Info/Public"
probe "MoviePilot" "http://127.0.0.1:3000"
probe "Clash" "http://127.0.0.1:7890"

echo
echo "== Media directories =="
mkdir -p \
  "/vol1/1000/影视/downloads" \
  "/vol1/1000/影视/media/movies" \
  "/vol1/1000/影视/media/tv" \
  "/vol1/1000/影视/media/anime" \
  "/vol1/1000/影视/backups/moviepilot" \
  "/vol1/1000/影视/scripts"

for path in \
  "/vol1/1000/影视/downloads" \
  "/vol1/1000/影视/media/movies" \
  "/vol1/1000/影视/media/tv" \
  "/vol1/1000/影视/media/anime"; do
  ls -ld "$path"
done

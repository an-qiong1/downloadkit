#!/usr/bin/env bash
set -euo pipefail

echo "== Host =="
hostname || true
date "+%F %T %z" || true

echo
echo "== Docker containers =="
docker ps --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}'

echo
echo "== Docker inspect target containers =="
for name in moviepilot qbittorrent jellyfin mihomo clash; do
  if docker inspect "$name" >/dev/null 2>&1; then
    echo "-- $name --"
    docker inspect "$name" --format 'Name={{.Name}} Image={{.Config.Image}} NetworkMode={{.HostConfig.NetworkMode}} Restart={{.HostConfig.RestartPolicy.Name}}'
    docker inspect "$name" --format '{{range .Mounts}}Mount={{.Source}} -> {{.Destination}} {{.Mode}}{{println}}{{end}}'
  fi
done

echo
echo "== Media directories =="
for path in \
  "/vol1/1000/影视" \
  "/vol1/1000/影视/downloads" \
  "/vol1/1000/影视/media" \
  "/vol1/1000/影视/media/movies" \
  "/vol1/1000/影视/media/tv" \
  "/vol1/1000/影视/media/anime" \
  "/vol1/1000/影视/backups" \
  "/vol1/1000/影视/scripts"; do
  if [ -e "$path" ]; then
    ls -ld "$path"
  else
    echo "MISSING $path"
  fi
done

echo
echo "== MoviePilot logs =="
docker logs --tail 100 moviepilot 2>&1 || true

echo
echo "== Jellyfin logs =="
docker logs --tail 100 jellyfin 2>&1 || true

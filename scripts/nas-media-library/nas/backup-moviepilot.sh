#!/usr/bin/env bash
set -euo pipefail

container="${MOVIEPILOT_CONTAINER:-moviepilot}"
backup_root="/vol1/1000/影视/backups/moviepilot"
ts="$(date +%Y%m%d-%H%M%S)"
backup_dir="$backup_root/$ts"

mkdir -p "$backup_dir"

if ! docker inspect "$container" >/dev/null 2>&1; then
  echo "ERROR: container not found: $container" >&2
  exit 1
fi

copy_if_exists() {
  local src="$1"
  local name="$2"
  if docker exec "$container" test -e "$src"; then
    docker cp "$container:$src" "$backup_dir/$name"
    echo "BACKUP $src -> $backup_dir/$name"
  else
    echo "SKIP missing $src"
  fi
}

copy_if_exists "/app/app/helper/sites.py" "sites.py"
copy_if_exists "/app/app/helper/sites_backend.so" "sites_backend.so"
copy_if_exists "/app/app/helper/_sites_backend.so" "_sites_backend.so"
copy_if_exists "/app/app/modules/indexer/spider/__init__.py" "spider__init__.py"

docker inspect "$container" > "$backup_dir/docker-inspect-moviepilot.json"
docker logs --tail 300 "$container" > "$backup_dir/docker-logs-tail300.txt" 2>&1 || true

echo "Backup complete: $backup_dir"

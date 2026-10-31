#!/bin/sh
# Start or stop the lab from the repo root.
# Usage: scripts/lab.sh up -d
set -eu
root="$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)"
compose() {
  docker compose \
    --project-directory "$root/deploy/lab" \
    --env-file "$root/.env" \
    "$@"
}
# The crawler fills these. Docker mounts a missing file as a directory.
for f in hub/assets/catalog.json portal/directory/catalog.json; do
  [ -f "$root/$f" ] || printf '[]\n' > "$root/$f"
done
cmd="${1:-}"
case "$cmd" in
  up|down|stop|start|restart|ps)
    compose -f "$root/deploy/lab/compose.yml" "$@"
    compose -p newmarket-mesh-hub -f "$root/deploy/lab/hub.yml" "$@"
    compose -p newmarket-mesh-square -f "$root/deploy/lab/square.yml" "$@"
    compose -p newmarket-mesh-names -f "$root/deploy/lab/names.yml" "$@"
    ;;
  *)
    compose -f "$root/deploy/lab/compose.yml" "$@"
    ;;
esac

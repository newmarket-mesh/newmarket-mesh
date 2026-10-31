#!/bin/sh
# Start the hub once 100.64.0.1 is on tailscale0.
# Caddy binds that address, so it will not start without it.
set -eu
root="$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)"
i=0
while [ "$i" -lt 60 ]; do
  if ip -4 addr show dev tailscale0 2>/dev/null | grep -q 'inet 100.64.0.1/'; then
    exec "$root/scripts/lab.sh" up -d
  fi
  i=$((i + 1))
  sleep 1
done
echo "tailscale0 is not 100.64.0.1" >&2
exit 1

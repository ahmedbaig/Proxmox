#!/usr/bin/env bash
# Run ON THE PROXMOX HOST. Installs Grafana Alloy on every container and on the
# host itself, and points them all at Loki on the metrics container.
#
# Composition per host:
#   all          journald
#   proxy (111)  + nginx access/error logs
#   apps (113)   + docker container logs
#
# Alloy runs as the "alloy" user and cannot read the journal unless it is in
# the systemd-journal group — the package does not always add it, and the
# failure is silent: the service starts, reports healthy, and ships nothing.

set -uo pipefail

BASE=/root/alloy-base.alloy
DOCKER=/root/alloy-docker.alloy
NGINX=/root/alloy-nginx.alloy

install_alloy() {
  local target="$1" hostname="$2" extra="${3:-}"
  echo "=== $hostname ($target) ==="

  local run
  if [ "$target" = "host" ]; then
    run() { bash -c "$1"; }
    cp "$BASE" /tmp/alloy-build.alloy
    [ -n "$extra" ] && cat "$extra" >> /tmp/alloy-build.alloy
    sed -i "s/__HOSTNAME__/$hostname/g" /tmp/alloy-build.alloy
  else
    cp "$BASE" /tmp/alloy-build.alloy
    [ -n "$extra" ] && cat "$extra" >> /tmp/alloy-build.alloy
    sed -i "s/__HOSTNAME__/$hostname/g" /tmp/alloy-build.alloy
  fi

  if [ "$target" = "host" ]; then
    DEBIAN_FRONTEND=noninteractive apt-get install -y -qq alloy >/dev/null 2>&1
    cp /tmp/alloy-build.alloy /etc/alloy/config.alloy
    usermod -aG systemd-journal alloy 2>/dev/null
    systemctl enable --now alloy >/dev/null 2>&1
    systemctl restart alloy
    sleep 3
    printf '  alloy: %s\n' "$(systemctl is-active alloy)"
  else
    # The Grafana apt repo is only on the metrics container so far.
    pct exec "$target" -- bash -c '
      export DEBIAN_FRONTEND=noninteractive
      if ! command -v alloy >/dev/null 2>&1; then
        apt-get install -y -qq curl gpg ca-certificates >/dev/null 2>&1
        mkdir -p /etc/apt/keyrings
        curl -fsSL https://apt.grafana.com/gpg.key | gpg --batch --yes --dearmor -o /etc/apt/keyrings/grafana.gpg
        echo "deb [signed-by=/etc/apt/keyrings/grafana.gpg] https://apt.grafana.com stable main" > /etc/apt/sources.list.d/grafana.list
        apt-get update -qq
        apt-get install -y -qq alloy >/dev/null 2>&1
      fi
    '
    pct push "$target" /tmp/alloy-build.alloy /etc/alloy/config.alloy
    pct exec "$target" -- bash -c '
      usermod -aG systemd-journal alloy 2>/dev/null
      # Docker socket access, where a socket exists.
      [ -S /var/run/docker.sock ] && usermod -aG docker alloy 2>/dev/null
      # nginx log directory is 0755 root:adm on Debian.
      [ -d /var/log/nginx ] && usermod -aG adm alloy 2>/dev/null
      systemctl enable --now alloy >/dev/null 2>&1
      systemctl restart alloy
      sleep 3
      printf "  alloy: %s\n" "$(systemctl is-active alloy)"
    '
  fi
}

install_alloy 110 dns1
install_alloy 111 proxy "$NGINX"
install_alloy 118 gitlab
install_alloy 119 registry
install_alloy 112 db
install_alloy 113 apps "$DOCKER"
install_alloy 114 metrics
install_alloy host pve

echo
echo "done"

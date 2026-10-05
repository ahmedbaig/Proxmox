#!/usr/bin/env bash
# Run ON THE PROXMOX HOST. Copies the wildcard certificate from the proxy
# container to every other container that terminates TLS, and restarts what
# needs restarting.
#
# acme.sh renews on CT 111 and reloads nginx there, but nothing else learns
# about it. Without this, the database engines would keep serving the old
# certificate until someone noticed — which, given renewal is every ~75 days,
# would be a long time.
#
# Idempotent: compares fingerprints and does nothing when they already match,
# so it is safe to run from cron daily.

set -uo pipefail

SRC_CT=111
SRC_CRT=/etc/nginx/ssl/baig.crt
SRC_KEY=/etc/nginx/ssl/baig.key
STAGE=/root/.cert-stage

mkdir -p "$STAGE"
pct pull "$SRC_CT" "$SRC_CRT" "$STAGE/baig.crt" 2>/dev/null
pct pull "$SRC_CT" "$SRC_KEY" "$STAGE/baig.key" 2>/dev/null

if [ ! -s "$STAGE/baig.crt" ]; then
  echo "ERROR: could not pull certificate from CT $SRC_CT"
  exit 1
fi

NEW_FP=$(openssl x509 -in "$STAGE/baig.crt" -noout -fingerprint -sha256 | cut -d= -f2)
echo "source fingerprint: $NEW_FP"
echo "expires:            $(openssl x509 -in "$STAGE/baig.crt" -noout -enddate | cut -d= -f2)"

# --- CT 112: database engines ----------------------------------------------
CUR_FP=$(pct exec 112 -- openssl x509 -in /etc/ssl/baig/baig.crt -noout -fingerprint -sha256 2>/dev/null | cut -d= -f2)

if [ "$CUR_FP" = "$NEW_FP" ]; then
  echo "CT 112: already current, nothing to do"
else
  echo "CT 112: installing new certificate"
  pct exec 112 -- mkdir -p /etc/ssl/baig
  pct push 112 "$STAGE/baig.crt" /etc/ssl/baig/baig.crt
  pct push 112 "$STAGE/baig.key" /etc/ssl/baig/baig.key

  # Each engine runs as its own user and needs to read the key. A shared group
  # is cleaner than copying the key four times with four owners.
  pct exec 112 -- bash -c '
    getent group certaccess >/dev/null || groupadd certaccess
    for u in postgres mysql mongod redis couchdb; do
      id "$u" >/dev/null 2>&1 && usermod -aG certaccess "$u"
    done
    chown root:certaccess /etc/ssl/baig/baig.crt /etc/ssl/baig/baig.key
    chmod 640 /etc/ssl/baig/baig.key
    chmod 644 /etc/ssl/baig/baig.crt

    # PostgreSQL refuses to start if the key is group-readable, regardless of
    # the group. It needs its own copy owned by postgres at 0600.
    install -o postgres -g postgres -m 600 /etc/ssl/baig/baig.key /var/lib/postgresql/baig.key
    install -o postgres -g postgres -m 644 /etc/ssl/baig/baig.crt /var/lib/postgresql/baig.crt
  '

  for svc in postgresql mariadb mongod; do
    pct exec 112 -- systemctl restart "$svc" 2>/dev/null \
      && echo "  restarted $svc" \
      || echo "  WARNING: $svc failed to restart"
  done
fi

# --- simple targets: one directory, one owner group, one reload ------------
# push_simple <ct> <dir> <group> <reload command>
push_simple() {
  local ct=$1 dir=$2 grp=$3 reload=$4
  if ! pct status "$ct" 2>/dev/null | grep -q running; then
    echo "CT $ct: not running, skipped"; return
  fi
  local cur
  cur=$(pct exec "$ct" -- openssl x509 -in "$dir/baig.crt" -noout -fingerprint -sha256 2>/dev/null | cut -d= -f2)
  if [ "$cur" = "$NEW_FP" ]; then
    echo "CT $ct: already current, nothing to do"; return
  fi
  echo "CT $ct: installing new certificate"
  pct exec "$ct" -- mkdir -p "$dir"
  pct push "$ct" "$STAGE/baig.crt" "$dir/baig.crt"
  pct push "$ct" "$STAGE/baig.key" "$dir/baig.key"
  pct exec "$ct" -- bash -c "chown root:$grp '$dir/baig.crt' '$dir/baig.key'; chmod 644 '$dir/baig.crt'; chmod 640 '$dir/baig.key'"
  pct exec "$ct" -- bash -c "$reload" && echo "  reloaded" || echo "  WARNING: reload failed on CT $ct"
}

# CT 119 registry (docker-registry reads the key as its own user)
push_simple 119 /etc/docker/registry/tls docker-registry "systemctl restart docker-registry"

# CT 118 gitlab (omnibus nginx; skipped until the container exists)
push_simple 118 /etc/gitlab/ssl root "gitlab-ctl hup nginx >/dev/null 2>&1 || true"

echo "done"

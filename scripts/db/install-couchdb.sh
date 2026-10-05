#!/usr/bin/env bash
# Run INSIDE CT 112. Installs CouchDB 3.x as the backend for Obsidian
# Self-hosted LiveSync.
#
# Usage: install-couchdb.sh <admin-password> <erlang-cookie>
#
# Standalone (single node) — LiveSync does not want a cluster. Bound to
# 0.0.0.0 so the Trusted VLAN can reach it; auth is required for every request.

set -euo pipefail
PW="$1"
COOKIE="$2"

# The signing key lives on couchdb.apache.org, which is a different name from
# the repo host and may resolve independently. Fall back to the jfrog copy.
if ! curl -fsSL https://couchdb.apache.org/repo/keys.asc -o /tmp/couchdb-keys.asc 2>/dev/null; then
  echo "couchdb.apache.org unreachable, trying jfrog mirror for the key"
  curl -fsSL https://apache.jfrog.io/artifactory/couchdb-deb/repo/keys.asc -o /tmp/couchdb-keys.asc
fi
gpg --batch --yes --dearmor -o /usr/share/keyrings/couchdb-archive-keyring.gpg /tmp/couchdb-keys.asc

echo "deb [signed-by=/usr/share/keyrings/couchdb-archive-keyring.gpg] https://apache.jfrog.io/artifactory/couchdb-deb/ trixie main" \
  > /etc/apt/sources.list.d/couchdb.list

debconf-set-selections <<EOF
couchdb couchdb/mode select standalone
couchdb couchdb/bindaddress string 0.0.0.0
couchdb couchdb/cookie string $COOKIE
couchdb couchdb/adminpass password $PW
couchdb couchdb/adminpass_again password $PW
EOF

apt-get update -qq
DEBIAN_FRONTEND=noninteractive apt-get install -y -qq couchdb

systemctl enable --now couchdb
sleep 3
systemctl is-active couchdb
curl -s http://127.0.0.1:5984/ | head -c 200
echo

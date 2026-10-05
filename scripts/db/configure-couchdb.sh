#!/usr/bin/env bash
# Run INSIDE CT 112. Applies the configuration Obsidian Self-hosted LiveSync
# requires, then creates the vault database.
#
# Usage: configure-couchdb.sh <admin-password> <vault-db-name>
#
# Defaults are unusable for LiveSync as shipped: CouchDB caps documents at 8 MB
# and rejects the app:// origins Obsidian uses on desktop and mobile.

set -euo pipefail
PW="$1"
DB="${2:-obsidian}"
API="http://127.0.0.1:5984"
AUTH="admin:$PW"

put() {
  local path="$1" val="$2"
  curl -sS -u "$AUTH" -X PUT "$API/_node/_local/_config/$path" \
       -H 'Content-Type: application/json' -d "\"$val\"" >/dev/null
  printf '  %-46s = %s\n' "$path" "$val"
}

echo "config:"
# Single node, no clustering. LiveSync replicates client-side.
put couchdb/single_node true
# Obsidian attachments and large notes exceed the 8 MB default.
put couchdb/max_document_size 50000000
put chttpd/max_http_request_size 4294967296
# Every request must authenticate — the database is reachable from the VLAN.
put chttpd/require_valid_user true
put chttpd_auth/require_valid_user true
# Browser-style auth prompt rather than a redirect to Fauxton.
put httpd/WWW-Authenticate 'Basic realm=\"couchdb\"'
put chttpd_auth/authentication_redirect /_utils/session.html
# CORS: desktop Obsidian sends app://obsidian.md, mobile sends
# capacitor://localhost. Credentials must be allowed or auth never reaches us.
put httpd/enable_cors true
put chttpd/enable_cors true
put cors/credentials true
put cors/origins 'app://obsidian.md,capacitor://localhost,http://localhost'

echo "restart:"
systemctl restart couchdb
for i in $(seq 1 20); do
  curl -sf "$API/" >/dev/null 2>&1 && break
  sleep 1
done
echo "  up"

echo "databases:"
for sys in _users _replicator _global_changes; do
  code=$(curl -sS -u "$AUTH" -o /dev/null -w '%{http_code}' -X PUT "$API/$sys")
  printf '  %-16s %s\n' "$sys" "$code"
done
code=$(curl -sS -u "$AUTH" -o /dev/null -w '%{http_code}' -X PUT "$API/$DB")
printf '  %-16s %s\n' "$DB" "$code"

echo "verify:"
curl -sS -u "$AUTH" "$API/_all_dbs"; echo
echo -n "  cors origins: "; curl -sS -u "$AUTH" "$API/_node/_local/_config/cors/origins"; echo
echo -n "  max doc size: "; curl -sS -u "$AUTH" "$API/_node/_local/_config/couchdb/max_document_size"; echo
echo -n "  anonymous access (expect 401): "
curl -s -o /dev/null -w '%{http_code}\n' "$API/$DB"

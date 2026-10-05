#!/usr/bin/env bash
# Run INSIDE CT 116. Add, list or remove WireGuard peers.
#
#   wg-peer.sh add <name> [full|split]   default: full
#   wg-peer.sh list
#   wg-peer.sh remove <name>
#
# full   all client traffic goes through home — you get AdGuard's 102 blocklists
#        on mobile data, and internal names resolve everywhere
# split  only lab subnets are routed; everything else uses the client's own
#        connection. Lighter, but no ad blocking away from home
#
# Client configs land in /etc/wireguard/peers/<name>.conf and are also printed
# as a QR code for phones.

set -euo pipefail

WG_NET=10.9.0
WG_IF=wg0
PEERS=/etc/wireguard/peers
# The endpoint clients dial. baig.network is kept current by the DDNS job on
# CT 111, so this survives a WAN address change.
ENDPOINT=baig.network:51820
# Clients resolve through dns1, which gives them ad blocking and internal names.
CLIENT_DNS=10.10.20.2

LAB_ROUTES="10.10.10.0/24, 10.10.20.0/24, 10.10.30.0/24, 10.10.50.0/24, 192.168.0.0/25"

umask 077
mkdir -p "$PEERS"

next_ip() {
  # .1 is the server; start clients at .2
  local used
  # The config writer emits "AllowedIPs   = " with padding, so this must not
  # assume a single space — it silently matched nothing and handed every peer
  # 10.9.0.2, which breaks routing for all but the first.
  used=$(grep -hoE "AllowedIPs[[:space:]]*=[[:space:]]*$WG_NET\.[0-9]+" /etc/wireguard/$WG_IF.conf 2>/dev/null \
         | grep -oE '[0-9]+$' | sort -n | tail -1)
  echo $(( ${used:-1} + 1 ))
}

case "${1:-}" in
  add)
    NAME="${2:?usage: wg-peer.sh add <name> [full|split]}"
    MODE="${3:-full}"
    [ -f "$PEERS/$NAME.conf" ] && { echo "peer '$NAME' already exists"; exit 1; }

    OCTET=$(next_ip)
    [ "$OCTET" -gt 254 ] && { echo "address space exhausted"; exit 1; }

    CPRIV=$(wg genkey)
    CPUB=$(echo "$CPRIV" | wg pubkey)
    PSK=$(wg genpsk)   # post-quantum-ish extra layer, costs nothing
    SPUB=$(cat /etc/wireguard/server.pub)

    if [ "$MODE" = "split" ]; then
      ALLOWED="$LAB_ROUTES"
    else
      ALLOWED="0.0.0.0/0"
    fi

    cat >> /etc/wireguard/$WG_IF.conf <<EOF

# peer: $NAME  ($MODE tunnel, added $(date -u +%Y-%m-%d))
[Peer]
PublicKey    = $CPUB
PresharedKey = $PSK
AllowedIPs   = $WG_NET.$OCTET/32
EOF

    cat > "$PEERS/$NAME.conf" <<EOF
# WireGuard client: $NAME
# $MODE tunnel. Import this file, or scan the QR code.
[Interface]
PrivateKey = $CPRIV
Address    = $WG_NET.$OCTET/32
DNS        = $CLIENT_DNS

[Peer]
PublicKey    = $SPUB
PresharedKey = $PSK
Endpoint     = $ENDPOINT
AllowedIPs   = $ALLOWED
PersistentKeepalive = 25
EOF

    systemctl reload "wg-quick@$WG_IF" 2>/dev/null || {
      wg syncconf "$WG_IF" <(wg-quick strip "$WG_IF")
    }

    echo "added '$NAME' as $WG_NET.$OCTET  ($MODE tunnel)"
    echo "config: $PEERS/$NAME.conf"
    echo
    qrencode -t ansiutf8 < "$PEERS/$NAME.conf"
    ;;

  list)
    echo "configured peers:"
    grep -E '^# peer:' /etc/wireguard/$WG_IF.conf 2>/dev/null | sed 's/^# peer: /  /' || echo "  none"
    echo
    echo "live handshakes:"
    wg show "$WG_IF" latest-handshakes 2>/dev/null | while read -r key ts; do
      if [ "${ts:-0}" = "0" ]; then
        echo "  ${key:0:16}…  never connected"
      else
        echo "  ${key:0:16}…  $(( ($(date +%s) - ts) / 60 )) min ago"
      fi
    done
    ;;

  remove)
    NAME="${2:?usage: wg-peer.sh remove <name>}"
    [ -f "$PEERS/$NAME.conf" ] || { echo "no such peer: $NAME"; exit 1; }
    # Delete the comment line, the [Peer] header and its three fields.
    python3 - "$NAME" <<'PY'
import re, sys
name = sys.argv[1]
p = "/etc/wireguard/wg0.conf"
s = open(p).read()
s = re.sub(rf"\n# peer: {re.escape(name)} .*?\n\[Peer\]\n(?:[^\[\n]*\n)*", "\n", s)
open(p, "w").write(s)
PY
    rm -f "$PEERS/$NAME.conf"
    systemctl restart "wg-quick@$WG_IF"
    echo "removed '$NAME'"
    ;;

  *)
    sed -n '3,16p' "$0" | sed 's/^# \{0,1\}//'
    exit 1
    ;;
esac

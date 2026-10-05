#!/usr/bin/env bash
# Run INSIDE CT 116 (vpn, 10.10.50.20). One-time WireGuard server setup.
#
# Placed on the Lab VLAN rather than Servers on purpose: a VPN endpoint is the
# most exposed thing in the lab, and Lab has no standing access to Servers, so
# clients get exactly the access you grant rule by rule. The Raspberry Pi keeps
# running OpenVPN untouched until this is proven.
#
# Clients are NATed to 10.10.50.20 on the way out, so the UX7 needs no static
# route for the VPN subnet — one less thing to forget. The trade-off is that
# every VPN client appears as 10.10.50.20 in firewall logs.

set -euo pipefail

WG_NET=10.9.0
WG_PORT=51820
WG_IF=wg0

umask 077
mkdir -p /etc/wireguard/peers

if [ -f /etc/wireguard/server.key ]; then
  echo "server key already exists, reusing"
else
  wg genkey > /etc/wireguard/server.key
  wg pubkey < /etc/wireguard/server.key > /etc/wireguard/server.pub
  echo "generated server keypair"
fi

SERVER_PRIV=$(cat /etc/wireguard/server.key)

cat > /etc/wireguard/$WG_IF.conf <<EOF
# /etc/wireguard/$WG_IF.conf  —  CT 116 (vpn, 10.10.50.20)
# Peers are appended below by wg-peer.sh. Do not hand-edit peer blocks.
[Interface]
Address    = $WG_NET.1/24
ListenPort = $WG_PORT
PrivateKey = $SERVER_PRIV

# Masquerade so the UX7 needs no route back to $WG_NET.0/24.
PostUp   = sysctl -qw net.ipv4.ip_forward=1
PostUp   = iptables -t nat -A POSTROUTING -s $WG_NET.0/24 -o eth0 -j MASQUERADE
PostUp   = iptables -A FORWARD -i %i -j ACCEPT
PostUp   = iptables -A FORWARD -o %i -j ACCEPT
PostDown = iptables -t nat -D POSTROUTING -s $WG_NET.0/24 -o eth0 -j MASQUERADE
PostDown = iptables -D FORWARD -i %i -j ACCEPT
PostDown = iptables -D FORWARD -o %i -j ACCEPT
EOF

# Persist forwarding across reboots; PostUp covers the running case.
echo 'net.ipv4.ip_forward = 1' > /etc/sysctl.d/99-wg-forward.conf

systemctl enable --now "wg-quick@$WG_IF" >/dev/null 2>&1
systemctl restart "wg-quick@$WG_IF"
sleep 2

echo
echo "interface:"
wg show "$WG_IF" 2>/dev/null | sed 's/^/  /' || echo "  FAILED to start"
echo "  server public key: $(cat /etc/wireguard/server.pub)"
echo "  listening on udp/$WG_PORT"

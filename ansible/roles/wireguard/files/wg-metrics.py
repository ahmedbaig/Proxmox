#!/usr/bin/env python3
"""WireGuard metrics for Prometheus, via the node_exporter textfile collector.

Runs on CT 116 from a systemd timer. There is no packaged WireGuard exporter on
Debian 13, and the common third-party one does not do geolocation — which is the
interesting part here: knowing *where* a peer is connecting from, and noticing
when that changes.

Emitted metrics:
  wireguard_peer_receive_bytes_total      per peer, counter
  wireguard_peer_transmit_bytes_total     per peer, counter
  wireguard_peer_last_handshake_seconds   unix timestamp, 0 = never
  wireguard_peer_handshake_age_seconds    derived, easier to alert on
  wireguard_peer_up                       1 if handshake within 3 minutes
  wireguard_peers                         total configured
  wireguard_peers_connected               currently handshaking
  wireguard_server_public_ip_info         label-only, the WAN address peers dial
  wireguard_peer_geo_info                 label-only: country, region, city, asn

Peer names come from WGDashboard's database so the labels match the UI. Geo
lookups are cached on disk and only refreshed when a peer's endpoint IP
changes, so a peer reconnecting from the same network costs nothing.
"""
import json
import os
import socket
import sqlite3
import subprocess
import sys
import time
import urllib.request

OUT = "/var/lib/prometheus/node-exporter/wireguard.prom"
CACHE = "/var/lib/prometheus/node-exporter/.wg-geo-cache.json"
WGDB = "/opt/WGDashboard/src/db/wgdashboard.db"
IFACE = "wg0"
UP_WINDOW = 180  # a peer with keepalive 21-25s is stale well before this


def peer_names():
    """public key -> friendly name, so labels match what the UI shows."""
    names = {}
    try:
        con = sqlite3.connect(f"file:{WGDB}?mode=ro", uri=True)
        for pid, name in con.execute("select id, name from wg0"):
            if name:
                names[pid] = name
        con.close()
    except Exception:
        pass
    return names


def load_cache():
    try:
        return json.load(open(CACHE))
    except Exception:
        return {}


def save_cache(c):
    tmp = CACHE + ".tmp"
    json.dump(c, open(tmp, "w"))
    os.replace(tmp, CACHE)


def geolocate(ip, cache):
    """Look up an IP once and remember it. Private ranges are skipped."""
    if ip in cache:
        return cache[ip]
    if ip.startswith(("10.", "192.168.", "127.", "172.16.", "172.17.", "172.18.")):
        info = {"country": "private", "code": "", "region": "", "city": "",
                "asn": "", "lat": "", "lon": ""}
    else:
        info = {"country": "unknown", "code": "", "region": "", "city": "",
                "asn": "", "lat": "", "lon": ""}
        try:
            url = f"http://ip-api.com/json/{ip}?fields=status,country,countryCode,regionName,city,as,lat,lon"
            with urllib.request.urlopen(url, timeout=8) as r:
                d = json.load(r)
            if d.get("status") == "success":
                info = {
                    "country": d.get("country", "") or "unknown",
                    "code": d.get("countryCode", "") or "",
                    "region": d.get("regionName", "") or "",
                    "city": d.get("city", "") or "",
                    "asn": (d.get("as", "") or "").split(" ")[0],
                    "lat": d.get("lat", ""),
                    "lon": d.get("lon", ""),
                }
        except Exception:
            pass  # keep "unknown"; it will be retried next run
    cache[ip] = info
    return info


def esc(v):
    return str(v).replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")


def wan_ip():
    for url in ("https://api.ipify.org", "https://ifconfig.me/ip"):
        try:
            with urllib.request.urlopen(url, timeout=8) as r:
                ip = r.read().decode().strip()
            socket.inet_aton(ip)
            return ip
        except Exception:
            continue
    return ""


def main():
    try:
        dump = subprocess.run(
            ["wg", "show", IFACE, "dump"], capture_output=True, text=True, timeout=10
        ).stdout.strip().splitlines()
    except Exception as e:
        print(f"wg show failed: {e}", file=sys.stderr)
        return 1

    if not dump:
        return 1

    names = peer_names()
    cache = load_cache()
    now = int(time.time())
    lines = []

    def emit(name, mtype, help_text, samples):
        if not samples:
            return
        lines.append(f"# HELP {name} {help_text}")
        lines.append(f"# TYPE {name} {mtype}")
        lines.extend(samples)

    rx, tx, hs, age, up, geo = [], [], [], [], [], []
    lat_s, lon_s = [], []
    connected = 0
    peers = dump[1:]  # first line is the interface

    for line in peers:
        f = line.split("\t")
        if len(f) < 8:
            continue
        pub, endpoint, allowed, last, rxb, txb = f[0], f[2], f[3], int(f[4]), int(f[5]), int(f[6])
        name = names.get(pub, pub[:12])
        ip = endpoint.rsplit(":", 1)[0] if endpoint and endpoint != "(none)" else ""
        lbl = f'peer="{esc(name)}",public_key="{esc(pub)}"'

        rx.append(f"wireguard_peer_receive_bytes_total{{{lbl}}} {rxb}")
        tx.append(f"wireguard_peer_transmit_bytes_total{{{lbl}}} {txb}")
        hs.append(f"wireguard_peer_last_handshake_seconds{{{lbl}}} {last}")

        a = (now - last) if last else -1
        age.append(f"wireguard_peer_handshake_age_seconds{{{lbl}}} {a}")

        is_up = 1 if last and (now - last) <= UP_WINDOW else 0
        connected += is_up
        up.append(f"wireguard_peer_up{{{lbl}}} {is_up}")

        if ip:
            g = geolocate(ip, cache)
            geo.append(
                f'wireguard_peer_geo_info{{{lbl},endpoint_ip="{esc(ip)}",'
                f'country="{esc(g["country"])}",country_code="{esc(g.get("code",""))}",'
                f'region="{esc(g["region"])}",'
                f'city="{esc(g["city"])}",asn="{esc(g["asn"])}",'
                f'allowed_ips="{esc(allowed)}"}} 1'
            )
            # A geomap needs numeric lat/lon as metric VALUES, not labels.
            if g.get("lat") not in ("", None):
                geo_lbl = (f'{lbl},endpoint_ip="{esc(ip)}",city="{esc(g["city"])}",'
                           f'country="{esc(g["country"])}"')
                lat_s.append(f'wireguard_peer_latitude{{{geo_lbl}}} {g["lat"]}')
                lon_s.append(f'wireguard_peer_longitude{{{geo_lbl}}} {g["lon"]}')

    emit("wireguard_peer_receive_bytes_total", "counter", "Bytes received from peer", rx)
    emit("wireguard_peer_transmit_bytes_total", "counter", "Bytes sent to peer", tx)
    emit("wireguard_peer_last_handshake_seconds", "gauge", "Unix time of last handshake, 0 if never", hs)
    emit("wireguard_peer_handshake_age_seconds", "gauge", "Seconds since last handshake, -1 if never", age)
    emit("wireguard_peer_up", "gauge", f"1 if the peer handshook within {UP_WINDOW}s", up)
    emit("wireguard_peer_geo_info", "gauge", "Peer endpoint location, label-only", geo)
    emit("wireguard_peer_latitude", "gauge", "Peer endpoint latitude, for geomap", lat_s)
    emit("wireguard_peer_longitude", "gauge", "Peer endpoint longitude, for geomap", lon_s)

    lines += [
        "# HELP wireguard_peers Total configured peers",
        "# TYPE wireguard_peers gauge",
        f"wireguard_peers {len(peers)}",
        "# HELP wireguard_peers_connected Peers with a recent handshake",
        "# TYPE wireguard_peers_connected gauge",
        f"wireguard_peers_connected {connected}",
    ]

    wan = wan_ip()
    if wan:
        g = geolocate(wan, cache)
        lines += [
            "# HELP wireguard_server_public_ip_info The WAN address peers dial, label-only",
            "# TYPE wireguard_server_public_ip_info gauge",
            f'wireguard_server_public_ip_info{{ip="{esc(wan)}",country="{esc(g["country"])}",'
            f'city="{esc(g["city"])}",asn="{esc(g["asn"])}"}} 1',
        ]

    save_cache(cache)
    tmp = OUT + ".tmp"
    with open(tmp, "w") as fh:
        fh.write("\n".join(lines) + "\n")
    os.replace(tmp, OUT)  # atomic, so node_exporter never reads a partial file
    return 0


if __name__ == "__main__":
    sys.exit(main())

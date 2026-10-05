#!/usr/bin/env python3
"""Cloudflare DDNS for baig.network. Runs on CT 111 from cron.

Creates the apex A record if it does not exist, and updates it whenever the
WAN address changes. DNS-only (grey cloud): Cloudflare answers the query and
traffic goes straight to the UX7, so the source whitelisting on the router
keeps working exactly as configured.

Apex only, deliberately. Service names stay internal — *.baig.network resolves
to the proxy via AdGuard for anyone on the LAN or the VPN, and does not exist
in public DNS at all.

The token is the one acme.sh already uses: Zone:DNS:Edit on this zone only.
"""
import json
import re
import sys
import urllib.error
import urllib.request

ZONE = "baig.network"
RECORD = "baig.network"
TTL = 120  # short, because Leaptel hands out a dynamic address

conf = open("/root/.acme.sh/account.conf").read()


def val(key):
    m = re.search(rf"^{key}='([^']*)'", conf, re.M)
    return m.group(1) if m else None


token = val("SAVED_CF_Token") or val("CF_Token")
if not token:
    sys.exit("no Cloudflare token in /root/.acme.sh/account.conf")

H = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def api(path, method="GET", body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        "https://api.cloudflare.com/client/v4" + path, data=data, headers=H, method=method
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        sys.exit(f"cloudflare {method} {path} failed: {e.code} {e.read().decode()[:300]}")


def current_wan():
    # Two independent sources; if they disagree, do nothing rather than publish
    # a wrong address.
    seen = []
    for url, pick in (
        ("https://api.ipify.org", lambda t: t.strip()),
        ("https://cloudflare.com/cdn-cgi/trace", lambda t: dict(
            l.split("=", 1) for l in t.strip().splitlines() if "=" in l)["ip"]),
    ):
        try:
            with urllib.request.urlopen(url, timeout=15) as r:
                seen.append(pick(r.read().decode()))
        except Exception:
            pass
    if not seen:
        sys.exit("could not determine WAN address")
    if len(set(seen)) != 1:
        sys.exit(f"WAN address sources disagree ({seen}); not updating")
    return seen[0]


ip = current_wan()

zones = api(f"/zones?name={ZONE}")["result"]
if not zones:
    sys.exit(f"zone {ZONE} not visible to this token")
zid = zones[0]["id"]

recs = api(f"/zones/{zid}/dns_records?type=A&name={RECORD}")["result"]

if not recs:
    api(f"/zones/{zid}/dns_records", "POST", {
        "type": "A", "name": RECORD, "content": ip, "ttl": TTL, "proxied": False,
        "comment": "apex -> home WAN. DDNS by cf-ddns.py on CT 111.",
    })
    print(f"created {RECORD} A {ip}")
else:
    rec = recs[0]
    fixes = {}
    if rec["content"] != ip:
        fixes["content"] = ip
    # Enforce DNS-only. A proxied record would send traffic through
    # Cloudflare's edge, which breaks the source whitelisting on the UX7 —
    # requests would arrive from Cloudflare IPs, not the allowed sources — and
    # would not cover the VPN at all, since that is not HTTP.
    if rec.get("proxied"):
        fixes["proxied"] = False
    if rec.get("ttl") != TTL:
        fixes["ttl"] = TTL

    if fixes:
        api(f"/zones/{zid}/dns_records/{rec['id']}", "PATCH", fixes)
        desc = ", ".join(
            f"{k}: {rec.get(k)!r} -> {v!r}" for k, v in fixes.items()
        )
        print(f"updated {RECORD} ({desc})")
    else:
        print(f"{RECORD} A {ip} already current, DNS-only, ttl={TTL}")

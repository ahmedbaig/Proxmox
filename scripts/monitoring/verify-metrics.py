#!/usr/bin/env python3
"""Run inside CT 114. Summarises Prometheus target health, active alerts and
the current certificate expiry margin."""
import json
import urllib.request
from collections import Counter

P = "http://127.0.0.1:9090"


def get(path, params=None):
    url = P + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=20) as r:
        return json.load(r)


import urllib.parse  # noqa: E402

targets = get("/api/v1/targets")["data"]["activeTargets"]
print("=== target health by job ===")
counts = Counter((t["labels"].get("job"), t["health"]) for t in targets)
for (job, health), n in sorted(counts.items()):
    print(f"  {job:<16} {health:<9} {n}")
print(f"  TOTAL {len(targets)}")

print("\n=== down targets ===")
down = [t for t in targets if t["health"] == "down"]
if not down:
    print("  none")
for t in down[:15]:
    inst = t["labels"].get("instance", "?")
    print(f"  {t['labels'].get('job'):<14} {inst:<48} {t.get('lastError','')[:60]}")

print("\n=== active alerts ===")
alerts = get("/api/v1/alerts")["data"]["alerts"]
print(f"  {len(alerts)} active")
for name, n in Counter(a["labels"]["alertname"] for a in alerts).items():
    print(f"    {name}: {n}")

print("\n=== certificate expiry margin ===")
r = get("/api/v1/query", {"query": "min((probe_ssl_earliest_cert_expiry - time())/86400)"})
res = r["data"]["result"]
print(f"  {float(res[0]['value'][1]):.1f} days" if res else "  no data yet")

print("\n=== loki: log lines in the last 5m ===")
try:
    with urllib.request.urlopen(
        "http://127.0.0.1:3100/loki/api/v1/label/host/values", timeout=20
    ) as r:
        hosts = json.load(r)["data"]
    print("  hosts shipping:", ", ".join(sorted(hosts)))
except Exception as e:
    print("  loki query failed:", e)

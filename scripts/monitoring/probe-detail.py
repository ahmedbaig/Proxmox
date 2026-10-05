#!/usr/bin/env python3
"""Run inside CT 114. Lists every blackbox probe and why it is failing."""
import json
import urllib.parse
import urllib.request

P = "http://127.0.0.1:9090"


def q(expr):
    url = P + "/api/v1/query?" + urllib.parse.urlencode({"query": expr})
    with urllib.request.urlopen(url, timeout=20) as r:
        return json.load(r)["data"]["result"]


success = {m["metric"]["instance"]: m["value"][1] for m in q("probe_success")}
status = {m["metric"]["instance"]: m["value"][1] for m in q("probe_http_status_code")}
ssl = {m["metric"]["instance"]: m["value"][1] for m in q("probe_http_ssl")}
expiry = {
    m["metric"]["instance"]: float(m["value"][1])
    for m in q("(probe_ssl_earliest_cert_expiry - time())/86400")
}

print(f"{'instance':<44} {'ok':<4} {'http':<6} {'ssl':<4} cert_days")
for inst in sorted(success):
    ok = "yes" if success[inst] == "1" else "NO"
    print(
        f"  {inst:<42} {ok:<4} {status.get(inst,'-'):<6} "
        f"{ssl.get(inst,'-'):<4} {expiry.get(inst,float('nan')):.0f}"
        if inst in expiry
        else f"  {inst:<42} {ok:<4} {status.get(inst,'-'):<6} {ssl.get(inst,'-'):<4} -"
    )

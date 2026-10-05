import base64, json, urllib.request
H={"Authorization":"Basic "+base64.b64encode(b"ahmed:05vJ35cYMacMini").decode(),
   "Content-Type":"application/json"}
def call(p, body=None):
    d=json.dumps(body).encode() if body is not None else None
    r=urllib.request.Request("http://10.10.20.2"+p, data=d, headers=H, method="POST" if d else "GET")
    with urllib.request.urlopen(r, timeout=20) as x:
        raw=x.read(); return json.loads(raw) if raw.strip() else {}

st=call("/control/filtering/status")
rules=st.get("user_rules",[])
ahmedpi=[r for r in rules if "ahmedpi" in r or "ddns.net" in r]
print("  rules mentioning ddns.net:")
for r in ahmedpi: print("   ", r)

# Dedupe while preserving order
seen=set(); dedup=[]
for r in rules:
    if r not in seen: seen.add(r); dedup.append(r)
if len(dedup)!=len(rules):
    call("/control/filtering/set_rules",{"rules":dedup})
    print(f"  removed {len(rules)-len(dedup)} duplicate rule(s)")
else:
    print(f"  no duplicates ({len(rules)} rules)")

# which blocklist holds ||ddns.net^
for f in st.get("filters") or []:
    if f.get("id")==1767243001:
        print("  blocklist blocking ddns.net:", f.get("name"), "|", f.get("url"))

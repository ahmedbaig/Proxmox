# Runbooks

All of these assume `ssh-add ~/.ssh/id_rsa` has been run on the Mac mini first
— the key is passphrase-protected, and without it every SSH attempt fails with
`Permission denied (publickey,password)` even though it is authorised.

## Move a service to a different host

The whole point of the flat naming scheme. No DNS change needed.

```bash
# 1. Edit the one line
#    proxy_pass http://10.10.20.10:8084;  →  http://10.10.20.6:8084;

# 2. Deploy
scp baig.conf root@10.10.20.20:/root/baig.conf
ssh root@10.10.20.20 'pct push 111 /root/baig.conf /etc/nginx/conf.d/baig.conf \
  && pct exec 111 -- nginx -t \
  && pct exec 111 -- systemctl reload nginx'

# 3. Verify
curl -o /dev/null -w '%{http_code}\n' https://<service>.baig.network/
```

## Add a new service

1. Run it somewhere, note host and port.
2. Add a `server` block to `baig.conf` copying an existing one, change
   `server_name` and `proxy_pass`.
3. Deploy as above.
4. Add it to the blackbox probe list in `/etc/prometheus/prometheus.yml` on
   CT 114 so it is monitored and its certificate watched.
5. Add it to the service register at `/var/www/hosts/index.html` on CT 111.

No DNS entry is needed — `*.baig.network` already points at the proxy.

## Add a new host (not a service)

Host names are per-VLAN and resolve directly, so they **do** need a DNS entry:

```
AdGuard → Filters → DNS rewrites → Add
  <name>.servers.baig.network → 10.10.20.x
```

Without it, the wildcard sends the name to the proxy and nginx closes the
connection with 444.

> [!CAUTION]
> **`pct set <id> --delete searchdomain` does NOT remove the search domain**
> It deletes the *container's* key, which makes the container **inherit the
> Proxmox node's** value — currently `servers.baig.network`. That is how CT 116 and
> CT 117 ended up with a Servers search domain while sitting on the Lab VLAN.
>
> Editing `/etc/resolv.conf` by hand does not help either: Proxmox rewrites the
> `# --- BEGIN PVE ---` block on every container start. Both verified 27 Sep 2026.
>
> The only durable control is setting it explicitly to the container's own VLAN
> domain:
>
> ```bash
> pct set <id> --searchdomain lab.baig.network    # or servers./iot./home.
> pct reboot <id> && pct exec <id> -- cat /etc/resolv.conf
> ```
>
> Never `--searchdomain ""` — that leaves a bare `search` line which BIND's
> parser rejects outright (`dig: parse of /etc/resolv.conf failed`).

## Create a container

See the recipe in [Proxmox and Containers](proxmox-and-containers.md). Afterwards:

```bash
# node_exporter
pct exec <id> -- apt-get install -y prometheus-node-exporter

# log shipping
cp /root/alloy-base.alloy /tmp/a.alloy
sed -i "s/__HOSTNAME__/<name>/g" /tmp/a.alloy
pct exec <id> -- apt-get install -y alloy      # needs the Grafana apt repo
pct push <id> /tmp/a.alloy /etc/alloy/config.alloy
pct exec <id> -- bash -c 'usermod -aG systemd-journal alloy; systemctl enable --now alloy'
```

Then add `10.10.20.x:9100` to the `node` job in `prometheus.yml`.

## Renew or reissue the certificate

Renewal is automatic — cron on CT 111 every six hours. To add a new domain:

```bash
ssh root@10.10.20.20 'pct exec 111 -- /root/.acme.sh/acme.sh --issue --dns dns_cf \
  -d baig.network -d "*.baig.network" \
  -d "*.servers.baig.network" -d "*.home.baig.network" \
  -d "*.lab.baig.network" -d "*.iot.baig.network" \
  -d "*.main.baig.network" -d "*.new.baig.network" \
  --force'

ssh root@10.10.20.20 'pct exec 111 -- /root/.acme.sh/acme.sh --install-cert -d baig.network --ecc \
  --key-file /etc/nginx/ssl/baig.key \
  --fullchain-file /etc/nginx/ssl/baig.crt \
  --reloadcmd "systemctl reload nginx"'

# Push it to the database container too
ssh root@10.10.20.20 '/root/distribute-certs.sh'
```

Check what a certificate covers:

```bash
ssh root@10.10.20.20 'pct exec 111 -- openssl x509 -in /etc/nginx/ssl/baig.crt \
  -noout -text | grep -A 3 "Subject Alternative Name"'
```

## Check the whole lab is healthy

```bash
# Prometheus target health, alerts, certificate margin
ssh root@10.10.20.20 'pct exec 114 -- python3 /root/verify-metrics.py'

# Which probes are failing and why
ssh root@10.10.20.20 'pct exec 114 -- python3 /root/probe-detail.py'

# Everything through the proxy
for n in home grafana prometheus alertmanager obsidian yamtrack webhook \
         mailcatcher pve dns1 plex; do
  printf '%-14s ' "$n"
  curl -sS -o /dev/null -w '%{http_code}\n' --max-time 10 "https://$n.baig.network/"
done
```

Or just open **https://grafana.baig.network** → *Service Health — baig.network*.

## Audit every Grafana dashboard for broken panels

Runs every panel's query against its own datasource and checks layout and titles.
Lives on CT 115 as `/root/audit.py`:

```bash
ssh root@10.10.20.20 'pct exec 115 -- python3 /root/audit.py'
```

`OK` means every panel returned data and no two panels overlap. Read a `FAIL`
carefully before believing it — most no-data findings are metrics nobody is
producing (Windows, the work dev stack, Hive), not broken panels. See
[Monitoring — Dashboard state, audited 27 Sep 2026](monitoring.md#dashboard-state-audited-27-sep-2026) for the two traps that make an
audit report false failures.

## Check the DNS flow collectors

The flow map on *DNS — AdGuard* depends on two timers on CT 110. If it empties,
check them before suspecting Grafana:

```bash
ssh root@10.10.20.20 'pct exec 110 -- bash -c "
  systemctl list-timers --no-pager | grep -E \"unbound-metrics|dns-flow\"
  systemctl status dns-flow-metrics.service --no-pager | tail -5
"'

# Did node_exporter accept the files? Non-zero means it rejected one -- usually a
# duplicate series, which takes down EVERY metric in that file, not just the bad one.
ssh root@10.10.20.20 'pct exec 110 -- curl -s localhost:9100/metrics | grep node_textfile_scrape_error'

# Run the collector by hand and read the errors
ssh root@10.10.20.20 'pct exec 110 -- bash -c "
  set -a; . /etc/default/dns-flow-metrics; set +a
  /usr/local/bin/dns-flow-metrics.py && echo OK
"'
```

`dns_flow_collector_up 0` means the AdGuard API call failed — almost always the
credentials in `/etc/default/dns-flow-metrics` after a password rotation.

## The Internet Speed dashboard has gone flat

Speedtests are scheduled by **pm2 on the Mac mini**, not by cron and not on
Proxmox. A flat dashboard almost always means pm2 is not running rather than
anything being wrong with Grafana.

```bash
# Is the schedule even loaded? Two entries expected.
# "stopped" is the HEALTHY state for a cron_restart job -- it runs, exits, waits.
pm2 list

# Nothing listed, or the daemon had to spawn? It did not survive a reboot.
launchctl list | grep com.baig.pm2
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.baig.pm2.plist
pm2 resurrect

# When did a test last actually publish?
ssh root@10.10.20.20 'pct exec 114 -- curl -s \
  "localhost:9090/api/v1/query?query=time()-speedtest_last_run_timestamp_seconds"'

# Force one run now
pm2 restart speedtest-monitor
tail -5 ~/scripts/macmini_sydney_1/logs/speedtest.log
```

If the **wired** series is current and only Wi-Fi is stale, the log will say
`en1 is not active`. That is Wi-Fi being off, and the script refusing to publish
wired numbers under a `wifi` label. Nothing to fix unless you want the comparison.

> [!CAUTION]
> **Each test moves about 0.9 GB**
> The wired series alone is ~45 GB/day. Don't leave a second schedule running by
> accident; `speedtest_transferred_bytes_total` shows the real figure.

## Confirm DNS is still leaving encrypted

```bash
# Live sockets to the DoT upstreams. Unbound has no counter that proves this.
ssh root@10.10.20.20 'pct exec 110 -- ss -tnH state established | grep ":853"'

# How much left unencrypted in the last 24h. Should be exactly 0.
ssh root@10.10.20.20 'pct exec 114 -- curl -s \
  "localhost:9090/api/v1/query?query=dns_queries_leaving_unencrypted"'

# If it is non-zero, check WHICH upstream before assuming a leak -- a domain-scoped
# internal upstream reports as a bare address and is not egress at all.
ssh root@10.10.20.20 'pct exec 110 -- grep -A6 -E "^ *(upstream_dns|fallback_dns|local_ptr_upstreams)" \
  /opt/AdGuardHome/AdGuardHome.yaml'
```

A silent fallback from DoT to plain port 53 **keeps working** — the ISP's
interceptor answers — so nothing breaks and nothing alerts. This is the check.

## Diagnose "it says the certificate is wrong"

Nine times out of ten this is DNS, not TLS. See [Known Traps](known-traps.md).

```bash
# Does the name resolve at all?
ssh root@10.10.20.20 'pct exec 110 -- dig +short @127.0.0.1 <name>'

# Does Unbound resolve it?
ssh root@10.10.20.20 'pct exec 110 -- dig +short @127.0.0.1 -p 5335 <name>'

# Compare against a public resolver
ssh root@10.10.20.20 'pct exec 110 -- dig +short @1.1.1.1 <name>'
```

If the first returns `10.10.20.3` for a public hostname, the search domain has
been appended and the wildcard caught it.

## Check whether port 53 is still intercepted

```bash
ssh root@10.10.20.20 'pct exec 112 -- dig @192.0.2.1 example.com | grep -E "flags:|ANSWER"'
```

`192.0.2.1` is unroutable by definition. **Any answer means interception is
still active.** If it ever times out instead, Leaptel has stopped, and the
`forward-zone` in Unbound could be removed to restore true recursion.

## Query logs

Grafana → Explore → Loki. See [Monitoring](monitoring.md) for useful starting queries.

```bash
# Or from the command line
ssh root@10.10.20.20 'pct exec 114 -- curl -sG \
  "http://127.0.0.1:3100/loki/api/v1/query_range" \
  --data-urlencode "query={job=\"systemd-journal\",host=\"proxy\"}" \
  --data-urlencode "limit=20"'
```

## Add a VPN client

**Web UI**: https://wireguard.baig.network — create, download, QR code, live
handshake stats.

**Command line**:

```bash
ssh root@10.10.20.20 'pct exec 116 -- /root/wg-peer.sh add <name> full'   # all traffic via home
ssh root@10.10.20.20 'pct exec 116 -- /root/wg-peer.sh add <name> split'  # lab subnets only
ssh root@10.10.20.20 'pct exec 116 -- /root/wg-peer.sh list'
```

`full` gives you AdGuard's blocklists on mobile data. `split` suits servers —
Oracle uses it, so a tunnel drop cannot break its own internet or DNS.

Print a QR code for a phone:

```bash
ssh root@10.10.20.20 'pct exec 116 -- qrencode -t ansiutf8 < /etc/wireguard/peers/<name>.conf'
```

## Check the VPNs

```bash
# WireGuard peers and handshake ages
ssh root@10.10.20.20 'pct exec 116 -- /root/wg-peer.sh list'

# OpenVPN on the Pi — check the RIGHT unit
ssh pi@192.168.0.3 'systemctl is-active openvpn@server; sudo ss -lnup | grep 1194'
```

`openvpn-server@server` is disabled and must stay that way — see
[Remote Access](remote-access.md).

## Test Telegram alerting

```bash
ssh root@10.10.20.20 'pct exec 114 -- amtool alert add \
  alertname=Test severity=warning instance=manual \
  --annotation=summary="test" --alertmanager.url=http://127.0.0.1:9093'
```

Re-point it at a different bot or chat:

```bash
ssh root@10.10.20.20 '/root/apply-telegram.sh <bot-token> <chat-id>'
```

## Back up what matters

Not yet automated. The things that would actually hurt to lose:

| What | Where |
|---|---|
| Databases | CT 112 — `pg_dumpall`, `mariadb-dump`, `mongodump` |
| Grafana dashboards | CT 115 `/var/lib/grafana/grafana.db` |
| nginx config | CT 111 `/etc/nginx/conf.d/baig.conf` |
| Certificate + acme account | CT 111 `/root/.acme.sh/` |
| AdGuard config | CT 110 `/opt/AdGuardHome/AdGuardHome.yaml` |
| Obsidian vault | `~/Documents/Obsidian Vault` on the Mac mini, plus CouchDB on CT 112 |
| WireGuard keys | CT 116 `/etc/wireguard/` — peers and server key |
| Gatus config | Oracle box `/home/ubuntu/docker/gatus-config.yaml` |

Proxmox can back up whole containers to `local` — that covers most of this in
one step and is the obvious next improvement.

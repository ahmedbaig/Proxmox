# Flow — live network map

`https://flow.baig.network` is a live Tube-map of the network: DNS lookups, connections and VPN sessions moving from device to VLAN, through the UX7 and the ISP, to the internet. Source: [ahmedbaig/dns-flow](https://github.com/ahmedbaig/dns-flow).

## Where the pieces run

| Piece | Where | Managed by |
|---|---|---|
| Bridge + map (`flow` Compose stack, port 8787) | CT 113 apps | `apps` role, built from `../dns-flow` (`apps_flow_source`) |
| `flow` database (devices, identifiers, sightings, networks, audit) | CT 112 db | `db` role; secret `homelab-secrets/flow/postgres.sops.yaml` |
| UniFi syslog receiver (`{job="unifi"}`, port 1514) | CT 114 metrics, Alloy | `alloy` fragment `unifi_syslog`, enabled in `host_vars/metrics.yml` |
| `flow.baig.network` vhost behind Entra SSO | CT 111 proxy | `proxy` role |
| UniFi router dashboard | CT 115 grafana | `grafana` role, `dashboards/unifi.json` |

The UX7 sends its activity log to `10.10.20.5:1514` (UniFi Network → *Activity Logging (SIEM server)*).

## Data sources

- AdGuard `/control/querylog`, polled every 1.5 s with the `apps_adguard_password` account. Not `querylog.json`: AdGuard keeps `size_memory` (1000) entries in memory before writing the file.
- Loki `{job="unifi"}`: DHCPACK, UBNT_ROAM, `stahtd` Wi-Fi events, firewall lines (`SRC=`/`DPT=`).
- Loki `{job="nginx", log_type="access"}`: connections into services.
- Prometheus `wireguard_peer_handshake_age_seconds` and `wireguard_peer_geo_info` from `wg-metrics.py` on CT 116.

VPN clients are NATed to `10.10.50.20`, so the bridge attributes that traffic to the active peer and marks it as a guess when more than one peer is up.

## Redeploying

```sh
ansible-playbook playbooks/apps.yml
```

Copies the changed `dns-flow` files to `/opt/stacks/flow/app` and rebuilds only the `flow` container.

## Traps

- `playbooks/db.yml` also rewrites MariaDB's tuning file (comment-only drift) and restarts MariaDB. The `flow` role and database were created with the role's own SQL instead.
- The SSO lines on CT 111 (`include /etc/nginx/snippets/sso-auth.conf` on 11 vhosts, dozzle's `Remote-*` headers, `large_client_header_buffers`) were live-only until 18 Oct 2026; they are in `baig.conf.j2` and `nginx.conf` now. Run `playbooks/proxy.yml --check --diff` before every proxy change.

# Docs

Notes for the homelab this repo builds: one Proxmox VE host, ten Debian LXC
containers, four VLANs, domain `baig.network`. Written while building it, so
they record what broke and why as much as what is there.

Start with the [Lab Map](lab-map.md).

| Page | What it covers |
|---|---|
| [Lab Map](lab-map.md) | The whole lab in one diagram, fixed addresses, where to go next |
| [Network Topology](network-topology.md) | Physical wiring, VLANs, firewall zones |
| [Firewall Policies](firewall-policies.md) | Every zone rule, what it unblocks, what it costs |
| [Remote Access](remote-access.md) | WireGuard, OpenVPN, and how anything gets in |
| [DNS](dns.md) | AdGuard Home, Unbound over DoT, rewrites |
| [Proxmox and Containers](proxmox-and-containers.md) | Container inventory, the bridge trap, the container recipe, capacity |
| [Databases](databases.md) | CT 112: PostgreSQL, MariaDB, MongoDB, Redis, CouchDB |
| [Reverse Proxy and Certificates](reverse-proxy-and-certificates.md) | nginx, the wildcard certificate, renewal and distribution |
| [Monitoring](monitoring.md) | Prometheus, Loki, Alertmanager, Grafana |
| [External Monitoring](external-monitoring.md) | Gatus on the Oracle bastion, the view from outside |
| [CI and Registry](ci-and-registry.md) | Self-hosted GitLab, Docker registry, runners, Terraform state |
| [Host Lifecycle](host-lifecycle.md) | Onboarding and offboarding checklist, change log |
| [Runbooks](runbooks.md) | Step-by-step procedures |
| [Known Traps](known-traps.md) | Everything that has broken, and why it will again |
| [Migration Status](migration-status.md) | What has moved off the Mac mini, what has not |

Secrets are never in these pages. They live, encrypted, in a private repo.

# proxmox

My homelab as code: one Proxmox VE host running ten unprivileged Debian 13 LXC containers for DNS, reverse proxy, databases, monitoring, VPN, GitLab and a Docker registry.

- **Terraform** describes the containers (adopted with `import` blocks, never recreated).
- **Ansible** configures what runs inside them, reaching each container through `pct` on the host, so no SSH keys live in the containers.
- **Secrets** come from a private repo encrypted with SOPS + age; nothing secret is stored here.

```mermaid
graph LR
    subgraph PVE["Proxmox VE 9 · 10.10.20.20"]
        subgraph S["VLAN 20 · servers"]
            dns1["110 dns1<br/>AdGuard + Unbound"]
            proxy["111 proxy<br/>nginx + wildcard TLS"]
            db["112 db<br/>Postgres · MariaDB · Mongo · Redis · CouchDB"]
            apps["113 apps<br/>Docker apps"]
            metrics["114 metrics<br/>Prometheus · Loki · Alertmanager"]
            grafana["115 grafana"]
        end
        subgraph L["VLAN 50 · lab"]
            vpn["116 vpn<br/>WireGuard"]
            docker["117 docker host<br/>CI runners"]
            gitlab["118 gitlab"]
            registry["119 registry"]
        end
    end
    proxy --> grafana & gitlab & registry & apps
    metrics --> dns1 & proxy & db & apps & vpn & docker & gitlab & registry
```

## Layout

| Path | What |
|---|---|
| [`terraform/`](terraform) | Containers (`bpg/proxmox`), state kept in the lab GitLab |
| [`ansible/`](ansible) | One role per service, one playbook per container, `site.yml` for everything |
| [`scripts/`](scripts) | Operational scripts: certificates, DNS metrics, monitoring checks, WireGuard peers, CouchDB |
| [`docs/`](docs) | How it all fits together: network, DNS, proxy and certificates, databases, monitoring, runbooks, known traps |

## Use

Needs `terraform`, `ansible`, `sops` and `age`, the age key for the secrets repo, and SSH to the Proxmox host as root.

```bash
git clone git@github.com:ahmedbaig/proxmox.git
git clone git@github.com:ahmedbaig/homelab-secrets.git   # private; or set HOMELAB_SECRETS

./scripts/bootstrap-terraform-secrets.sh   # once: Proxmox API token + GitLab state token

cd terraform && ./tf.sh plan               # should report no changes against the live host

cd ../ansible
ansible-playbook playbooks/site.yml --check --diff
ansible-playbook playbooks/proxy.yml
```

Everything is checked against the running lab before it is committed: `terraform plan` shows no changes and every playbook runs in `--check` mode with nothing to change.

## Not in here

The Docker host on CT 117 runs a private work test stack; only its generic host setup (Docker, egress policy, GitLab runner install) is public.

# alloy

Ships each host's systemd journal to Loki on the metrics container (CT 114) with [Grafana Alloy](https://grafana.com/docs/alloy/).
Hosts that run Docker or nginx append an extra fragment for those logs.

| Variable | Default | Meaning |
|---|---|---|
| `alloy_hostname` | `inventory_hostname` | Value of the `host` label on every log line |
| `alloy_loki_push_url` | `http://10.10.20.5:3100/loki/api/v1/push` | Loki push endpoint |
| `alloy_extras` | `[]` | Fragments to append: `docker` (container logs via the Docker socket), `nginx` (access/error logs, parsed) |
| `alloy_groups` | `[systemd-journal]` | Groups for the `alloy` user; `docker` / `adm` are added automatically for those extras |

The role also owns the Grafana apt repository. Other roles that need a package from it (Loki, Grafana) reuse it with:

```yaml
- ansible.builtin.include_role:
    name: alloy
    tasks_from: apt_repo
```

## Using it on a host

Add the role after `common` in that host's playbook, and set extras in `host_vars` when needed:

```yaml
- hosts: proxy
  roles:
    - common
    - proxy
    - alloy
```

```yaml
# inventory/host_vars/proxy.yml
alloy_extras: [nginx]

# inventory/host_vars/apps.yml
alloy_extras: [docker]
```

Where it runs today: dns1, proxy (`nginx`), db, apps (`docker`), metrics, grafana, gitlab, registry, docker, and the Proxmox host itself (not managed by this inventory).
In check mode, the role already shows no changes on all nine containers.
